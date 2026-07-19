from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import GeoObject, RiskFactor, Territory, ThematicLayer


class TerritorySerializer(GeoFeatureModelSerializer):
    """Сериализует территорию в GeoJSON Feature.

    geo_field='geometry' — эта геометрия становится geometry у Feature,
    остальные поля попадают в properties. Набор Feature'ов Leaflet рисует
    напрямую через L.geoJSON().
    """

    class Meta:
        model = Territory
        geo_field = "geometry"
        fields = (
            "id",
            "kato_code",
            "name_ru",
            "name_kz",
            "level",
            "parent",
            "population",
            "area_km2",
        )


class ThematicLayerSerializer(serializers.ModelSerializer):
    """Слой для панели слоёв фронта (панель строится динамически)."""

    class Meta:
        model = ThematicLayer
        fields = ("id", "code", "name_ru", "color_hex", "description", "sort_order")


class RiskFactorSerializer(serializers.ModelSerializer):
    """Один индикатор в расшифровке балла (ТЗ п.14)."""

    class Meta:
        model = RiskFactor
        fields = (
            "indicator_code",
            "indicator_name",
            "raw_value",
            "weight",
            "contribution",
        )


class GeoObjectListSerializer(serializers.ModelSerializer):
    """Строка списка во вкладке «Риски» (компании района)."""

    paid_total = serializers.SerializerMethodField()
    territory_name = serializers.CharField(source="territory.name_ru", default=None)

    class Meta:
        model = GeoObject
        fields = (
            "id",
            "external_id",
            "name",
            "territory",
            "territory_name",
            "risk_score",
            "risk_level",
            "paid_total",
        )

    def get_paid_total(self, obj):
        return (obj.attributes or {}).get("paid_total")


class GeoObjectDetailSerializer(serializers.ModelSerializer):
    """Карточка объекта: атрибуты + расшифровка риска по RiskFactor (ТЗ п.14)."""

    risk_factors = RiskFactorSerializer(many=True, read_only=True)
    territory_name = serializers.CharField(source="territory.name_ru", default=None)

    class Meta:
        model = GeoObject
        fields = (
            "id",
            "external_id",
            "name",
            "layer",
            "territory",
            "territory_name",
            "source_system",
            "imported_at",
            "risk_score",
            "risk_level",
            "attributes",
            "risk_factors",
        )
