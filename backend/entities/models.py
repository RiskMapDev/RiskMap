from django.db import models

class LegalEntity(models.Model):
    name               = models.CharField(max_length=500)
    bin_iin            = models.CharField(max_length=12, unique=True)
    director           = models.CharField(max_length=300, blank=True)
    founder            = models.CharField(max_length=300, blank=True)
    address            = models.CharField(max_length=500, blank=True)
    okved              = models.CharField(max_length=50, blank=True)
    registration_date  = models.DateField(null=True, blank=True)
    tax_load           = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    risk_transit       = models.BooleanField(default=False)
    risk_fictitious    = models.BooleanField(default=False)
    risk_nominal       = models.BooleanField(default=False)
    risk_affiliated    = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self): return f'{self.name} ({self.bin_iin})'
