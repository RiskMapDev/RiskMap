from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count, Q, Avg
from .models import AnalyticsReport
from .serializers import AnalyticsReportSerializer
from regions.models import District
from budget.models import BudgetProgram
from procurement.models import ProcurementContract
from risks.models import RiskMaterial
from agro.models import SubsidyRecipient

class AnalyticsReportViewSet(viewsets.ModelViewSet):
    queryset = AnalyticsReport.objects.select_related('district','created_by').all()
    serializer_class = AnalyticsReportSerializer
    filter_backends  = [DjangoFilterBackend]
    filterset_fields = ['year','format','status','district']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard(request):
    year     = int(request.GET.get('year', 2024))
    district = request.GET.get('district')

    budget_qs = BudgetProgram.objects.filter(year=year)
    risk_qs   = RiskMaterial.objects.filter(year=year)
    proc_qs   = ProcurementContract.objects.filter(year=year)
    subsidy_qs = SubsidyRecipient.objects.filter(year=year)

    if district:
        budget_qs  = budget_qs.filter(district=district)
        risk_qs    = risk_qs.filter(district=district)
        proc_qs    = proc_qs.filter(district=district)
        subsidy_qs = subsidy_qs.filter(district=district)

    budget_agg = budget_qs.aggregate(total=Sum('allocated') or 0, spent=Sum('spent') or 0)
    by_sphere  = list(budget_qs.values('sphere').annotate(allocated=Sum('allocated'), spent=Sum('spent')))

    risk_agg = risk_qs.aggregate(total_amount=Sum('amount') or 0, count=Count('id'))
    risk_counts = {
        'erdr_count':       risk_qs.filter(status='erdr').count(),
        'prevention_count': risk_qs.filter(status='prevention').count(),
        'analysis_count':   risk_qs.filter(status='analysis').count(),
        'completed_count':  risk_qs.filter(status='completed').count(),
    }
    by_sphere_risk = list(risk_qs.values('sphere').annotate(total=Sum('amount'), count=Count('id')))

    top_districts = list(
        risk_qs.values('district__name').annotate(total_risk=Sum('amount')).order_by('-total_risk')[:7]
    )
    top_suppliers = list(
        proc_qs.filter(Q(risk_single=True)|Q(risk_overpriced=True)|Q(risk_splitting=True)|Q(risk_affiliation=True))
        .values('supplier_name').annotate(total=Sum('amount')).order_by('-total')[:7]
    )
    top_subsidy = list(
        subsidy_qs.values('name').annotate(total=Sum('amount')).order_by('-total')[:7]
    )

    procurement_agg = proc_qs.aggregate(total=Sum('amount') or 0, count=Count('id'))
    risk_contracts = proc_qs.filter(
        Q(risk_single=True)|Q(risk_overpriced=True)|Q(risk_splitting=True)|Q(risk_affiliation=True)
    ).aggregate(count=Count('id'), amount=Sum('amount') or 0)

    return Response({
        'year': year,
        'district_count': District.objects.count(),
        'budget': {
            'total':    float(budget_agg['total'] or 0),
            'spent':    float(budget_agg['spent'] or 0),
            'by_sphere': by_sphere,
        },
        'risks': {
            'total_amount': float(risk_agg['total_amount'] or 0),
            'count':        risk_agg['count'],
            'by_sphere':    by_sphere_risk,
            **risk_counts,
        },
        'procurement': {
            'total':         float(procurement_agg['total'] or 0),
            'count':         procurement_agg['count'],
            'risk_count':    risk_contracts['count'],
            'risk_amount':   float(risk_contracts['amount'] or 0),
        },
        'top_districts':         top_districts,
        'top_suppliers':         top_suppliers,
        'top_subsidy_recipients': top_subsidy,
    })
