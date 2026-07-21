"""Выборка подграфа связей (ТЗ 13).

**Весь граф в браузер не отдаётся.** Это не оптимизация, а требование ТЗ 20:
при больших объёмах объектов фильтрация и кластеризация выполняются на сервере.
В витрине 11 782 узла и 16 266 связей; одна отдача целиком — это мегабайты
JSON, секунды разбора и раскладка, в которой всё равно ничего не разобрать.
Поэтому наружу отдаётся окружение **одного** узла с двумя ограничителями:
глубиной обхода и предельным числом узлов. Раскрытие соседа — отдельный запрос
от того же эндпоинта с новым центром.

**Усечение всегда объявляется.** Если соседей больше, чем помещается, ответ
несёт `truncated`, число скрытых узлов и их общее количество. Молчаливое
обрезание страшнее отсутствия данных: пользователь делает вывод «связей мало»
по картинке, которая на самом деле показывает «связей слишком много».

**Порядок обхода не случаен.** При нехватке места первыми в подграф попадают
достоверные связи и узлы с высоким уровнем риска. Обрезать нужно наименее
существенное, а не то, что оказалось дальше в физическом порядке строк.

**ИИН маскируется здесь, а не в маршруте.** Идентификатор физического лица
проходит через `services.masking`, и полное раскрытие журналируется. Оставить
маскирование маршруту значило бы, что новый эндпоинт, автор которого про него
забудет, отдаст персональные данные молча.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models.access import User
from app.db.models.graph import (
    EntityRelation,
    GraphNode,
    NodeType,
    RelationConfidence,
    RelationDirection,
    RelationType,
)
from app.risk.core import RiskLevel
from app.services import masking
from app.services.audit import RequestContext

#: Предел глубины обхода. Два шага — это «связанные с моими связанными»; на
#: третьем шаге в окружение попадает половина графа через любую программу
#: субсидирования, и картинка перестаёт что-либо означать.
MAX_DEPTH: Final = 2

#: Сколько узлов помещается в один ответ по умолчанию и максимум. Верхний
#: предел жёсткий: параметр приходит от клиента, а клиент не источник истины
#: о том, сколько сервер готов отдать.
DEFAULT_MAX_NODES: Final = 60
MAX_NODES_LIMIT: Final = 200

#: Сколько строк связей читается за один шаг обхода. Предохранитель против
#: узла-концентратора: у программы субсидирования соседей три тысячи, и без
#: предела один шаг вытянул бы их все, чтобы затем выбросить.
EDGE_SCAN_LIMIT: Final = 2000

#: Минимальная длина строки поиска. По одной букве осмысленной выборки не
#: получится, а полный скан таблицы получится.
MIN_QUERY_LENGTH: Final = 2


@dataclass(frozen=True, slots=True)
class NodeView:
    """Узел в том виде, в каком он уходит наружу."""

    key: str
    node_type: str
    node_type_label: str
    label: str
    sublabel: str | None
    identifier: dict[str, Any] | None
    """Замаскированный БИН/ИИН. `None` — идентификатора у узла нет вовсе."""

    identifier_kind: str | None
    risk_level: str
    risk_level_label: str
    risk_score: float | None
    risk_is_preliminary: bool
    degree: int
    source_layer: str
    ref_entity_type: str | None
    ref_entity_id: str | None
    attributes: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "node_type": self.node_type,
            "node_type_label": self.node_type_label,
            "label": self.label,
            "sublabel": self.sublabel,
            "identifier": self.identifier,
            "identifier_kind": self.identifier_kind,
            "risk_level": self.risk_level,
            "risk_level_label": self.risk_level_label,
            "risk_score": self.risk_score,
            "risk_is_preliminary": self.risk_is_preliminary,
            "degree": self.degree,
            "source_layer": self.source_layer,
            "ref_entity_type": self.ref_entity_type,
            "ref_entity_id": self.ref_entity_id,
            "attributes": self.attributes,
        }


@dataclass(frozen=True, slots=True)
class EdgeView:
    """Связь в том виде, в каком она уходит наружу."""

    id: str
    relation_type: str
    relation_type_label: str
    source: str
    target: str
    direction: str
    confidence: str
    confidence_label: str
    confidence_basis: str
    source_layer: str
    derivation_rule: str
    amount: float | None
    data_as_of: str | None
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "relation_type": self.relation_type,
            "relation_type_label": self.relation_type_label,
            "source": self.source,
            "target": self.target,
            "direction": self.direction,
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "confidence_basis": self.confidence_basis,
            "source_layer": self.source_layer,
            "derivation_rule": self.derivation_rule,
            "amount": self.amount,
            "data_as_of": self.data_as_of,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class Subgraph:
    """Окружение узла и честный отчёт о том, что в него не поместилось."""

    center: str
    nodes: list[NodeView] = field(default_factory=list)
    edges: list[EdgeView] = field(default_factory=list)
    depth: int = 1
    max_nodes: int = DEFAULT_MAX_NODES
    truncated: bool = False
    omitted_nodes: int = 0
    total_neighbors: int = 0
    """Сколько связей у центрального узла всего — до всех ограничений."""

    scope_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "depth": self.depth,
            "max_nodes": self.max_nodes,
            "truncated": self.truncated,
            "omitted_nodes": self.omitted_nodes,
            "total_neighbors": self.total_neighbors,
            "scope_note": self.scope_note,
        }


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------


def _risk_level(raw: str | None) -> RiskLevel:
    """Уровень риска узла с приведением к перечислению.

    Отсутствие уровня — это `UNKNOWN`, а не пропуск поля: «нет данных» —
    полноправный уровень по ТЗ 7.3, и узел без оценки обязан быть виден
    именно как неизмеренный, а не как нейтральный.
    """
    try:
        return RiskLevel(str(raw))
    except ValueError:
        return RiskLevel.UNKNOWN


def _scope_note(allowed: Collection[uuid.UUID] | None) -> str:
    if allowed is None:
        return (
            "Показаны связи всех территорий, включая факты без территориальной "
            "привязки."
        )
    return (
        "Показаны только связи доступных вам территорий. Связи, у которых "
        "территория в источнике не указана, в выборку не входят — подтвердить "
        "их принадлежность вашей зоне нечем."
    )


def _apply_scope(
    stmt: Select[Any], column: Any, allowed: Collection[uuid.UUID] | None
) -> Select[Any]:
    """Территориальное ограничение доступа.

    Записи без территории ограниченному пользователю не показываются — то же
    правило, что и в `TerritoryScope.allows`. Иначе через «неопределённые»
    строки утекали бы чужие районы.
    """
    if allowed is None:
        return stmt
    return stmt.where(column.in_(allowed))


def _mask_identifiers(
    rows: Sequence[GraphNode],
    *,
    user: User,
    session: Session | None,
    context: RequestContext | None,
) -> dict[str, dict[str, Any] | None]:
    """Идентификаторы узлов, приведённые к правам пользователя.

    БИН и ИИН обрабатываются по-разному, и это не придирка. БИН — публичный
    реквизит юридического лица из открытого реестра; прятать его не от чего, и
    именно он делает граф проверяемым. ИИН — персональные данные, и его полное
    раскрытие пишется в журнал одной записью на выборку (см. `masking`).
    """
    result: dict[str, dict[str, Any] | None] = {}

    person_nodes = [row for row in rows if row.identifier_kind == "iin" and row.identifier]
    masked = masking.reveal_many(
        [row.identifier for row in person_nodes],
        user=user,
        session=session,
        context=context,
        field="iin",
        entity_type="graph_node",
    )
    for row, value in zip(person_nodes, masked, strict=True):
        result[row.node_key] = value.to_dict()

    for row in rows:
        if row.node_key in result:
            continue
        result[row.node_key] = (
            {"value": row.identifier, "present": True, "access": "full"}
            if row.identifier
            else None
        )
    return result


def _to_node_views(
    rows: Sequence[GraphNode],
    *,
    user: User,
    session: Session | None,
    context: RequestContext | None,
) -> list[NodeView]:
    identifiers = _mask_identifiers(rows, user=user, session=session, context=context)
    views: list[NodeView] = []
    for row in rows:
        level = _risk_level(row.risk_level)
        views.append(
            NodeView(
                key=row.node_key,
                node_type=str(row.node_type),
                node_type_label=NodeType(str(row.node_type)).label_ru,
                label=row.label,
                sublabel=row.sublabel,
                identifier=identifiers.get(row.node_key),
                identifier_kind=row.identifier_kind,
                risk_level=level.value,
                risk_level_label=level.label_ru,
                risk_score=row.risk_score,
                risk_is_preliminary=row.risk_is_preliminary,
                degree=row.degree,
                source_layer=row.source_layer,
                ref_entity_type=row.ref_entity_type,
                ref_entity_id=str(row.ref_entity_id) if row.ref_entity_id else None,
                attributes=dict(row.attributes or {}),
            )
        )
    return views


def _to_edge_view(relation: EntityRelation, source_key: str, target_key: str) -> EdgeView:
    return EdgeView(
        id=str(relation.id),
        relation_type=str(relation.relation_type),
        relation_type_label=RelationType(str(relation.relation_type)).label_ru,
        source=source_key,
        target=target_key,
        direction=str(relation.direction),
        confidence=str(relation.confidence),
        confidence_label=RelationConfidence(str(relation.confidence)).label_ru,
        confidence_basis=relation.confidence_basis,
        source_layer=relation.source_layer,
        derivation_rule=relation.derivation_rule,
        amount=float(relation.amount) if isinstance(relation.amount, Decimal) else None,
        data_as_of=relation.data_as_of.isoformat() if relation.data_as_of else None,
        evidence=dict(relation.evidence or {}),
    )


# ---------------------------------------------------------------------------
# Точка входа: поиск узла
# ---------------------------------------------------------------------------


def search_nodes(
    session: Session,
    query: str,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    node_types: Iterable[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    user: User,
    context: RequestContext | None = None,
) -> list[NodeView]:
    """Найти узлы по наименованию или ФИО — точка входа в граф.

    Пустой запрос — не ошибка, а «покажи всех»: витрина перелистывается
    страницами в том же порядке, что и результаты поиска. Это не выдача графа
    целиком (ТЗ 20): отдаётся страница узлов без единой связи между ними, а
    связи по-прежнему только через `neighborhood` вокруг названного узла.

    Поиск идёт **только** по метке узла. По идентификатору искать нельзя:
    строка запроса попадает в журнал доступа и в адресную строку, и поиск по
    ИИН превратил бы оба в хранилище персональных данных (см. санитайзер
    `services/audit._sanitize`, который вычищает такие ключи принудительно).

    Порядок выдачи — по убыванию тревожности и связности: если совпадений
    много, первым должно оказаться то, ради чего в граф вообще заходят.
    """
    normalized = query.strip()
    if normalized and len(normalized) < MIN_QUERY_LENGTH:
        return []

    stmt = _search_query(normalized, node_types, allowed_territory_ids)

    rows = (
        session.execute(
            stmt.order_by(
                _risk_order(GraphNode.risk_level),
                GraphNode.degree.desc(),
                # Устойчивый третий ключ: без него две страницы подряд могут
                # показать один и тот же узел, а другой не показать вовсе —
                # уровень риска и связность совпадают у тысяч записей.
                GraphNode.node_key.asc(),
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
        .scalars()
        .all()
    )
    return _to_node_views(rows, user=user, session=session, context=context)


def _search_query(
    normalized: str,
    node_types: Iterable[str] | None,
    allowed_territory_ids: Collection[uuid.UUID] | None,
) -> Select[Any]:
    """Отбор без сортировки и постраничности — общий для выдачи и счёта."""
    stmt = select(GraphNode)
    if normalized:
        stmt = stmt.where(GraphNode.label.ilike(f"%{normalized}%"))

    types = [str(item) for item in (node_types or []) if item]
    if types:
        stmt = stmt.where(GraphNode.node_type.in_(types))

    return _apply_scope(stmt, GraphNode.territory_id, allowed_territory_ids)


def count_nodes(
    session: Session,
    query: str,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    node_types: Iterable[str] | None = None,
) -> int:
    """Сколько узлов подходит под отбор целиком.

    Считается до постраничности: «показано 20 из 11 782» — единственное, что
    отличает начало длинного списка от его конца.
    """
    normalized = query.strip()
    if normalized and len(normalized) < MIN_QUERY_LENGTH:
        return 0

    stmt = _search_query(normalized, node_types, allowed_territory_ids)
    return session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def _risk_order(column: Any) -> Any:
    """Сортировка «сначала тревожное».

    «Нет данных» ставится не в конец, а сразу после измеренных высоких: это
    не благополучие, а незнание, и прятать такие узлы в хвост выдачи значит
    повторять ошибку, от которой предостерегает `risk/core.py`.
    """
    return case(
        (column == RiskLevel.CRITICAL.value, 0),
        (column == RiskLevel.HIGH.value, 1),
        (column == RiskLevel.MEDIUM.value, 2),
        (column == RiskLevel.LOW.value, 4),
        else_=3,
    )


def node_by_key(
    session: Session,
    key: str,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    user: User,
    context: RequestContext | None = None,
) -> NodeView | None:
    """Один узел по ключу, с проверкой территориальной области видимости."""
    stmt = _apply_scope(
        select(GraphNode).where(GraphNode.node_key == key),
        GraphNode.territory_id,
        allowed_territory_ids,
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return _to_node_views([row], user=user, session=session, context=context)[0]


def relation_breakdown(
    session: Session,
    key: str,
    *,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Сколько у узла связей каждого типа — до всех ограничений выборки.

    Нужно, чтобы предупредить об усечении **до** раскрытия, а не после.
    Пользователь, видящий «показано 60 из 3 214», понимает, что смотрит
    фрагмент; пользователь, видящий просто 60 узлов, — нет.
    """
    node = session.execute(
        select(GraphNode.id).where(GraphNode.node_key == key)
    ).scalar_one_or_none()
    if node is None:
        return []

    stmt = select(
        EntityRelation.relation_type,
        EntityRelation.confidence,
        func.count().label("count"),
    ).where(
        or_(EntityRelation.source_node_id == node, EntityRelation.target_node_id == node)
    )
    stmt = _apply_scope(stmt, EntityRelation.territory_id, allowed_territory_ids)

    rows = session.execute(
        stmt.group_by(EntityRelation.relation_type, EntityRelation.confidence)
    ).all()

    merged: dict[str, dict[str, Any]] = {}
    for relation_type, confidence, count in rows:
        bucket = merged.setdefault(
            str(relation_type),
            {
                "relation_type": str(relation_type),
                "label": RelationType(str(relation_type)).label_ru,
                "confirmed": 0,
                "probable": 0,
                "total": 0,
            },
        )
        key_name = (
            "confirmed"
            if RelationConfidence(str(confidence)) is RelationConfidence.CONFIRMED
            else "probable"
        )
        bucket[key_name] += int(count)
        bucket["total"] += int(count)
    return sorted(merged.values(), key=lambda item: -int(item["total"]))


