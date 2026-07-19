from rest_framework.routers import DefaultRouter
from .views import DistrictViewSet, OfficialViewSet
router = DefaultRouter()
router.register('districts', DistrictViewSet)
router.register('officials', OfficialViewSet)
urlpatterns = router.urls
