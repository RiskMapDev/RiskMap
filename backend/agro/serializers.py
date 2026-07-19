from rest_framework import serializers
from .models import SubsidyRecipient

class SubsidyRecipientSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    class Meta:
        model = SubsidyRecipient
        fields = '__all__'
