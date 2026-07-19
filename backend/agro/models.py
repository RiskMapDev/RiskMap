from django.db import models
from regions.models import District

class SubsidyRecipient(models.Model):
    TYPES = [('plant','Растениеводство'),('animal','Животноводство'),
             ('equipment','Техника'),('irrigation','Орошение'),('other','Иное')]
    district             = models.ForeignKey(District, on_delete=models.CASCADE, related_name='subsidies')
    name                 = models.CharField(max_length=500)
    bin_iin              = models.CharField(max_length=12)
    program              = models.CharField(max_length=300)
    subsidy_type         = models.CharField(max_length=20, choices=TYPES)
    amount               = models.DecimalField(max_digits=20, decimal_places=2)
    year                 = models.IntegerField()
    source               = models.CharField(max_length=200, blank=True)
    related_project      = models.CharField(max_length=300, blank=True)
    bank                 = models.CharField(max_length=200, blank=True)
    risk_concentration   = models.BooleanField(default=False)
    risk_repeat          = models.BooleanField(default=False)
    risk_affiliation     = models.BooleanField(default=False)
    risk_no_activity     = models.BooleanField(default=False)

    class Meta:
        ordering = ['-amount']

    def __str__(self): return self.name
