from django.db import models
from regions.models import District

class SubsoilContract(models.Model):
    STATUSES = [('active','Действующий'),('suspended','Приостановлен'),
                ('terminated','Расторгнут'),('expired','Истёк')]
    TYPES    = [('exploration','Разведка'),('production','Добыча'),('combined','Совмещённый')]

    district          = models.ForeignKey(District, on_delete=models.CASCADE, related_name='subsoil')
    contract_number   = models.CharField(max_length=100)
    company_name      = models.CharField(max_length=500)
    company_bin       = models.CharField(max_length=12)
    mineral_type      = models.CharField(max_length=200)
    contract_type     = models.CharField(max_length=20, choices=TYPES, default='production')
    start_date        = models.DateField(null=True, blank=True)
    end_date          = models.DateField(null=True, blank=True)
    status            = models.CharField(max_length=20, choices=STATUSES, default='active')
    area_ha           = models.FloatField(default=0)
    obligations_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    fulfilled_amount   = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    risk_nonpayment   = models.BooleanField(default=False)
    risk_overextract   = models.BooleanField(default=False)
    lat               = models.FloatField(null=True, blank=True)
    lng               = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['company_name']

    def __str__(self): return f'{self.company_name} — {self.mineral_type}'
