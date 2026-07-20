"""Сборка данных отчёта.

Отчёт в этой системе — документ, который ляжет на стол руководителю и
переживёт разговор, в котором его цифры будут оспаривать. Отсюда устройство
модуля.

**Отчёт строится по той же выборке, что список и карта.** Вход — `QuerySpec`,
тот же самый объект, что описывает состояние экрана. Иначе отчёт «по текущим
фильтрам» показывал бы не то, что видит пользователь, и расхождение обнаружили
бы в самый неподходящий момент.

**Значения форматируются здесь, а не в отрисовщике.** Ячейка отчёта — это
:class:`Cell`: готовый текст плюс, отдельно, настоящее число для Excel.
Отрисовщик числа не форматирует и `None` не интерпретирует. Причина
принципиальная: если отдать `None` в ячейку Word или Excel, там появится пустое
место, а пустое место в таблице читается как ноль. Три отрисовщика — три шанса
ошибиться одинаково; лучше принять решение один раз здесь.

**Отчёт обязан признаваться в собственной неполноте.** Выборка, в которую попали
объекты с серым уровнем или предварительным баллом, описывается числом в
отдельном разделе перед данными — до таблиц, а не в сноске под ними. Отчёт,
умалчивающий о неполноте, опаснее отсутствия отчёта: он выдаёт незнание за
благополучие.

**Формирование журналируется здесь же.** `build_report` пишет
`REPORT_GENERATED` сам, как `masking.reveal` сам пишет `SENSITIVE_VIEW`.
Вариант «журналировать в эндпоинте» работает ровно до первого нового
эндпоинта, автор которого про журнал забудет.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.queryspec import ObjectType, QuerySpec, SortField, SortOrder
from app.db.base import utcnow
from app.db.models.access import AuditAction, User
from app.db.models.infrastructure import (
    ConstructionExpertiseObject,
    PppProject,
    ProjectEntity,
)
from app.db.models.organization import (
    Organization,
    OrganizationPersonRole,
    PersonRoleKind,
)
from app.db.models.source import SourceDataset, SourceFile
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory
from app.risk.core import RiskLevel
from app.services import audit, catalog, masking
from app.services.audit import RequestContext
from app.services.catalog import ObjectCard

#: Единственный способ напечатать отсутствующее значение. Ни ноль, ни пустая
#: ячейка, ни прочерк: читатель отчёта должен видеть словами, что значения нет.
NO_DATA: Final = "нет данных"

#: Пометка предварительного балла. Ставится рядом с самим числом, а не в
#: легенде: легенду в распечатанной таблице никто не читает.
PRELIMINARY_MARK: Final = "предварительный"

#: Значение есть, но роль пользователя не позволяет его увидеть. Отличается от
#: `NO_DATA` намеренно — см. `app/services/masking.py`: «ИИН не заполнен» и
#: «вам не положено его видеть» это разные факты, и путать их нельзя.
CLOSED_BY_ROLE: Final = "доступ закрыт ролью"

#: Заголовок раздела о полноте. Вынесен в константу, потому что по нему
#: проверяют присутствие раздела и тесты, и отрисовщики.
WARNING_HEADING: Final = "Предупреждение о полноте данных"

#: Первая строка раздела, когда пробелы есть.
WARNING_MARKER: Final = "ВНИМАНИЕ: выборка неполна."

#: Первая строка раздела, когда пробелов нет. Раздел присутствует всегда:
#: отсутствие раздела читатель истолкует как «проверку не делали».
WARNING_CLEAN: Final = "Пробелов в оценках выборки не обнаружено."

#: Потолок строк, которые отчёт вытягивает из выборки. Выборка на миллион
#: записей не превращается в документ, который кто-то прочтёт, а попытка
#: собрать такой документ выведет из строя сервер. Усечение не скрывается —
#: о нём пишется в разделе о полноте.
MAX_REPORT_ROWS: Final = 5000

#: Размер страницы при вычитывании выборки. Совпадает с потолком `QuerySpec`.
_PAGE_SIZE: Final = 200

#: Сколько строк показывать в списковых таблицах отчёта.
_LIST_LIMIT: Final = 200

#: Сколько строк в «топах» — рейтингах и перечнях-выжимках.
_TOP_LIMIT: Final = 25


# --- Ячейка ------------------------------------------------------------------


def _money_format(unit: str) -> str:
    """Числовой формат Excel для денежной суммы.

    Единица подставляется в формат, а не приписывается к числу текстом: иначе
    ячейка перестаёт быть числом, и книгу нельзя ни отсортировать, ни сложить.
    """
    return '# ##0.00" ' + unit + '"'


@dataclass(frozen=True, slots=True)
class Cell:
    """Значение в таблице отчёта.

    `text` — то, что увидит человек, в любом из трёх форматов. `number` —
    то же значение числом, и только для Excel: в книге, которую откроют, чтобы
    отсортировать и просуммировать, числа обязаны быть числами.

    `number is None` при `is_missing=False` — законная комбинация: так
    выглядит предварительный балл. Число у него есть, но в столбец
    окончательных баллов его класть нельзя, иначе Excel просуммирует и усреднит
    несравнимое.
    """

    text: str
    number: float | None = None
    is_missing: bool = False
    number_format: str = ""
    """Формат числа для Excel. Пустая строка — формат по умолчанию.

    Задаётся здесь, а не в отрисовщике: доля 0,35 без формата «0,0%» в книге
    выглядит как тридцать пять сотых чего-то, и читатель книги увидел бы не то
    же самое, что читатель Word.
    """

    @staticmethod
    def missing() -> Cell:
        return Cell(text=NO_DATA, number=None, is_missing=True)

    @staticmethod
    def of(value: str | None) -> Cell:
        """Текстовое значение. Пустая строка — это тоже отсутствие значения."""
        if value is None or not value.strip():
            return Cell.missing()
        return Cell(text=value.strip())

    @staticmethod
    def whole(value: int | None) -> Cell:
        """Количество. Настоящий ноль печатается нулём — это не отсутствие."""
        if value is None:
            return Cell.missing()
        return Cell(text=f"{value:d}", number=float(value), number_format="0")

    @staticmethod
    def money(value: Decimal | float | None, unit: str = "₸") -> Cell:
        if value is None:
            return Cell.missing()
        amount = float(value)
        # Неразрывный пробел разделителем разрядов: иначе число переносится
        # по строке и «1 200» читается как две разные цифры.
        rendered = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
        return Cell(text=f"{rendered} {unit}", number=amount, number_format=_money_format(unit))

    @staticmethod
    def score(value: float | None, *, preliminary: bool = False) -> Cell:
        """Балл риска.

        Предварительный балл получает пометку в тексте и **не** получает
        числового представления. Смешивать его с окончательными в одном
        числовом столбце нельзя: полноты данных под ним не хватило, и любая
        арифметика по такому столбцу даст цифру, за которой ничего нет.
        """
        if value is None:
            return Cell.missing()
        rendered = f"{value:.1f}".replace(".", ",")
        if preliminary:
            return Cell(text=f"{rendered} ({PRELIMINARY_MARK})", number=None)
        return Cell(text=rendered, number=float(value), number_format="0.0")

    @staticmethod
    def percent(value: float | None) -> Cell:
        """Доля [0, 1] в процентах."""
        if value is None:
            return Cell.missing()
        return Cell(text=f"{value * 100:.0f}%", number=float(value), number_format="0%")

    @staticmethod
    def share(part: int, whole: int) -> Cell:
        """Доля части в целом.

        Доля от нуля не равна нулю — она не определена, и печатается как
        «нет данных». Ноль здесь означал бы «таких объектов нет», а объектов
        нет вообще никаких.
        """
        if whole <= 0:
            return Cell.missing()
        return Cell(
            text=f"{part / whole * 100:.1f}%".replace(".", ","),
            number=part / whole,
            number_format="0.0%",
        )

    @staticmethod
    def when(value: date | None) -> Cell:
        if value is None:
            return Cell.missing()
        return Cell(text=value.strftime("%d.%m.%Y"))


# --- Структура документа -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportColumn:
    """Колонка таблицы отчёта."""

    title: str
    numeric: bool = False
    """Выравнивать вправо и отдавать Excel числом, если оно есть."""

    width: float = 1.0
    """Относительная ширина — учитывается в PDF, где ширины задаются явно."""


@dataclass(frozen=True, slots=True)
class ReportTable:
    """Таблица отчёта."""

    title: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[tuple[Cell, ...], ...]
    note: str = ""
    """Пояснение под таблицей: чего в ней нет и почему."""

    @property
    def is_empty(self) -> bool:
        return not self.rows


@dataclass(frozen=True, slots=True)
class ReportSection:
    """Раздел отчёта: заголовок, текст, таблицы."""

    title: str
    paragraphs: tuple[str, ...] = ()
    tables: tuple[ReportTable, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Источник данных с датой актуальности.

    ТЗ (раздел 17) требует, чтобы выгруженный отчёт содержал источник данных.
    Одного названия мало: цифра без даты актуальности выдаёт прошлогоднее
    состояние за сегодняшнее, поэтому дата — обязательная часть ссылки, а её
    отсутствие называется вслух, а не оставляется пустым.
    """

    layer_code: str
    file_name: str
    sheet_names: tuple[str, ...]
    data_as_of: date | None
    row_count: int | None

    @property
    def as_of_text(self) -> str:
        if self.data_as_of is None:
            return f"{NO_DATA} (дата актуальности в источнике не указана)"
        return self.data_as_of.strftime("%d.%m.%Y")


