"""Выдача территорий: иерархия, геометрия, показатели.

Геометрия отдаётся не той же, что хранится. Для обзорного масштаба нужен
упрощённый контур, иначе на карту республики уедет несколько мегабайт границ
и требование ТЗ «главная страница ≤ 5 секунд» будет нарушено на ровном месте.
Упрощение выбирается по масштабу, а исходная геометрия остаётся нетронутой:
все расчёты площадей и пространственные запросы идут по ней.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.territory import (
    BoundaryVersion,
    PopulationStat,
    Territory,
    TerritoryGeometry,
    TerritoryLevel,
)
from app.risk.core import RiskLevel
from app.services.territory_risk import layer_coverage


@dataclass(frozen=True, slots=True)
class GeometryDetail:
    """Какой вариант геометрии отдавать на данном масштабе."""

    column: str
    description: str


def geometry_for_zoom(zoom: float) -> GeometryDetail:
    """Выбрать вариант геометрии под масштаб карты.

    Границы порогов подобраны по смыслу уровней, а не по красивым числам:
    до 6 показывается вся страна, к 9 — область целиком, дальше нужен
    полный контур, потому что видны отдельные изгибы границы.
    """
    if zoom < 6:
        return GeometryDetail("geom_simplified_low", "обзорный масштаб")
    if zoom < 9:
        return GeometryDetail("geom_simplified_mid", "средний масштаб")
    return GeometryDetail("geom", "исходная геометрия")


def _decimal(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def list_territories(
    session: Session,
    *,
    level: TerritoryLevel | None = None,
    parent_code: str | None = None,
    only_current: bool = True,
) -> list[Territory]:
    """Территории с их населением и алиасами."""
    stmt = (
        select(Territory)
        .options(selectinload(Territory.population_stats), selectinload(Territory.aliases))
        .order_by(Territory.name_ru)
    )
    if level is not None:
        stmt = stmt.where(Territory.level == level)
    if only_current:
        stmt = stmt.where(Territory.is_current.is_(True))
    if parent_code is not None:
        parent = session.scalar(select(Territory).where(Territory.code == parent_code))
        if parent is None:
            return []
        stmt = stmt.where(Territory.parent_id == parent.id)

    return list(session.scalars(stmt).all())


def territory_by_code(session: Session, code: str) -> Territory | None:
    stmt = (
        select(Territory)
        .where(Territory.code == code)
        .options(selectinload(Territory.population_stats), selectinload(Territory.aliases))
    )
    return session.scalar(stmt)


def latest_population(territory: Territory) -> PopulationStat | None:
    """Самая свежая запись о населении.

    Возвращается именно запись, а не число: пользователю нужна и дата, на
    которую данные актуальны. Показать население без даты — значит выдать
    цифру полугодовой давности за сегодняшнюю.
    """
    if not territory.population_stats:
        return None
    return max(territory.population_stats, key=lambda stat: stat.as_of_date)


def territory_properties(territory: Territory) -> dict[str, Any]:
    """Свойства территории для карточки и popup.

    Состав полей повторяет popup с UI-референса: название, казахское
    название, адм. центр, население, площадь. Отсутствующие значения
    остаются `None` и обязаны отображаться как «нет данных», а не как ноль.
    """
    population = latest_population(territory)

    return {
        "code": territory.code,
        "name_ru": territory.name_ru,
        "name_kk": territory.name_kk,
        "level": territory.level,
        "kato_code": territory.kato_code,
        "iso3166_2": territory.iso3166_2,
        "admin_center": territory.admin_center_name,
        "area_km2": _decimal(territory.area_km2),
        "area_km2_computed": _decimal(territory.area_km2_computed),
        "population": population.total if population else None,
        "population_as_of": population.as_of_date.isoformat() if population else None,
        "population_urban": population.urban_total if population else None,
        "population_rural": population.rural_total if population else None,
        "parent_code": territory.parent.code if territory.parent else None,
    }


def territories_geojson(
    session: Session,
    *,
    levels: Sequence[TerritoryLevel] | None = None,
    parent_code: str | None = None,
    zoom: float = 7.0,
    layer: str | None = None,
) -> dict[str, Any]:
    """Границы территорий как FeatureCollection.

    Атрибуция лицензии кладётся в сам ответ, а не только в документацию:
    границы под ODbL нельзя показывать без указания авторства, и надёжнее
    отдавать его вместе с данными, чем надеяться, что клиент не забудет.

    Если задан `layer`, к свойствам добавляется уровень риска территории по
    этому слою и распределение объектов по уровням. Сводка по коллекции
    сообщает, сколько объектов слоя вообще попало на карту: слой, показанный
    наполовину, обязан выглядеть как показанный наполовину.
    """
    detail = geometry_for_zoom(zoom)
    geom_column = getattr(TerritoryGeometry, detail.column)

    # Если упрощённого варианта нет, берётся исходный: пустая геометрия на
    # карте выглядит как отсутствие территории, а это неправда.
    geom_expr = func.coalesce(geom_column, TerritoryGeometry.geom)

    stmt = (
        select(
            Territory,
            func.ST_AsGeoJSON(geom_expr).label("geometry"),
            func.ST_AsGeoJSON(TerritoryGeometry.centroid).label("centroid"),
        )
        .join(TerritoryGeometry, TerritoryGeometry.territory_id == Territory.id)
        .options(selectinload(Territory.population_stats))
        .where(Territory.is_current.is_(True))
    )

    # Несколько уровней сразу, потому что города областного значения — это
    # отдельный уровень иерархии, но на карте они равноправны районам и
    # покрывают территорию вместе с ними. Запросить только районы значит
    # оставить на карте дыры на месте Конаева и Алатау.
    if levels:
        stmt = stmt.where(Territory.level.in_(levels))
    if parent_code is not None:
        parent = session.scalar(select(Territory).where(Territory.code == parent_code))
        if parent is None:
            return {"type": "FeatureCollection", "features": [], "attribution": ""}
        stmt = stmt.where(Territory.parent_id == parent.id)

    coverage = layer_coverage(session, layer) if layer else None

    features: list[dict[str, Any]] = []
    attributions: set[str] = set()
    shown = 0

    for territory, geometry_json, centroid_json in session.execute(stmt).all():
        properties = territory_properties(territory)
        if centroid_json:
            properties["centroid"] = json.loads(centroid_json)

        if coverage is not None:
            risk = coverage.risk_for(territory.id)
            shown += risk.total
            properties["risk_level"] = risk.level.value
            properties["risk_layer"] = layer
            # Распределение отдаётся рядом с уровнем: цвет показывает худший
            # объект, а понять, один он или половина района, можно только по
            # разбивке.
            properties["risk_counts"] = {
                item.value: risk.counts.get(item, 0) for item in RiskLevel
            }
            properties["objects_total"] = risk.total

        features.append(
            {
                "type": "Feature",
                "id": territory.code,
                "geometry": json.loads(geometry_json) if geometry_json else None,
                "properties": properties,
            }
        )

    for version in session.scalars(select(BoundaryVersion)).all():
        if version.attribution_text:
            attributions.add(version.attribution_text)

    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
        "attribution": " · ".join(sorted(attributions)),
        "geometry_detail": detail.description,
    }

    if coverage is not None:
        # Разница между «всего в слое» и «показано на карте» — это объекты без
        # территории и объекты другого уровня привязки. Молчать о ней нельзя:
        # карта, показывающая 57 % слоя, неотличима от полной, пока не назовёшь
        # число.
        payload["layer"] = {
            "code": layer,
            "objects_total": coverage.total,
            "objects_shown": shown,
            "objects_not_shown": coverage.total - shown,
            "objects_without_territory": coverage.unplaced,
        }

    return payload


def territory_tree(session: Session) -> list[dict[str, Any]]:
    """Иерархия территорий для выпадающего списка фильтра.

    Плоский список с указанием родителя, а не вложенная структура: клиенту
    удобнее строить дерево самому, а плоский вид переживает смену числа
    уровней без изменения формата ответа.
    """
    territories = session.scalars(
        select(Territory)
        .where(Territory.is_current.is_(True))
        .order_by(Territory.level, Territory.name_ru)
    ).all()

    by_id = {t.id: t for t in territories}

    return [
        {
            "code": t.code,
            "name_ru": t.name_ru,
            "name_kk": t.name_kk,
            "level": t.level,
            "parent_code": by_id[t.parent_id].code if t.parent_id in by_id else None,
        }
        for t in territories
    ]
