"""Загрузка данных слоёв 8.3–8.7 в PostgreSQL.

    python -m scripts.load_layers --layer all
    python -m scripts.load_layers --layer 8.5
    python -m scripts.load_layers --layer all --dry-run

Импортёры книг уже умеют читать источники и считать риск; этот скрипт
добавляет запись. Общая механика — происхождение, upsert пачками, журнал
качества, задание импорта — живёт в :mod:`app.importers.persistence`, здесь
только предметная часть каждого слоя.

Три правила, общие для всех пяти загрузчиков.

**Риск считает загрузчик, а не книга.** Все баллы получены через
`app.risk.core.evaluate` из значений индикаторов. Это не перестраховка: в
книге 8.5 все 10 240 формул лежат без кэша и читаются как `None`, а расчётные
листы 8.4 и 8.6 — статические экспорты вовсе без формул. Значения книги
используются только как контрольные и сверяются после загрузки.

**Территория берётся из справочника или не берётся вовсе.** Название,
которого нет в таблице алиасов, оставляет `territory_id` пустым и попадает в
журнал с кодом `territory_not_resolved`. Подставить «похожий» район означало
бы приписать чужие деньги чужой территории.

**Сухой прогон выполняет всё и откатывает.** Все ограничения базы, типы и
внешние ключи проверяются по-настоящему; в базе не остаётся ни задания, ни
строк, ни замечаний.

Код возврата: 0 — успех; 1 — не сошёлся контроль либо есть замечания уровня
ERROR; 2 — загрузка упала. Ненулевой код при расхождении контроля нужен,
чтобы запуск из планировщика не считался успешным только потому, что скрипт
не упал.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.budget import BudgetMonthlyMetric, BudgetProgram
from app.db.models.infrastructure import (
    ConstructionExpertiseObject,
    ParticipantRole,
    PppProject,
    ProjectEntity,
    ProjectEntityKind,
    ProjectParticipant,
    TerritoryPrecision,
)
from app.db.models.organization import (
    Identifier,
    IdentifierKind,
    Organization,
    TerritoryStatus,
)
from app.db.models.procurement import (
    Contract,
    ContractAddition,
    Customer,
    Lot,
    Procurement,
    Supplier,
)
from app.db.models.source import IssueSeverity
from app.db.models.subsidy import SubsidyPayment, SubsidyProgram, SubsidyRecipient
from app.db.session import session_scope
from app.importers import budget_8_3 as budget
from app.importers import infrastructure_8_6 as infra
from app.importers import organizations_8_7 as orgs
from app.importers import procurement_8_4 as procurement
from app.importers import subsidies_8_5 as subsidies
from app.importers.persistence import (
    IssueRecord,
    LayerJob,
    LayerReport,
    TerritoryIndex,
    check_controls,
    explanation_ru,
    factors_payload,
    load_territory_index,
    risk_payload,
    stable_id,
    table_of,
)
from app.risk.core import RiskResult
from app.risk.layers.budget import BUDGET_8_3, rank_within_month
from app.risk.layers.infrastructure import (
    evaluate_expertise_conclusion,
    evaluate_ppp_project,
)
from app.risk.layers.organizations import ORGANIZATION_MODEL, evaluate_organization
from app.risk.layers.organizations import preliminary_level as org_preliminary_level
from app.risk.layers.procurement import PROCUREMENT_8_4, evaluate_contract
from app.risk.layers.subsidies import METHODOLOGY_SHEET as SUBSIDIES_METHODOLOGY_SHEET
from app.services.territory_resolver import normalize_territory_name

# --- Контрольные значения ----------------------------------------------------
# Числа взяты из аудита книг. Допуск задаётся отдельно и не по вкусу: счётчики
# сверяются точно, максимальные баллы — с точностью до десятой (аудит округляет
# их до одного знака), денежные суммы — до копейки.

SCORE_TOLERANCE: Final[float] = 0.05
"""Допуск для максимального балла: аудит приводит его округлённым до 0,1."""

MONEY_TOLERANCE: Final[float] = 1.0
"""Допуск для контрольных сумм: аудит приводит их без дробной части."""

CONTROLS_8_3: Final[dict[str, float]] = {
    "monthly_rows": 240,
    "max_score": 75.0,
    "level_low": 187,
    "level_medium": 52,
    "level_high": 0,
    "level_critical": 1,
}

CONTROLS_8_4: Final[dict[str, float]] = {
    "contracts": 355,
    "max_score": 67.1,
    "level_low": 89,
    "level_medium": 172,
    "level_high": 43,
    "level_critical": 48,
    "level_unknown": 3,
    "total_amount": 7_198_964_138.99,
}

CONTROLS_8_5: Final[dict[str, float]] = {
    "recipients": 3413,
    "payments": 21521,
    "total_amount": 67_535_553_445,
    "max_score": 72.095,
    "level_low": 3344,
    "level_medium": 67,
    "level_high": 2,
    "level_critical": 0,
}

CONTROLS_8_6: Final[dict[str, float]] = {
    "ppp_projects": 1323,
    "ppp_max_score": 85.7,
    "ppp_level_low": 1066,
    "ppp_level_medium": 141,
    "ppp_level_high": 44,
    "ppp_level_critical": 8,
    "ppp_level_unknown": 64,
    "expertise_conclusions": 4842,
    "expertise_max_score": 67.1,
    "expertise_level_low": 4221,
    "expertise_level_medium": 567,
    "expertise_level_high": 54,
}

CONTROLS_8_7: Final[dict[str, float]] = {
    "organizations": 3668,
    "max_score": 93.3,
    "strict_level_unknown": 3645,
    "strict_level_critical": 23,
}

_SCORE_METRICS: Final[frozenset[str]] = frozenset(
    {"max_score", "ppp_max_score", "expertise_max_score"}
)
_MONEY_METRICS: Final[frozenset[str]] = frozenset({"total_amount"})


def _tolerances(expected: Mapping[str, float]) -> dict[str, float]:
    """Допуск на каждый контроль: счётчики точно, баллы и суммы — с запасом."""
    limits: dict[str, float] = {}
    for name in expected:
        if name in _SCORE_METRICS:
            limits[name] = SCORE_TOLERANCE
        elif name in _MONEY_METRICS:
            limits[name] = MONEY_TOLERANCE
    return limits


def level_counts(results: Iterable[RiskResult]) -> dict[str, float]:
    """Распределение по уровням в терминах контрольных значений."""
    counter = Counter(str(result.level) for result in results)
    return {f"level_{level}": float(counter.get(level, 0)) for level in
            ("low", "medium", "high", "critical", "unknown")}


def max_score(results: Iterable[RiskResult]) -> float:
    scores = [result.score for result in results if result.score is not None]
    return max(scores) if scores else 0.0


# --- Мелкие преобразования ---------------------------------------------------


def dec(value: float | Decimal | None, *, places: int | None = None) -> Decimal | None:
    """Число в Decimal для колонок NUMERIC.

    Через `str()`, а не напрямую из float: `Decimal(0.1)` даёт
    `0.1000000000000000055511151231257827`, и такая величина уже не совпадает
    с контрольной суммой книги до копейки.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        result = value
    else:
        if value != value or value in (float("inf"), float("-inf")):  # NaN и бесконечности
            return None
        result = Decimal(str(value))
    if places is not None:
        result = round(result, places)
    return result


def parse_dmy(text: str) -> dt.date | None:
    """Дата из строки «12.06.2026». В книге 8.6 это текст, а не дата."""
    parts = text.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return dt.date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None


class Truncator:
    """Обрезка значений под длину колонки с учётом факта обрезки.

    Молча подрезать нельзя: обрезанное наименование перестаёт совпадать с
    источником, и по нему уже не найти строку в книге. Поэтому каждый случай
    считается и попадает в журнал качества одним сводным замечанием на поле.
    """

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def fit(self, value: str | None, length: int, field: str) -> str | None:
        if value is None:
            return None
        if len(value) <= length:
            return value
        self.counts[field] += 1
        return value[:length]

    def issues(self) -> list[IssueRecord]:
        return [
            IssueRecord(
                severity=IssueSeverity.WARNING,
                code="value_truncated",
                message=(
                    f"Поле {field}: {count} значений длиннее колонки и сохранены "
                    f"обрезанными. Полное значение осталось только в источнике."
                ),
                column_name=field,
                context={"rows_affected": count},
            )
            for field, count in self.counts.most_common()
        ]


def summarize_issues(records: Sequence[Any], *, limit: int = 5) -> list[IssueRecord]:
    """Свернуть построчные замечания импортёра в сводные — по коду и колонке.

    Импортёр 8.5 выдаёт замечание на каждую проблемную строку, и на 21 521
    выплате это десятки тысяч одинаковых сообщений. В журнал идёт по одному
    замечанию на пару «код + колонка» с числом строк и примерами адресов:
    смысл сохраняется, объём становится читаемым.
    """
    grouped: dict[tuple[str, str | None, str], list[Any]] = defaultdict(list)
    for record in records:
        grouped[(record.code, record.column_name, str(record.severity))].append(record)

    result: list[IssueRecord] = []
    for (code, column, severity), items in grouped.items():
        first = items[0]
        result.append(
            IssueRecord(
                severity=IssueSeverity(severity),
                code=code,
                message=f"{first.message} Затронуто строк: {len(items)}.",
                source_row_ref=first.source_row_ref,
                column_name=column,
                context={
                    "rows_affected": len(items),
                    "sample_rows": [item.source_row_ref for item in items[:limit]],
                },
            )
        )
    return result


def file_date(path: Path) -> dt.date:
    """Дата файла-источника как дата актуальности данных.

    Используется только там, где книга не содержит ни одной даты отчётного
    периода (слой 8.7). Это заведомо слабое утверждение — «данные не новее
    даты выгрузки», — и именно поэтому оно сопровождается замечанием, а не
    выдаётся за отчётную дату.
    """
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC).date()


# --- Слой 8.3: бюджетные риски -----------------------------------------------