@dataclass(frozen=True, slots=True)
class CompletenessWarning:
    """Признание отчёта в собственной неполноте."""

    total: int
    unknown_level: int
    """Объекты с серым уровнем: об их риске ничего не известно."""

    preliminary_score: int
    """Объекты, у которых балл есть, но полноты под ним не хватило."""

    without_territory: int
    """Объекты, которые не лягут ни на карту, ни в разрез по территориям."""

    truncated_to: int | None = None
    """Сколько строк реально прочитано, если выборка оказалась больше потолка."""

    @property
    def has_gaps(self) -> bool:
        return bool(self.unknown_level or self.preliminary_score or self.truncated_to)

    @property
    def lines(self) -> tuple[str, ...]:
        """Текст раздела. Каждый пробел назван числом, а не намёком."""
        if not self.has_gaps:
            return (
                WARNING_CLEAN,
                f"Уровень риска определён у всех объектов выборки ({self.total}); "
                f"предварительных баллов в выборке нет.",
            )

        lines: list[str] = [WARNING_MARKER]

        if self.unknown_level:
            lines.append(
                f"Из {self.total} объектов выборки у {self.unknown_level} уровень риска "
                f"не определён — «{RiskLevel.UNKNOWN.label_ru}». Это "
                f"{self.unknown_level / self.total * 100:.1f}% выборки, если считать "
                f"от общего числа объектов. Такие объекты НЕ являются благополучными: "
                f"о них ничего не известно, и выводы отчёта их не охватывают."
                if self.total
                else f"Объектов с неопределённым уровнем риска: {self.unknown_level}."
            )

        if self.preliminary_score:
            lines.append(
                f"У {self.preliminary_score} объектов балл предварительный: полноты "
                f"исходных данных не хватило для окончательного вывода. Такой балл "
                f"помечен в таблицах словом «{PRELIMINARY_MARK}», не участвует в "
                f"числовых столбцах и не сравним с окончательными баллами."
            )

        if self.without_territory:
            lines.append(
                f"У {self.without_territory} объектов не определена территория — "
                f"в разрезах по территориям они собраны в отдельную строку и на карту "
                f"не попадают."
            )

        if self.truncated_to is not None:
            lines.append(
                f"Выборка больше, чем помещается в отчёт: прочитано {self.truncated_to} "
                f"строк из {self.total}. Таблицы ниже построены по прочитанной части, "
                f"сводные показатели — по всей выборке. Сузьте фильтры, если нужен "
                f"пообъектный перечень целиком."
            )

        return tuple(lines)


@dataclass(frozen=True, slots=True)
class ReportDocument:
    """Готовые данные отчёта — то, что отрисовщик превращает в файл.

    Отрисовщик не ходит в базу и ничего не досчитывает. Всё, что попадёт в
    документ, решено здесь, и три формата одного отчёта гарантированно
    содержат одни и те же цифры.
    """

    template: ReportTemplate
    title: str
    subtitle: str
    generated_at: datetime
    generated_by_name: str
    generated_by_role: str
    filters: tuple[tuple[str, str], ...]
    sources: tuple[SourceRef, ...]
    warning: CompletenessWarning
    sections: tuple[ReportSection, ...]
    notes: tuple[str, ...] = ()

    @property
    def generated_at_text(self) -> str:
        """Дата и время формирования. Часовой пояс указывается явно.

        Без пояса время отчёта, собранного на сервере в UTC, читатель отнесёт
        к своему поясу и ошибётся на пять часов — ровно столько между UTC и
        Астаной.
        """
        return self.generated_at.strftime("%d.%m.%Y %H:%M") + " UTC"

    @property
    def file_stem(self) -> str:
        """Основа имени файла: кириллица, без расширения."""
        stamp = self.generated_at.strftime("%Y-%m-%d_%H-%M")
        return f"{self.title} {stamp}".replace("/", "-")


# --- Шаблоны -----------------------------------------------------------------


