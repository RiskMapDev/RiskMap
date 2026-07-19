from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import SubsoilContract
from .serializers import SubsoilContractSerializer

class SubsoilContractViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SubsoilContract.objects.select_related('district').all()
    serializer_class = SubsoilContractSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['district','status','contract_type','risk_nonpayment']
    search_fields    = ['company_name','company_bin','mineral_type']
