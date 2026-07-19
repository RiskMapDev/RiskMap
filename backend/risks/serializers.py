from rest_framework import serializers
from .models import RiskMaterial

class RiskMaterialSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    analyst_name  = serializers.CharField(source='analyst.get_full_name', read_only=True)
    class Meta:
        model = RiskMaterial
        fields = '__all__'
