from django.db import models
from django.conf import settings
from regions.models import District

class AnalyticsReport(models.Model):
    FORMATS  = [('pdf','PDF'),('xlsx','Excel')]
    STATUSES = [('pending','Ожидание'),('processing','Обработка'),('done','Готово'),('error','Ошибка')]
    title      = models.CharField(max_length=300)
    district   = models.ForeignKey(District, on_delete=models.SET_NULL, null=True, blank=True)
    year       = models.IntegerField()
    format     = models.CharField(max_length=5, choices=FORMATS)
    status     = models.CharField(max_length=15, choices=STATUSES, default='pending')
    file       = models.FileField(upload_to='reports/', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    error_msg  = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self): return f'{self.title} ({self.status})'
