from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import RiskMaterial
from .serializers import RiskMaterialSerializer

class RiskMaterialViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskMaterial.objects.select_related('district','analyst').all()
    serializer_class = RiskMaterialSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','sphere','status','level','year']
    search_fields    = ['description','subject_name']
    ordering_fields  = ['amount','detected_at']
