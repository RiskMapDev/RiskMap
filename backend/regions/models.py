from django.db import models

class District(models.Model):
    RISK = [('low','Низкий'),('medium','Средний'),('high','Высокий'),('critical','Критический')]
    code        = models.CharField(max_length=10, unique=True)
    name        = models.CharField(max_length=200)
    name_kz     = models.CharField(max_length=200, blank=True)
    center      = models.CharField(max_length=200, blank=True)
    population  = models.IntegerField(default=0)
    area_km2    = models.FloatField(default=0)
    risk_level  = models.CharField(max_length=10, choices=RISK, default='low')
    lat         = models.FloatField(null=True, blank=True)
    lng         = models.FloatField(null=True, blank=True)
    boundary_geojson = models.JSONField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self): return self.name

class Official(models.Model):
    POSITIONS = [('akim','Аким'),('deputy','Зам. акима'),('head_dept','Нач. управления'),('head_div','Нач. отдела')]
    district      = models.ForeignKey(District, on_delete=models.CASCADE, related_name='officials')
    full_name     = models.CharField(max_length=300)
    position      = models.CharField(max_length=20, choices=POSITIONS)
    position_name = models.CharField(max_length=200, blank=True)
    phone         = models.CharField(max_length=50, blank=True)
    email         = models.EmailField(blank=True)

    def __str__(self): return f'{self.full_name} — {self.district.name}'

class Locality(models.Model):
    district    = models.ForeignKey(District, on_delete=models.CASCADE, related_name='localities')
    name        = models.CharField(max_length=200)
    population  = models.IntegerField(default=0)
    is_center   = models.BooleanField(default=False)
    lat         = models.FloatField(null=True, blank=True)
    lng         = models.FloatField(null=True, blank=True)

    def __str__(self): return self.name
