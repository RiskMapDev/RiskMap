from rest_framework.routers import DefaultRouter
from .views import BudgetProgramViewSet
router = DefaultRouter()
router.register('programs', BudgetProgramViewSet)
urlpatterns = router.urls
