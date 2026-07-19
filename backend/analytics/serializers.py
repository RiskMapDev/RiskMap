from rest_framework import serializers
from .models import AnalyticsReport

class AnalyticsReportSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    class Meta:
        model = AnalyticsReport
        fields = '__all__'
