from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import (
    GeoObject,
    ImportBatch,
    RiskFactor,
    Territory,
    ThematicLayer,
)


@admin.register(Territory)
class TerritoryAdmin(GISModelAdmin):
    list_display = ("name_ru", "level", "kato_code", "parent", "population")
    list_filter = ("level",)
    search_fields = ("name_ru", "name_kz", "kato_code", "external_id")
    autocomplete_fields = ("parent",)
    ordering = ("level", "name_ru")


@admin.register(ThematicLayer)
class ThematicLayerAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "code", "color_hex", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name_ru", "code")


@admin.register(GeoObject)
class GeoObjectAdmin(GISModelAdmin):
    list_display = (
        "name", "layer", "territory", "source_system", "risk_level", "risk_score",
    )
    list_filter = ("layer", "risk_level", "source_system")
    search_fields = ("name", "external_id")


@admin.register(RiskFactor)
class RiskFactorAdmin(admin.ModelAdmin):
    list_display = (
        "indicator_name", "geo_object", "weight", "contribution", "calculated_at",
    )
    list_filter = ("indicator_code",)
    search_fields = ("indicator_name", "indicator_code")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "file_name", "source_name", "layer", "status", "total_rows", "created_at",
    )
    list_filter = ("status",)
