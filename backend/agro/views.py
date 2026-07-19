from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend
from .models import SubsidyRecipient
from .serializers import SubsidyRecipientSerializer

class SubsidyRecipientViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SubsidyRecipient.objects.select_related('district').all()
    serializer_class = SubsidyRecipientSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','year','subsidy_type','risk_concentration','risk_affiliation']
    search_fields    = ['name','bin_iin','program']
    ordering_fields  = ['amount']
