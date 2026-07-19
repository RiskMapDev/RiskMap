from rest_framework import serializers
from .models import SubsoilContract

class SubsoilContractSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    class Meta:
        model = SubsoilContract
        fields = '__all__'
