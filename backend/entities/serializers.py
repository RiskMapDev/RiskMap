from rest_framework import serializers
from .models import LegalEntity

class LegalEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalEntity
        fields = '__all__'
