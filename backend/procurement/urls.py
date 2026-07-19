from rest_framework.routers import DefaultRouter
from .views import ProcurementContractViewSet
router = DefaultRouter()
router.register('contracts', ProcurementContractViewSet)
urlpatterns = router.urls
