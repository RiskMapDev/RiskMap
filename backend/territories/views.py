import json

from django.db.models import FloatField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .analytics import aggregate, object_metrics
from .models import GeoObject, Territory, ThematicLayer
from .serializers import (
    GeoObjectDetailSerializer,
    GeoObjectListSerializer,
    TerritorySerializer,
    ThematicLayerSerializer,
)

DEFAULT_OBLAST_NAME = "Алматинская область"


class GeoObjectPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200


def parse_risk_levels(request):
    """?risk_level=high,critical -> {'high','critical'} или None."""
    raw = request.query_params.get("risk_level")
    if not raw:
        return None
    levels = {x.strip() for x in raw.split(",") if x.strip()}
    return levels or None


def parse_year(request):
    raw = request.query_params.get("year")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class TerritoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Территории (только чтение) в формате GeoJSON.

    Query-параметры:
      ?level=oblast|rayon|settlement  — фильтр по уровню
      ?parent=<id>                    — районы конкретной области
      ?parent=null                    — только верхний уровень (области)
    """

    serializer_class = TerritorySerializer
    pagination_class = None

    def get_queryset(self):
        qs = Territory.objects.all().order_by("level", "name_ru")

        level = self.request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)

        parent = self.request.query_params.get("parent")
        if parent == "null":
            qs = qs.filter(parent__isnull=True)
        elif parent:
            qs = qs.filter(parent_id=parent)

        return qs


class ThematicLayerViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/layers/ — активные слои для панели фронта."""

    serializer_class = ThematicLayerSerializer
    pagination_class = None
    queryset = ThematicLayer.objects.filter(is_active=True).order_by("sort_order", "name_ru")


class TerritoryRiskView(APIView):
    """GET /api/territories/risk/ — GeoJSON районов с агрегированным риском.

    Заливка карты: фронт красит по properties.risk_level (цвет не на бэке).
    Районы без подходящих объектов возвращаются с risk_level=null —
    их НЕ выкидываем, иначе на карте появятся дыры.

    Параметры: layer (обяз.), parent (id области, по умолч. Алматинская),
    year, risk_level (CSV).
    """

    def get(self, request):
        layer_code = request.query_params.get("layer")
        year = parse_year(request)
        risk_levels = parse_risk_levels(request)

        parent_id = request.query_params.get("parent")
        if parent_id:
            oblast = get_object_or_404(Territory, pk=parent_id)
        else:
            oblast = get_object_or_404(
                Territory, level=Territory.Level.OBLAST, name_ru=DEFAULT_OBLAST_NAME
            )

        rayons = oblast.children.all().order_by("name_ru")

        # Объекты слоя по этим районам — одним запросом, группируем в Python.
        objects = GeoObject.objects.filter(territory__in=rayons)
        if layer_code:
            objects = objects.filter(layer__code=layer_code)
        objects_by_rayon = {}
        for obj in objects:
            objects_by_rayon.setdefault(obj.territory_id, []).append(obj)

        features = []
        for rayon in rayons:
            metrics = aggregate(
                objects_by_rayon.get(rayon.id, []), year=year, risk_levels=risk_levels
            )
            features.append({
                "type": "Feature",
                "geometry": json.loads(rayon.geometry.geojson),
                "properties": {
                    "id": rayon.id,
                    "name_ru": rayon.name_ru,
                    "name_kz": rayon.name_kz,
                    "kato_code": rayon.kato_code,
                    "population": rayon.population,
                    "area_km2": rayon.area_km2,
                    "risk_score": metrics["avg_risk_weighted"],
                    "risk_level": metrics["risk_level"],
                    "objects_count": metrics["objects_count"],
                    "high_risk_count": metrics["high_risk_count"],
                    "paid_total": metrics["paid_total"],
                    "risk_exposure": metrics["risk_exposure"],
                },
            })

        return Response({"type": "FeatureCollection", "features": features})


