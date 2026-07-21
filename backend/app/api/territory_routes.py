"""Эндпоинты территорий: справочник, границы, карточка."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models.territory import TerritoryLevel
from app.db.session import get_db
from app.services import territories as service
from app.services.layers import LAYERS, LAYERS_BY_CODE, layers_for_level

router = APIRouter(prefix="/territories", tags=["территории"])


@router.get("", summary="Справочник территорий")
def list_territories(
    session: Annotated[Session, Depends(get_db)],
    level: Annotated[TerritoryLevel | None, Query(description="Уровень иерархии")] = None,
    parent: Annotated[str | None, Query(description="Код родительской территории")] = None,
) -> list[dict[str, Any]]:
    items = service.list_territories(session, level=level, parent_code=parent)
    return [service.territory_properties(item) for item in items]


@router.get("/tree", summary="Иерархия территорий для фильтра")
def territory_tree(session: Annotated[Session, Depends(get_db)]) -> list[dict[str, Any]]:
    return service.territory_tree(session)


@router.get("/geojson", summary="Границы территорий")
def territories_geojson(
    session: Annotated[Session, Depends(get_db)],
    level: Annotated[
        list[TerritoryLevel] | None,
        Query(description="Уровни иерархии. Параметр повторяемый: районы и города вместе"),
    ] = None,
    parent: Annotated[str | None, Query()] = None,
    zoom: Annotated[
        float,
        Query(ge=0, le=22, description="Масштаб карты: от него зависит детализация контура"),
    ] = 7.0,
    layer: Annotated[
        str | None,
        Query(description="Код тематического слоя: заливка считается по его оценкам риска"),
    ] = None,
) -> dict[str, Any]:
    if layer is not None and layer not in LAYERS_BY_CODE:
        known = ", ".join(sorted(LAYERS_BY_CODE))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Слой {layer!r} не описан. Есть: {known}",
        )
    return service.territories_geojson(
        session, levels=level, parent_code=parent, zoom=zoom, layer=layer
    )


@router.get("/layers", summary="Тематические слои и их доступность по уровням")
def thematic_layers(
    level: Annotated[
        TerritoryLevel | None,
        Query(description="Если задан, отдаются только слои с данными на этом уровне"),
    ] = None,
) -> list[dict[str, Any]]:
    """Каталог слоёв.

    Клиенту отдаётся не только список доступных слоёв, но и причина
    недоступности остальных. Пустая заливка на карте неотличима от нулевого
    риска, поэтому интерфейс обязан объяснить, что данных нет.
    """
    selected = layers_for_level(level) if level is not None else LAYERS
    available = {layer.code for layer in selected}

    return [
        {
            "code": layer.code,
            "title": layer.title,
            "description": layer.description,
            "render": layer.render,
            "levels": sorted(layer.levels),
            "source_layer": layer.source_layer,
            "enabled_by_default": layer.enabled_by_default,
            "coverage_note": layer.coverage_note,
            "available": layer.code in available,
            "unavailability_reason": (
                layer.unavailability_reason(level) if level is not None else ""
            ),
        }
        for layer in LAYERS
    ]


@router.get("/{code}", summary="Карточка территории")
def territory_card(
    code: str,
    session: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    territory = service.territory_by_code(session, code)
    if territory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Территория {code!r} не найдена",
        )

    payload = service.territory_properties(territory)
    payload["aliases"] = [
        {"alias": alias.alias, "kind": alias.kind, "source_layer": alias.source_layer}
        for alias in territory.aliases
    ]
    payload["available_layers"] = [
        layer.code for layer in layers_for_level(territory.level)
    ]
    return payload
