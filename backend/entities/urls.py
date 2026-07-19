from rest_framework.routers import DefaultRouter
from .views import LegalEntityViewSet
router = DefaultRouter()
router.register('entities', LegalEntityViewSet)
urlpatterns = router.urls
