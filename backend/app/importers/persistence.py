"""Общая механика записи слоёв 8.3–8.7 в базу.

Импортёры книг уже написаны и умеют главное: прочитать источник и посчитать
риск. Чего они принципиально не делают — не пишут в базу. Этот модуль
закрывает ровно этот разрыв и держит в одном месте решения, которые иначе
разъехались бы по пяти загрузчикам.

**Идемпотентность держится на первичном ключе, а не на предварительном SELECT.**
Ключ строки выводится из естественного ключа источника функцией
:func:`stable_id`: `uuid5(namespace, "таблица|natural_key")`. Такой ключ один и
тот же при каждом запуске, поэтому повторная загрузка попадает в
`ON CONFLICT (id) DO UPDATE` и обновляет ту же строку, а не создаёт вторую.
Вариант «сначала выбрать существующие, потом решить» пришлось бы выполнять
21 521 раз на одном лишь слое 8.5, и он ломается при параллельных запусках.

У детерминированного ключа есть второе, менее очевидное следствие, ради
которого он и выбран: **ссылки между таблицами считаются, а не выясняются**.
`subsidy_payments.recipient_id` — это `stable_id("subsidy_recipients", БИН)`, и
знать настоящий идентификатор получателя для вставки выплаты не нужно. То же
для наследования в слое 8.6, где строка супертипа и строка подтипа обязаны
иметь один идентификатор.

**Пишем пачками.** 21 521 выплата, 74 831 бюджетный факт и 4842 заключения —
это не тот объём, который можно вставлять построчно через ORM. Здесь
используется Core-вставка списком словарей; размер пачки считается от числа
колонок, потому что ограничение PostgreSQL — на число параметров запроса
(65 535), а не на число строк.

**«Создано» и «обновлено» различаются по `xmax`.** У строки, только что
вставленной, `xmax = 0`; у обновлённой — нет. Это позволяет получить оба
счётчика из того же запроса, не делая второго прохода по таблице.

**Замечания о неопознанных территориях группируются по написанию.** Построчная
запись дала бы более двадцати тысяч строк журнала за один запуск, из которых
99 % повторяют друг друга. Пользователю мастера импорта нужен список
непонятых названий с числом вхождений и примерами строк, а не двадцать тысяч
одинаковых сообщений. Само правило при этом не смягчается: территория
неопознанной строки остаётся NULL, угадывание запрещено.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Table, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models.source import (
    DataQualityIssue,
    ImportJob,
    ImportStatus,
    IssueSeverity,
    SourceDataset,
    SourceFile,
)
from app.db.models.territory import Territory, TerritoryAlias
from app.risk.core import RiskResult
from app.services.territory_resolver import Resolution, ResolutionStatus, TerritoryResolver

NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f1f0a2c-2f3e-5a4b-9c8d-0e1f2a3b4c5d")
"""Пространство имён проекта для uuid5.

Константа, а не случайная величина: от неё зависит совпадение ключей между
запусками, то есть вся идемпотентность. Менять её — то же самое, что очистить
все таблицы фактов.
"""

MAX_BIND_PARAMS: Final[int] = 30_000
"""Потолок числа параметров в одном запросе.

