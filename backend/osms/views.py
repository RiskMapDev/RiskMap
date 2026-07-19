from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import OSMSData
from .serializers import OSMSDataSerializer

class OSMSDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OSMSData.objects.select_related('district').all()
    serializer_class = OSMSDataSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','year','status','risk_flag']
    search_fields    = ['employer_name','employer_bin']
    ordering_fields  = ['debt_amount','contributions']
