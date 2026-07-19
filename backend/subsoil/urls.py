from rest_framework.routers import DefaultRouter
from .views import SubsoilContractViewSet
router = DefaultRouter()
router.register('contracts', SubsoilContractViewSet)
urlpatterns = router.urls
