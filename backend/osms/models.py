from django.db import models
from regions.models import District

class OSMSData(models.Model):
    STATUSES = [('registered','Зарегистрирован'),('paying','Оплачивает'),
                ('debt','Долг'),('exempt','Льгота'),('unknown','Неизвестен')]
    district           = models.ForeignKey(District, on_delete=models.CASCADE, related_name='osms_data')
    year               = models.IntegerField()
    employer_name      = models.CharField(max_length=500)
    employer_bin       = models.CharField(max_length=12)
    employees_count    = models.IntegerField(default=0)
    registered_count   = models.IntegerField(default=0)
    unregistered_count = models.IntegerField(default=0)
    contributions      = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    debt_amount        = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status             = models.CharField(max_length=20, choices=STATUSES, default='registered')
    risk_flag          = models.BooleanField(default=False)

    class Meta:
        ordering = ['-debt_amount']

    def __str__(self): return f'{self.employer_name} | ОСМС {self.year}'
