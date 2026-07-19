from django.db import models
from regions.models import District

class ProcurementContract(models.Model):
    METHODS = [
        ('one_source','Из одного источника'),('tender','Конкурс'),
        ('price_request','Запрос ценовых предложений'),('auction','Аукцион'),
    ]
    STATUSES = [
        ('active','Активный'),('completed','Исполнен'),
        ('delayed','Просрочен'),('terminated','Расторгнут'),
    ]
    district         = models.ForeignKey(District, on_delete=models.CASCADE, related_name='contracts')
    contract_number  = models.CharField(max_length=100, unique=True)
    customer_name    = models.CharField(max_length=500)
    customer_bin     = models.CharField(max_length=12, blank=True)
    supplier_name    = models.CharField(max_length=500)
    supplier_bin     = models.CharField(max_length=12, blank=True)
    subject          = models.TextField()
    method           = models.CharField(max_length=20, choices=METHODS)
    amount           = models.DecimalField(max_digits=20, decimal_places=2)
    year             = models.IntegerField()
    contract_date    = models.DateField(null=True, blank=True)
    deadline_date    = models.DateField(null=True, blank=True)
    status           = models.CharField(max_length=20, choices=STATUSES, default='active')
    amendments_count = models.IntegerField(default=0)
    # Risk flags
    risk_single      = models.BooleanField(default=False)
    risk_overpriced  = models.BooleanField(default=False)
    risk_splitting   = models.BooleanField(default=False)
    risk_affiliation = models.BooleanField(default=False)

    @property
    def risk_count(self):
        return sum([self.risk_single, self.risk_overpriced, self.risk_splitting, self.risk_affiliation])

    class Meta:
        ordering = ['-year', '-amount']
        indexes = [models.Index(fields=['district','year']), models.Index(fields=['supplier_bin'])]

    def __str__(self): return self.contract_number