def load_budget(session: Session, *, source_dir: Path, dry_run: bool = False) -> LayerReport:
    """Загрузить слой 8.3: справочник статей и расчёт «область × месяц».

    Сырьё (74 831 строка листа RAW_DATA) в этой загрузке **не сохраняется**, и
    это не упущение, а следствие ограничения схемы. Естественная единица
    бюджетной статьи — её путь в иерархии: одно и то же сочетание «код +
    наименование + уровень» встречается под разными родителями (например,
    «Управление водных ресурсов и ирригации области» лежит и под «Коммунальное
    хозяйство», и под «Водное хозяйство», и под «Сельское хозяйство»). Путей
    955, а ограничение `uq_budget_program_code_name_level` допускает 416
    строк; ключ факта `(program_id, территория, год, месяц)` при такой
    свёртке теряет 26 510 строк из 74 831. Записать две трети данных, выдав их
    за все, хуже, чем не записать: суммы по бюджету стали бы заниженными
    незаметно. Расхождение зафиксировано в сверке и в журнале качества.
    """
    job = LayerJob(session, layer_code="8.3", importer="budget_8_3", dry_run=dry_run)
    job.start()
    index = load_territory_index(session)
    truncator = Truncator()

    path = budget.resolve_workbook(source_dir)
    source = job.source_file(path)

    for problem in budget.check_parameters_match_model(path):
        job.issue(
            IssueSeverity.ERROR,
            "model_parameters_mismatch",
            f"Лист «Параметры» расходится с моделью: {problem}",
        )

    rows = budget.load_monthly_rows(path)
    results = budget.evaluate_rows(rows)
    ranks = rank_within_month(results)
    job.count_read(len(rows))

    # Дата актуальности выводится из самих данных — последний месяц расчёта, —
    # а не из даты запуска: путать «когда загрузили» и «на что данные» нельзя.
    periods = [budget.parse_period(row.inputs.period) for row in rows]
    last_month, last_year = max(periods, key=lambda pair: (pair[1], pair[0]))
    data_as_of = _end_of_month(last_year, last_month)

    # --- справочник статей ---------------------------------------------------
    facts = list(budget.iter_raw_facts(path))
    catalog = _budget_programs(facts)

    raw_dataset = job.dataset(
        source,
        sheet_name=budget.SHEET_RAW,
        role="raw",
        row_count=len(facts),
        data_as_of=data_as_of,
        header_row=1,
    )
    program_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for key, item in catalog.entries.items():
        code, name, level = key
        # Наименования статей доходят до 398 знаков, а `natural_key` —
        # `String(255)`. Идентификатор строки считается по полному ключу,
        # поэтому уникальность не страдает; в колонку едет обрезанная форма,
        # и сам факт обрезки попадает в журнал.
        natural_key = f"{code}|{name}|{level}"
        stored_key = truncator.fit(natural_key, 255, "budget_programs.natural_key")
        parent_key = catalog.parent_of.get(key)
        is_ambiguous = key in catalog.ambiguous
        program_rows[level].append(
            {
                "id": stable_id("budget_programs", natural_key),
                "code": None if code is None else str(code),
                "name": name,
                "level": level,
                "is_leaf": item["is_leaf"],
                "parent_id": (
                    None
                    if parent_key is None or is_ambiguous
                    else stable_id(
                        "budget_programs", f"{parent_key[0]}|{parent_key[1]}|{parent_key[2]}"
                    )
                ),
                "source_parent_code": item["parent_code"],
                **job.provenance(
                    raw_dataset,
                    natural_key=stored_key or natural_key,
                    source_row_ref=item["source_row_ref"],
                    data_as_of=data_as_of,
                    validation_status="warning" if is_ambiguous else "ok",
                    validation_notes=(
                        {
                            "parent_ambiguous": True,
                            "reason": (
                                "статья встречается под несколькими родителями; "
                                "родитель не проставлен, чтобы не выбирать за источник"
                            ),
                        }
                        if is_ambiguous
                        else None
                    ),
                ),
            }
        )
    # Уровень за уровнем: внешний ключ на родителя не отложенный, и родитель
    # обязан существовать к моменту вставки потомка.
    for level in sorted(program_rows):
        job.upsert(table_of(BudgetProgram), program_rows[level], label="budget_programs")

    if catalog.ambiguous:
        job.issue(
            IssueSeverity.WARNING,
            "program_parent_ambiguous",
            f"У {len(catalog.ambiguous)} статей из {len(catalog.entries)} родитель "
            f"различается между срезами «регион × месяц». Родитель не проставлен: "
            f"выбирать за источник по большинству голосов значило бы выдумать иерархию.",
            context={"programs_affected": len(catalog.ambiguous)},
        )

    job.count_skipped(len(facts))
    job.issue(
        IssueSeverity.ERROR,
        "schema_cannot_represent_source",
        (
            f"Лист RAW_DATA ({len(facts)} строк) не загружен: ограничение "
            f"uq_budget_program_code_name_level допускает {len(catalog.entries)} статей, "
            f"а различных путей в иерархии {catalog.stats['distinct_paths']}. "
            f"При свёртке к «код + наименование + уровень» ключ факта "
            f"(program_id, территория, период) теряет "
            f"{catalog.stats['rows_lost_by_schema_key']} строк из {len(facts)}. "
            f"Требуется решение по схеме: ключевать статью путём в иерархии."
        ),
        context=catalog.stats,
    )

    # --- расчёт «область × месяц» -------------------------------------------
    monthly_dataset = job.dataset(
        source,
        sheet_name=budget.SHEET_MONTHLY,
        role="raw",
        row_count=len(rows),
        data_as_of=data_as_of,
        header_row=1,
    )
    metric_rows: list[dict[str, Any]] = []
    for row, result in zip(rows, results, strict=True):
        raw = row.inputs.raw
        territory_id, _ = index.lookup(row.source_region_name, row_ref=row.source_row_ref)
        natural_key = f"{row.inputs.territory_id}|{row.inputs.period}"
        risk = result.risk
        metric_rows.append(
            {
                "id": stable_id("budget_monthly_metrics", natural_key),
                "territory_id": territory_id,
                "source_territory_code": row.inputs.territory_id,
                "source_region_name": truncator.fit(
                    row.source_region_name, 255, "source_region_name"
                ),
                "territory_name_normalized": normalize_territory_name(row.inputs.territory_name),
                "geo_level": row.geo_level,
                "parent_territory_code": row.parent_territory_id,
                "period": row.inputs.period,
                "period_month": row.inputs.month,
                "period_year": budget.parse_period(row.inputs.period)[1],
                "r01_revenue_execution": dec(raw.r01_dohody_ispolnenie),
                "r02_expense_execution": dec(raw.r02_zatraty_ispolnenie),
                "r04_revision_intensity": dec(raw.r04_intensivnost_utochneniy),
                "r05_profile_error": dec(raw.r05_oshibka_profilya),
                "r06_balance_deviation": dec(raw.r06_otklonenie_saldo),
                "r07_cash_buffer_months": dec(raw.r07_kassovyy_bufer),
                "r09_absorption_pressure": dec(raw.r09_davlenie_ostatka),
                "r10_commitment_lag": dec(raw.r10_otstavanie_obyazatelstv),
                "r11_unpaid_commitments": dec(raw.r11_neoplachennye_obyazatelstva),
                "r12_underexecution_width": dec(raw.r12_shirina_nedoispolneniya),
                "r13_expense_hhi": dec(raw.r13_hhi),
                "r14_financial_ops_deviation": dec(raw.r14_finansovye_operatsii),
                "r15_quality_flags": int(raw.r15_flagi_kachestva),
                "closing_balance": dec(row.inputs.closing_balance),
                "model_code": BUDGET_8_3.code,
                "model_version": BUDGET_8_3.version,
                "risk_score": dec(risk.score),
                "risk_level": str(risk.level),
                "rank_in_month": ranks.get(result.key),
                "data_completeness": dec(result.data_completeness, places=5),
                "indicator_completeness": dec(risk.completeness, places=5),
                "override_triggered": result.override_triggered,
                "missing_roots_flag": bool(row.missing_roots_flag),
                "factors": risk_payload(risk),
                "explanation_ru": _budget_explanation(risk),
                **job.provenance(
                    monthly_dataset,
                    natural_key=natural_key,
                    source_row_ref=row.source_row_ref,
                    data_as_of=data_as_of,
                    validation_status="warning" if row.missing_roots_flag else "ok",
                    validation_notes=(
                        {
                            "missing_roots_flag": row.missing_roots_flag,
                            "reason": "в срезе отсутствует корневой раздел книги",
                        }
                        if row.missing_roots_flag
                        else None
                    ),
                ),
            }
        )
    job.upsert(table_of(BudgetMonthlyMetric), metric_rows, label="budget_monthly_metrics")

    actual = {
        "monthly_rows": float(len(rows)),
        "max_score": max_score(item.risk for item in results),
        **level_counts(item.risk for item in results),
    }
    job.add_controls(
        check_controls(CONTROLS_8_3, actual, tolerances=_tolerances(CONTROLS_8_3))
    )
    job.extend_issues(index.issues())
    job.extend_issues(truncator.issues())
    job.report.territory = index.report()
    return job.finish(
        {
            "layer": "8.3",
            "raw_facts_not_loaded": catalog.stats,
            "programs_loaded": len(catalog.entries),
            "programs_with_ambiguous_parent": len(catalog.ambiguous),
            "data_as_of": data_as_of.isoformat(),
        }
    )


ProgramKey = tuple[int | None, str, int]
"""Статья в терминах ограничения `uq_budget_program_code_name_level`."""

MAX_HIERARCHY_DEPTH: Final[int] = 8
"""Предохранитель обхода вверх: уровней в книге пять, цикла быть не должно."""


@dataclass(frozen=True, slots=True)
class BudgetPrograms:
    """Справочник статей, восстановленный из листа RAW_DATA."""

    entries: dict[ProgramKey, dict[str, Any]]
    parent_of: dict[ProgramKey, ProgramKey | None]
    ambiguous: set[ProgramKey]
    stats: dict[str, int]


