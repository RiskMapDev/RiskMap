"""Эндпоинты графа взаимосвязей (ТЗ 13).

Четыре маршрута, и такое дробление намеренно.

`/graph/legend` и `/graph/stats` отвечают на вопрос «что вообще бывает в
графе»: перечень типов и состав витрины. Они не зависят от выбранного узла и
не должны перезапрашиваться при каждом раскрытии.

`/graph/search` — точка входа. Граф не имеет «первой страницы»: показать
что-то по умолчанию значит либо отдать всё (запрещено ТЗ 20), либо выбрать
узел произвольно. Пользователь называет субъект сам.

`/graph/neighbors` — единственный маршрут выдачи подграфа, и он же
обслуживает раскрытие соседа: раскрытие — это тот же запрос с новым центром.
Отдельный «expand» пришлось бы держать в согласии с основным запросом по
фильтрам и лимитам, и рассогласование было бы вопросом времени.

Права. Граф читается по `DATA_VIEW` — тому же праву, что список и карточки:
он показывает те же записи в другой проекции, и собственное право позволило
бы настроить доступ, при котором человек видит связи, но не видит объектов,
из которых они выведены. Территориальное ограничение накладывается на сервере
и к клиентским параметрам не восприимчиво.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, RequestCtx
from app.core.permissions import (
    PermissionCode,
    TerritoryScope,
    get_territory_scope,
    require_permission,
)
from app.services import graph

router = APIRouter(prefix="/graph", tags=["граф связей"])

ScopeDep = Annotated[TerritoryScope, Depends(get_territory_scope)]


def _split(raw: str | None) -> list[str]:
    """Разобрать список, переданный через запятую.

    Тот же способ, что в выборке объектов: адресная строка интерфейса и запрос
    к API должны совпадать один в один, иначе ссылка воспроизводит не то.
    """
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@router.get(
    "/legend",
    summary="Типы узлов, связей и достоверностей",
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def graph_legend() -> dict[str, Any]:
    """Словари для панели фильтров и легенды."""
    return graph.legend()


@router.get(
    "/stats",
    summary="Состав витрины связей",
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def graph_stats(session: DbSession) -> dict[str, Any]:
    """Сколько узлов и связей каждого типа выведено из данных.

    Территориальное ограничение здесь намеренно не применяется: это сводка о
    самой витрине, а не выборка записей. Пользователю района полезно знать, что
    связь «учредитель» отсутствует во всей системе, а не в его районе.
    """
    return graph.stats(session)


@router.get(
    "/search",
    summary="Поиск узла — точка входа в граф",
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def graph_search(
    session: DbSession,
    scope: ScopeDep,
    user: CurrentUser,
    context: RequestCtx,
    q: Annotated[str, Query(min_length=1, max_length=255, description="Наименование или ФИО")],
    node_types: Annotated[str | None, Query(description="Через запятую")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """Узлы, чья подпись содержит строку запроса.

    Поиск идёт только по наименованию и ФИО. По идентификатору не ищем: строка
    запроса оседает в журнале и в адресной строке, и поиск по ИИН превратил бы
    их в хранилище персональных данных.
    """
    nodes = graph.search_nodes(
        session,
        q,
        allowed_territory_ids=scope.allowed_ids,
        node_types=_split(node_types),
        limit=limit,
        user=user,
        context=context,
    )
    return {
        "items": [node.to_dict() for node in nodes],
        "query": q,
        "min_query_length": graph.MIN_QUERY_LENGTH,
        "scope_restricted": scope.allowed_ids is not None,
    }


@router.get(
    "/node/{node_key}",
    summary="Карточка узла и разбивка его связей по типам",
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def graph_node(
    session: DbSession,
    scope: ScopeDep,
    user: CurrentUser,
    context: RequestCtx,
    node_key: str,
) -> dict[str, Any]:
    """Узел и то, сколько у него связей каждого типа.

    Разбивка отдаётся до раскрытия окружения намеренно: пользователь должен
    заранее знать, что у выбранного узла три тысячи связей и он увидит их
    часть, а не обнаруживать это по обрезанной картинке.
    """
    node = graph.node_by_key(
        session,
        node_key,
        allowed_territory_ids=scope.allowed_ids,
        user=user,
        context=context,
    )
    if node is None:
        # Один и тот же ответ на «узла нет» и «узел вне вашей территории».
        # Разные ответы позволяли бы перебором ключей выяснить состав чужого
        # района, а состав — это уже сведения.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Узел не найден или вне зоны доступа"
        )

    return {
        "node": node.to_dict(),
        "relations": graph.relation_breakdown(
            session, node_key, allowed_territory_ids=scope.allowed_ids
        ),
    }


@router.get(
    "/neighbors",
    summary="Подграф вокруг узла",
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def graph_neighbors(
    session: DbSession,
    scope: ScopeDep,
    user: CurrentUser,
    context: RequestCtx,
    node: Annotated[str, Query(description="Ключ центрального узла")],
    depth: Annotated[int, Query(ge=1, le=graph.MAX_DEPTH)] = 1,
    max_nodes: Annotated[int, Query(ge=2, le=graph.MAX_NODES_LIMIT)] = graph.DEFAULT_MAX_NODES,
    relation_types: Annotated[str | None, Query(description="Через запятую")] = None,
    min_confidence: Annotated[
        str | None, Query(description="confirmed — только достоверные связи")
    ] = None,
) -> dict[str, Any]:
    """Окружение узла с ограничением глубины и числа узлов.

    Верхние границы `depth` и `max_nodes` заданы в самой сигнатуре, а не
    проверяются в теле: параметры приходят от клиента, и запрос «отдай весь
    граф» обязан упереться в 422 на границе API, а не в память сервера.
    Ответ всегда содержит `truncated` и число скрытых узлов — усечение
    объявляется, а не выполняется молча.
    """
    subgraph = graph.neighborhood(
        session,
        node,
        depth=depth,
        max_nodes=max_nodes,
        relation_types=_split(relation_types),
        min_confidence=min_confidence,
        allowed_territory_ids=scope.allowed_ids,
        user=user,
        context=context,
    )
    if subgraph is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Узел не найден или вне зоны доступа"
        )
    return subgraph.to_dict()
