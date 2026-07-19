from django.db import models
from django.conf import settings
from regions.models import District

class RiskMaterial(models.Model):
    SPHERES = [
        ('procurement','Госзакупки'),('construction','Строительство'),
        ('agro','АПК/Субсидии'),('osms','ОСМС'),('subsoil','Недропользование'),
        ('budget','Бюджет'),('tax','Налоги'),('other','Иное'),
    ]
    STATUSES = [
        ('analysis','Анализ'),('prevention','Превенция'),('material','Материал'),
        ('erdr','ЕРДР'),('in_progress','В производстве'),('completed','Завершено'),
    ]
    LEVELS = [('low','Низкий'),('medium','Средний'),('high','Высокий'),('critical','Критический')]
    SOURCES = [('internal','Внутренний'),('external','Внешний'),('citizen','Обращение граждан'),('media','СМИ')]

    district     = models.ForeignKey(District, on_delete=models.CASCADE, related_name='risks')
    sphere       = models.CharField(max_length=20, choices=SPHERES)
    subject_name = models.CharField(max_length=500, blank=True)
    amount       = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    description  = models.TextField()
    status       = models.CharField(max_length=20, choices=STATUSES, default='analysis')
    level        = models.CharField(max_length=10, choices=LEVELS, default='medium')
    source       = models.CharField(max_length=20, choices=SOURCES, default='internal')
    detected_at  = models.DateField()
    year         = models.IntegerField()
    analyst      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='risk_materials')
    measures     = models.TextField(blank=True)
    result       = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [models.Index(fields=['district','year','level'])]

    def __str__(self): return f'{self.district.name} | {self.sphere} | {self.level}'
