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
    list_display = ("name", "level", "kato_code", "parent", "population")
    list_filter = ("level",)
    search_fields = ("name", "name_en", "kato_code", "external_id")
    autocomplete_fields = ("parent",)
    ordering = ("level", "name")


@admin.register(ThematicLayer)
class ThematicLayerAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "order")
    list_editable = ("is_active", "order")
    search_fields = ("name", "code")


@admin.register(GeoObject)
class GeoObjectAdmin(GISModelAdmin):
    list_display = ("name", "layer", "territory", "risk_level", "risk_score")
    list_filter = ("layer", "risk_level")
    search_fields = ("name",)


@admin.register(RiskFactor)
class RiskFactorAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "layer", "weight", "threshold")
    search_fields = ("name", "code")


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("file_name", "layer", "status", "rows_total", "created_at")
    list_filter = ("status",)