Формальное ограничение PostgreSQL — 65 535; берём половину с запасом, потому
что к колонкам строки добавляются параметры выражения `ON CONFLICT`.
"""

MAX_ISSUE_SAMPLES: Final[int] = 5
"""Сколько адресов строк сохранять в примере к сгруппированному замечанию."""


def stable_id(scope: str, natural_key: str) -> uuid.UUID:
    """Детерминированный первичный ключ по естественному ключу источника.

    `scope` — имя таблицы. Без него два слоя с одинаковым естественным ключом
    (например, БИН в организациях и в поставщиках) получили бы один и тот же
    идентификатор, и вторая вставка молча перезаписала бы первую.
    """
    return uuid.uuid5(NAMESPACE, f"{scope}|{natural_key}")


def table_of(model: type[Any]) -> Table:
    """Таблица модели с уточнённым типом.

    `Model.__table__` объявлен в SQLAlchemy как `FromClause`, а массовой
    вставке нужна именно `Table` — у представления нет ни имени, ни списка
    ограничений. Проверка выполняется в момент вызова, а не подавляется
    приведением типа: подсунуть сюда представление — ошибка, и она должна
    быть видна.
    """
    table = model.__table__
    if not isinstance(table, Table):
        raise TypeError(f"{model.__name__}: ожидалась таблица, получено {type(table).__name__}")
    return table


def jsonable(value: object) -> Any:
    """Привести значение к тому, что примет JSONB.

    Отдельная функция, потому что в расшифровках факторов лежит `raw_value`
    произвольного вида: дата, словарь признаков, булево, а иногда `nan` из
    Excel. `nan` и бесконечности JSONB не принимает вовсе — они превращаются в
    текст, чтобы исходное значение осталось видимым, а вставка не падала.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]
    return str(value)


# --- Расшифровка риска -------------------------------------------------------


def factors_payload(result: RiskResult) -> list[dict[str, Any]]:
    """Расшифровка вклада каждого индикатора, включая НЕизмеренные.

    Неизмеренные включены намеренно и с причиной в `note`: именно они
    объясняют пользователю, почему полнота ниже ста процентов и почему уровень
    может оказаться серым. Убрать их из выгрузки — значит оставить серый
    уровень без объяснения.
    """
    return [
        {
            "code": factor.code,
            "name": factor.name,
            "weight": factor.weight,
            "value": factor.value,
            "contribution": factor.contribution,
            "measured": factor.measured,
            "effect": factor.effect,
            "direction": str(factor.direction),
            "raw_value": jsonable(factor.raw_value),
            "note": factor.note,
            "source": factor.source,
        }
        for factor in result.factors
    ]


def risk_payload(result: RiskResult) -> dict[str, Any]:
    """Полная карточка расчёта: балл, веса, полнота, уровень, факторы."""
    return {
        "model": result.model_code,
        "version": result.model_version,
        "raw_score": result.raw_score,
        "available_weight": result.available_weight,
        "total_weight": result.total_weight,
        "normalized_score": result.normalized_score,
        "score": result.score,
        "completeness": result.completeness,
        "level": str(result.level),
        "is_preliminary": result.is_preliminary,
        "override_applied": result.override_applied,
        "notes": list(result.notes),
        "factors": factors_payload(result),
    }


def explanation_ru(result: RiskResult, *, limit: int = 5) -> str:
    """Текст «почему такой балл» для карточки объекта.

    Перечисляются факторы, действительно поднявшие балл, по убыванию вклада.
    Если не поднял ни один — так и написано: пустая строка выглядела бы как
    сбой формирования текста, а не как «рисковых факторов не выявлено».
    """
    raising = result.top_factors(limit)
    if not raising:
        if result.score is None:
            return "Балл не рассчитан: не измерен ни один индикатор."
        return "Ни один индикатор не повысил риск."
    parts = [
        f"{factor.code} {factor.name} — вклад {factor.contribution:.1f} из {factor.weight:g}"
        for factor in raising
        if factor.contribution is not None
    ]
    unmeasured = result.unmeasured_factors
    text = "; ".join(parts)
    if unmeasured:
        text += f". Не измерено индикаторов: {len(unmeasured)}"
    return text


# --- Счётчики и сверка -------------------------------------------------------


@dataclass(slots=True)
class UpsertCounts:
    """Что сделала одна пачка вставок."""

    created: int = 0
    updated: int = 0
    duplicates: int = 0
    """Строк, свёрнутых как повтор естественного ключа внутри одного запуска."""

    @property
    def total(self) -> int:
        return self.created + self.updated

    def merge(self, other: UpsertCounts) -> None:
        self.created += other.created
        self.updated += other.updated
        self.duplicates += other.duplicates


