"""Заполняет population/area_km2 у уже загруженных территорий.

Данные — из документов аналитика (площади и население Алматинской области,
площади остальных областей РК), первоисточник — stat.gov.kz. Не создаёт
территории, только обновляет существующие по точному совпадению name_ru —
поэтому запускать после load_boundaries.

Запуск:
    python manage.py load_territory_stats
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from territories.models import Territory

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "socioeconomic_almaty.json"


class Command(BaseCommand):
    help = "Заполняет population/area_km2 территорий из socioeconomic_almaty.json"

    def handle(self, *args, **options):
        if not DATA_FILE.exists():
            raise CommandError(f"Файл не найден: {DATA_FILE}")

        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        updated = missing = 0

        for name_ru, area in data["oblast_area_km2"].items():
            n = Territory.objects.filter(
                level=Territory.Level.OBLAST, name_ru=name_ru
            ).update(area_km2=area)
            if n:
                updated += n
            else:
                missing += 1
                self.stdout.write(self.style.WARNING(f"Область не найдена: {name_ru}"))

        almaty = data["almaty_region"]
        n = Territory.objects.filter(
            level=Territory.Level.OBLAST, name_ru=almaty["name_ru"]
        ).update(population=almaty["population"], area_km2=almaty["area_km2"])
        if n:
            updated += n
        else:
            missing += 1
            self.stdout.write(
                self.style.WARNING(f"Область не найдена: {almaty['name_ru']}")
            )

        for d in almaty["districts"]:
            n = Territory.objects.filter(
                level=Territory.Level.RAYON,
                parent__name_ru=almaty["name_ru"],
                name_ru=d["name_ru"],
            ).update(population=d["population"], area_km2=d["area_km2"])
            if n:
                updated += n
            else:
                missing += 1
                self.stdout.write(self.style.WARNING(f"Район не найден: {d['name_ru']}"))

        msg = f"Обновлено: {updated}"
        if missing:
            msg += f", не найдено: {missing}"
        self.stdout.write(self.style.SUCCESS(msg))
