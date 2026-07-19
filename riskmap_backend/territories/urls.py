from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DashboardView,
    GeoObjectViewSet,
    TerritoryRiskView,
    TerritoryViewSet,
    ThematicLayerViewSet,
)

router = DefaultRouter()
router.register(r"territories", TerritoryViewSet, basename="territory")
router.register(r"layers", ThematicLayerViewSet, basename="layer")
router.register(r"geo-objects", GeoObjectViewSet, basename="geoobject")

urlpatterns = [
    # Явные пути ДО роутера: иначе /territories/risk/ уедет в detail-роут
    # территории (risk будет принят за {pk}).
    path("territories/risk/", TerritoryRiskView.as_view(), name="territory-risk"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    *router.urls,
]
