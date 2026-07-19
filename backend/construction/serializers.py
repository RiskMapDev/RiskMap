from rest_framework import serializers
from .models import ConstructionObject

class ConstructionObjectSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    class Meta:
        model = ConstructionObject
        fields = '__all__'
