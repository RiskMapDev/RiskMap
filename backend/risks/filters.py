import django_filters
from .models import RiskMaterial


class RiskMaterialFilter(django_filters.FilterSet):
    year     = django_filters.NumberFilter()
    district = django_filters.NumberFilter()
    sphere   = django_filters.CharFilter()
    status   = django_filters.CharFilter()
    level    = django_filters.CharFilter()
    has_erdr = django_filters.BooleanFilter(method='filter_erdr')
    min_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='gte')
    max_amount = django_filters.NumberFilter(field_name='amount', lookup_expr='lte')

    def filter_erdr(self, qs, name, value):
        if value:
            return qs.filter(status='erdr')
        return qs

    class Meta:
        model = RiskMaterial
        fields = ['year', 'district', 'sphere', 'status', 'level']
