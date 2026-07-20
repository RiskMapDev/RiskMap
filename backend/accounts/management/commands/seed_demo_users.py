"""Создаёт демо-пользователей под все роли из ТЗ (раздел 5).

Нужен, чтобы после `docker compose up` можно было сразу войти во фронтенд,
не выполняя createsuperuser руками. Идемпотентно: существующих не трогает.

Запуск:
    python manage.py seed_demo_users
"""

from django.core.management.base import BaseCommand

from accounts.models import User

DEMO_USERS = [
    # username, пароль, ФИО, роль, is_staff/is_superuser
    ("admin", "admin123", "Администратор системы", User.Role.ADMIN, True),
    ("analyst1", "analyst123", "Асанова Г.М.", User.Role.ANALYST, False),
    ("manager1", "manager123", "Руководитель управления", User.Role.MANAGER, False),
    ("viewer1", "viewer123", "Пользователь (просмотр)", User.Role.VIEWER, False),
]


class Command(BaseCommand):
    help = "Создаёт демо-пользователей под роли ТЗ (admin/analyst1/manager1/viewer1)"

    def handle(self, *args, **options):
        created = skipped = 0
        for username, password, full_name, role, is_admin in DEMO_USERS:
            if User.objects.filter(username=username).exists():
                skipped += 1
                continue
            user = User(
                username=username,
                full_name=full_name,
                role=role,
                is_staff=is_admin,
                is_superuser=is_admin,
            )
            user.set_password(password)
            user.save()
            created += 1
            self.stdout.write(f"  {username} / {password} — {user.get_role_display()}")

        msg = f"Пользователи: создано {created}"
        if skipped:
            msg += f", уже были {skipped}"
        self.stdout.write(self.style.SUCCESS(msg))
