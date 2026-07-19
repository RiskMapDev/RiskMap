from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum
from .models import BudgetProgram
from .serializers import BudgetProgramSerializer

class BudgetProgramViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BudgetProgram.objects.select_related('district').all()
    serializer_class = BudgetProgramSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['district','year','sphere']
    search_fields    = ['program_name','program_code']
    ordering_fields  = ['year','allocated','execution_pct']

    @action(detail=False)
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        data = qs.values('sphere').annotate(
            total_allocated=Sum('allocated'),
            total_spent=Sum('spent'),
        ).order_by('sphere')
        return Response(list(data))
