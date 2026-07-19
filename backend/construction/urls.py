from rest_framework.routers import DefaultRouter
from .views import ConstructionObjectViewSet
router = DefaultRouter()
router.register('objects', ConstructionObjectViewSet)
urlpatterns = router.urls
