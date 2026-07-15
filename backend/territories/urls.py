from rest_framework.routers import DefaultRouter

from .views import TerritoryViewSet

router = DefaultRouter()
router.register(r"territories", TerritoryViewSet, basename="territory")

urlpatterns = router.urls