class DashboardView(APIView):
    """GET /api/dashboard/ — сводка по области ИЛИ по району.

    Один эндпоинт на оба уровня: передали область -> сводка области,
    передали район -> сводка района (фронту на зуме не нужен второй
    эндпоинт, только другой ?territory=).

    Параметры: layer, territory (id, по умолч. Алматинская область),
    year, risk_level (CSV).
    """

    def get(self, request):
        layer_code = request.query_params.get("layer")
        year = parse_year(request)
        risk_levels = parse_risk_levels(request)

        territory_id = request.query_params.get("territory")
        if territory_id:
            territory = get_object_or_404(Territory, pk=territory_id)
        else:
            territory = get_object_or_404(
                Territory, level=Territory.Level.OBLAST, name_ru=DEFAULT_OBLAST_NAME
            )

        # Область -> объекты во всех её районах; район -> объекты района.
        if territory.level == Territory.Level.OBLAST:
            objects = GeoObject.objects.filter(territory__parent=territory)
        else:
            objects = GeoObject.objects.filter(territory=territory)
        if layer_code:
            objects = objects.filter(layer__code=layer_code)
        objects = list(objects.select_related("territory"))

        metrics = aggregate(objects, year=year, risk_levels=risk_levels)

        # Топы считаем на том же отфильтрованном множестве.
        enriched = []
        for obj in objects:
            m = object_metrics(obj, year)
            if m is None:
                continue
            paid, score, level = m
            if risk_levels and level not in risk_levels:
                continue
            enriched.append({
                "id": obj.id,
                "name": obj.name,
                "external_id": obj.external_id,
                "territory_name": obj.territory.name_ru if obj.territory_id else None,
                "risk_score": score,
                "risk_level": level,
                "paid_total": round(paid, 2),
                "risk_exposure": round((score or 0) * paid / 100.0, 2),
            })

        top_risk = sorted(
            enriched, key=lambda x: (x["risk_score"] is None, -(x["risk_score"] or 0))
        )[:5]
        top_exposure = sorted(enriched, key=lambda x: -x["risk_exposure"])[:5]

        return Response({
            "territory": {
                "id": territory.id,
                "name_ru": territory.name_ru,
                "level": territory.level,
            },
            "paid_total": metrics["paid_total"],
            "objects_count": metrics["objects_count"],
            "risk_exposure": metrics["risk_exposure"],
            "avg_risk_weighted": metrics["avg_risk_weighted"],
            "by_level": metrics["by_level"],
            "top_risk": top_risk,
            "top_exposure": top_exposure,
        })


class GeoObjectViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/geo-objects/ — список компаний слоя + карточка.

    Параметры: layer, territory, risk_level (CSV), year (членство — объект
    активен в этом году), search (по name / external_id).
    Сортировка: ?ordering=-risk_score | -paid_total.

    Замечание по year: в списке год ФИЛЬТРУЕТ состав (какие объекты активны
    в этом году), а балл/сумма показываются итоговые. Пересчёт риска на год
    делают карта (/territories/risk/) и дашборд; список — это дрилл-даун.
    """

    pagination_class = GeoObjectPagination

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GeoObjectDetailSerializer
        return GeoObjectListSerializer

    def get_queryset(self):
        qs = GeoObject.objects.select_related("territory")
        if self.action == "retrieve":
            return qs.prefetch_related("risk_factors")

        params = self.request.query_params

        layer_code = params.get("layer")
        if layer_code:
            qs = qs.filter(layer__code=layer_code)

        territory_id = params.get("territory")
        if territory_id:
            qs = qs.filter(territory_id=territory_id)

        risk_levels = parse_risk_levels(self.request)
        if risk_levels:
            qs = qs.filter(risk_level__in=risk_levels)

        year = parse_year(self.request)
        if year is not None:
            # Объект активен в году, если в attributes.by_year есть его ключ.
            qs = qs.filter(**{f"attributes__by_year__{year}__isnull": False})

        search = params.get("search")
        if search:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=search) | Q(external_id__icontains=search))

        # paid_total лежит в JSON — аннотируем для сортировки по сумме.
        qs = qs.annotate(
            paid_total_num=Cast(
                KeyTextTransform("paid_total", "attributes"), FloatField()
            )
        )

        ordering = params.get("ordering", "-risk_score")
        allowed = {
            "risk_score": "risk_score",
            "-risk_score": "-risk_score",
            "paid_total": "paid_total_num",
            "-paid_total": "-paid_total_num",
        }
        return qs.order_by(allowed.get(ordering, "-risk_score"), "id")