@dataclass(frozen=True, slots=True)
class ControlCheck:
    """Сверка одного контрольного значения книги с посчитанным.

    Хранится и ожидаемое, и полученное, и допуск. Булев ответ «сошлось» тут
    производный: расхождение нужно видеть числом, иначе его нечем объяснить.
    """

    metric: str
    expected: float
    actual: float
    tolerance: float = 0.0

    @property
    def delta(self) -> float:
        return self.actual - self.expected

    @property
    def matches(self) -> bool:
        return abs(self.delta) <= self.tolerance

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "expected": self.expected,
            "actual": self.actual,
            "delta": self.delta,
            "tolerance": self.tolerance,
            "matches": self.matches,
        }


def check_controls(
    expected: Mapping[str, float],
    actual: Mapping[str, float],
    *,
    tolerances: Mapping[str, float] | None = None,
    default_tolerance: float = 0.0,
) -> list[ControlCheck]:
    """Сверить контрольные значения книги с посчитанными загрузчиком.

    Контроль, для которого нет посчитанной величины, не пропускается молча:
    он попадает в результат со значением NaN и заведомо не сходится. Иначе
    опечатка в имени показателя выглядела бы как успешная сверка.
    """
    limits = tolerances or {}
    return [
        ControlCheck(
            metric=name,
            expected=float(want),
            actual=float(actual.get(name, float("nan"))),
            tolerance=limits.get(name, default_tolerance),
        )
        for name, want in expected.items()
    ]


@dataclass(slots=True)
class IssueRecord:
    """Замечание к качеству данных до записи в базу.

    Обычный dataclass, а не ORM-объект: замечания собираются и в сухом
    прогоне, и до того, как задание импорта получит идентификатор.
    """

    severity: IssueSeverity
    code: str
    message: str
    source_row_ref: str | None = None
    column_name: str | None = None
    raw_value: str | None = None
    context: dict[str, Any] | None = None


# --- Территории --------------------------------------------------------------


