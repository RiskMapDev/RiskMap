from django.db import models
from regions.models import District

class ConstructionObject(models.Model):
    CATEGORIES = [
        ('school','Школа'),('hospital','Больница'),('fap','ФАП'),
        ('culture','Дом культуры'),('road','Дорога'),('water','Водоснабжение'),
        ('gas','Газоснабжение'),('electricity','Электроснабжение'),
        ('heat','Теплоснабжение'),('social','Социальный объект'),('digital','Цифровизация'),
    ]
    FINANCING = [('republican','Республиканский'),('local','Местный'),('mixed','Смешанный'),('private','Частный')]
    STATUSES = [('planned','Планируется'),('in_progress','В работе'),('completed','Завершен'),
                ('delayed','Задержка'),('suspended','Приостановлен')]
    RISK_LEVELS = [('low','Низкий'),('medium','Средний'),('high','Высокий')]

    district          = models.ForeignKey(District, on_delete=models.CASCADE, related_name='construction_objects')
    name              = models.CharField(max_length=500)
    category          = models.CharField(max_length=20, choices=CATEGORIES)
    locality          = models.CharField(max_length=200, blank=True)
    customer_name     = models.CharField(max_length=500)
    contractor_name   = models.CharField(max_length=500, blank=True)
    designer_name     = models.CharField(max_length=500, blank=True)
    design_cost       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    contract_amount   = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    financing_source  = models.CharField(max_length=20, choices=FINANCING, default='local')
    start_date        = models.DateField(null=True, blank=True)
    end_date          = models.DateField(null=True, blank=True)
    actual_status     = models.CharField(max_length=20, choices=STATUSES, default='in_progress')
    readiness_pct     = models.IntegerField(default=0)
    risk_level        = models.CharField(max_length=10, choices=RISK_LEVELS, default='low')
    overprice_amount  = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    lat               = models.FloatField(null=True, blank=True)
    lng               = models.FloatField(null=True, blank=True)
    notes             = models.TextField(blank=True)

    class Meta:
        ordering = ['-risk_level', 'name']

    def __str__(self): return self.name
