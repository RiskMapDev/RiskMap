import django_filters
from .models import BudgetProgram


class BudgetProgramFilter(django_filters.FilterSet):
    year    = django_filters.NumberFilter()
    sphere  = django_filters.CharFilter()
    district = django_filters.NumberFilter()
    min_allocated = django_filters.NumberFilter(field_name='allocated', lookup_expr='gte')
    max_allocated = django_filters.NumberFilter(field_name='allocated', lookup_expr='lte')

    class Meta:
        model = BudgetProgram
        fields = ['year', 'sphere', 'district']
