"""Загрузка административных границ Казахстана.

- Все области РК (ADM1) — только контур, без районов.
- Районы (ADM2) — только для одной области (по умолчанию Алматинской).

Запуск:
    python manage.py load_boundaries
    python manage.py load_boundaries --district-region Almaty

Источник данных и его ограничения — см. territories/data/SOURCE.md.
"""

import json
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from territories.models import Territory
from territories.reference_data import ALMATY_DISTRICT_RU, REGION_RU

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def to_multipolygon(geojson_geometry: dict) -> MultiPolygon:
    """Приводит Polygon/MultiPolygon из GeoJSON к MultiPolygon (SRID 4326)."""
    geom = GEOSGeometry(json.dumps(geojson_geometry), srid=4326)
    if geom.geom_type == "Polygon":
        geom = MultiPolygon(geom, srid=4326)
    elif geom.geom_type != "MultiPolygon":
        raise CommandError(f"Неподдерживаемый тип геометрии: {geom.geom_type}")
    return geom


class Command(BaseCommand):
    help = "Загружает границы областей РК и районов выбранной области"

    def add_arguments(self, parser):
        parser.add_argument(
            "--regions-file",
            default=str(DATA_DIR / "kz_1.json"),
            help="Путь к GeoJSON областей (ADM1)",
        )
        parser.add_argument(
            "--districts-file",
            default=str(DATA_DIR / "kz_2.json"),
            help="Путь к GeoJSON районов (ADM2)",
        )
        parser.add_argument(
            "--district-region",
            default="Almaty",
            help="Английское имя области (GADM NAME_1), районы которой грузить",
        )

    def handle(self, *args, **options):
        regions_path = Path(options["regions_file"])
        districts_path = Path(options["districts_file"])
        target_region = options["district_region"]

        for path in (regions_path, districts_path):
            if not path.exists():
                raise CommandError(f"Файл не найден: {path}")

        with transaction.atomic():
            regions = self._load_regions(regions_path)
            self._load_districts(districts_path, target_region, regions)

        self.stdout.write(self.style.SUCCESS("Готово."))

    def _load_regions(self, path: Path) -> dict:
        """Создаёт/обновляет области. Возвращает {GID_1: Territory}."""
        data = json.loads(path.read_text(encoding="utf-8"))
        by_gid = {}
        created = updated = 0

        for feature in data["features"]:
            props = feature["properties"]
            # В kz_1.json встречаются служебные записи с GID_2 — это не
            # уровень области, пропускаем их.
            if props.get("GID_2"):
                continue
            gid = props.get("GID_1")
            name_en = props.get("NAME_1")
            if not gid or not name_en:
                continue
            # Не плодим дубли, если область уже встретилась.
            if gid in by_gid:
                continue

            ru_name, kato = REGION_RU.get(name_en, (name_en, None))
            obj, is_created = Territory.objects.update_or_create(
                gadm_gid=gid,
                defaults={
                    "kato_code": kato,
                    "name": ru_name,
                    "name_en": name_en,
                    "level": Territory.Level.REGION,
                    "parent": None,
                    "geometry": to_multipolygon(feature["geometry"]),
                },
            )
            by_gid[gid] = obj
            created += is_created
            updated += not is_created

        self.stdout.write(
            f"Области: создано {created}, обновлено {updated}, всего {len(by_gid)}"
        )
        return by_gid

    def _load_districts(self, path: Path, target_region: str, regions: dict):
        """Создаёт/обновляет районы указанной области."""
        data = json.loads(path.read_text(encoding="utf-8"))
        created = updated = skipped = 0

        for feature in data["features"]:
            props = feature["properties"]
            if props.get("NAME_1") != target_region:
                continue
            gid = props.get("GID_2")
            name_en = props.get("NAME_2")
            parent_gid = props.get("GID_1")
            if not gid or not name_en:
                continue

            parent = regions.get(parent_gid)
            if parent is None:
                # Родительская область не загружена — пропускаем район.
                skipped += 1
                continue

            ru_name, kato = ALMATY_DISTRICT_RU.get(name_en, (name_en, None))
            _, is_created = Territory.objects.update_or_create(
                gadm_gid=gid,
                defaults={
                    "kato_code": kato,
                    "name": ru_name,
                    "name_en": name_en,
                    "level": Territory.Level.DISTRICT,
                    "parent": parent,
                    "geometry": to_multipolygon(feature["geometry"]),
                },
            )
            created += is_created
            updated += not is_created

        msg = f"Районы ({target_region}): создано {created}, обновлено {updated}"
        if skipped:
            msg += f", пропущено без родителя {skipped}"
        self.stdout.write(msg)