# ---------------------------------------------------------------------------
# Обход окружения
# ---------------------------------------------------------------------------


def neighborhood(
    session: Session,
    key: str,
    *,
    depth: int = 1,
    max_nodes: int = DEFAULT_MAX_NODES,
    relation_types: Iterable[str] | None = None,
    min_confidence: str | None = None,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
    user: User,
    context: RequestContext | None = None,
) -> Subgraph | None:
    """Подграф вокруг узла: обход в ширину с двумя ограничителями.

    Обход идёт по уровням, и на каждом уровне связи читаются одним запросом на
    весь фронт, а не по запросу на узел: второе дало бы N+1 и на узле-хабе
    выродилось бы в тысячи обращений к базе.

    Бюджет узлов расходуется по мере обхода. Как только он исчерпан, новые
    узлы не добавляются, а связи, ведущие к ним, отбрасываются — ребро в
    пустоту нарисовать невозможно, а нарисовать его к случайно попавшему узлу
    значит соврать о структуре.
    """
    depth = max(1, min(depth, MAX_DEPTH))
    max_nodes = max(2, min(max_nodes, MAX_NODES_LIMIT))

    center = session.execute(
        select(GraphNode).where(GraphNode.node_key == key)
    ).scalar_one_or_none()
    if center is None:
        return None
    # Центр проверяется той же областью видимости, что и всё остальное: без
    # этого ограниченный пользователь, угадав ключ, получил бы карточку узла
    # чужого района, пусть и без связей.
    if allowed_territory_ids is not None and center.territory_id not in allowed_territory_ids:
        return None

    subgraph = Subgraph(
        center=key,
        depth=depth,
        max_nodes=max_nodes,
        scope_note=_scope_note(allowed_territory_ids),
    )

    visited: dict[uuid.UUID, GraphNode] = {center.id: center}
    frontier: set[uuid.UUID] = {center.id}
    seen_edges: set[uuid.UUID] = set()

    types = [str(item) for item in (relation_types or []) if item]
    only_confirmed = (
        min_confidence is not None
        and str(min_confidence) == RelationConfidence.CONFIRMED.value
    )

    subgraph.total_neighbors = _count_incident(
        session,
        center.id,
        types=types,
        only_confirmed=only_confirmed,
        allowed=allowed_territory_ids,
    )

    for _ in range(depth):
        if not frontier:
            break

        source_node = aliased(GraphNode)
        target_node = aliased(GraphNode)

        stmt = (
            select(EntityRelation, source_node, target_node)
            .join(source_node, EntityRelation.source_node_id == source_node.id)
            .join(target_node, EntityRelation.target_node_id == target_node.id)
            .where(
                or_(
                    EntityRelation.source_node_id.in_(frontier),
                    EntityRelation.target_node_id.in_(frontier),
                )
            )
        )
        if types:
            stmt = stmt.where(EntityRelation.relation_type.in_(types))
        if only_confirmed:
            stmt = stmt.where(
                EntityRelation.confidence == RelationConfidence.CONFIRMED.value
            )
        stmt = _apply_scope(stmt, EntityRelation.territory_id, allowed_territory_ids)

        # Порядок обрезания: сперва достоверные связи, затем более тревожные
        # концы, затем крупные суммы. Обрезать нужно наименее существенное.
        stmt = stmt.order_by(
            case(
                (EntityRelation.confidence == RelationConfidence.CONFIRMED.value, 0),
                else_=1,
            ),
            _risk_order(target_node.risk_level),
            _risk_order(source_node.risk_level),
            EntityRelation.amount.desc().nullslast(),
            EntityRelation.id,
        ).limit(EDGE_SCAN_LIMIT)

        rows = session.execute(stmt).all()
        next_frontier: set[uuid.UUID] = set()

        for relation, source_row, target_row in rows:
            other = target_row if relation.source_node_id in frontier else source_row
            if other.id not in visited:
                if len(visited) >= max_nodes:
                    # Бюджет исчерпан: узел и ведущая к нему связь не
                    # показываются, но факт пропуска попадает в ответ.
                    subgraph.truncated = True
                    subgraph.omitted_nodes += 1
                    continue
                visited[other.id] = other
                next_frontier.add(other.id)

            if relation.id not in seen_edges:
                seen_edges.add(relation.id)
                subgraph.edges.append(
                    _to_edge_view(relation, source_row.node_key, target_row.node_key)
                )

        if len(rows) >= EDGE_SCAN_LIMIT:
            # Предохранитель сработал: связей больше, чем читается за шаг.
            subgraph.truncated = True

        frontier = next_frontier

    subgraph.nodes = _to_node_views(
        list(visited.values()), user=user, session=session, context=context
    )
    return subgraph