class ReportTemplate(StrEnum):
    """Восемь шаблонов ТЗ (раздел 17) и референса «Отчёты и экспорт».

    Коды в URL — латиницей и через дефис: они попадают в адресную строку и в
    сохранённые ссылки, а кириллический путь там переживает не всякий прокси.
    """

    REGION_SUMMARY = "region-summary"
    TERRITORY = "territory"
    ORGANIZATION = "organization"
    PROJECT = "project"
    INDUSTRY = "industry"
    RISK_CATEGORY = "risk-category"
    RATINGS = "ratings"
    HIGH_RISK = "high-risk"

    @property
    def label(self) -> str:
        """Название шаблона.

        Не `title`: `StrEnum` наследует `str`, у которого `title` — метод
        приведения регистра, и свойство с таким именем перекрыло бы его.
        """
        return TEMPLATE_TITLES[self][0]

    @property
    def description(self) -> str:
        return TEMPLATE_TITLES[self][1]


#: Названия и описания — дословно с референса, раздел 6 «Отчёты и экспорт».
TEMPLATE_TITLES: Final[dict[ReportTemplate, tuple[str, str]]] = {
    ReportTemplate.REGION_SUMMARY: (
        "Сводный отчёт по региону",
        "Общая аналитика по области с рейтингами и динамикой",
    ),
    ReportTemplate.TERRITORY: (
        "Отчёт по территории",
        "Детальный анализ района: бюджет, закупки, организации, риски",
    ),
    ReportTemplate.ORGANIZATION: (
        "Справка по организации",
        "Полное досье: риск, договоры, связи, история изменений",
    ),
    ReportTemplate.PROJECT: (
        "Отчёт по объекту/проекту",
        "Карточка проекта с финансами, участниками, индикаторами",
    ),
    ReportTemplate.INDUSTRY: (
        "Анализ по отрасли",
        "Сравнительная аналитика и риски по выбранной отрасли",
    ),
    ReportTemplate.RISK_CATEGORY: (
        "Отчёт по категории риска",
        "Объекты с критическим и высоким уровнем",
    ),
    ReportTemplate.RATINGS: (
        "Рейтинги территорий и отраслей",
        "Сравнительный рейтинг по ключевым индикаторам",
    ),
    ReportTemplate.HIGH_RISK: (
        "Перечень высокорисковых объектов",
        "Реестр с расшифровкой факторов",
    ),
}


#: Человекочитаемые названия типов объектов — для фильтров и разрезов.
OBJECT_TYPE_LABELS: Final[dict[ObjectType, str]] = {
    ObjectType.TERRITORY: "Территория",
    ObjectType.CONTRACT: "Договор госзакупок",
    ObjectType.SUBSIDY_RECIPIENT: "Получатель субсидий",
    ObjectType.PPP_PROJECT: "Проект ГЧП",
    ObjectType.EXPERTISE_OBJECT: "Заключение экспертизы",
    ObjectType.ORGANIZATION: "Организация",
}

#: Слой, из которого приходит объект каждого типа, — для перечня источников.
_TYPE_TO_LAYER: Final[dict[ObjectType, str]] = {
    ObjectType.TERRITORY: "8.1",
    ObjectType.CONTRACT: "8.4",
    ObjectType.SUBSIDY_RECIPIENT: "8.5",
    ObjectType.PPP_PROJECT: "8.6",
    ObjectType.EXPERTISE_OBJECT: "8.6",
    ObjectType.ORGANIZATION: "8.7",
}

#: Порядок уровней в таблицах: от самого тревожного к спокойному, «нет данных»
#: в конце — но всегда присутствует строкой, а не выпадает при нулевом счёте.
_LEVEL_ORDER: Final[tuple[RiskLevel, ...]] = (
    RiskLevel.CRITICAL,
    RiskLevel.HIGH,
    RiskLevel.MEDIUM,
    RiskLevel.LOW,
    RiskLevel.UNKNOWN,
)

_SORT_LABELS: Final[dict[SortField, str]] = {
    SortField.RISK: "по уровню риска",
    SortField.AMOUNT: "по сумме",
    SortField.RELEVANCE: "по дате актуальности данных",
    SortField.NAME: "по наименованию",
}


# --- Сводка по выборке -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectionStats:
    """Показатели всей выборки, а не прочитанной страницы.

    Считаются агрегатом в базе. Считать их по прочитанным строкам было бы
    ошибкой: при усечении выборки предупреждение о неполноте назвало бы
    заниженное число, то есть соврало бы ровно в том месте, ради которого
    оно существует.
    """

    total: int
    by_level: Mapping[RiskLevel, int]
    preliminary_score: int
    without_territory: int


def selection_stats(
    session: Session,
    spec: QuerySpec,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
) -> SelectionStats:
    """Агрегаты по всей выборке."""
    by_level = catalog.level_counts(
        session, spec, allowed_territory_ids=allowed_territory_ids
    )

    # `build_query` отдаёт и запрос, и подзапрос с нормализованными колонками.
    # Нам нужен запрос целиком: агрегаты считаются по той же выборке со всеми
    # её условиями, а не по одному лишь UNION слоёв.
    statement, _ = catalog.build_query(
        spec.without_pagination(), allowed_territory_ids=allowed_territory_ids
    )
    subquery = statement.subquery("selection")

    # Предварительным считается балл, который есть: строка без балла попадает в
    # «нет данных» и учитывается там, а не дважды.
    preliminary = func.count().filter(
        subquery.c.risk_is_preliminary.is_(True),
        subquery.c.risk_score.is_not(None),
    )
    no_territory = func.count().filter(subquery.c.territory_id.is_(None))

    row = session.execute(
        select(func.count(), preliminary, no_territory).select_from(subquery)
    ).one()

    return SelectionStats(
        total=int(row[0] or 0),
        by_level=by_level,
        preliminary_score=int(row[1] or 0),
        without_territory=int(row[2] or 0),
    )


def collect_cards(
    session: Session,
    spec: QuerySpec,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    limit: int = MAX_REPORT_ROWS,
) -> tuple[tuple[ObjectCard, ...], bool]:
    """Вычитать выборку целиком, а не одну страницу.

    Возвращает карточки и признак усечения. Постраничность `QuerySpec`
    относится к экрану; отчёт по одной странице был бы отчётом по случайному
    подмножеству, о чём читатель не догадался бы.
    """
    collected: list[ObjectCard] = []
    page = 1

    while len(collected) < limit:
        chunk_spec = spec.model_copy(update={"page": page, "page_size": _PAGE_SIZE})
        cards, _ = catalog.list_objects(
            session, chunk_spec, allowed_territory_ids=allowed_territory_ids
        )
        if not cards:
            return tuple(collected), False
        collected.extend(cards)
        if len(cards) < _PAGE_SIZE:
            return tuple(collected[:limit]), False
        page += 1

    return tuple(collected[:limit]), True


# --- Фильтры человекочитаемо -------------------------------------------------


