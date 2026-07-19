from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import ConstructionObject
from .serializers import ConstructionObjectSerializer

class ConstructionObjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConstructionObject.objects.select_related('district').all()
    serializer_class = ConstructionObjectSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','category','actual_status','risk_level','financing_source']
    search_fields    = ['name','customer_name','contractor_name','locality']
    ordering_fields  = ['readiness_pct','contract_amount']