def _budget_programs(facts: Sequence[budget.BudgetRawFact]) -> BudgetPrograms:
    """Собрать справочник статей и восстановить иерархию по срезам.

    Родитель в источнике задан идентификатором строки, уникальным только
    внутри среза «регион × месяц». Поэтому сначала строится карта «срез +
    идентификатор → строка», и лишь потом по ней восстанавливаются связи.

    Статьи, у которых родитель различается между срезами, помечаются
    неоднозначными: у иерархии не бывает двух правильных ответов, и выбор по
    большинству голосов был бы выдумкой импортёра.

    Попутно считается, сколько различных **путей** в иерархии стоит за этими
    статьями. Именно эта величина показывает, что схема не вмещает источник:
    путей заметно больше, чем сочетаний «код + наименование + уровень».
    """
    by_slice: dict[tuple[str, str, int], budget.BudgetRawFact] = {
        (fact.region_source, fact.period, fact.source_id): fact for fact in facts
    }

    def key_of(fact: budget.BudgetRawFact) -> ProgramKey:
        return (fact.code, fact.name, fact.level)

    def path_of(fact: budget.BudgetRawFact) -> tuple[ProgramKey, ...]:
        chain: list[ProgramKey] = []
        cursor: budget.BudgetRawFact | None = fact
        for _ in range(MAX_HIERARCHY_DEPTH):
            if cursor is None:
                break
            chain.append(key_of(cursor))
            if cursor.parent_id is None:
                break
            cursor = by_slice.get((cursor.region_source, cursor.period, cursor.parent_id))
        return tuple(reversed(chain))

    entries: dict[ProgramKey, dict[str, Any]] = {}
    votes: dict[ProgramKey, set[ProgramKey | None]] = defaultdict(set)
    paths: set[tuple[ProgramKey, ...]] = set()
    slice_keys: set[tuple[str, str, ProgramKey]] = set()

    for position, fact in enumerate(facts, start=2):
        key = key_of(fact)
        if key not in entries:
            entries[key] = {
                "is_leaf": fact.is_leaf,
                "parent_code": fact.parent_code,
                "source_row_ref": f"{budget.SHEET_RAW}!A{position}",
            }
        parent = (
            by_slice.get((fact.region_source, fact.period, fact.parent_id))
            if fact.parent_id is not None
            else None
        )
        votes[key].add(None if parent is None else key_of(parent))
        slice_keys.add((fact.region_source, fact.period, key))
        paths.add(path_of(fact))

    ambiguous = {key for key, parents in votes.items() if len(parents) > 1}
    parent_of = {
        key: next(iter(parents)) for key, parents in votes.items() if len(parents) == 1
    }

    return BudgetPrograms(
        entries=entries,
        parent_of=parent_of,
        ambiguous=ambiguous,
        stats={
            "source_rows": len(facts),
            "distinct_paths": len(paths),
            "distinct_slice_keys": len(slice_keys),
            "rows_lost_by_schema_key": len(facts) - len(slice_keys),
            "programs_allowed_by_schema": len(entries),
        },
    )


