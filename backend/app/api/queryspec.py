"""Каноническое описание выборки.

ТЗ требует, чтобы «Списком» и «На карте» были двумя представлениями **одной**
выборки, а не двумя страницами с расходящимся состоянием. Единственный надёжный
способ это обеспечить — одно описание фильтров, из которого одинаково строятся
и запрос карты, и запрос списка, и ссылка в адресной строке.

Отсюда три свойства этого модуля:

* фильтры описаны один раз и живут в одном объекте;
* объект умеет превращаться в параметры URL и обратно без потерь, иначе
  кнопка «назад» в браузере восстановит не то состояние;
* сортировка и страница — часть выборки, а не отдельное состояние компонента.

Отдельно про уровень риска. `unknown` — полноправное значение фильтра, и по
умолчанию оно **включено**. Если убрать его из умолчаний, пользователь, не
трогавший фильтры, увидит только измеренные объекты и решит, что видит всё.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Self
from urllib.parse import urlencode

from pydantic import BaseModel, Field, field_validator, model_validator

from app.risk.core import RiskLevel


class SortField(StrEnum):
    """Поля сортировки из ТЗ, раздел про режим списка."""

    RISK = "risk"
    AMOUNT = "amount"
    RELEVANCE = "relevance"
    """По дате актуальности данных."""

    NAME = "name"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class ObjectType(StrEnum):
    """Типы объектов, участвующие в выборке.

    Совпадают со слоями данных. Организации входят в список, хотя на карту не
    выводятся: у них нет географии, но искать и открывать их карточку нужно.
    """

    TERRITORY = "territory"
    CONTRACT = "contract"
    SUBSIDY_RECIPIENT = "subsidy_recipient"
    PPP_PROJECT = "ppp_project"
    EXPERTISE_OBJECT = "expertise_object"
    ORGANIZATION = "organization"


class QuerySpec(BaseModel):
    """Выборка: что показать, как отсортировать, какую страницу.

    Значения по умолчанию подобраны так, чтобы пустая выборка означала «всё,
    что есть», а не «ничего»: пользователь, впервые открывший экран, должен
    увидеть данные, а не пустой список с просьбой настроить фильтры.
    """

    model_config = {"extra": "forbid"}

    # --- Период --------------------------------------------------------------

    date_from: date | None = None
    date_to: date | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)

    compare_to_from: date | None = None
    compare_to_to: date | None = None
    """Второй период для сравнения. ТЗ требует кнопку «Сравнить периоды»."""

    # --- Территория ----------------------------------------------------------

    territory_codes: list[str] = Field(default_factory=list)
    include_child_territories: bool = True
    """Выбор области подразумевает её районы — иначе выбор области даёт пусто."""

    # --- Предметные фильтры --------------------------------------------------

    object_types: list[ObjectType] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)

    customer_ids: list[str] = Field(default_factory=list)
    supplier_ids: list[str] = Field(default_factory=list)
    recipient_ids: list[str] = Field(default_factory=list)

    amount_min: float | None = Field(default=None, ge=0)
    amount_max: float | None = Field(default=None, ge=0)

    # --- Риск ----------------------------------------------------------------

    risk_levels: list[RiskLevel] = Field(
        default_factory=lambda: list(RiskLevel),
        description=(
            "По умолчанию включены ВСЕ уровни, включая «нет данных». Иначе "
            "пользователь, не трогавший фильтры, увидит только измеренные "
            "объекты и решит, что видит всё."
        ),
    )
    completeness_min: float | None = Field(default=None, ge=0, le=1)
    completeness_max: float | None = Field(default=None, ge=0, le=1)
    only_category_a: bool = False
    """Только объекты со сработавшим жёстким переопределением уровня."""

    # --- Поиск ---------------------------------------------------------------

    search: str | None = Field(default=None, max_length=255)

    # --- Представление -------------------------------------------------------

    sort: SortField = SortField.RISK
    order: SortOrder = SortOrder.DESC
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)

    @field_validator("search")
    @classmethod
    def _strip_search(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("territory_codes", "industries", "sources", "statuses", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Принять и повторяющийся параметр, и список через запятую.

        Браузеры и клиенты передают множественные значения по-разному
        (`?t=a&t=b` против `?t=a,b`). Поддерживаем оба, иначе ссылка,
        собранная вручную, молча теряет часть фильтров.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _check_ranges(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("начало периода позже его конца")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("нижняя граница суммы больше верхней")
        if (
            self.completeness_min is not None
            and self.completeness_max is not None
            and self.completeness_min > self.completeness_max
        ):
            raise ValueError("нижняя граница полноты больше верхней")
        if not self.risk_levels:
            raise ValueError(
                "не выбран ни один уровень риска — такая выборка всегда пуста; "
                "чтобы снять фильтр, оставьте все уровни включёнными"
            )
        return self

    # --- Представление в URL -------------------------------------------------

    def to_query_params(self) -> dict[str, str]:
        """Параметры адресной строки.

        Значения, равные умолчанию, опускаются: ссылка должна оставаться
        читаемой, а не тащить три десятка параметров, ничего не меняющих.
        """
        defaults = QuerySpec()
        params: dict[str, str] = {}

        for name, value in self.model_dump(exclude_none=True).items():
            default = getattr(defaults, name)
            if isinstance(default, list):
                default_set = {str(item) for item in default}
                current_set = {str(item) for item in value}
                if current_set == default_set:
                    continue
                if value:
                    params[name] = ",".join(str(item) for item in value)
                else:
                    # Пустой список отличается от умолчания и должен
                    # сохраняться в ссылке, иначе фильтр «ничего не выбрано»
                    # восстановится как «выбрано всё».
                    params[name] = ""
                continue

            if value == default:
                continue
            params[name] = str(value)

        return params

    def to_query_string(self) -> str:
        return urlencode(self.to_query_params())

    @classmethod
    def from_query_params(cls, params: dict[str, Any]) -> QuerySpec:
        """Разобрать параметры адресной строки.

        Пустая строка у списочного параметра означает «выбрано пусто», а
        отсутствие параметра — «значение по умолчанию». Разница существенна:
        первое даёт пустую выборку, второе — полную.
        """
        prepared: dict[str, Any] = {}
        list_fields = {
            name
            for name, field in cls.model_fields.items()
            if str(field.annotation).startswith("list")
        }

        for key, raw in params.items():
            if key not in cls.model_fields:
                continue
            if key in list_fields:
                if raw == "" or raw is None:
                    prepared[key] = []
                elif isinstance(raw, str):
                    prepared[key] = [p.strip() for p in raw.split(",") if p.strip()]
                else:
                    prepared[key] = raw
            else:
                prepared[key] = raw

        return cls.model_validate(prepared)

    # --- Удобства ------------------------------------------------------------

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def includes_unknown_risk(self) -> bool:
        return RiskLevel.UNKNOWN in self.risk_levels

    @property
    def has_active_filters(self) -> bool:
        """Отличается ли выборка от умолчания.

        Нужно интерфейсу: если фильтры не тронуты, показывать чипы и кнопку
        сброса незачем.
        """
        return bool(self.to_query_params().keys() - {"page", "page_size", "sort", "order"})

    def active_filter_chips(self) -> list[tuple[str, str]]:
        """Пары «поле → человекочитаемое значение» для чипов над списком."""
        chips: list[tuple[str, str]] = []

        if self.year:
            chips.append(("Период", str(self.year)))
        elif self.date_from or self.date_to:
            начало = self.date_from.strftime("%d.%m.%Y") if self.date_from else "…"
            конец = self.date_to.strftime("%d.%m.%Y") if self.date_to else "…"
            chips.append(("Период", f"{начало} — {конец}"))

        if self.territory_codes:
            chips.append(("Территория", f"выбрано: {len(self.territory_codes)}"))
        if self.object_types:
            chips.append(("Тип объекта", f"выбрано: {len(self.object_types)}"))
        if self.industries:
            chips.append(("Отрасль", f"выбрано: {len(self.industries)}"))
        if self.statuses:
            chips.append(("Статус", f"выбрано: {len(self.statuses)}"))

        if self.amount_min is not None or self.amount_max is not None:
            низ = f"{self.amount_min:,.0f}" if self.amount_min is not None else "0"
            верх = f"{self.amount_max:,.0f}" if self.amount_max is not None else "∞"
            chips.append(("Сумма", f"{низ} — {верх} ₸"))

        if set(self.risk_levels) != set(RiskLevel):
            names = ", ".join(level.label_ru for level in self.risk_levels)
            chips.append(("Уровень риска", names))

        if self.completeness_min is not None or self.completeness_max is not None:
            низ = f"{(self.completeness_min or 0) * 100:.0f}%"
            верх = f"{(self.completeness_max or 1) * 100:.0f}%"
            chips.append(("Полнота данных", f"{низ} — {верх}"))

        if self.only_category_a:
            chips.append(("Категория", "только категория A"))

        if self.search:
            chips.append(("Поиск", self.search))

        return chips

    def for_page(self, page: int) -> QuerySpec:
        return self.model_copy(update={"page": page})

    def without_pagination(self) -> QuerySpec:
        """Та же выборка без страницы — для карты и агрегатов.

        Карта показывает выборку целиком: пагинация относится только к списку.
        """
        return self.model_copy(update={"page": 1, "page_size": 200})


class PageInfo(BaseModel):
    """Сведения о странице результата."""

    page: int
    page_size: int
    total: int
    total_pages: int

    @classmethod
    def build(cls, spec: QuerySpec, total: int) -> PageInfo:
        pages = (total + spec.page_size - 1) // spec.page_size if total else 0
        return cls(page=spec.page, page_size=spec.page_size, total=total, total_pages=pages)

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1
