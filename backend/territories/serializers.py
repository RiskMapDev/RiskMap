from rest_framework_gis.serializers import GeoFeatureModelSerializer

from .models import Territory


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
