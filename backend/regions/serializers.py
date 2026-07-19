from rest_framework import serializers
from .models import District, Official, Locality

class OfficialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Official
        fields = '__all__'

class LocalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Locality
        fields = '__all__'

class DistrictSerializer(serializers.ModelSerializer):
    officials = OfficialSerializer(many=True, read_only=True)
    class Meta:
        model = District
        fields = '__all__'

class DistrictListSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        exclude = ['boundary_geojson']