def describe_filters(
    session: Session,
    spec: QuerySpec,
    *,
    scope_territory_name: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Применённые фильтры словами, а не JSON.

    ТЗ требует, чтобы отчёт содержал применённые фильтры. Читатель отчёта —
    руководитель, а не разработчик, и `{"risk_levels":["high"]}` для него не
    сведения, а шум. Поэтому здесь каждый фильтр разворачивается в пару
    «название → значение», а коды территорий подменяются их названиями из
    справочника.
    """
    described: list[tuple[str, str]] = []

    if spec.year:
        described.append(("Период", f"{spec.year} год"))
    elif spec.date_from or spec.date_to:
        start = spec.date_from.strftime("%d.%m.%Y") if spec.date_from else "не ограничено"
        end = spec.date_to.strftime("%d.%m.%Y") if spec.date_to else "не ограничено"
        described.append(("Период", f"с {start} по {end}"))

    if spec.compare_to_from or spec.compare_to_to:
        start = (
            spec.compare_to_from.strftime("%d.%m.%Y") if spec.compare_to_from else "не ограничено"
        )
        end = spec.compare_to_to.strftime("%d.%m.%Y") if spec.compare_to_to else "не ограничено"
        described.append(("Период сравнения", f"с {start} по {end}"))

    if spec.territory_codes:
        described.append(("Территории", _territory_names(session, spec.territory_codes)))
        described.append(
            (
                "Вложенные территории",
                "включены" if spec.include_child_territories else "не включены",
            )
        )

    if spec.object_types:
        names = ", ".join(OBJECT_TYPE_LABELS.get(t, str(t)) for t in spec.object_types)
        described.append(("Типы объектов", names))

    for label, values in (
        ("Слои", spec.layers),
        ("Отрасли", spec.industries),
        ("Источники", spec.sources),
        ("Статусы", spec.statuses),
        ("Заказчики", spec.customer_ids),
        ("Поставщики", spec.supplier_ids),
        ("Получатели поддержки", spec.recipient_ids),
    ):
        if values:
            described.append((label, ", ".join(values)))

    if spec.amount_min is not None or spec.amount_max is not None:
        low = f"{spec.amount_min:,.0f}".replace(",", " ") if spec.amount_min else "0"
        high = (
            f"{spec.amount_max:,.0f}".replace(",", " ")
            if spec.amount_max is not None
            else "без верхней границы"
        )
        described.append(("Сумма", f"от {low} до {high} ₸"))

    # Уровни риска описываются всегда, но «все уровни» — это умолчание, а не
    # применённый фильтр. Строка нужна читателю, а вот считать по ней выборку
    # отфильтрованной нельзя: иначе фраза «фильтры не применялись» не появится
    # никогда, и её отсутствие перестанет что-либо значить.
    levels_line: tuple[str, str]
    if set(spec.risk_levels) == set(RiskLevel):
        levels_line = (
            "Уровни риска",
            "все уровни, включая «" + RiskLevel.UNKNOWN.label_ru + "»",
        )
    else:
        names = ", ".join(level.label_ru for level in _LEVEL_ORDER if level in spec.risk_levels)
        # Отсутствие серого уровня в фильтре — важное для читателя
        # обстоятельство: отчёт заведомо не видит объектов без оценки.
        suffix = (
            ""
            if spec.includes_unknown_risk
            else "; объекты без оценки риска в отчёт НЕ включены"
        )
        levels_line = ("Уровни риска", names + suffix)
        described.append(levels_line)

    if spec.completeness_min is not None or spec.completeness_max is not None:
        low = f"{(spec.completeness_min or 0) * 100:.0f}%"
        high = f"{(spec.completeness_max or 1) * 100:.0f}%"
        described.append(("Полнота данных", f"от {low} до {high}"))

    if spec.only_category_a:
        described.append(("Категория", "только объекты категории A"))

    if spec.search:
        described.append(("Поисковый запрос", spec.search))

    if not described:
        described.append(
            ("Фильтры", "не применялись — в выборку вошли все доступные объекты")
        )
    if levels_line not in described:
        # Строка об уровнях присутствует в любом случае — и когда фильтр задан,
        # и когда он оставлен по умолчанию.
        described.append(levels_line)

    order = "по убыванию" if spec.order is SortOrder.DESC else "по возрастанию"
    described.append(("Сортировка", f"{_SORT_LABELS[spec.sort]}, {order}"))

    if scope_territory_name:
        # Ограничение роли — тоже фильтр, хотя пользователь его не задавал.
        # Умолчать о нём значило бы выдать часть картины за целое.
        described.append(
            (
                "Территориальное ограничение роли",
                f"{scope_territory_name} и подчинённые единицы",
            )
        )

    return tuple(described)


def _territory_names(session: Session, codes: Sequence[str]) -> str:
    """Названия территорий по кодам; неизвестный код называется кодом."""
    rows = session.execute(
        select(Territory.code, Territory.name_ru).where(Territory.code.in_(list(codes)))
    ).all()
    known: dict[str, str] = {row.code: row.name_ru for row in rows}
    return ", ".join(
        known.get(code, f"код {code} (в справочнике не найден)") for code in codes
    )


# --- Источники ---------------------------------------------------------------


def collect_sources(
    session: Session, layer_codes: Iterable[str] | None = None
) -> tuple[SourceRef, ...]:
    """Перечень источников с датой актуальности каждого.

    Берутся только наборы с ролью `raw`: лист «Методика» описывает, как
    считать, а не что показывать, и в перечне источников отчёта ему не место.
    """
    stmt = (
        select(SourceDataset, SourceFile.file_name)
        .join(SourceFile, SourceFile.id == SourceDataset.source_file_id)
        .where(SourceDataset.role == "raw")
        .order_by(SourceDataset.layer_code, SourceFile.file_name)
    )
    codes = {code for code in (layer_codes or ()) if code}
    if codes:
        stmt = stmt.where(SourceDataset.layer_code.in_(sorted(codes)))

    grouped: dict[tuple[str, str], list[SourceDataset]] = {}
    for dataset, file_name in session.execute(stmt).all():
        key = (dataset.layer_code or NO_DATA, file_name)
        grouped.setdefault(key, []).append(dataset)

    refs: list[SourceRef] = []
    for (layer_code, file_name), datasets in sorted(grouped.items()):
        dates = [d.data_as_of for d in datasets if d.data_as_of is not None]
        rows = [d.row_count for d in datasets if d.row_count is not None]
        refs.append(
            SourceRef(
                layer_code=layer_code,
                file_name=file_name,
                sheet_names=tuple(
                    sorted({d.sheet_name for d in datasets if d.sheet_name})
                ),
                # Из нескольких листов одной книги берётся самая ранняя дата:
                # книга не свежее самого старого своего листа, и округлять
                # в сторону свежести здесь опаснее всего.
                data_as_of=min(dates) if dates else None,
                row_count=sum(rows) if rows else None,
            )
        )
    return tuple(refs)


# --- Общие таблицы -----------------------------------------------------------


def _level_table(stats: SelectionStats) -> ReportTable:
    """Распределение выборки по уровням риска."""
    rows = tuple(
        (
            Cell.of(level.label_ru),
            Cell.whole(stats.by_level.get(level, 0)),
            Cell.share(stats.by_level.get(level, 0), stats.total),
        )
        for level in _LEVEL_ORDER
    )
    return ReportTable(
        title="Распределение по уровням риска",
        columns=(
            ReportColumn("Уровень риска", width=2.0),
            ReportColumn("Объектов", numeric=True),
            ReportColumn("Доля выборки", numeric=True),
        ),
        rows=rows,
        note=(
            "Уровень «Нет данных» — не низкий риск, а его отсутствие: объект не "
            "измерен. Строка присутствует всегда, даже при нулевом значении."
        ),
    )


def _objects_table(cards: Sequence[ObjectCard], title: str, *, limit: int) -> ReportTable:
    """Пообъектный перечень выборки."""
    shown = list(cards[:limit])
    rows = tuple(
        (
            Cell.of(OBJECT_TYPE_LABELS.get(card.object_type, str(card.object_type))),
            Cell.of(card.title),
            Cell.of(card.territory_name),
            Cell.money(card.amount, card.amount_unit),
            Cell.score(card.risk_score, preliminary=card.risk_is_preliminary),
            Cell.of(card.risk_level.label_ru),
            Cell.percent(card.risk_completeness),
            Cell.of(card.source_layer),
        )
        for card in shown
    )
    note = ""
    if len(cards) > limit:
        note = (
            f"Показаны первые {limit} объектов из {len(cards)} прочитанных. "
            f"Порядок соответствует сортировке выборки."
        )
    return ReportTable(
        title=title,
        columns=(
            ReportColumn("Тип", width=1.3),
            ReportColumn("Наименование", width=3.2),
            ReportColumn("Территория", width=1.6),
            ReportColumn("Сумма", numeric=True, width=1.6),
            ReportColumn("Балл", numeric=True, width=1.2),
            ReportColumn("Уровень", width=1.2),
            ReportColumn("Полнота", numeric=True),
            ReportColumn("Слой"),
        ),
        rows=rows,
        note=note,
    )


def _territory_table(cards: Sequence[ObjectCard], *, limit: int) -> ReportTable:
    """Рейтинг территорий по числу тревожных объектов."""
    buckets: dict[str | None, dict[str, int]] = {}
    for card in cards:
        key = card.territory_name
        bucket = buckets.setdefault(key, {"total": 0, "alarm": 0, "unknown": 0})
        bucket["total"] += 1
        if card.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            bucket["alarm"] += 1
        if card.risk_level is RiskLevel.UNKNOWN:
            bucket["unknown"] += 1

    ordered = sorted(
        buckets.items(), key=lambda item: (-item[1]["alarm"], -item[1]["total"])
    )
    rows: list[tuple[Cell, ...]] = []
    for position, (name, bucket) in enumerate(ordered[:limit], start=1):
        rows.append(
            (
                Cell.whole(position),
                # Территория не определена — это не «нет данных о названии»,
                # а факт о самом объекте, и он называется прямо.
                Cell.of(name) if name else Cell.of("Территория не определена"),
                Cell.whole(bucket["total"]),
                Cell.whole(bucket["alarm"]),
                Cell.whole(bucket["unknown"]),
                Cell.share(bucket["alarm"], bucket["total"]),
            )
        )

    return ReportTable(
        title="Рейтинг территорий",
        columns=(
            ReportColumn("№", numeric=True, width=0.5),
            ReportColumn("Территория", width=3.0),
            ReportColumn("Объектов", numeric=True),
            ReportColumn("Критический и высокий", numeric=True, width=1.6),
            ReportColumn("Без оценки", numeric=True),
            ReportColumn("Доля тревожных", numeric=True, width=1.3),
        ),
        rows=tuple(rows),
        note=(
            "Рейтинг построен по прочитанной части выборки. Территории с равным "
            "числом тревожных объектов упорядочены по общему числу объектов."
        ),
    )


def _type_table(cards: Sequence[ObjectCard]) -> ReportTable:
    """Разрез выборки по типам объектов."""
    buckets: dict[ObjectType, dict[str, int]] = {}
    for card in cards:
        bucket = buckets.setdefault(card.object_type, {"total": 0, "alarm": 0, "unknown": 0})
        bucket["total"] += 1
        if card.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            bucket["alarm"] += 1
        if card.risk_level is RiskLevel.UNKNOWN:
            bucket["unknown"] += 1

    rows = tuple(
        (
            Cell.of(OBJECT_TYPE_LABELS.get(object_type, str(object_type))),
            Cell.whole(bucket["total"]),
            Cell.whole(bucket["alarm"]),
            Cell.whole(bucket["unknown"]),
        )
        for object_type, bucket in sorted(
            buckets.items(), key=lambda item: -item[1]["total"]
        )
    )
    return ReportTable(
        title="Разрез по типам объектов",
        columns=(
            ReportColumn("Тип объекта", width=2.4),
            ReportColumn("Всего", numeric=True),
            ReportColumn("Критический и высокий", numeric=True, width=1.6),
            ReportColumn("Без оценки", numeric=True),
        ),
        rows=rows,
    )


def _empty_note(cards: Sequence[ObjectCard]) -> tuple[str, ...]:
    """Пояснение к пустой выборке.

    Пустой отчёт без объяснения читается как «рисков нет». Это неверно: он
    означает «под заданные условия ничего не подошло».
    """
    if cards:
        return ()
    return (
        "Под заданные условия не подошёл ни один объект. Это не означает "
        "отсутствия рисков — это означает, что выборка пуста. Проверьте период, "
        "территорию и уровни риска в перечне применённых фильтров выше.",
    )


# --- Разрезы, требующие отдельных запросов -----------------------------------


def _industry_table(
    session: Session, *, allowed_territory_ids: Collection[uuid.UUID] | None
) -> ReportTable:
    """Разрез по отраслям.

    Отрасль есть только у объектов слоя 8.6: у проектов ГЧП это сектор, у
    заключений экспертизы — отрасль. У договоров и организаций отраслевого
    признака в источниках нет вовсе, и приписывать им отрасль по ОКЭД нельзя:
    ОКЭД — вид деятельности юридического лица, а не отрасль объекта.

    Считается агрегатом в базе, а не обходом сущностей: слой 8.6 — это тысячи
    строк, и вытягивать их в память ради пяти чисел в таблице значило бы
    нарушить требование ТЗ по времени отклика на ровном месте. Запрос идёт по
    таблицам напрямую, потому что подтипы хранятся раздельно (наследование с
    объединением таблиц), и признак отрасли лежит в подтипе, а уровень риска —
    в базовой таблице.
    """
    buckets: dict[str | None, dict[str, int]] = {}

    def add(industry: str | None, level: str | None, count: int) -> None:
        key = industry.strip() if industry and industry.strip() else None
        bucket = buckets.setdefault(key, {"total": 0, "alarm": 0, "unknown": 0})
        bucket["total"] += count
        if level in (RiskLevel.CRITICAL.value, RiskLevel.HIGH.value):
            bucket["alarm"] += count
        if level is None or level == RiskLevel.UNKNOWN.value:
            bucket["unknown"] += count

    entity = ProjectEntity.__table__
    for model, column_name in (
        (PppProject, "sector"),
        (ConstructionExpertiseObject, "industry"),
    ):
        subtype = model.__table__
        industry_column = subtype.c[column_name]
        stmt = (
            select(industry_column, entity.c.risk_level, func.count())
            .select_from(subtype.join(entity, entity.c.id == subtype.c.id))
            .group_by(industry_column, entity.c.risk_level)
        )
        if allowed_territory_ids is not None:
            stmt = stmt.where(entity.c.territory_id.in_(allowed_territory_ids))
        for industry, level, count in session.execute(stmt).all():
            add(industry, level, int(count))

    ordered = sorted(buckets.items(), key=lambda item: (-item[1]["alarm"], -item[1]["total"]))
    rows = tuple(
        (
            Cell.of(name) if name else Cell.missing(),
            Cell.whole(bucket["total"]),
            Cell.whole(bucket["alarm"]),
            Cell.whole(bucket["unknown"]),
            Cell.share(bucket["alarm"], bucket["total"]),
        )
        for name, bucket in ordered[:_TOP_LIMIT]
    )
    return ReportTable(
        title="Разрез по отраслям",
        columns=(
            ReportColumn("Отрасль", width=3.0),
            ReportColumn("Объектов", numeric=True),
            ReportColumn("Критический и высокий", numeric=True, width=1.6),
            ReportColumn("Без оценки", numeric=True),
            ReportColumn("Доля тревожных", numeric=True, width=1.3),
        ),
        rows=rows,
        note=(
            "Отрасль известна только для проектов ГЧП (сектор) и заключений "
            "экспертизы (отрасль). Договоры госзакупок и организации в этот "
            "разрез не входят: отраслевого признака в их источниках нет. "
            f"Строка «{NO_DATA}» — объекты слоя 8.6, у которых отрасль в "
            "источнике не заполнена."
        ),
    )


def _organization_table(
    session: Session,
    spec: QuerySpec,
    *,
    user: User,
    context: RequestContext | None,
    allowed_territory_ids: Collection[uuid.UUID] | None,
) -> ReportTable:
    """Досье организаций с маскированием ИИН руководителя.

    БИН организации не маскируется: это идентификатор юридического лица из
    открытого реестра. ИИН руководителя — персональные данные, и он проходит
    через `masking`, который сам пишет в журнал факт полного раскрытия.
    """
    stmt = (
        select(Organization)
        .options(
            selectinload(Organization.person_roles).selectinload(
                OrganizationPersonRole.person
            )
        )
        .order_by(Organization.risk_score.desc().nullslast(), Organization.name)
        .limit(_LIST_LIMIT)
    )

    levels = [level.value for level in spec.risk_levels]
    if set(spec.risk_levels) != set(RiskLevel):
        stmt = stmt.where(Organization.risk_level_strict.in_(levels))
    if spec.only_category_a:
        stmt = stmt.where(Organization.is_category_a.is_(True))
    if spec.search:
        pattern = f"%{spec.search}%"
        stmt = stmt.where(or_(Organization.name.ilike(pattern), Organization.bin.ilike(pattern)))
    if allowed_territory_ids is not None:
        stmt = stmt.where(Organization.territory_id.in_(allowed_territory_ids))

    organizations = list(session.execute(stmt).scalars())

    directors: list[str | None] = []
    for organization in organizations:
        director = next(
            (
                role.person
                for role in organization.person_roles
                if role.role is PersonRoleKind.DIRECTOR and role.person is not None
            ),
            None,
        )
        directors.append(director.iin if director is not None else None)

    masked = masking.reveal_many(
        directors,
        user=user,
        session=session,
        context=context,
        field="iin",
        entity_type="organization",
    )

    rows = tuple(
        (
            Cell.of(organization.name),
            Cell.of(organization.bin),
            Cell.score(
                organization.risk_score, preliminary=organization.risk_is_preliminary
            ),
            Cell.of(
                RiskLevel(organization.risk_level_strict).label_ru
                if organization.risk_level_strict
                else RiskLevel.UNKNOWN.label_ru
            ),
            Cell.percent(organization.risk_completeness),
            Cell.of("да" if organization.is_category_a else "нет"),
            _identifier_cell(value),
        )
        for organization, value in zip(organizations, masked, strict=True)
    )

    return ReportTable(
        title="Организации выборки",
        columns=(
            ReportColumn("Организация", width=3.2),
            ReportColumn("БИН", width=1.3),
            ReportColumn("Балл", numeric=True),
            ReportColumn("Уровень", width=1.2),
            ReportColumn("Полнота", numeric=True),
            ReportColumn("Категория A", width=1.1),
            ReportColumn("ИИН руководителя", width=1.6),
        ),
        rows=rows,
        note=(
            "Уровень указан строгий: предварительный балл слоя 8.7 показан рядом "
            f"с пометкой «{PRELIMINARY_MARK}» и уровень не подменяет. ИИН "
            "руководителя показан согласно роли; полное раскрытие журналируется."
        ),
    )


def _identifier_cell(value: masking.MaskedValue) -> Cell:
    """Ячейка с персональным идентификатором.

    Три состояния, и все три различимы: значения нет, значение скрыто ролью,
    значение показано (целиком или в маске). Свести «скрыто» к «нет данных»
    нельзя: пользователь решит, что данные неполны, и заведёт обращение о
    пропаже сведений, которых на самом деле не лишён никто.
    """
    if not value.present:
        return Cell.missing()
    if value.value is None:
        return Cell(text=CLOSED_BY_ROLE)
    return Cell(text=value.value)


def _project_table(
    session: Session, *, allowed_territory_ids: Collection[uuid.UUID] | None
) -> ReportTable:
    """Карточки проектов и заключений экспертизы с ключевыми полями."""
    ppp_stmt = select(PppProject).order_by(PppProject.risk_score.desc().nullslast())
    expertise_stmt = select(ConstructionExpertiseObject).order_by(
        ConstructionExpertiseObject.risk_score.desc().nullslast()
    )
    if allowed_territory_ids is not None:
        ppp_stmt = ppp_stmt.where(ProjectEntity.territory_id.in_(allowed_territory_ids))
        expertise_stmt = expertise_stmt.where(
            ProjectEntity.territory_id.in_(allowed_territory_ids)
        )

    rows: list[tuple[Cell, ...]] = []

    for project in session.execute(ppp_stmt.limit(_TOP_LIMIT)).scalars():
        rows.append(
            (
                Cell.of("Проект ГЧП"),
                Cell.of(project.title),
                Cell.of(project.sector),
                Cell.money(project.investments),
                Cell.score(project.risk_score, preliminary=project.risk_is_preliminary),
                Cell.of(_level_label(project.risk_level)),
                Cell.percent(project.risk_completeness),
                Cell.of(project.risk_override_applied),
            )
        )

    for conclusion in session.execute(expertise_stmt.limit(_TOP_LIMIT)).scalars():
        rows.append(
            (
                Cell.of("Заключение экспертизы"),
                Cell.of(conclusion.title),
                Cell.of(conclusion.industry),
                # Стоимость полного комплекта хранится строкой из книги и
                # числом не является — печатается как есть либо «нет данных».
                Cell.of(conclusion.full_set_cost),
                Cell.score(
                    conclusion.risk_score, preliminary=conclusion.risk_is_preliminary
                ),
                Cell.of(_level_label(conclusion.risk_level)),
                Cell.percent(conclusion.risk_completeness),
                Cell.of(conclusion.risk_override_applied),
            )
        )

    return ReportTable(
        title="Объекты и проекты",
        columns=(
            ReportColumn("Тип", width=1.6),
            ReportColumn("Наименование", width=3.4),
            ReportColumn("Отрасль / сектор", width=1.8),
            ReportColumn("Стоимость", numeric=True, width=1.6),
            ReportColumn("Балл", numeric=True),
            ReportColumn("Уровень", width=1.2),
            ReportColumn("Полнота", numeric=True),
            ReportColumn("Переопределение", width=1.6),
        ),
        rows=tuple(rows),
        note=(
            "Колонка «Переопределение» заполнена, только если уровень назначен "
            "жёстким правилом методики в обход баллов."
        ),
    )


def _level_label(value: str | None) -> str:
    """Название уровня по значению из базы; неизвестное — «нет данных»."""
    if not value:
        return RiskLevel.UNKNOWN.label_ru
    try:
        return RiskLevel(value).label_ru
    except ValueError:
        return RiskLevel.UNKNOWN.label_ru


def _factor_table(
    session: Session,
    cards: Sequence[ObjectCard],
    *,
    user: User,
    context: RequestContext | None,
) -> ReportTable:
    """Расшифровка факторов для высокорисковых получателей субсидий.

    Реестр высокорисковых объектов по референсу должен идти «с расшифровкой
    факторов». Расшифровка берётся у слоя 8.5, где факторы разложены по
    отдельным колонкам, а идентификатор получателя — персональные данные и
    проходит через маскирование.
    """
    keys = [
        card.object_id
        for card in cards
        if card.object_type is ObjectType.SUBSIDY_RECIPIENT
    ][:_TOP_LIMIT]

    if not keys:
        return ReportTable(
            title="Расшифровка факторов риска",
            columns=(ReportColumn("Получатель"),),
            rows=(),
            note=(
                "В выборке нет получателей субсидий — слоя, для которого "
                "расшифровка факторов доступна пообъектно."
            ),
        )

    recipients = list(
        session.execute(
            select(SubsidyRecipient)
            .where(SubsidyRecipient.natural_key.in_(keys))
            .order_by(SubsidyRecipient.risk_score.desc().nullslast())
        ).scalars()
    )

    masked = masking.reveal_many(
        [recipient.xin for recipient in recipients],
        user=user,
        session=session,
        context=context,
        field="xin",
        entity_type="subsidy_recipient",
    )

    rows = tuple(
        (
            Cell.of(recipient.name),
            _identifier_cell(value),
            Cell.score(recipient.risk_score),
            Cell.of(_level_label(recipient.risk_level)),
            Cell.percent(recipient.s1_concentration),
            Cell.percent(recipient.s2_repetition),
            Cell.percent(recipient.s3_affiliation),
            Cell.percent(recipient.s4_process_anomaly),
            Cell.percent(recipient.s5_amount_outlier),
        )
        for recipient, value in zip(recipients, masked, strict=True)
    )

    return ReportTable(
        title="Расшифровка факторов риска",
        columns=(
            ReportColumn("Получатель", width=3.0),
            ReportColumn("ИИН / БИН", width=1.5),
            ReportColumn("Балл", numeric=True),
            ReportColumn("Уровень", width=1.2),
            ReportColumn("S1 концентрация", numeric=True, width=1.2),
            ReportColumn("S2 повторяемость", numeric=True, width=1.2),
            ReportColumn("S3 аффилированность", numeric=True, width=1.3),
            ReportColumn("S4 аномалия процесса", numeric=True, width=1.3),
            ReportColumn("S5 выброс суммы", numeric=True, width=1.2),
        ),
        rows=rows,
        note=(
            "Значение фактора — нормированный вклад в балл, от 0 до 100%. "
            f"«{NO_DATA}» означает, что фактор не измерен, а не что он равен нулю."
        ),
    )


# --- Сборка разделов по шаблонам ---------------------------------------------


def _sections(
    template: ReportTemplate,
    *,
    session: Session,
    spec: QuerySpec,
    cards: tuple[ObjectCard, ...],
    stats: SelectionStats,
    user: User,
    context: RequestContext | None,
    allowed_territory_ids: Collection[uuid.UUID] | None,
) -> tuple[ReportSection, ...]:
    """Состав разделов конкретного шаблона."""
    overview = ReportSection(
        title="Общие показатели выборки",
        paragraphs=(
            f"Всего объектов в выборке: {stats.total}.",
            *_empty_note(cards),
        ),
        tables=(_level_table(stats),),
    )

    if template is ReportTemplate.REGION_SUMMARY:
        return (
            overview,
            ReportSection(title="Структура выборки", tables=(_type_table(cards),)),
            ReportSection(
                title="Территориальный разрез",
                tables=(_territory_table(cards, limit=_TOP_LIMIT),),
            ),
            ReportSection(
                title="Наиболее тревожные объекты",
                tables=(_objects_table(_alarming(cards), "Топ объектов", limit=_TOP_LIMIT),),
            ),
        )

    if template is ReportTemplate.TERRITORY:
        return (
            overview,
            ReportSection(title="Структура выборки", tables=(_type_table(cards),)),
            ReportSection(
                title="Объекты территории",
                tables=(_objects_table(cards, "Перечень объектов", limit=_LIST_LIMIT),),
            ),
        )

    if template is ReportTemplate.ORGANIZATION:
        return (
            overview,
            ReportSection(
                title="Досье организаций",
                paragraphs=(
                    "Организации слоя 8.7 не имеют территориальной привязки в "
                    "источнике. Пользователю, ограниченному территорией, они "
                    "недоступны — подтвердить его право на них нечем.",
                ),
                tables=(
                    _organization_table(
                        session,
                        spec,
                        user=user,
                        context=context,
                        allowed_territory_ids=allowed_territory_ids,
                    ),
                ),
            ),
        )

    if template is ReportTemplate.PROJECT:
        return (
            overview,
            ReportSection(
                title="Объекты и проекты",
                tables=(
                    _project_table(session, allowed_territory_ids=allowed_territory_ids),
                ),
            ),
        )

    if template is ReportTemplate.INDUSTRY:
        return (
            overview,
            ReportSection(
                title="Отраслевой разрез",
                tables=(
                    _industry_table(session, allowed_territory_ids=allowed_territory_ids),
                ),
            ),
        )

    if template is ReportTemplate.RISK_CATEGORY:
        selected = [
            card
            for card in cards
            if card.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
        ]
        return (
            overview,
            ReportSection(
                title="Объекты критического и высокого уровня",
                paragraphs=(
                    f"Отобрано объектов: {len(selected)} из {len(cards)} прочитанных. "
                    "Объекты без оценки риска в эту таблицу не входят — но это не "
                    "значит, что их уровень низкий: он неизвестен, и их число "
                    "названо в разделе о полноте.",
                ),
                tables=(
                    _objects_table(selected, "Перечень по категории риска", limit=_LIST_LIMIT),
                ),
            ),
        )

    if template is ReportTemplate.RATINGS:
        return (
            overview,
            ReportSection(
                title="Рейтинг территорий",
                tables=(_territory_table(cards, limit=_TOP_LIMIT),),
            ),
            ReportSection(
                title="Рейтинг отраслей",
                tables=(
                    _industry_table(session, allowed_territory_ids=allowed_territory_ids),
                ),
            ),
            ReportSection(title="Разрез по типам объектов", tables=(_type_table(cards),)),
        )

    high_risk = _alarming(cards)
    return (
        overview,
        ReportSection(
            title="Реестр высокорисковых объектов",
            tables=(_objects_table(high_risk, "Высокорисковые объекты", limit=_LIST_LIMIT),),
        ),
        ReportSection(
            title="Расшифровка факторов",
            tables=(_factor_table(session, high_risk, user=user, context=context),),
        ),
    )


def _alarming(cards: Sequence[ObjectCard]) -> list[ObjectCard]:
    """Объекты критического и высокого уровня в порядке убывания балла.

    Объекты без балла идут последними, но не исключаются: у объекта может быть
    жёстко переопределённый уровень без числового балла, и потерять такой
    объект в перечне высокорисковых было бы худшей из возможных потерь.
    """
    selected = [
        card for card in cards if card.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
    ]
    selected.sort(
        key=lambda card: (
            card.risk_level.order,
            card.risk_score if card.risk_score is not None else -1.0,
        ),
        reverse=True,
    )
    return selected


# --- Точка входа -------------------------------------------------------------


def build_report(
    session: Session,
    template: ReportTemplate,
    spec: QuerySpec,
    *,
    user: User,
    context: RequestContext | None = None,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    scope_territory_name: str | None = None,
    record_audit: bool = True,
) -> ReportDocument:
    """Собрать данные отчёта и записать формирование в журнал.

    Журналирование внутри сборки, а не в эндпоинте, — то же решение, что в
    `masking.reveal`: отчёт нельзя сформировать мимо журнала. `record_audit`
    существует ради тестов самой сборки и по умолчанию включён.
    """
    stats = selection_stats(session, spec, allowed_territory_ids=allowed_territory_ids)
    cards, truncated = collect_cards(
        session, spec, allowed_territory_ids=allowed_territory_ids
    )

    layer_codes = {card.source_layer for card in cards if card.source_layer}
    if not layer_codes:
        # Пустая выборка не повод умолчать об источниках: читатель должен
        # видеть, по каким данным система искала и не нашла.
        types = spec.object_types or list(_TYPE_TO_LAYER)
        layer_codes = {_TYPE_TO_LAYER[t] for t in types if t in _TYPE_TO_LAYER}

    warning = CompletenessWarning(
        total=stats.total,
        unknown_level=stats.by_level.get(RiskLevel.UNKNOWN, 0),
        preliminary_score=stats.preliminary_score,
        without_territory=stats.without_territory,
        truncated_to=len(cards) if truncated else None,
    )

    document = ReportDocument(
        template=template,
        title=template.label,
        subtitle=template.description,
        generated_at=utcnow(),
        generated_by_name=user.full_name,
        generated_by_role=user.role.title,
        filters=describe_filters(
            session, spec, scope_territory_name=scope_territory_name
        ),
        sources=collect_sources(session, layer_codes),
        warning=warning,
        sections=_sections(
            template,
            session=session,
            spec=spec,
            cards=cards,
            stats=stats,
            user=user,
            context=context,
            allowed_territory_ids=allowed_territory_ids,
        ),
        notes=(
            "Отчёт сформирован по той же выборке, что показывают экраны «Списком» "
            "и «На карте»: перечень применённых фильтров приведён выше полностью.",
            f"Отсутствующее значение печатается как «{NO_DATA}». Ноль в таблице "
            "означает измеренный ноль, а не отсутствие данных.",
        ),
    )

    if record_audit:
        record_generated(
            session,
            user,
            template=template,
            spec=spec,
            stats=stats,
            context=context,
        )

    return document


def record_generated(
    session: Session | None,
    user: User,
    *,
    template: ReportTemplate,
    spec: QuerySpec,
    stats: SelectionStats,
    context: RequestContext | None = None,
) -> None:
    """Записать формирование отчёта.

    В подробности уходит состав выборки — но не сами данные: журнал фиксирует,
    что и по каким условиям было собрано, а не содержимое собранного.
    """
    audit.record(
        AuditAction.REPORT_GENERATED,
        session=session,
        user=user,
        context=context,
        entity_type="report",
        entity_id=str(template),
        details={
            "template": str(template),
            "filters": dict(spec.to_query_params()),
            "objects_total": stats.total,
            "objects_unknown_level": stats.by_level.get(RiskLevel.UNKNOWN, 0),
            "objects_preliminary_score": stats.preliminary_score,
        },
    )


def record_export(
    session: Session | None,
    user: User,
    *,
    template: ReportTemplate,
    export_format: str,
    file_name: str,
    size_bytes: int,
    context: RequestContext | None = None,
) -> None:
    """Записать выгрузку файла.

    Отдельно от формирования: ТЗ разводит эти события, и по существу они
    разные. Формирование остаётся внутри периметра, выгрузка выносит данные
    наружу — и именно её ищут, когда разбирают утечку.
    """
    audit.record(
        AuditAction.EXPORT,
        session=session,
        user=user,
        context=context,
        entity_type="report",
        entity_id=str(template),
        details={
            "template": str(template),
            "format": export_format,
            "file_name": file_name,
            "size_bytes": size_bytes,
        },
    )


def template_catalog() -> list[dict[str, str]]:
    """Каталог шаблонов для экрана «Отчёты и экспорт»."""
    return [
        {"code": str(template), "title": template.label, "description": template.description}
        for template in ReportTemplate
    ]


__all__ = [
    "CLOSED_BY_ROLE",
    "MAX_REPORT_ROWS",
    "NO_DATA",
    "OBJECT_TYPE_LABELS",
    "PRELIMINARY_MARK",
    "TEMPLATE_TITLES",
    "WARNING_CLEAN",
    "WARNING_HEADING",
    "WARNING_MARKER",
    "Cell",
    "CompletenessWarning",
    "ReportColumn",
    "ReportDocument",
    "ReportSection",
    "ReportTable",
    "ReportTemplate",
    "SelectionStats",
    "SourceRef",
    "build_report",
    "collect_cards",
    "collect_sources",
    "describe_filters",
    "record_export",
    "record_generated",
    "selection_stats",
    "template_catalog",
]
