import django_filters
from .models import ProcurementContract


class ContractFilter(django_filters.FilterSet):
    year     = django_filters.NumberFilter()
    district = django_filters.NumberFilter()
    method   = django_filters.CharFilter()
    status   = django_filters.CharFilter()
    min_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='lte')
    has_risk   = django_filters.BooleanFilter(method='filter_has_risk')
    customer_bin = django_filters.CharFilter()
    supplier_bin = django_filters.CharFilter()

    def filter_has_risk(self, qs, name, value):
        if value:
            return qs.filter(
                risk_single=True) | qs.filter(risk_overpriced=True) | \
                qs.filter(risk_splitting=True) | qs.filter(risk_affiliation=True)
        return qs

    class Meta:
        model = ProcurementContract
        fields = ['year', 'district', 'method', 'status']
