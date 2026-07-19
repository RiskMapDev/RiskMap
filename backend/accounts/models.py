from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLES = [
        ('superadmin','Суперадмин'),('admin','Администратор'),
        ('analyst','Аналитик'),('manager','Менеджер'),('viewer','Наблюдатель'),
    ]
    role      = models.CharField(max_length=20, choices=ROLES, default='viewer')
    full_name = models.CharField(max_length=300, blank=True)
    phone     = models.CharField(max_length=50, blank=True)

    def __str__(self): return self.username
