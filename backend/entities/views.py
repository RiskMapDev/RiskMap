from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import LegalEntity
from .serializers import LegalEntitySerializer

class LegalEntityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LegalEntity.objects.all()
    serializer_class = LegalEntitySerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['risk_transit','risk_fictitious','risk_nominal','risk_affiliated']
    search_fields    = ['name','bin_iin','director','founder']