def _count_incident(
    session: Session,
    node_id: uuid.UUID,
    *,
    types: Sequence[str],
    only_confirmed: bool,
    allowed: Collection[uuid.UUID] | None,
) -> int:
    """Сколько связей у узла всего — знаменатель для честного «показано N из M»."""
    stmt = select(func.count()).select_from(EntityRelation).where(
        or_(EntityRelation.source_node_id == node_id, EntityRelation.target_node_id == node_id)
    )
    if types:
        stmt = stmt.where(EntityRelation.relation_type.in_(list(types)))
    if only_confirmed:
        stmt = stmt.where(EntityRelation.confidence == RelationConfidence.CONFIRMED.value)
    stmt = _apply_scope(stmt, EntityRelation.territory_id, allowed)
    return int(session.scalar(stmt) or 0)


# ---------------------------------------------------------------------------
# Легенда
# ---------------------------------------------------------------------------


def legend() -> dict[str, Any]:
    """Словари типов для панели фильтров и легенды.

    Отдаются сервером, а не зашиваются в интерфейс: перечень типов задаётся
    моделью данных, и разъезд подписей между API и экраном — вопрос времени.
    """
    return {
        "node_types": [
            {"code": str(item), "label": item.label_ru} for item in NodeType
        ],
        "relation_types": [
            {"code": str(item), "label": item.label_ru} for item in RelationType
        ],
        "confidence": [
            {
                "code": RelationConfidence.CONFIRMED.value,
                "label": RelationConfidence.CONFIRMED.label_ru,
                "style": "solid",
                "note": "Связь доказана совпадением идентификатора или ключом источника.",
            },
            {
                "code": RelationConfidence.PROBABLE.value,
                "label": RelationConfidence.PROBABLE.label_ru,
                "style": "dashed",
                "note": (
                    "Связь выведена из совпадения наименования или адреса. "
                    "Требует проверки: тёзки и общие бизнес-центры не исключены."
                ),
            },
        ],
        "directions": [str(item) for item in RelationDirection],
        "limits": {
            "max_depth": MAX_DEPTH,
            "default_max_nodes": DEFAULT_MAX_NODES,
            "max_nodes": MAX_NODES_LIMIT,
        },
    }


