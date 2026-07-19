from rest_framework import serializers
from .models import BudgetProgram

class BudgetProgramSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True)
    class Meta:
        model = BudgetProgram
        fields = '__all__'
