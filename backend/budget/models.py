from django.db import models
from regions.models import District

class BudgetProgram(models.Model):
    SPHERES = [
        ('construction','Строительство'),('housing','ЖКХ'),('roads','Дороги'),
        ('education','Образование'),('healthcare','Здравоохранение'),
        ('agriculture','АПК'),('social','Социальная сфера'),('digitalization','Цифровизация'),
    ]
    district        = models.ForeignKey(District, on_delete=models.CASCADE, related_name='budgets')
    year            = models.IntegerField()
    sphere          = models.CharField(max_length=30, choices=SPHERES)
    program_name    = models.CharField(max_length=500)
    program_code    = models.CharField(max_length=50, blank=True)
    administrator   = models.CharField(max_length=300, blank=True)
    allocated       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    spent           = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    remainder       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    execution_pct   = models.FloatField(default=0)
    financing_source = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['year', 'sphere']
        indexes = [models.Index(fields=['district','year','sphere'])]

    def __str__(self): return f'{self.district.name} | {self.sphere} | {self.year}'