def stats(session: Session) -> dict[str, Any]:
    """Состав витрины: сколько узлов и связей какого типа выведено.

    Типы с нулём остаются в ответе. «Учредителей 0» — содержательный факт: он
    означает, что состава учредителей нет в источниках, а не что связь забыли
    реализовать.
    """
    node_counts: dict[str, int] = {
        str(node_type): int(count)
        for node_type, count in session.execute(
            select(GraphNode.node_type, func.count()).group_by(GraphNode.node_type)
        ).all()
    }
    relation_rows = session.execute(
        select(EntityRelation.relation_type, EntityRelation.confidence, func.count()).group_by(
            EntityRelation.relation_type, EntityRelation.confidence
        )
    ).all()

    relations: dict[str, dict[str, Any]] = {
        str(item): {
            "code": str(item),
            "label": item.label_ru,
            "confirmed": 0,
            "probable": 0,
            "total": 0,
        }
        for item in RelationType
    }
    for relation_type, confidence, count in relation_rows:
        bucket = relations[str(relation_type)]
        name = (
            "confirmed"
            if RelationConfidence(str(confidence)) is RelationConfidence.CONFIRMED
            else "probable"
        )
        bucket[name] += int(count)
        bucket["total"] += int(count)

    return {
        "nodes": [
            {
                "code": str(item),
                "label": item.label_ru,
                "count": node_counts.get(str(item), 0),
            }
            for item in NodeType
        ],
        "nodes_total": sum(node_counts.values()),
        "relations": list(relations.values()),
        "relations_total": sum(int(item["total"]) for item in relations.values()),
    }


__all__ = [
    "DEFAULT_MAX_NODES",
    "EDGE_SCAN_LIMIT",
    "MAX_DEPTH",
    "MAX_NODES_LIMIT",
    "MIN_QUERY_LENGTH",
    "EdgeView",
    "NodeView",
    "Subgraph",
    "legend",
    "neighborhood",
    "node_by_key",
    "relation_breakdown",
    "search_nodes",
    "stats",
]