@dataclass(slots=True)
class TerritoryIndex:
    """Сопоставитель названий плюс соответствие «код территории → id в базе».

    Собирается один раз из справочника алиасов и дальше работает по памяти:
    ходить в базу за каждой из 21 521 строки нельзя.

    Здесь же копится статистика сопоставления. Она нужна и отчёту, и полю
    `ImportJob.territory_match_report`: «сколько строк осталось без территории»
    — показатель качества загрузки, а не мелочь для отладки.
    """

    resolver: TerritoryResolver
    ids: dict[str, uuid.UUID]
    levels: dict[str, str] = field(default_factory=dict)
    """Уровень территории по коду.

    Нужен там, где от уровня зависит смысл записи: в слое 8.6 точность
    привязки («район» или «только область») — отдельное поле, и вывести её
    можно лишь зная, что именно опознал резолвер.
    """

    resolved: int = 0
    not_found: int = 0
    ambiguous: int = 0
    empty: int = 0
    unresolved_names: Counter[str] = field(default_factory=Counter)
    unresolved_samples: dict[str, list[str]] = field(default_factory=dict)

    def lookup(self, raw_name: object, *, row_ref: str | None = None) -> tuple[
        uuid.UUID | None, Resolution
    ]:
        """Найти территорию по названию из книги.

        Возвращается и идентификатор, и полный разбор: вызывающему коду нужно
        знать не только «не нашли», но и почему — пусто в источнике, написание
        неизвестно или подходит нескольким территориям. Эти три случая
        по-разному читаются пользователем.
        """
        text = None if raw_name is None else str(raw_name)
        resolution = self.resolver.resolve(text)

        if resolution.status is ResolutionStatus.RESOLVED:
            code = resolution.territory_code
            territory_id = self.ids.get(code) if code else None
            if territory_id is not None:
                self.resolved += 1
                return territory_id, resolution
            # Код известен резолверу, но территории с таким кодом в базе нет.
            # Это рассогласование справочника, а не свойство книги.
            self.not_found += 1
        elif resolution.status is ResolutionStatus.NOT_FOUND:
            self.not_found += 1
        elif resolution.status is ResolutionStatus.AMBIGUOUS:
            self.ambiguous += 1
        else:
            self.empty += 1
            return None, resolution

        key = resolution.raw.strip() or "(пусто)"
        self.unresolved_names[key] += 1
        if row_ref is not None:
            samples = self.unresolved_samples.setdefault(key, [])
            if len(samples) < MAX_ISSUE_SAMPLES:
                samples.append(row_ref)
        return None, resolution

    @property
    def unresolved_rows(self) -> int:
        return self.not_found + self.ambiguous

    def report(self) -> dict[str, Any]:
        """Сводка сопоставления для `ImportJob.territory_match_report`."""
        return {
            "resolved": self.resolved,
            "not_found": self.not_found,
            "ambiguous": self.ambiguous,
            "empty_in_source": self.empty,
            "distinct_unresolved_names": len(self.unresolved_names),
            "unresolved_names": [
                {"name": name, "rows": count}
                for name, count in self.unresolved_names.most_common()
            ],
        }

    def issues(self) -> list[IssueRecord]:
        """Замечания о неопознанных названиях — по одному на написание.

        Группировка по написанию, а не по строке: см. модульный docstring.
        Число затронутых строк и примеры адресов сохраняются в контексте, так
        что трассировка до источника не теряется.
        """
        return [
            IssueRecord(
                severity=IssueSeverity.WARNING,
                code="territory_not_resolved",
                message=(
                    f"Название «{name}» не сопоставлено ни с одной территорией "
                    f"справочника; затронуто строк: {count}. "
                    f"territory_id оставлен пустым — угадывание запрещено."
                ),
                source_row_ref=next(iter(self.unresolved_samples.get(name, [])), None),
                raw_value=name,
                context={
                    "rows_affected": count,
                    "sample_rows": self.unresolved_samples.get(name, []),
                },
            )
            for name, count in self.unresolved_names.most_common()
        ]


def load_territory_index(session: Session) -> TerritoryIndex:
    """Собрать сопоставитель по тому, что лежит в справочнике территорий.

    Источник истины — таблица алиасов, а не зашитый в код перечень написаний:
    справочник наполняется отдельным импортёром, и дублировать его здесь
    значило бы завести вторую, расходящуюся версию правды.
    """
    rows = session.execute(
        select(TerritoryAlias.alias, Territory.code).join(
            Territory, Territory.id == TerritoryAlias.territory_id
        )
    ).all()
    resolver = TerritoryResolver()
    resolver.add_many((str(alias), str(code)) for alias, code in rows)

    catalog = session.execute(select(Territory.code, Territory.id, Territory.level)).all()
    return TerritoryIndex(
        resolver=resolver,
        ids={str(code): territory_id for code, territory_id, _ in catalog},
        levels={str(code): str(level) for code, _, level in catalog},
    )


# --- Массовая запись ---------------------------------------------------------


def _dedupe(
    rows: Sequence[Mapping[str, Any]], index_elements: Sequence[str]
) -> tuple[list[dict[str, Any]], int]:
    """Свернуть повторы естественного ключа внутри одной загрузки.

    PostgreSQL отказывается выполнять `ON CONFLICT DO UPDATE`, если один и тот
    же ключ встречается в запросе дважды («cannot affect row a second time»).
    Повтор внутри книги — это факт о данных, и он возвращается счётчиком, а не
    прячется: побеждает последняя строка, как при последовательной записи.
    """
    seen: dict[tuple[Any, ...], int] = {}
    result: list[dict[str, Any]] = []
    duplicates = 0
    for row in rows:
        key = tuple(row[column] for column in index_elements)
        position = seen.get(key)
        if position is None:
            seen[key] = len(result)
            result.append(dict(row))
        else:
            result[position] = dict(row)
            duplicates += 1
    return result, duplicates


