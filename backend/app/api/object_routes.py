"""Эндпоинты выборки объектов: список, сводка по уровням.

Список и карта строятся по одной и той же выборке — см. `app.api.queryspec`.
Территориальное ограничение накладывается здесь, на сервере, а не на клиенте:
клиент не источник истины о правах, и запрос с чужой территорией обязан
упереться в сервер, а не в интерфейс.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.api.queryspec import PageInfo, QuerySpec
from app.core.permissions import (
    PermissionCode,
    TerritoryScope,
    get_territory_scope,
    require_permission,
)
from app.risk.core import RiskLevel
from app.services import catalog

router = APIRouter(prefix="/objects", tags=["объекты"])

ScopeDep = Annotated[TerritoryScope, Depends(get_territory_scope)]


def _spec_from_query(request_params: dict[str, Any]) -> QuerySpec:
    return QuerySpec.from_query_params(request_params)


@router.get(
    "",
    summary="Выборка объектов",
    dependencies=[Depends(require_permission(PermissionCode.MAP_VIEW))],
)
def list_objects(
    session: DbSession,
    scope: ScopeDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
    search: Annotated[str | None, Query(max_length=255)] = None,
    object_types: Annotated[str | None, Query(description="Через запятую")] = None,
    territory_codes: Annotated[str | None, Query(description="Через запятую")] = None,
    risk_levels: Annotated[str | None, Query(description="Через запятую")] = None,
    amount_min: Annotated[float | None, Query(ge=0)] = None,
    amount_max: Annotated[float | None, Query(ge=0)] = None,
    sort: Annotated[str, Query()] = "risk",
    order: Annotated[str, Query()] = "desc",
) -> dict[str, Any]:
    """Страница выборки.

    Параметры повторяют имена канонической выборки, чтобы адресная строка
    интерфейса и запрос к API совпадали один в один. Расхождение между ними
    неизбежно приводит к тому, что ссылка воспроизводит не ту выборку.
    """
    spec = _spec_from_query(
        {
            "page": page,
            "page_size": page_size,
            "search": search,
            "object_types": object_types,
            "territory_codes": territory_codes,
            "risk_levels": risk_levels,
            "amount_min": amount_min,
            "amount_max": amount_max,
            "sort": sort,
            "order": order,
        }
    )

    cards, total = catalog.list_objects(
        session, spec, allowed_territory_ids=scope.allowed_ids
    )
    page_info = PageInfo.build(spec, total)

    return {
        "items": [
            {
                "object_type": card.object_type,
                "object_id": card.object_id,
                "title": card.title,
                "subtitle": card.subtitle,
                "territory_code": card.territory_code,
                "territory_name": card.territory_name,
                "amount": float(card.amount) if card.amount is not None else None,
                "amount_unit": card.amount_unit,
                "risk_score": card.risk_score,
                "risk_level": card.risk_level,
                "risk_is_preliminary": card.risk_is_preliminary,
                "risk_completeness": card.risk_completeness,
                "status": card.status,
                "source_layer": card.source_layer,
            }
            for card in cards
        ],
        "page": page_info.model_dump(),
        "applied_filters": spec.active_filter_chips(),
        "query": spec.to_query_params(),
    }


@router.get(
    "/summary",
    summary="Распределение выборки по уровням риска",
    dependencies=[Depends(require_permission(PermissionCode.RISK_VIEW))],
)
def objects_summary(
    session: DbSession,
    scope: ScopeDep,
    search: Annotated[str | None, Query(max_length=255)] = None,
    object_types: Annotated[str | None, Query()] = None,
    territory_codes: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Сводка по всей выборке, а не по текущей странице.

    Уровень «нет данных» присутствует в ответе всегда, даже когда он нулевой:
    его отсутствие в сводке читалось бы как «неизмеренных объектов не бывает».
    """
    spec = _spec_from_query(
        {
            "search": search,
            "object_types": object_types,
            "territory_codes": territory_codes,
        }
    )

    counts = catalog.level_counts(session, spec, allowed_territory_ids=scope.allowed_ids)
    measured = sum(count for level, count in counts.items() if level is not RiskLevel.UNKNOWN)

    return {
        "levels": {level.value: count for level, count in counts.items()},
        "labels": {level.value: level.label_ru for level in RiskLevel},
        "total": sum(counts.values()),
        "measured": measured,
        "unmeasured": counts[RiskLevel.UNKNOWN],
    }
