from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Пользователь системы. Роли — по ТЗ, раздел 5 "Пользователи и роли"."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        ANALYST = "analyst", "Аналитик"
        MANAGER = "manager", "Руководитель"
        VIEWER = "viewer", "Пользователь с правом просмотра"

    full_name = models.CharField("ФИО", max_length=255, blank=True)
    role = models.CharField(
        "Роль", max_length=20, choices=Role.choices, default=Role.VIEWER
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self):
        return self.full_name or self.username
