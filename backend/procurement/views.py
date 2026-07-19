from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count, Q
from .models import ProcurementContract
from .serializers import ProcurementContractSerializer

class ProcurementContractViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProcurementContract.objects.select_related('district').all()
    serializer_class = ProcurementContractSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','year','method','status','risk_single','risk_overpriced','risk_splitting','risk_affiliation']
    search_fields    = ['supplier_name','supplier_bin','customer_name','subject','contract_number']
    ordering_fields  = ['amount','year']

    @action(detail=False)
    def risks(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response({
            'single_source': qs.filter(risk_single=True).count(),
            'overpriced':    qs.filter(risk_overpriced=True).count(),
            'splitting':     qs.filter(risk_splitting=True).count(),
            'affiliation':   qs.filter(risk_affiliation=True).count(),
            'total_amount':  qs.filter(
                Q(risk_single=True)|Q(risk_overpriced=True)|Q(risk_splitting=True)|Q(risk_affiliation=True)
            ).aggregate(s=Sum('amount'))['s'] or 0,
        })
