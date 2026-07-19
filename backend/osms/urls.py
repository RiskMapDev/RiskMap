from rest_framework.routers import DefaultRouter
from .views import OSMSDataViewSet
router = DefaultRouter()
router.register('data', OSMSDataViewSet)
urlpatterns = router.urls
