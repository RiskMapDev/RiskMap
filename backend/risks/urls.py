from rest_framework.routers import DefaultRouter
from .views import RiskMaterialViewSet
router = DefaultRouter()
router.register('materials', RiskMaterialViewSet)
urlpatterns = router.urls
