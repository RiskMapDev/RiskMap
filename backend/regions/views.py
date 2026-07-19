from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import District, Official, Locality
from .serializers import DistrictSerializer, DistrictListSerializer, OfficialSerializer, LocalitySerializer

class DistrictViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = District.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['risk_level']
    search_fields    = ['name','code']

    def get_serializer_class(self):
        if self.action == 'list':
            return DistrictListSerializer
        return DistrictSerializer

class OfficialViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Official.objects.select_related('district').all()
    serializer_class = OfficialSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['district','position']
