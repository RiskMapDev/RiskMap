from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import AnalyticsReportViewSet, dashboard

router = DefaultRouter()
router.register('reports', AnalyticsReportViewSet)

urlpatterns = router.urls + [
    path('dashboard/', dashboard),
]
