"""Единый список объектов всех слоёв.

ТЗ требует, чтобы «Списком» и «На карте» показывали одну выборку. Значит,
объекты пяти слоёв — договоры, получатели субсидий, проекты ГЧП, заключения
экспертизы и организации — должны попадать в один список, сортироваться по
одному правилу и постранично отдаваться одним запросом.

Слои устроены по-разному: у договора есть сумма и поставщик, у заключения
экспертизы — проектировщик и стадия, у организации нет даже территории.
Поэтому каждый слой приводится к общей карточке, а различия остаются в поле
`details` — их показывает карточка объекта, а не список.

Запрос собирается как UNION ALL нормализованных выборок, а сортировка и
постраничность выполняются базой. Собирать список в Python значило бы
вытянуть все строки всех слоёв на каждый запрос, а ТЗ требует работы с
миллионом записей.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Select,
    SQLColumnExpression,
    String,
    case,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.api.queryspec import ObjectType, QuerySpec, SortField, SortOrder
from app.db.models.infrastructure import ProjectEntity, ProjectEntityKind
from app.db.models.organization import Organization
from app.db.models.procurement import Contract
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory
from app.risk.core import RiskLevel

# Колонка модели (`InstrumentedAttribute`) и выражение (`func.coalesce(...)`) —
# разные типы, но оба годятся как элемент SELECT. Общий надтип позволяет
# принимать и то и другое, не опускаясь до `Any`.
type ColumnLike = SQLColumnExpression[Any]


@dataclass(frozen=True, slots=True)
class ObjectCard:
    """Карточка объекта в списке.

    Состав полей задан ТЗ: тип, название, территория, сумма, балл, уровень,
    полнота, главные факторы, статус, источник, дата актуальности.
    """

    object_type: ObjectType
    object_id: str
    title: str
    subtitle: str | None

    territory_code: str | None
    territory_name: str | None

    amount: Decimal | None
    amount_unit: str

    risk_score: float | None
    risk_level: RiskLevel
    risk_is_preliminary: bool
    risk_completeness: float | None

    status: str | None
    source_layer: str
    data_as_of: str | None

    @property
    def has_measured_risk(self) -> bool:
        return self.risk_level is not RiskLevel.UNKNOWN


# Общий набор колонок, к которому приводится каждый слой. Порядок обязан
# совпадать во всех выборках UNION — иначе база молча склеит разные поля.
_COLUMNS = (
    "object_type",
    "object_id",
    "title",
    "subtitle",
    "territory_id",
    "amount",
    "amount_unit",
    "risk_score",
    "risk_level",
    "risk_is_preliminary",
    "risk_completeness",
    "status",
    "source_layer",
)


def _normalized(
    *,
    object_type: ObjectType,
    object_id: ColumnLike,
    title: ColumnLike,
    subtitle: ColumnLike | None,
    territory_id: ColumnLike | None,
    amount: ColumnLike | None,
    amount_unit: str,
    risk_score: ColumnLike | None,
    risk_level: ColumnLike,
    risk_is_preliminary: ColumnLike,
    risk_completeness: ColumnLike | None,
    status: ColumnLike | None,
    source_layer: str,
) -> list[ColumnLike]:
    """Привести колонки слоя к общему виду."""
    null_text = literal(None, type_=String)

    return [
        literal(object_type.value).label("object_type"),
        func.cast(object_id, String).label("object_id"),
        title.label("title"),
        (subtitle if subtitle is not None else null_text).label("subtitle"),
        (territory_id if territory_id is not None else literal(None)).label("territory_id"),
        (amount if amount is not None else literal(None)).label("amount"),
        literal(amount_unit).label("amount_unit"),
        (risk_score if risk_score is not None else literal(None)).label("risk_score"),
        risk_level.label("risk_level"),
        risk_is_preliminary.label("risk_is_preliminary"),
        (risk_completeness if risk_completeness is not None else literal(None)).label(
            "risk_completeness"
        ),
        (status if status is not None else null_text).label("status"),
        literal(source_layer).label("source_layer"),
    ]


def _contracts_select() -> Select[Any]:
    return select(
        *_normalized(
            object_type=ObjectType.CONTRACT,
            object_id=Contract.contract_id,
            title=Contract.contract_id,
            subtitle=Contract.brief_content_ru,
            territory_id=Contract.territory_id,
            # Фактическая сумма договора важнее плановой: риск считается по
            # тому, что заплачено, а не по тому, что предполагалось.
            amount=func.coalesce(Contract.final_amount, Contract.planned_amount),
            amount_unit="₸",
            risk_score=Contract.risk_score,
            risk_level=func.coalesce(Contract.risk_level, literal(RiskLevel.UNKNOWN.value)),
            risk_is_preliminary=Contract.is_preliminary,
            risk_completeness=Contract.completeness,
            status=Contract.contract_status,
            source_layer="8.4",
        )
    )


def _subsidy_recipients_select() -> Select[Any]:
    return select(
        *_normalized(
            object_type=ObjectType.SUBSIDY_RECIPIENT,
            object_id=SubsidyRecipient.natural_key,
            title=SubsidyRecipient.name,
            subtitle=None,
            territory_id=SubsidyRecipient.territory_id,
            amount=SubsidyRecipient.total_amount,
            amount_unit="₸",
            risk_score=SubsidyRecipient.risk_score,
            risk_level=SubsidyRecipient.risk_level,
            # В методике слоя 8.5 серого уровня нет вовсе, поэтому и
            # предварительного балла быть не может.
            risk_is_preliminary=literal(False),
            risk_completeness=SubsidyRecipient.risk_completeness,
            status=None,
            source_layer="8.5",
        )
    )


def _project_entities_select(kind: ProjectEntityKind, object_type: ObjectType) -> Select[Any]:
    return select(
        *_normalized(
            object_type=object_type,
            object_id=ProjectEntity.id,
            title=ProjectEntity.title,
            subtitle=ProjectEntity.territory_raw,
            territory_id=ProjectEntity.territory_id,
            amount=None,
            amount_unit="₸",
            risk_score=ProjectEntity.risk_score,
            risk_level=func.coalesce(
                ProjectEntity.risk_level, literal(RiskLevel.UNKNOWN.value)
            ),
            risk_is_preliminary=ProjectEntity.risk_is_preliminary,
            risk_completeness=ProjectEntity.risk_completeness,
            status=None,
            source_layer="8.6",
        )
    ).where(ProjectEntity.kind == kind)


def _organizations_select() -> Select[Any]:
    return select(
        *_normalized(
            object_type=ObjectType.ORGANIZATION,
            object_id=Organization.bin,
            title=Organization.name,
            subtitle=None,
            # Территории у организаций нет ни в одном виде — см. слой 8.7.
            territory_id=None,
            amount=None,
            amount_unit="₸",
            risk_score=Organization.risk_score,
            # Официальный уровень — строгий. Предварительный показывается
            # рядом с баллом, но не подменяет уровень в фильтрах и агрегатах.
            risk_level=func.coalesce(
                Organization.risk_level_strict, literal(RiskLevel.UNKNOWN.value)
            ),
            # Полнота в этом слое максимум 40.9 % — ниже порога серого,
            # поэтому балл всегда предварительный, кроме категории A, где
            # уровень назначен жёстким правилом.
            risk_is_preliminary=Organization.risk_level_strict == literal(
                RiskLevel.UNKNOWN.value
            ),
            risk_completeness=Organization.risk_completeness,
            status=None,
            source_layer="8.7",
        )
    )


_BUILDERS: dict[ObjectType, Any] = {
    ObjectType.CONTRACT: _contracts_select,
    ObjectType.SUBSIDY_RECIPIENT: _subsidy_recipients_select,
    ObjectType.PPP_PROJECT: lambda: _project_entities_select(
        ProjectEntityKind.PPP_PROJECT, ObjectType.PPP_PROJECT
    ),
    ObjectType.EXPERTISE_OBJECT: lambda: _project_entities_select(
        ProjectEntityKind.EXPERTISE_CONCLUSION, ObjectType.EXPERTISE_OBJECT
    ),
    ObjectType.ORGANIZATION: _organizations_select,
}


def _risk_order_expression(level_column: ColumnLike) -> ColumnElement[Any]:
    """Порядок уровней для сортировки «по риску».

    Задан явно, а не алфавитом: по алфавиту получается
    `critical < high < low < medium`, что бессмысленно. «Нет данных» получает
    ранг −1 и не притворяется низким риском: объект без оценки не должен
    уезжать в благополучный конец списка.
    """
    ranked: ColumnElement[Any] = case(
        (level_column == RiskLevel.CRITICAL.value, 3),
        (level_column == RiskLevel.HIGH.value, 2),
        (level_column == RiskLevel.MEDIUM.value, 1),
        (level_column == RiskLevel.LOW.value, 0),
        else_=-1,
    )
    return ranked


def build_query(
    spec: QuerySpec, *, allowed_territory_ids: Collection[uuid.UUID] | None = None
) -> tuple[Select[Any], Any]:
    """Собрать запрос выборки объектов и подзапрос с нормализованными колонками.

    Подзапрос возвращается вторым значением, потому что сортировка и агрегаты
    обращаются к его колонкам. Доставать их из `Select.froms` — приём хрупкий:
    состав источников меняется при любой правке запроса.

    `allowed_territory_ids` — территориальное ограничение пользователя.
    `None` означает «доступны все территории», пустой список — «ни одной»,
    и это разные вещи: пустой список обязан давать пустую выборку, а не полную.
    """
    types = spec.object_types or list(_BUILDERS)
    parts = [_BUILDERS[t]() for t in types if t in _BUILDERS]

    if not parts:
        # Пустая выборка описывается явным условием, а не отсутствием
        # запроса: вызывающему проще, когда тип возвращаемого значения один.
        parts = [_contracts_select().where(literal(False))]

    unified = (
        parts[0].union_all(*parts[1:]).subquery("objects")
        if len(parts) > 1
        else parts[0].subquery("objects")
    )

    stmt = select(
        unified,
        Territory.code.label("territory_code"),
        Territory.name_ru.label("territory_name"),
    ).outerjoin(Territory, Territory.id == unified.c.territory_id)

    levels = [level.value for level in spec.risk_levels]
    stmt = stmt.where(unified.c.risk_level.in_(levels))

    if spec.amount_min is not None:
        stmt = stmt.where(unified.c.amount >= spec.amount_min)
    if spec.amount_max is not None:
        stmt = stmt.where(unified.c.amount <= spec.amount_max)

    if spec.completeness_min is not None:
        stmt = stmt.where(unified.c.risk_completeness >= spec.completeness_min)
    if spec.completeness_max is not None:
        stmt = stmt.where(unified.c.risk_completeness <= spec.completeness_max)

    if spec.territory_codes:
        stmt = stmt.where(Territory.code.in_(spec.territory_codes))

    if allowed_territory_ids is not None:
        # Объекты без территории (организации слоя 8.7) недоступны
        # пользователю, ограниченному территорией: подтвердить его право на
        # них нечем.
        stmt = stmt.where(unified.c.territory_id.in_(allowed_territory_ids))

    if spec.search:
        pattern = f"%{spec.search.strip()}%"
        stmt = stmt.where(
            or_(
                unified.c.title.ilike(pattern),
                unified.c.object_id.ilike(pattern),
                unified.c.subtitle.ilike(pattern),
            )
        )

    return stmt, unified


def _sorted(stmt: Select[Any], spec: QuerySpec, unified: Any) -> Select[Any]:
    descending = spec.order is SortOrder.DESC

    if spec.sort is SortField.RISK:
        # Балл как вторичный ключ: внутри уровня объекты идут от более
        # тревожного к менее.
        primary = _risk_order_expression(unified.c.risk_level)
        secondary = unified.c.risk_score
    elif spec.sort is SortField.AMOUNT:
        primary = unified.c.amount
        secondary = unified.c.title
    elif spec.sort is SortField.NAME:
        primary = unified.c.title
        secondary = unified.c.object_id
    else:
        primary = unified.c.risk_score
        secondary = unified.c.title

    order = [
        primary.desc().nullslast() if descending else primary.asc().nullsfirst(),
        secondary.desc().nullslast() if descending else secondary.asc().nullsfirst(),
        # Устойчивый третий ключ: без него две страницы подряд могут показать
        # один и тот же объект, а другой не показать вовсе.
        unified.c.object_id.asc(),
    ]
    return stmt.order_by(*order)


def list_objects(
    session: Session,
    spec: QuerySpec,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
) -> tuple[list[ObjectCard], int]:
    """Страница выборки и общее число объектов."""
    stmt, unified = build_query(spec, allowed_territory_ids=allowed_territory_ids)

    # Общее число считается до постраничности: пользователю нужно знать,
    # сколько объектов нашлось всего, а не сколько уместилось на странице.
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = _sorted(stmt, spec, unified)
    rows = session.execute(stmt.offset(spec.offset).limit(spec.page_size)).mappings().all()

    cards = [
        ObjectCard(
            object_type=ObjectType(row["object_type"]),
            object_id=row["object_id"],
            title=row["title"],
            subtitle=row["subtitle"],
            territory_code=row["territory_code"],
            territory_name=row["territory_name"],
            amount=row["amount"],
            amount_unit=row["amount_unit"],
            risk_score=row["risk_score"],
            risk_level=RiskLevel(row["risk_level"]),
            risk_is_preliminary=bool(row["risk_is_preliminary"]),
            risk_completeness=row["risk_completeness"],
            status=row["status"],
            source_layer=row["source_layer"],
            data_as_of=None,
        )
        for row in rows
    ]

    return cards, total


def level_counts(
    session: Session,
    spec: QuerySpec,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
) -> dict[RiskLevel, int]:
    """Распределение выборки по уровням риска.

    Считается по той же выборке, что и список, но без постраничности: сводка
    относится ко всей выборке, а не к текущей странице.
    """
    stmt, _ = build_query(
        spec.without_pagination(), allowed_territory_ids=allowed_territory_ids
    )
    scoped = stmt.subquery()

    counts = dict.fromkeys(RiskLevel, 0)
    rows = session.execute(
        select(scoped.c.risk_level, func.count()).group_by(scoped.c.risk_level)
    ).all()

    for level_value, count in rows:
        counts[RiskLevel(level_value)] = count

    return counts
