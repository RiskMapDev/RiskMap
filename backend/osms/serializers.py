from rest_framework import serializers
from .models import OSMSData

class OSMSDataSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    class Meta:
        model = OSMSData
        fields = '__all__'
