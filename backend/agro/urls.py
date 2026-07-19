from rest_framework.routers import DefaultRouter
from .views import SubsidyRecipientViewSet
router = DefaultRouter()
router.register('subsidies', SubsidyRecipientViewSet)
urlpatterns = router.urls