def bulk_upsert(
    session: Session,
    table: Table,
    rows: Sequence[Mapping[str, Any]],
    *,
    index_elements: Sequence[str] = ("id",),
    immutable_columns: Sequence[str] = ("created_at",),
) -> UpsertCounts:
    """Записать строки пачками с обновлением по конфликту ключа.

    Все словари обязаны иметь один и тот же набор ключей: `INSERT` со списком
    значений берёт колонки из первой строки, и разнобой дал бы тихий сдвиг
    данных. Несоответствие — отказ, а не попытка починить.
    """
    counts = UpsertCounts()
    if not rows:
        return counts

    columns = list(rows[0].keys())
    expected = set(columns)
    for position, row in enumerate(rows):
        if set(row.keys()) != expected:
            raise ValueError(
                f"{table.name}: строка {position} имеет другой набор колонок "
                f"({sorted(set(row.keys()) ^ expected)}). Массовая вставка требует "
                "одинаковых ключей во всех словарях."
            )

    prepared, duplicates = _dedupe(rows, index_elements)
    counts.duplicates = duplicates

    updatable = [
        column
        for column in columns
        if column not in set(index_elements) and column not in set(immutable_columns)
    ]
    chunk_size = max(1, MAX_BIND_PARAMS // max(1, len(columns)))

    for start in range(0, len(prepared), chunk_size):
        chunk = prepared[start : start + chunk_size]
        statement = pg_insert(table).values(chunk)
        assignments: dict[str, Any] = {
            column: statement.excluded[column] for column in updatable
        }
        if "updated_at" in table.c and "updated_at" not in assignments:
            # Обновление через Core не запускает ORM-хук `onupdate`, поэтому
            # отметку времени проставляем явно: иначе у обновлённой строки
            # останется время первой загрузки.
            assignments["updated_at"] = func.now()
        statement = statement.on_conflict_do_update(
            index_elements=list(index_elements), set_=assignments
        )
        # `xmax = 0` истинно только у строки, вставленной этим запросом, —
        # так «создано» и «обновлено» получаются без второго прохода.
        inserted_flags: Sequence[Any] = session.execute(
            statement.returning(literal_column("(xmax = 0)"))
        ).all()
        for (inserted,) in inserted_flags:
            if inserted:
                counts.created += 1
            else:
                counts.updated += 1
    return counts


# --- Отчёт и задание ---------------------------------------------------------


@dataclass(slots=True)
class LayerReport:
    """Что сделал (или сделал бы) импорт одного слоя."""

    layer_code: str
    importer: str
    dry_run: bool = False
    job_id: uuid.UUID | None = None
    source_files: list[str] = field(default_factory=list)
    tables: dict[str, UpsertCounts] = field(default_factory=dict)
    controls: list[ControlCheck] = field(default_factory=list)
    issues: list[IssueRecord] = field(default_factory=list)
    territory: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error: str | None = None

    @property
    def rows_written(self) -> int:
        return sum(counts.total for counts in self.tables.values())

    @property
    def failed_controls(self) -> list[ControlCheck]:
        return [control for control in self.controls if not control.matches]

    @property
    def errors(self) -> list[IssueRecord]:
        return [item for item in self.issues if item.severity is IssueSeverity.ERROR]

    def summary_ru(self) -> str:
        prefix = "СУХОЙ ПРОГОН — ничего не записано\n" if self.dry_run else ""
        tables = "\n".join(
            f"    {name:<34} создано {counts.created:>7}, обновлено {counts.updated:>7}"
            + (f", свёрнуто дублей {counts.duplicates}" if counts.duplicates else "")
            for name, counts in self.tables.items()
        )
        failed = self.failed_controls
        control_line = (
            f"  контроли: сошлось {len(self.controls) - len(failed)} из {len(self.controls)}"
            if self.controls
            else "  контролей нет"
        )
        return (
            f"{prefix}Слой {self.layer_code} ({self.importer}), "
            f"{self.duration_seconds:.1f} с, строк {self.rows_written}\n"
            f"{tables}\n"
            f"{control_line}\n"
            f"  замечаний {len(self.issues)}, из них ошибок {len(self.errors)}"
        )


class LayerJob:
    """Задание импорта одного слоя: происхождение, запись, сверка, журнал.

    Ведёт всё, что обязано быть одинаковым у пяти загрузчиков: регистрацию
    файла-источника по хешу, набор данных (лист), провенанс каждой строки,
    счётчики и запись `ImportJob`. Предметная часть — что именно читать и как
    считать риск — остаётся в загрузчике слоя.
    """

    def __init__(
        self,
        session: Session,
        *,
        layer_code: str,
        importer: str,
        dry_run: bool = False,
    ) -> None:
        self.session = session
        self.layer_code = layer_code
        self.importer = importer
        self.dry_run = dry_run
        self.report = LayerReport(layer_code=layer_code, importer=importer, dry_run=dry_run)
        self.job: ImportJob | None = None
        self._started_at = utcnow()
        self._rows_read = 0
        self._rows_skipped = 0

    # --- запуск ------------------------------------------------------------

    def start(self) -> ImportJob:
        """Открыть задание.

        Задание создаётся и в сухом прогоне: статус `dry_run` и последующий
        откат — честнее, чем не заводить запись вовсе, потому что все проверки
        базы (ограничения, типы, внешние ключи) обязаны отработать по-настоящему.
        """
        job = ImportJob(
            id=uuid.uuid4(),
            importer=self.importer,
            layer_code=self.layer_code,
            status=ImportStatus.DRY_RUN if self.dry_run else ImportStatus.RUNNING,
            is_dry_run=self.dry_run,
            started_at=self._started_at,
        )
        self.session.add(job)
        self.session.flush()
        self.job = job
        self.report.job_id = job.id
        return job

    @property
    def job_id(self) -> uuid.UUID:
        if self.job is None:
            raise RuntimeError("Задание импорта не открыто: вызовите start()")
        return self.job.id

    # --- происхождение ------------------------------------------------------

    def source_file(self, path: Path, *, origin: str = "source_data_dir") -> SourceFile:
        """Зафиксировать файл-источник по SHA-256.

        Хеш — единственный надёжный признак тождества книги: часть имён лежит в
        Unicode NFD и совпадает с NFC-вариантом только после свёртки. Повторная
        загрузка того же файла переиспользует запись, а не заводит вторую.
        """
        from scripts.source_manifest import normalize_name, sha256_of

        digest = sha256_of(path)
        existing = self.session.scalars(
            select(SourceFile).where(SourceFile.sha256 == digest)
        ).one_or_none()
        if existing is not None:
            if str(path) not in self.report.source_files:
                self.report.source_files.append(str(path))
            self._attach_source_file(existing)
            return existing

        stat = path.stat()
        source = SourceFile(
            id=stable_id("source_files", digest),
            file_name=path.name,
            normalized_name=normalize_name(path.name),
            sha256=digest,
            size_bytes=stat.st_size,
            origin=origin,
        )
        self.session.add(source)
        self.session.flush()
        self.report.source_files.append(str(path))
        self._attach_source_file(source)
        return source

    def _attach_source_file(self, source: SourceFile) -> None:
        if self.job is not None and self.job.source_file_id is None:
            self.job.source_file_id = source.id

    def dataset(
        self,
        source: SourceFile,
        *,
        sheet_name: str,
        role: str = "raw",
        row_count: int | None = None,
        data_as_of: date | None = None,
        header_row: int | None = None,
    ) -> SourceDataset:
        """Зарегистрировать лист книги как набор данных.

        Роль листа фиксируется явно: лист методики описывает, как считать, и
        его строки не должны превращаться в объекты на карте.
        """
        existing = self.session.scalars(
            select(SourceDataset).where(
                SourceDataset.source_file_id == source.id,
                SourceDataset.sheet_name == sheet_name,
            )
        ).one_or_none()
        dataset = existing or SourceDataset(
            id=stable_id("source_datasets", f"{source.sha256}|{sheet_name}"),
            source_file_id=source.id,
            sheet_name=sheet_name,
            role=role,
        )
        dataset.layer_code = self.layer_code
        dataset.role = role
        dataset.row_count = row_count
        dataset.data_as_of = data_as_of
        dataset.header_row = header_row
        if existing is None:
            self.session.add(dataset)
        self.session.flush()
        return dataset

    def provenance(
        self,
        dataset: SourceDataset,
        *,
        natural_key: str,
        source_row_ref: str | None,
        data_as_of: date | None,
        validation_status: str = "ok",
        validation_notes: dict[str, Any] | None = None,
        data_version: int = 1,
    ) -> dict[str, Any]:
        """Колонки происхождения для одной строки.

        Выделено в функцию, чтобы ни один слой не мог «забыть» часть полей:
        требование ТЗ — у каждой записи известны источник, задание, ключ,
        адрес строки и обе даты, — иначе объяснить пользователю цифру нечем.
        """
        return {
            "source_dataset_id": dataset.id,
            "import_job_id": self.job_id,
            "source_row_ref": source_row_ref,
            "natural_key": natural_key,
            "imported_at": self._started_at,
            "data_as_of": data_as_of,
            "validation_status": validation_status,
            "validation_notes": jsonable(validation_notes) if validation_notes else None,
            "data_version": data_version,
            "is_current": True,
        }

    # --- запись -------------------------------------------------------------

    def upsert(
        self,
        table: Table,
        rows: Sequence[Mapping[str, Any]],
        *,
        label: str | None = None,
        index_elements: Sequence[str] = ("id",),
    ) -> UpsertCounts:
        """Записать строки таблицы и учесть их в отчёте."""
        counts = bulk_upsert(self.session, table, rows, index_elements=index_elements)
        name = label or table.name
        existing = self.report.tables.get(name)
        if existing is None:
            self.report.tables[name] = counts
        else:
            existing.merge(counts)
        self.session.flush()
        return counts

    def count_read(self, rows: int) -> None:
        """Учесть прочитанные строки источника (не то же, что записанные)."""
        self._rows_read += rows

    def count_skipped(self, rows: int) -> None:
        self._rows_skipped += rows

    # --- журнал качества ----------------------------------------------------

    def issue(
        self,
        severity: IssueSeverity,
        code: str,
        message: str,
        *,
        source_row_ref: str | None = None,
        column_name: str | None = None,
        raw_value: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.report.issues.append(
            IssueRecord(
                severity=severity,
                code=code,
                message=message,
                source_row_ref=source_row_ref,
                column_name=column_name,
                raw_value=raw_value,
                context=context,
            )
        )

    def extend_issues(self, records: Sequence[IssueRecord]) -> None:
        self.report.issues.extend(records)

    def _write_issues(self) -> None:
        """Записать накопленные замечания одной пачкой.

        Идентификатор строки журнала выводится из задания и порядкового номера:
        повторный запуск того же задания не может создать дубликаты, а разные
        задания дают разные ключи.
        """
        if not self.report.issues:
            return
        rows = [
            {
                "id": stable_id("data_quality_issues", f"{self.job_id}|{position}"),
                "import_job_id": self.job_id,
                "severity": item.severity,
                "code": item.code,
                "message": item.message,
                "source_row_ref": item.source_row_ref,
                "column_name": item.column_name,
                "raw_value": item.raw_value,
                "context": jsonable(item.context) if item.context is not None else None,
            }
            for position, item in enumerate(self.report.issues)
        ]
        bulk_upsert(self.session, table_of(DataQualityIssue), rows)

    # --- сверка и завершение ------------------------------------------------

    def add_controls(self, controls: Sequence[ControlCheck]) -> None:
        """Добавить результаты сверки.

        Несошедшийся контроль не «чинится» подгонкой: он остаётся в отчёте
        числом и одновременно попадает в журнал качества как ошибка — так
        расхождение видно и в мастере импорта, и в коде возврата скрипта.
        """
        self.report.controls.extend(controls)
        for control in controls:
            if control.matches:
                continue
            self.issue(
                IssueSeverity.ERROR,
                "control_value_mismatch",
                f"Контроль «{control.metric}»: ожидалось {control.expected:g}, "
                f"получено {control.actual:g} (расхождение {control.delta:+g}).",
                context=control.as_dict(),
            )

    def finish(self, reconciliation: dict[str, Any] | None = None) -> LayerReport:
        """Закрыть задание, записать сверку и — в сухом прогоне — откатить всё.

        Сверка кладётся в `ImportJob.reconciliation` целиком, включая
        несошедшиеся контроли: задание импорта — это документ о том, что
        произошло, а не витрина успехов.

        Откат сухого прогона выполняется **здесь**, а не в вызывающем скрипте.
        Причина не стилистическая: пока откат жил в CLI, любой другой вызов
        загрузчика с `dry_run=True` — из теста, из мастера импорта, из консоли —
        молча записывал данные в базу. Обещание «сухой прогон ничего не
        оставляет» должно выполняться тем же объектом, который его даёт.
        """
        job = self.job
        if job is None:
            raise RuntimeError("Задание импорта не открыто: вызовите start()")

        territory = self.report.territory
        payload: dict[str, Any] = {
            "controls": [control.as_dict() for control in self.report.controls],
            "controls_passed": len(self.report.controls) - len(self.report.failed_controls),
            "controls_total": len(self.report.controls),
            "tables": {
                name: {
                    "created": counts.created,
                    "updated": counts.updated,
                    "duplicates": counts.duplicates,
                }
                for name, counts in self.report.tables.items()
            },
        }
        if reconciliation:
            payload.update(jsonable(reconciliation))
        self.report.reconciliation = payload

        self._write_issues()

        finished_at = utcnow()
        job.rows_read = self._rows_read
        job.rows_created = sum(counts.created for counts in self.report.tables.values())
        job.rows_updated = sum(counts.updated for counts in self.report.tables.values())
        job.rows_skipped = self._rows_skipped
        job.rows_failed = len(self.report.errors)
        job.reconciliation = payload
        job.territory_match_report = jsonable(territory) if territory else None
        job.finished_at = finished_at
        job.status = ImportStatus.DRY_RUN if self.dry_run else ImportStatus.SUCCEEDED
        self.session.flush()

        self.report.duration_seconds = (finished_at - self._started_at).total_seconds()

        if self.dry_run:
            # Отчёт уже целиком собран в памяти, поэтому откат ничего из него
            # не забирает. В базе при этом не остаётся ни задания, ни строк,
            # ни замечаний — а все ограничения, типы и внешние ключи успели
            # проверить настоящие вставки.
            self.session.rollback()

        return self.report

    def fail(self, error: BaseException) -> None:
        """Пометить задание упавшим.

        Вызывается до отката транзакции, поэтому запись всё равно исчезнет;
        смысл в том, чтобы состояние задания в памяти совпадало с отчётом,
        который увидит оператор.
        """
        self.report.error = str(error)
        if self.job is not None:
            self.job.status = ImportStatus.FAILED
            self.job.error_message = str(error)
            self.job.finished_at = utcnow()


__all__ = [
    "MAX_BIND_PARAMS",
    "MAX_ISSUE_SAMPLES",
    "NAMESPACE",
    "ControlCheck",
    "IssueRecord",
    "LayerJob",
    "LayerReport",
    "TerritoryIndex",
    "UpsertCounts",
    "bulk_upsert",
    "check_controls",
    "explanation_ru",
    "factors_payload",
    "jsonable",
    "load_territory_index",
    "risk_payload",
    "stable_id",
    "table_of",
]