def _end_of_month(year: int, month: int) -> dt.date:
    """Последний день месяца — дата, на которую актуален месячный срез."""
    first_of_next = dt.date(year + month // 12, month % 12 + 1, 1)
    return first_of_next - dt.timedelta(days=1)


def _budget_explanation(result: RiskResult) -> str:
    """Индикаторы с баллом не ниже 50 — так описан смысл колонки в модели."""
    strong = [
        f"{factor.code} {factor.name} ({(factor.value or 0.0) * 100:.0f})"
        for factor in result.measured_factors
        if (factor.value or 0.0) >= 0.5
    ]
    if not strong:
        return "Индикаторов с баллом 50 и выше нет."
    return "Индикаторы с баллом 50 и выше: " + "; ".join(strong)


# --- Слой 8.4: госзакупки ----------------------------------------------------


def load_procurement(session: Session, *, source_dir: Path, dry_run: bool = False) -> LayerReport:
    """Загрузить слой 8.4: поставщики, заказчики, объявления, лоты, договоры.

    Единица оценки — договор, и риск считается заново из значений метрик:
    расчётный лист книги формул не содержит вовсе, поэтому взять оттуда балл
    значило бы скопировать чужой результат, не проверив его.

    Поставщики заводятся только те, у которых есть договоры (26 из 3668
    организаций листа `organization_profile`). Остальные организации — предмет
    слоя 8.7, и дублировать их здесь незачем.
    """
    job = LayerJob(session, layer_code="8.4", importer="procurement_8_4", dry_run=dry_run)
    job.start()
    index = load_territory_index(session)
    truncator = Truncator()

    path = procurement.resolve_workbook(source_dir)
    source = job.source_file(path)
    book = procurement.load_workbook_8_4(path)

    # Листы `lots` и `lots_details` содержат мусорные строки-продолжения:
    # многострочная ячейка характеристики лота при выгрузке рассыпалась на
    # отдельные строки, где в колонке идентификатора объявления стоит текст
    # вроде «Объем тела котла». Признак настоящей строки — числовой
    # идентификатор объявления; таких ровно 358 на обоих листах.
    real_lots = [lot for lot in book.lots if lot.announcement_id.isdigit()]
    real_details = [detail for detail in book.lot_details if detail.announcement_id.isdigit()]
    junk_rows = (len(book.lots) - len(real_lots)) + (len(book.lot_details) - len(real_details))

    inputs = procurement.build_contract_inputs(book)
    results = [evaluate_contract(item) for item in inputs]
    job.count_read(len(book.calc_rows))

    data_as_of = _procurement_data_as_of(book)
    calc_dataset = job.dataset(
        source,
        sheet_name=procurement.SHEET_CALC,
        role="raw",
        row_count=len(book.calc_rows),
        data_as_of=data_as_of,
        header_row=procurement.CALC_HEADER_ROW,
    )
    # Лист сырых договоров регистрируется как набор данных, хотя строки
    # договоров ссылаются на расчётный лист: происхождение должно перечислять
    # все прочитанные листы, а не только те, чей адрес попал в строку.
    job.dataset(
        source,
        sheet_name=procurement.SHEET_CONTRACTS,
        role="raw",
        row_count=len(book.contracts),
        data_as_of=data_as_of,
        header_row=1,
    )
    lots_dataset = job.dataset(
        source,
        sheet_name=procurement.SHEET_LOTS,
        role="raw",
        row_count=len(book.lots),
        data_as_of=data_as_of,
        header_row=1,
    )
    additions_dataset = job.dataset(
        source,
        sheet_name=procurement.SHEET_ADDITIONS,
        role="raw",
        row_count=sum(len(items) for items in book.additions.values()),
        data_as_of=data_as_of,
        header_row=1,
    )
    profile_dataset = job.dataset(
        source,
        sheet_name=procurement.SHEET_ORGANIZATIONS,
        role="raw",
        row_count=len(book.organizations),
        data_as_of=data_as_of,
        header_row=1,
    )

    # --- поставщики ----------------------------------------------------------
    supplier_bins = sorted({calc.supplier_bin for calc in book.calc_rows})
    supplier_rows: list[dict[str, Any]] = []
    for supplier_bin in supplier_bins:
        profile = book.organizations.get(supplier_bin)
        address = book.addresses.get(supplier_bin)
        territory_id, _ = index.lookup(
            address.territory_name if address else None,
            row_ref=f"{procurement.SHEET_REGISTRY}!{supplier_bin}",
        )
        supplier_rows.append(
            {
                "id": stable_id("suppliers", supplier_bin),
                "bin": supplier_bin,
                "name": profile.name if profile else "",
                "in_rnu_gz": profile.in_rnu_gz if profile else False,
                "in_lzhepred_list": profile.in_lzhepred_list if profile else False,
                "no_physical_activity": profile.no_physical_activity if profile else False,
                "high_oked_diversity": profile.high_oked_diversity if profile else False,
                "mass_address": profile.mass_address if profile else False,
                "nominal_director": profile.nominal_director if profile else False,
                "n_contracts": _as_int(profile.n_contracts) if profile else None,
                "max_direct_one_customer": (
                    _as_int(profile.max_direct_one_customer) if profile else None
                ),
                "pct_terminated": dec(profile.pct_terminated) if profile else None,
                "layer_8_7_points": profile.final_points_v2 if profile else None,
                "layer_8_7_level": profile.final_risk_level_v2 if profile else None,
                "territory_id": territory_id,
                "legal_address_raw": address.raw if address else None,
                "region_source_name": truncator.fit(
                    address.region if address else None, 255, "suppliers.region_source_name"
                ),
                "district_source_name": truncator.fit(
                    address.territory_name if address else None,
                    255,
                    "suppliers.district_source_name",
                ),
                **job.provenance(
                    profile_dataset,
                    natural_key=supplier_bin,
                    source_row_ref=f"{procurement.SHEET_ORGANIZATIONS}!{supplier_bin}",
                    data_as_of=data_as_of,
                ),
            }
        )
    job.upsert(table_of(Supplier), supplier_rows, label="suppliers")

    # --- заказчики -----------------------------------------------------------
    # Имя из расчётного листа обрезано до 60 знаков, и разные заказчики в нём
    # неразличимы. Ключом служит полное имя из листа `lots`, а усечённое
    # хранится рядом, чтобы сверка с расчётным листом осталась возможной.
    bin_by_customer = {
        detail.customer_name: detail.customer_bin
        for detail in real_details
        if detail.customer_name and detail.customer_bin
    }
    truncated_by_customer: dict[str, str | None] = {}
    for calc in book.calc_rows:
        full = book.customer_of(calc.contract_id)
        if full is not None:
            truncated_by_customer.setdefault(full, calc.customer_truncated)

    customer_names = sorted({lot.customer for lot in real_lots if lot.customer})
    customer_rows = [
        {
            "id": stable_id("procurement_customers", name),
            "name": name,
            "name_truncated": truncated_by_customer.get(name),
            "bin": bin_by_customer.get(name),
            "is_placeholder": False,
            "territory_id": None,
            **job.provenance(
                lots_dataset,
                natural_key=truncator.fit(name, 255, "procurement_customers.natural_key") or name,
                source_row_ref=procurement.SHEET_LOTS,
                data_as_of=data_as_of,
            ),
        }
        for name in customer_names
    ]
    job.upsert(table_of(Customer), customer_rows, label="procurement_customers")

    # --- объявления и лоты ---------------------------------------------------
    # Общего поля у листов нет, но связь есть и она точная: номер лота начинается
    # с идентификатора лота («68150337-ОК1» ↔ «68150337»). На наличных данных
    # так сходятся все 358 строк из 358 — это join, а не догадка.
    details_by_lot = {
        (detail.announcement_id, detail.lot_id): detail
        for detail in real_details
        if detail.lot_id
    }

    procurement_rows: dict[str, dict[str, Any]] = {}
    lot_rows: list[dict[str, Any]] = []
    lots_by_announcement: dict[str, list[procurement.LotRow]] = defaultdict(list)

    for lot in real_lots:
        if lot.announcement_number is None:
            continue
        lots_by_announcement[lot.announcement_number].append(lot)
        procurement_rows.setdefault(
            lot.announcement_number,
            {
                "id": stable_id("procurements", lot.announcement_number),
                "announcement_id": lot.announcement_id,
                "announcement_number": lot.announcement_number,
                "customer_id": (
                    stable_id("procurement_customers", lot.customer) if lot.customer else None
                ),
                "submitted_bids": _as_int(lot.submitted_bids),
                **job.provenance(
                    lots_dataset,
                    natural_key=lot.announcement_number,
                    source_row_ref=f"{procurement.SHEET_LOTS}!{lot.announcement_id}",
                    data_as_of=data_as_of,
                ),
            },
        )

    unlinked_details = 0
    for announcement_number, items in lots_by_announcement.items():
        for position, lot in enumerate(items, start=1):
            detail = details_by_lot.get(
                (lot.announcement_id, (lot.lot_number or "").split("-")[0])
            )
            if detail is None:
                unlinked_details += 1
            natural_key = f"{announcement_number}#{lot.lot_number or position}"
            lot_rows.append(
                {
                    "id": stable_id("procurement_lots", natural_key),
                    "procurement_id": stable_id("procurements", announcement_number),
                    "lot_id": detail.lot_id if detail else None,
                    "lot_number": lot.lot_number,
                    "lot_name": lot.lot_name,
                    "lot_status": lot.lot_status,
                    "tru_code": detail.tru_code if detail else None,
                    "unit": None,
                    "quantity": None,
                    "unit_price": None,
                    "planned_sum": dec(lot.planned_sum, places=2),
                    "delivery_kato": detail.delivery_kato if detail else None,
                    "delivery_address": detail.delivery_address if detail else None,
                    **job.provenance(
                        lots_dataset,
                        natural_key=natural_key,
                        source_row_ref=f"{procurement.SHEET_LOTS}!{lot.announcement_id}",
                        data_as_of=data_as_of,
                    ),
                }
            )
    job.upsert(table_of(Procurement), list(procurement_rows.values()), label="procurements")
    job.upsert(table_of(Lot), lot_rows, label="procurement_lots")

    if junk_rows:
        job.issue(
            IssueSeverity.WARNING,
            "source_row_is_continuation",
            f"На листах `lots` и `lots_details` отброшено {junk_rows} строк-продолжений: "
            f"многострочная характеристика лота при выгрузке рассыпалась на отдельные "
            f"строки, и в колонке идентификатора объявления там стоит текст, а не номер.",
            context={"rows_dropped": junk_rows},
        )
    if unlinked_details:
        job.issue(
            IssueSeverity.INFO,
            "lot_details_not_linked",
            f"У {unlinked_details} лотов детали (КАТО места поставки, код ТРУ) не "
            f"привязаны: строки `lots_details` с таким идентификатором лота нет.",
            context={"lots_affected": unlinked_details},
        )

    # --- договоры ------------------------------------------------------------
    contract_rows: list[dict[str, Any]] = []
    addition_rows: list[dict[str, Any]] = []
    without_customer = 0
    for calc, item, result in zip(book.calc_rows, inputs, results, strict=True):
        contract = book.contracts.get(calc.contract_id)
        customer = book.customer_of(calc.contract_id)
        if customer is None:
            without_customer += 1
        territory_id, _ = index.lookup(calc.district, row_ref=calc.source_row_ref)
        risk = result.risk
        announcement = contract.announcement_number if contract else None
        contract_rows.append(
            {
                "id": stable_id("contracts", calc.contract_id),
                "contract_id": calc.contract_id,
                "supplier_id": stable_id("suppliers", calc.supplier_bin),
                "customer_id": (
                    stable_id("procurement_customers", customer) if customer else None
                ),
                "procurement_id": (
                    stable_id("procurements", announcement)
                    if announcement in procurement_rows
                    else None
                ),
                "brief_content_ru": contract.brief_content_ru if contract else None,
                "subject_type": contract.subject_type if contract else None,
                "planned_method": contract.planned_method if contract else calc.method,
                "actual_method": contract.actual_method if contract else None,
                "planned_amount": dec(contract.planned_amount, places=2) if contract else None,
                "final_amount": dec(calc.final_amount, places=2),
                "actual_amount": dec(contract.actual_amount, places=2) if contract else None,
                "planned_exec_date": contract.planned_exec_date if contract else None,
                "actual_exec_date": contract.actual_exec_date if contract else None,
                "contract_status": contract.contract_status if contract else None,
                "is_terminated": item.is_terminated,
                "territory_id": territory_id,
                "region_source_name": truncator.fit(
                    calc.region, 255, "contracts.region_source_name"
                ),
                "district_source_name": truncator.fit(
                    calc.district, 255, "contracts.district_source_name"
                ),
                "model_code": PROCUREMENT_8_4.code,
                "model_version": PROCUREMENT_8_4.version,
                "s_raw": dec(risk.raw_score, places=3),
                "w_avail": dec(risk.available_weight, places=2),
                "s_norm": dec(risk.normalized_score, places=3),
                "significance_multiplier": dec(result.significance_multiplier, places=2),
                "risk_score": dec(risk.score, places=3),
                "risk_level": str(risk.level),
                "completeness": dec(risk.completeness, places=5),
                "is_preliminary": risk.is_preliminary,
                "override_reason": truncator.fit(
                    risk.override_applied or None, 255, "contracts.override_reason"
                ),
                "indicator_values": {
                    code: value for code, value in item.indicators.items() if value is not None
                },
                "factors": risk_payload(risk),
                "explanation_ru": explanation_ru(risk),
                **job.provenance(
                    calc_dataset,
                    natural_key=calc.contract_id,
                    source_row_ref=calc.source_row_ref,
                    data_as_of=data_as_of,
                    validation_status="warning" if risk.is_preliminary else "ok",
                    validation_notes=(
                        {"reason": "полнота ниже порога, уровень серый"}
                        if risk.is_preliminary
                        else None
                    ),
                ),
            }
        )

        additions = sorted(
            book.additions.get(calc.contract_id, []),
            key=lambda addition: addition.creation_date or dt.date.min,
        )
        for sequence, addition in enumerate(additions, start=1):
            natural_key = f"{calc.contract_id}#{sequence}"
            addition_rows.append(
                {
                    "id": stable_id("contract_additions", natural_key),
                    "contract_id": stable_id("contracts", calc.contract_id),
                    "sequence_number": sequence,
                    "creation_date": addition.creation_date,
                    "conclusion_date": addition.conclusion_date,
                    "planned_exec_date": addition.planned_exec_date,
                    "final_total_amount": dec(addition.final_total_amount, places=2),
                    "actual_total_amount": dec(addition.actual_total_amount, places=2),
                    "justification": addition.justification,
                    "changes_term": addition.changes_term,
                    **job.provenance(
                        additions_dataset,
                        natural_key=natural_key,
                        source_row_ref=f"{procurement.SHEET_ADDITIONS}!{calc.contract_id}",
                        data_as_of=data_as_of,
                        # Пустое обоснование — не отрицание продления, а
                        # отсутствие сведений; метрика B5 из-за этого занижена
                        # по построению, и строка помечается как неполная.
                        validation_status="warning" if addition.justification is None else "ok",
                        validation_notes=(
                            {"reason": "обоснование пусто: признак продления срока неизвестен"}
                            if addition.justification is None
                            else None
                        ),
                    ),
                }
            )
    job.upsert(table_of(Contract), contract_rows, label="contracts")
    job.upsert(table_of(ContractAddition), addition_rows, label="contract_additions")

    if without_customer:
        job.issue(
            IssueSeverity.INFO,
            "customer_unknown",
            f"У {without_customer} договоров заказчик неизвестен: объявления нет "
            f"(закупка из одного источника или через электронный магазин), а в "
            f"расчётном листе на его месте стоит заглушка «—». Ссылка на заказчика "
            f"оставлена пустой — заглушка не является организацией.",
            context={"contracts_affected": without_customer},
        )

    actual = {
        "contracts": float(len(results)),
        "max_score": max_score(item.risk for item in results),
        "total_amount": float(sum(calc.final_amount or 0.0 for calc in book.calc_rows)),
        **level_counts(item.risk for item in results),
    }
    job.add_controls(
        check_controls(CONTROLS_8_4, actual, tolerances=_tolerances(CONTROLS_8_4))
    )
    job.extend_issues(index.issues())
    job.extend_issues(truncator.issues())
    job.report.territory = index.report()
    return job.finish(
        {
            "layer": "8.4",
            "suppliers": len(supplier_rows),
            "customers": len(customer_rows),
            "procurements": len(procurement_rows),
            "lots": len(lot_rows),
            "additions": len(addition_rows),
            "data_as_of": data_as_of.isoformat() if data_as_of else None,
        }
    )


def _as_int(value: float | None) -> int | None:
    """Целое из числа, записанного в источнике строкой вида «5.0»."""
    return None if value is None else int(value)


def _procurement_data_as_of(book: procurement.ProcurementWorkbook) -> dt.date | None:
    """Дата актуальности слоя 8.4 — самая поздняя дата в самих договорах.

    Книга не объявляет отчётной даты, поэтому она выводится из данных: позже
    последней известной даты договора эти сведения быть не могут.
    """
    dates: list[dt.date] = []
    for contract in book.contracts.values():
        dates.extend(
            value
            for value in (contract.planned_exec_date, contract.actual_exec_date)
            if value is not None
        )
    for items in book.additions.values():
        dates.extend(
            value
            for addition in items
            for value in (addition.conclusion_date, addition.planned_exec_date)
            if value is not None
        )
    return max(dates) if dates else None


# --- Слой 8.5: субсидии ------------------------------------------------------


def load_subsidies(session: Session, *, source_dir: Path, dry_run: bool = False) -> LayerReport:
    """Загрузить слой 8.5: программы, получатели, выплаты.

    Самый большой слой по числу строк — 21 521 выплата, — и единственный, где
    балл в книге вообще недоступен: все 10 240 формул лежат без кэша и
    читаются как `None`. Балл считается здесь через ядро расчёта, а «книжный»
    балл (пустая ячейка = ноль, как в Excel) сохраняется рядом отдельным
    полем — он нужен, чтобы доказать, что книга прочитана правильно, и не
    годится ни для чего другого.

    Сопоставитель территорий берётся из справочника проекта, а не из
    внутреннего перечня импортёра: в системе одна таблица алиасов, и вторая,
    зашитая в код, неизбежно с ней разойдётся. Следствие: районы, относящиеся
    к области Жетысу и другим областям, в справочнике второго уровня
    отсутствуют и остаются без территории — это состояние данных, а не сбой.
    """
    job = LayerJob(session, layer_code="8.5", importer=subsidies.IMPORTER_NAME, dry_run=dry_run)
    job.start()
    index = load_territory_index(session)
    truncator = Truncator()

    result = subsidies.run_import(source_dir=source_dir, resolver=index.resolver)
    source = job.source_file(result.source_path)
    job.count_read(len(result.recipients) + len(result.payments))

    data_as_of = _subsidies_data_as_of(result)

    # Лист методики регистрируется с ролью `model_config`: веса и пороги —
    # это описание того, как считать, а не данные для показа на карте.
    job.dataset(
        source,
        sheet_name=SUBSIDIES_METHODOLOGY_SHEET,
        role="model_config",
        row_count=len(result.methodology.weights),
        data_as_of=data_as_of,
    )
    recipients_dataset = job.dataset(
        source,
        sheet_name=subsidies.SHEET_RECIPIENTS,
        role="raw",
        row_count=len(result.recipients),
        data_as_of=data_as_of,
        header_row=subsidies.HEADER_ROW,
    )
    payments_dataset = job.dataset(
        source,
        sheet_name=subsidies.SHEET_DATA,
        role="raw",
        row_count=len(result.payments),
        data_as_of=data_as_of,
        header_row=subsidies.HEADER_ROW,
    )

    # --- программы -----------------------------------------------------------
    program_rows = [
        {
            "id": stable_id("subsidy_programs", program.code),
            "code": program.code,
            "name": program.name,
            "animal_type": truncator.fit(program.animal_type, 128, "subsidy_programs.animal_type"),
            **job.provenance(
                payments_dataset,
                natural_key=program.code,
                source_row_ref=f"{subsidies.SHEET_DATA}!SubsidiesName",
                data_as_of=data_as_of,
            ),
        }
        for program in result.programs
    ]
    job.upsert(table_of(SubsidyProgram), program_rows, label="subsidy_programs")

    # --- получатели ----------------------------------------------------------
    recipient_rows: list[dict[str, Any]] = []
    for row in result.recipients:
        territory_id, _ = index.lookup(row.territory_name_raw, row_ref=row.source_row_ref)
        risk = row.result
        recipient_rows.append(
            {
                "id": stable_id("subsidy_recipients", row.xin),
                "xin": row.xin,
                "name": row.name,
                "director_name": truncator.fit(
                    row.director_name, 255, "subsidy_recipients.director_name"
                ),
                "territory_id": territory_id,
                "territory_name_raw": truncator.fit(
                    row.territory_name_raw, 255, "subsidy_recipients.territory_name_raw"
                ),
                "territory_resolution": str(row.territory_status),
                "total_amount": dec(row.total_amount, places=2),
                "payments_count": row.payments_count,
                "programs_count": row.programs_count,
                "animal_types_count": row.animal_types_count,
                "district_share": dec(row.district_share, places=6),
                "oblast_share": dec(row.oblast_share, places=6),
                "affiliated_count": row.affiliated_count,
                "anomalous_payment_share": dec(row.anomalous_payment_share, places=6),
                "amount_outlier_share": dec(row.amount_outlier_share, places=6),
                "s1_concentration": row.indicators["s1"],
                "s2_repetition": row.indicators["s2"],
                "s3_affiliation": row.indicators["s3"],
                "s4_process_anomaly": row.indicators["s4"],
                "s5_amount_outlier": row.indicators["s5"],
                "model_code": risk.model_code,
                "model_version": risk.model_version,
                "risk_score": risk.score,
                "risk_level": str(risk.level),
                "risk_completeness": risk.completeness,
                "risk_exposure": dec(row.exposure, places=2),
                "book_risk_score": row.book_result.score,
                "book_risk_level": str(row.book_result.level),
                "book_risk_exposure": dec(row.book_exposure, places=2),
                "book_rank": row.book_rank,
                "factors": risk_payload(risk),
                **job.provenance(
                    recipients_dataset,
                    natural_key=row.xin,
                    source_row_ref=row.source_row_ref,
                    data_as_of=data_as_of,
                    validation_status="warning" if risk.unmeasured_factors else "ok",
                    validation_notes=(
                        {
                            "unmeasured": [
                                factor.code for factor in risk.unmeasured_factors
                            ],
                            "reason": "индикатор не рассчитан в книге; балл нормирован "
                            "на доступный вес",
                        }
                        if risk.unmeasured_factors
                        else None
                    ),
                ),
            }
        )
    job.upsert(table_of(SubsidyRecipient), recipient_rows, label="subsidy_recipients")

    # --- выплаты -------------------------------------------------------------
    known_recipients = {row.xin for row in result.recipients}
    payment_rows: list[dict[str, Any]] = []
    orphan_payments = 0
    for payment in result.payments:
        if payment.xin not in known_recipients:
            # Выплата без получателя в витрине — рассогласование внутри книги.
            # Строку некуда привязать: `recipient_id` обязателен по схеме.
            orphan_payments += 1
            continue
        territory_id, _ = index.lookup(payment.territory_name_raw, row_ref=payment.source_row_ref)
        payment_rows.append(
            {
                "id": stable_id("subsidy_payments", payment.bid_number),
                "recipient_id": stable_id("subsidy_recipients", payment.xin),
                "program_id": (
                    stable_id("subsidy_programs", payment.program_code)
                    if payment.program_code
                    else None
                ),
                "territory_id": territory_id,
                "territory_name_raw": truncator.fit(
                    payment.territory_name_raw, 255, "subsidy_payments.territory_name_raw"
                ),
                "bid_number": payment.bid_number,
                "bid_status": truncator.fit(payment.bid_status, 64, "subsidy_payments.bid_status"),
                "animal_type": truncator.fit(
                    payment.animal_type, 128, "subsidy_payments.animal_type"
                ),
                "positive_decision_at": payment.positive_decision_at,
                "executed_at": payment.executed_at,
                "local_payment_at": payment.local_payment_at,
                "republic_payment_at": payment.republic_payment_at,
                "subsidies_norm": dec(payment.subsidies_norm, places=2),
                "amount_local": dec(payment.amount_local, places=2),
                "amount_republic": dec(payment.amount_republic, places=2),
                "amount_owed": dec(payment.amount_owed, places=2),
                "amount_total": dec(payment.amount_total, places=2),
                "decision_to_payment_days": payment.decision_to_payment_days,
                "flag_paid_before_decision": payment.flag_paid_before_decision,
                "flag_abnormal_lag": payment.flag_abnormal_lag,
                "flag_amount_outlier": payment.flag_amount_outlier,
                **job.provenance(
                    payments_dataset,
                    natural_key=payment.bid_number,
                    source_row_ref=payment.source_row_ref,
                    data_as_of=data_as_of,
                ),
            }
        )
    job.upsert(table_of(SubsidyPayment), payment_rows, label="subsidy_payments")
    job.count_skipped(orphan_payments)
    if orphan_payments:
        job.issue(
            IssueSeverity.ERROR,
            "payment_without_recipient",
            f"{orphan_payments} выплат ссылаются на БИН/ИИН, которого нет в витрине "
            f"получателей. Строки не загружены: ссылка на получателя обязательна.",
            context={"rows_affected": orphan_payments},
        )

    actual = {
        "recipients": float(len(result.recipients)),
        "payments": float(len(result.payments)),
        "total_amount": float(sum(row.total_amount for row in result.recipients)),
        "max_score": max_score(row.result for row in result.recipients),
        **level_counts(row.result for row in result.recipients),
    }
    job.add_controls(
        check_controls(CONTROLS_8_5, actual, tolerances=_tolerances(CONTROLS_8_5))
    )
    # Замечания импортёра приходят построчными; в журнал они идут сводными, по
    # одному на пару «код + колонка». Замечания о территории заменяются на
    # сводку самого сопоставителя — иначе одно и то же было бы сказано дважды.
    job.extend_issues(
        summarize_issues(
            [item for item in result.issues if item.code != "territory_not_resolved"]
        )
    )
    job.extend_issues(index.issues())
    job.extend_issues(truncator.issues())
    job.report.territory = index.report()
    return job.finish(
        {
            "layer": "8.5",
            "weights": dict(result.methodology.weights),
            "weight_sum": result.methodology.weight_sum,
            "book_total_exposure": result.book_total_exposure,
            "total_exposure": result.total_exposure,
            "programs": len(program_rows),
            "data_as_of": data_as_of.isoformat() if data_as_of else None,
        }
    )


def _subsidies_data_as_of(result: subsidies.ImportResult) -> dt.date | None:
    """Дата актуальности слоя 8.5 — самая поздняя дата выплаты.

    Книга отчётной даты не объявляет; последняя фактическая выплата — это
    ровно та граница, дальше которой сведения не простираются.
    """
    stamps = [
        value
        for payment in result.payments
        for value in (
            payment.local_payment_at,
            payment.republic_payment_at,
            payment.executed_at,
        )
        if value is not None
    ]
    return max(stamps).date() if stamps else None


# --- Слой 8.6: инфраструктурные проекты --------------------------------------

DISTRICT_LEVELS: Final[frozenset[str]] = frozenset({"district", "city", "rural_okrug"})
"""Уровни справочника, которые считаются районной точностью привязки."""


def _probe_territory(
    index: TerritoryIndex, candidates: Sequence[str], *, row_ref: str
) -> tuple[uuid.UUID | None, TerritoryPrecision]:
    """Опознать территорию по ряду кандидатов «от частного к общему».

    Местоположение объекта экспертизы записано строкой вида «Республика
    Казахстан, <область>, <район>;», а для Алматинской области — одним лишь
    коротким названием района. Кандидаты пробуются молча, и только победивший
    (или, если не победил никто, самый частный) регистрируется в статистике —
    иначе одна строка источника считалась бы тремя попытками сопоставления.

    Точность выводится из уровня найденной территории, а не из позиции
    кандидата: «Алматы» — это регион, хотя стоит на месте района.
    """
    for candidate in candidates:
        probe = index.resolver.resolve(candidate)
        code = probe.territory_code
        if not probe.ok or code is None or code not in index.ids:
            continue
        territory_id, _ = index.lookup(candidate, row_ref=row_ref)
        level = index.levels.get(code, "")
        precision = (
            TerritoryPrecision.DISTRICT
            if level in DISTRICT_LEVELS
            else TerritoryPrecision.REGION
        )
        return territory_id, precision

    index.lookup(candidates[0] if candidates else None, row_ref=row_ref)
    return None, TerritoryPrecision.NONE


def _location_candidates(location_raw: str) -> list[str]:
    """Разложить строку местоположения на кандидатов от района к стране."""
    first = location_raw.split(";")[0]
    parts = [part.strip() for part in first.split(",") if part.strip()]
    if len(parts) <= 1:
        return parts
    return [parts[-1], *reversed(parts[:-1])]


def load_infrastructure(
    session: Session, *, source_dir: Path, dry_run: bool = False
) -> LayerReport:
    """Загрузить слой 8.6: проекты ГЧП и заключения строительной экспертизы.

    Две несвязанные популяции пишутся в общий супертип `project_entities` и в
    два подтипа. Общего ключа между ними нет — проверены все кандидаты, — и
    ничто в этой загрузке их не смешивает: у каждой популяции своя модель
    риска, свой полный вес методики (110 против 90) и свой набор индикаторов.

    Точность территории у проектов ГЧП принудительно «область»: районной
    привязки нет ни в одном из пяти исходных реестров, и ограничение
    `ck_ppp_project_territory_is_region` не даёт записать иначе.
    """
    job = LayerJob(
        session, layer_code="8.6", importer="infrastructure_8_6", dry_run=dry_run
    )
    job.start()
    index = load_territory_index(session)
    truncator = Truncator()

    path = infra.read_source_dir(source_dir)
    source = job.source_file(path)
    data_as_of = infra.BOOK_CALCULATION_DATE

    projects = infra.read_ppp_projects(path)
    conclusions = infra.read_expertise_conclusions(path)
    job.count_read(len(projects) + len(conclusions))

    ppp_dataset = job.dataset(
        source,
        sheet_name=infra.SHEET_PPP_RAW,
        role="raw",
        row_count=len(projects),
        data_as_of=data_as_of,
        header_row=infra.PPP_FIRST_DATA_ROW - 1,
    )
    expertise_dataset = job.dataset(
        source,
        sheet_name=infra.SHEET_EXPERTISE_RAW,
        role="raw",
        row_count=len(conclusions),
        data_as_of=data_as_of,
        header_row=1,
    )

    # --- проекты ГЧП ---------------------------------------------------------
    population = infra.PppPopulation(projects)
    ppp_results: list[RiskResult] = []
    entity_rows: list[dict[str, Any]] = []
    ppp_rows: list[dict[str, Any]] = []
    participant_rows: list[dict[str, Any]] = []

    for project in projects:
        values = population.indicator_values(project)
        significance_k = population.significance_k(project)
        risk = evaluate_ppp_project(
            values, significance_k=significance_k, has_data_error=project.has_date_error
        )
        ppp_results.append(risk)

        natural_key = f"ppp/{project.registry_number}"
        entity_id = stable_id("project_entities", natural_key)
        territory_id, _ = _probe_territory(
            index, [project.region_raw] if project.region_raw else [],
            row_ref=project.source_row_ref,
        )
        entity_rows.append(
            _entity_row(
                job,
                entity_id=entity_id,
                kind=ProjectEntityKind.PPP_PROJECT,
                title=project.title,
                territory_id=territory_id,
                territory_raw=project.region_raw,
                # Ограничение базы разрешает проектам ГЧП только «область»:
                # район здесь был бы заведомо выдуманной точностью.
                precision=TerritoryPrecision.REGION,
                has_data_error=project.has_date_error,
                data_error_note=(
                    "окончание строительства раньше начала" if project.has_date_error else None
                ),
                risk=risk,
                significance_k=significance_k,
                dataset=ppp_dataset,
                natural_key=natural_key,
                source_row_ref=project.source_row_ref,
                data_as_of=data_as_of,
                truncator=truncator,
            )
        )
        ppp_rows.append(
            {
                "id": entity_id,
                "registry_number": project.registry_number,
                "region_raw": project.region_raw,
                "project_level": truncator.fit(
                    project.project_level, 32, "ppp_projects.project_level"
                ),
                "sector": truncator.fit(project.sector, 255, "ppp_projects.sector"),
                "object_kind": truncator.fit(project.object_kind, 255, "ppp_projects.object_kind"),
                "status_raw": truncator.fit(project.status_raw, 255, "ppp_projects.status_raw"),
                "is_terminated": project.is_terminated,
                "initiative_kind": truncator.fit(
                    project.initiative_kind, 128, "ppp_projects.initiative_kind"
                ),
                "contract_kind": truncator.fit(
                    project.contract_kind, 255, "ppp_projects.contract_kind"
                ),
                "capacity": truncator.fit(project.capacity, 255, "ppp_projects.capacity"),
                "private_partner_raw": project.private_partner_raw,
                "private_partner_key": truncator.fit(
                    project.private_partner_key, 255, "ppp_projects.private_partner_key"
                ),
                "government_partner_raw": project.government_partner_raw,
                "government_partner_key": truncator.fit(
                    project.government_partner_key, 255, "ppp_projects.government_partner_key"
                ),
                "contract_date": project.contract_date,
                "construction_start": project.construction_start,
                "construction_end": project.construction_end,
                "operation_start": project.operation_start,
                "operation_end": project.operation_end,
                "cost_initial": dec(project.cost_initial, places=2),
                "investments": dec(project.investments, places=2),
                "government_participation_form": project.government_participation_form,
                # Номер конкурса связывает конкурсы с договорами ГЧП, но не с
                # реестром проектов: этого поля в реестре нет.
                "contest_number": None,
                "source_url": project.source_url,
                "a1_terminated": _value_of(values, "A1"),
                "a2_partner_termination_history": _value_of(values, "A2"),
                "a3_partner_region_concentration": _value_of(values, "A3"),
                "a4_gov_partner_concentration": _value_of(values, "A4"),
                "a5_construction_overdue": _value_of(values, "A5"),
                "a6_investment_growth": _value_of(values, "A6"),
                "a7_non_competitive": _value_of(values, "A7"),
                "significance_top_quartile_cost": population.is_top_quartile_cost(project),
                "significance_republican": project.is_republican,
            }
        )
        participant_rows.extend(
            _participant_rows(
                job,
                entity_id=entity_id,
                entity_key=natural_key,
                pairs=(
                    (ParticipantRole.PRIVATE_PARTNER, project.private_partner_raw),
                    (ParticipantRole.GOVERNMENT_PARTNER, project.government_partner_raw),
                ),
                dataset=ppp_dataset,
                source_row_ref=project.source_row_ref,
                data_as_of=data_as_of,
                truncator=truncator,
            )
        )

    # --- заключения экспертизы -----------------------------------------------
    expertise_population = infra.ExpertisePopulation(conclusions)
    expertise_results: list[RiskResult] = []
    expertise_rows: list[dict[str, Any]] = []

    for conclusion in conclusions:
        values = expertise_population.indicator_values(conclusion)
        significance_k = expertise_population.significance_k(conclusion)
        risk = evaluate_expertise_conclusion(values, significance_k=significance_k)
        expertise_results.append(risk)

        natural_key = f"expertise/{conclusion.registration_number}"
        entity_id = stable_id("project_entities", natural_key)
        territory_id, precision = _probe_territory(
            index,
            _location_candidates(conclusion.location_raw),
            row_ref=conclusion.source_row_ref,
        )
        identity_key = "|".join(conclusion.object_identity_key)
        entity_rows.append(
            _entity_row(
                job,
                entity_id=entity_id,
                kind=ProjectEntityKind.EXPERTISE_CONCLUSION,
                title=conclusion.title,
                territory_id=territory_id,
                territory_raw=conclusion.location_raw,
                precision=precision,
                has_data_error=False,
                data_error_note=None,
                risk=risk,
                significance_k=significance_k,
                dataset=expertise_dataset,
                natural_key=natural_key,
                source_row_ref=conclusion.source_row_ref,
                data_as_of=data_as_of,
                truncator=truncator,
            )
        )
        expertise_rows.append(
            {
                "id": entity_id,
                "registration_number": conclusion.registration_number,
                "registration_number_raw": conclusion.registration_number.lstrip("0") or "0",
                "conclusion_number": truncator.fit(
                    conclusion.conclusion_number,
                    32,
                    "construction_expertise_objects.conclusion_number",
                ),
                "external_id": conclusion.external_id,
                "issue_date": parse_dmy(conclusion.issue_date_raw),
                "object_identity_key": truncator.fit(
                    identity_key, 512, "construction_expertise_objects.object_identity_key"
                ),
                "customer_raw": conclusion.customer_raw,
                "customer_key": truncator.fit(
                    conclusion.customer_key, 512, "construction_expertise_objects.customer_key"
                ),
                "designer_raw": conclusion.designer_raw,
                "designer_key": truncator.fit(
                    conclusion.designer_key, 512, "construction_expertise_objects.designer_key"
                ),
                "location_raw": conclusion.location_raw,
                "work_kind": truncator.fit(
                    conclusion.work_kind, 255, "construction_expertise_objects.work_kind"
                ),
                "design_stage": truncator.fit(
                    conclusion.design_stage, 255, "construction_expertise_objects.design_stage"
                ),
                "industry": truncator.fit(
                    conclusion.industry, 512, "construction_expertise_objects.industry"
                ),
                "object_kind": truncator.fit(
                    conclusion.object_kind, 512, "construction_expertise_objects.object_kind"
                ),
                "funding_source": truncator.fit(
                    conclusion.funding_source, 255, "construction_expertise_objects.funding_source"
                ),
                "expertise_place": truncator.fit(
                    conclusion.expertise_place,
                    255,
                    "construction_expertise_objects.expertise_place",
                ),
                "capacity": truncator.fit(
                    conclusion.capacity, 64, "construction_expertise_objects.capacity"
                ),
                "capacity_unit": truncator.fit(
                    conclusion.capacity_unit, 64, "construction_expertise_objects.capacity_unit"
                ),
                "author_supervision_status": truncator.fit(
                    conclusion.author_supervision_status,
                    128,
                    "construction_expertise_objects.author_supervision_status",
                ),
                "has_cost_estimate": conclusion.has_cost_estimate,
                "technological_complexity": truncator.fit(
                    conclusion.technological_complexity,
                    128,
                    "construction_expertise_objects.technological_complexity",
                ),
                "responsibility_level": truncator.fit(
                    conclusion.responsibility_level,
                    128,
                    "construction_expertise_objects.responsibility_level",
                ),
                "hazard_class": truncator.fit(
                    conclusion.hazard_class, 64, "construction_expertise_objects.hazard_class"
                ),
                "category": truncator.fit(
                    conclusion.category, 64, "construction_expertise_objects.category"
                ),
                "efficiency_class": truncator.fit(
                    conclusion.efficiency_class,
                    64,
                    "construction_expertise_objects.efficiency_class",
                ),
                "full_set_cost": truncator.fit(
                    conclusion.full_set_cost, 64, "construction_expertise_objects.full_set_cost"
                ),
                "b1_design_correction": _value_of(values, "B1"),
                "b2_repeated_expertise": _value_of(values, "B2"),
                "b3_author_supervision": _value_of(values, "B3"),
                "b4_no_cost_estimate": _value_of(values, "B4"),
                "b5_designer_concentration": _value_of(values, "B5"),
                "b6_customer_correction_share": _value_of(values, "B6"),
                "significance_hazard_class": conclusion.is_high_hazard,
                "significance_responsibility": conclusion.is_first_responsibility_level,
            }
        )
        participant_rows.extend(
            _participant_rows(
                job,
                entity_id=entity_id,
                entity_key=natural_key,
                pairs=(
                    (ParticipantRole.CUSTOMER, conclusion.customer_raw),
                    (ParticipantRole.GENERAL_DESIGNER, conclusion.designer_raw),
                ),
                dataset=expertise_dataset,
                source_row_ref=conclusion.source_row_ref,
                data_as_of=data_as_of,
                truncator=truncator,
            )
        )

    # Супертип пишется первым: подтипы ссылаются на него внешним ключом.
    job.upsert(table_of(ProjectEntity), entity_rows, label="project_entities")
    job.upsert(table_of(PppProject), ppp_rows, label="ppp_projects")
    job.upsert(
        table_of(ConstructionExpertiseObject),
        expertise_rows,
        label="construction_expertise_objects",
    )
    job.upsert(table_of(ProjectParticipant), participant_rows, label="project_participants")

    contests = infra.read_contests(path)
    job.issue(
        IssueSeverity.INFO,
        "sheet_not_loaded",
        f"Листы конкурсов ({len(contests)} строк) и договоров ГЧП "
        f"({len(infra.read_contracts(path))} строк) не загружены: таблицы для них "
        f"в схеме нет, а привязать их к проекту нечем — общего ключа между реестром "
        f"проектов и конкурсами не существует.",
        context={"contests": len(contests)},
    )

    ppp_levels = level_counts(ppp_results)
    expertise_levels = level_counts(expertise_results)
    actual = {
        "ppp_projects": float(len(projects)),
        "ppp_max_score": max_score(ppp_results),
        **{f"ppp_{name}": value for name, value in ppp_levels.items()},
        "expertise_conclusions": float(len(conclusions)),
        "expertise_max_score": max_score(expertise_results),
        **{f"expertise_{name}": value for name, value in expertise_levels.items()},
    }
    job.add_controls(
        check_controls(CONTROLS_8_6, actual, tolerances=_tolerances(CONTROLS_8_6))
    )
    job.extend_issues(index.issues())
    job.extend_issues(truncator.issues())
    job.report.territory = index.report()
    return job.finish(
        {
            "layer": "8.6",
            "ppp_levels": ppp_levels,
            "expertise_levels": expertise_levels,
            "distinct_objects": expertise_population.distinct_objects(),
            "objects_with_repeated_expertise": (
                expertise_population.distinct_objects_with_repeated_expertise()
            ),
            "participants": len(participant_rows),
            "data_as_of": data_as_of.isoformat(),
        }
    )


def _value_of(values: Mapping[str, Any], code: str) -> float | None:
    """Нормированное значение индикатора либо None, если он не измерен."""
    item = values.get(code)
    return None if item is None else item.value


def _entity_row(
    job: LayerJob,
    *,
    entity_id: uuid.UUID,
    kind: ProjectEntityKind,
    title: str,
    territory_id: uuid.UUID | None,
    territory_raw: str | None,
    precision: TerritoryPrecision,
    has_data_error: bool,
    data_error_note: str | None,
    risk: RiskResult,
    significance_k: float,
    dataset: Any,
    natural_key: str,
    source_row_ref: str,
    data_as_of: dt.date,
    truncator: Truncator,
) -> dict[str, Any]:
    """Строка супертипа слоя 8.6 — общая часть обеих популяций."""
    return {
        "id": entity_id,
        "kind": str(kind),
        "title": title,
        "territory_id": territory_id,
        "territory_raw": territory_raw,
        "territory_precision": str(precision),
        "has_data_error": has_data_error,
        "data_error_note": data_error_note,
        "risk_model_code": risk.model_code,
        "risk_model_version": risk.model_version,
        "risk_raw_score": risk.raw_score,
        "risk_available_weight": risk.available_weight,
        "risk_normalized_score": risk.normalized_score,
        "risk_significance_k": significance_k,
        "risk_score": risk.score,
        "risk_completeness": risk.completeness,
        "risk_level": str(risk.level),
        "risk_is_preliminary": risk.is_preliminary,
        "risk_override_applied": truncator.fit(
            risk.override_applied or None, 255, "project_entities.risk_override_applied"
        ),
        "risk_factors": factors_payload(risk),
        "risk_notes": list(risk.notes),
        **job.provenance(
            dataset,
            natural_key=natural_key,
            source_row_ref=source_row_ref,
            data_as_of=data_as_of,
            validation_status="warning" if has_data_error or risk.is_preliminary else "ok",
            validation_notes=(
                {
                    "has_data_error": has_data_error,
                    "is_preliminary": risk.is_preliminary,
                    "unmeasured": [factor.code for factor in risk.unmeasured_factors],
                }
                if has_data_error or risk.is_preliminary
                else None
            ),
        ),
    }


def _participant_rows(
    job: LayerJob,
    *,
    entity_id: uuid.UUID,
    entity_key: str,
    pairs: Sequence[tuple[ParticipantRole, str | None]],
    dataset: Any,
    source_row_ref: str,
    data_as_of: dt.date,
    truncator: Truncator,
) -> list[dict[str, Any]]:
    """Участники объекта: частный и государственный партнёр либо заказчик и
    генпроектировщик.

    БИН не заполняется: в реестрах слоя 8.6 его нет ни у одного участника
    (0 из 1014 у поставщиков ГЧП, 0 из 4842 у экспертизы), а сопоставление по
    наименованию дало два совпадения из 809 × 769, то есть шум.
    """
    rows: list[dict[str, Any]] = []
    for role, name in pairs:
        if not name or not name.strip():
            continue
        natural_key = f"{entity_key}|{role}"
        rows.append(
            {
                "id": stable_id("project_participants", natural_key),
                "project_entity_id": entity_id,
                "role": str(role),
                "name_raw": name,
                "name_key": truncator.fit(
                    infra.squash(name) or name.strip(), 512, "project_participants.name_key"
                ),
                "bin": None,
                "bin_source": None,
                "is_consortium_member": False,
                **job.provenance(
                    dataset,
                    natural_key=natural_key,
                    source_row_ref=source_row_ref,
                    data_as_of=data_as_of,
                ),
            }
        )
    return rows


# --- Слой 8.7: организации ---------------------------------------------------


def load_organizations(
    session: Session, *, source_dir: Path, dry_run: bool = False
) -> LayerReport:
    """Загрузить слой 8.7: хозяйствующие субъекты.

    Территориальной привязки у этого слоя нет вовсе: ни района, ни адреса, ни
    КАТО, ни координат — ни на одном из десяти листов книги. Поэтому
    `territory_id` остаётся пустым у всех 3668 организаций, а
    `territory_status` явно равен «не определена». Это штатное состояние, а не
    неудача сопоставления, и путать их нельзя.

    Сохраняются два уровня риска. Строгий (по ТЗ 7.3, с учётом полноты) —
    официальный; предварительный (по одному баллу) показывается рядом с серым
    уровнем. Максимальная полнота по выборке — 40,9 % при пороге 50 %, поэтому
    строгий результат: 3645 серых и 23 критических по категории A.
    """
    job = LayerJob(
        session, layer_code="8.7", importer="organizations_8_7", dry_run=dry_run
    )
    job.start()
    truncator = Truncator()

    from scripts.source_manifest import resolve_source

    path = resolve_source(source_dir, orgs.SOURCE_FILE_NAME)
    source = job.source_file(path)
    rows = orgs.read_organizations(path)
    job.count_read(len(rows))

    # В книге нет ни одной даты отчётного периода — ни на одном из листов.
    # Дата файла означает лишь «не новее»; выдавать её за отчётную нельзя,
    # поэтому рядом стоит замечание.
    data_as_of = file_date(path)
    job.issue(
        IssueSeverity.INFO,
        "reporting_date_unknown",
        f"В книге слоя 8.7 нет отчётной даты ни на одном листе. В data_as_of "
        f"записана дата выгрузки файла ({data_as_of.isoformat()}): она означает "
        f"«сведения не новее этой даты», а не дату, на которую они собраны.",
    )

    dataset = job.dataset(
        source,
        sheet_name=orgs.RISK_SHEET,
        role="raw",
        row_count=len(rows),
        data_as_of=data_as_of,
        header_row=orgs.HEADER_ROW,
    )

    organization_rows: list[dict[str, Any]] = []
    identifier_rows: list[dict[str, Any]] = []
    results: list[RiskResult] = []
    restored = 0

    for row in rows:
        values = orgs.indicator_values(row)
        risk = evaluate_organization(values)
        results.append(risk)
        organization_id = stable_id("organizations", row.bin)
        restored += int(row.leading_zeros_restored)

        organization_rows.append(
            {
                "id": organization_id,
                "bin": row.bin,
                "name": truncator.fit(row.name, 512, "organizations.name") or row.name[:512],
                "full_name": row.name,
                "reg_date": None,
                "address_id": None,
                "territory_id": None,
                "territory_status": str(TerritoryStatus.NOT_DETERMINED),
                "oked_main": None,
                "oked_sections": None,
                "krp_code": None,
                "employees_count": None,
                "tax_paid_total": None,
                "tax_burden_ratio": None,
                "vat_registered": None,
                "licenses": None,
                # Исходных величин индикаторов в книге нет: лист «Расчёт рисков»
                # содержит уже приведённые v, а числа организаций по адресу,
                # секций ОКЭД и компаний у руководителя остались в CSV, которого
                # в комплекте нет. Поля остаются пустыми, а не заполняются
                # обратным пересчётом из v — это были бы выдуманные величины.
                "address_company_count": None,
                "director_company_count": None,
                "oked_sections_count": None,
                "no_physical_activity": None,
                "inactive_kkm_only": None,
                "in_rnu_gz": row.is_category_a,
                "rnu_start_date": None,
                "rnu_end_date": None,
                "in_rnu_quasi": None,
                "in_lzhepred_list": None,
                "director_in_lzhepred": None,
                "kgd_unreliable_lists": None,
                "is_category_a": row.is_category_a,
                "category_a_reasons": ["A1"] if row.is_category_a else None,
                "risk_model_code": ORGANIZATION_MODEL.code,
                "risk_model_version": ORGANIZATION_MODEL.version,
                "risk_raw_score": risk.raw_score,
                "risk_available_weight": risk.available_weight,
                "risk_score": risk.score,
                "risk_completeness": risk.completeness,
                "risk_level_preliminary": str(org_preliminary_level(risk)),
                "risk_level_strict": str(risk.level),
                "risk_is_preliminary": risk.is_preliminary,
                "risk_override_applied": truncator.fit(
                    risk.override_applied or None, 255, "organizations.risk_override_applied"
                ),
                "risk_factors": factors_payload(risk),
                "risk_notes": list(risk.notes),
                **job.provenance(
                    dataset,
                    natural_key=row.bin,
                    source_row_ref=row.source_row_ref,
                    data_as_of=data_as_of,
                    validation_status="warning" if row.leading_zeros_restored else "ok",
                    validation_notes=(
                        {
                            "bin_raw": row.bin_raw,
                            "reason": "БИН хранился числом, ведущие нули восстановлены",
                        }
                        if row.leading_zeros_restored
                        else None
                    ),
                ),
            }
        )
        identifier_key = f"bin|{row.bin}|{row.bin}"
        identifier_rows.append(
            {
                "id": stable_id("identifiers", identifier_key),
                "kind": str(IdentifierKind.BIN),
                "raw_value": row.bin_raw,
                "normalized_value": row.bin,
                "leading_zeros_restored": row.leading_zeros_restored,
                "organization_id": organization_id,
                "person_id": None,
                **job.provenance(
                    dataset,
                    natural_key=identifier_key,
                    source_row_ref=row.source_row_ref,
                    data_as_of=data_as_of,
                ),
            }
        )

    job.upsert(table_of(Organization), organization_rows, label="organizations")
    job.upsert(table_of(Identifier), identifier_rows, label="identifiers")

    job.issue(
        IssueSeverity.WARNING,
        "leading_zeros_restored",
        f"У {restored} БИН из {len(rows)} восстановлены ведущие нули: в книге "
        f"идентификатор хранится целым числом. Исходное написание сохранено "
        f"в таблице идентификаторов.",
        context={"rows_affected": restored},
    )
    job.issue(
        IssueSeverity.INFO,
        "territory_not_available",
        f"У всех {len(rows)} организаций территория не определена: в книге нет "
        f"ни района, ни адреса, ни КАТО, ни координат. Слой в текущем состоянии "
        f"на карту не выводится.",
        context={"rows_affected": len(rows)},
    )

    strict = level_counts(results)
    actual = {
        "organizations": float(len(rows)),
        "max_score": max_score(results),
        "strict_level_unknown": strict["level_unknown"],
        "strict_level_critical": strict["level_critical"],
    }
    job.add_controls(
        check_controls(CONTROLS_8_7, actual, tolerances=_tolerances(CONTROLS_8_7))
    )
    job.extend_issues(truncator.issues())
    job.report.territory = {
        "resolved": 0,
        "not_found": 0,
        "ambiguous": 0,
        "empty_in_source": len(rows),
        "distinct_unresolved_names": 0,
        "note": "слой не содержит территориальной привязки — это состояние источника",
    }
    return job.finish(
        {
            "layer": "8.7",
            "strict_levels": strict,
            "preliminary_levels": {
                f"level_{level}": count
                for level, count in Counter(
                    str(org_preliminary_level(item)) for item in results
                ).items()
            },
            "leading_zeros_restored": restored,
            "data_as_of": data_as_of.isoformat(),
        }
    )


# --- Точка входа -------------------------------------------------------------

Loader = Callable[..., LayerReport]

LOADERS: Final[dict[str, Loader]] = {
    "8.3": load_budget,
    "8.4": load_procurement,
    "8.5": load_subsidies,
    "8.6": load_infrastructure,
    "8.7": load_organizations,
}
"""Порядок словаря — порядок загрузки при `--layer all`.

Слои независимы друг от друга: общих внешних ключей между ними нет, все они
ссылаются только на справочник территорий. Порядок выбран по номеру слоя,
чтобы вывод читался предсказуемо.
"""


def load_layers(
    session: Session,
    *,
    layers: Sequence[str],
    source_dir: Path,
    dry_run: bool = False,
) -> list[LayerReport]:
    """Загрузить перечисленные слои.

    Слой откатывается сам, если это сухой прогон (см. `LayerJob.finish`),
    поэтому здесь остаётся только страховка на случай исключения посреди
    загрузки: наполовину записанный комплект хуже незаписанного — витрина
    покажет часть объектов и будет выглядеть исправной.
    """
    reports: list[LayerReport] = []
    try:
        for code in layers:
            reports.append(LOADERS[code](session, source_dir=source_dir, dry_run=dry_run))
    except Exception:
        session.rollback()
        raise
    return reports


def _print_report(report: LayerReport) -> None:
    print(report.summary_ru())

    if report.controls:
        print("  Сверка с контрольными значениями книги:")
        for control in report.controls:
            mark = "=" if control.matches else "≠"
            print(
                f"    {control.metric:<26} ожидалось {control.expected:>16,.2f} "
                f"{mark} получено {control.actual:>16,.2f}"
                + ("" if control.matches else f"  РАСХОЖДЕНИЕ {control.delta:+,.2f}")
            )

    territory = report.territory
    if territory:
        print(
            f"  Территории: сопоставлено {territory.get('resolved', 0)}, "
            f"не опознано {territory.get('not_found', 0)}, "
            f"неоднозначно {territory.get('ambiguous', 0)}, "
            f"пусто в источнике {territory.get('empty_in_source', 0)}"
        )
        unresolved = territory.get("unresolved_names") or []
        for item in unresolved[:10]:
            print(f"    не опознано: «{item['name']}» — строк {item['rows']}")
        if len(unresolved) > 10:
            print(f"    …ещё написаний: {len(unresolved) - 10}")

    for item in report.issues:
        if item.severity is IssueSeverity.ERROR:
            print(f"  [ОШИБКА] {item.code}: {item.message}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--layer",
        default="all",
        choices=[*LOADERS, "all"],
        help="какой слой загружать; по умолчанию все",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="выполнить и откатить: показать результат, ничего не записав",
    )
    parser.add_argument("--source-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    source_dir = args.source_dir or get_settings().source_data_dir
    layers = list(LOADERS) if args.layer == "all" else [args.layer]

    try:
        with session_scope() as session:
            reports = load_layers(
                session, layers=layers, source_dir=source_dir, dry_run=args.dry_run
            )
    # Оператору импорта нужен внятный отказ, а не трассировка: сообщения про
    # пропавший файл или несовпавшую книгу адресованы человеку.
    except Exception as error:
        print(f"Загрузка не выполнена: {error}", file=sys.stderr)
        return 2

    for report in reports:
        _print_report(report)

    failed = [control for report in reports for control in report.failed_controls]
    errors = [item for report in reports for item in report.errors]
    total = sum(report.rows_written for report in reports)
    seconds = sum(report.duration_seconds for report in reports)
    print(f"Итого строк: {total}, время {seconds:.1f} с")

    if failed:
        print(f"Не сошлось контрольных значений: {len(failed)}", file=sys.stderr)
    if errors:
        print(f"Замечаний уровня ERROR: {len(errors)}", file=sys.stderr)
    return 1 if failed or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTROLS_8_3",
    "CONTROLS_8_4",
    "CONTROLS_8_5",
    "CONTROLS_8_6",
    "CONTROLS_8_7",
    "LOADERS",
    "Truncator",
    "dec",
    "level_counts",
    "load_budget",
    "load_infrastructure",
    "load_layers",
    "load_organizations",
    "load_procurement",
    "load_subsidies",
    "main",
    "max_score",
    "parse_dmy",
    "summarize_issues",
]
