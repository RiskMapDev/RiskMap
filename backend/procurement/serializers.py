from rest_framework import serializers
from .models import ProcurementContract

class ProcurementContractSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    risk_count    = serializers.IntegerField(read_only=True)
    class Meta:
        model = ProcurementContract
        fields = '__all__'
