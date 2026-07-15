"""Загрузка административных границ Казахстана из OpenStreetMap.

- Все 20 регионов РК (17 областей + 3 города респ. значения) — контур.
- Районы/города обл. значения — только для одной области (по умолчанию
  Алматинской, в её текущих постреформенных границах).

Запуск:
    python manage.py load_boundaries

Источник данных, история его получения и ограничения — см.
territories/data/SOURCE.md.

ВАЖНО: команда полностью пересобирает таблицу Territory из файлов-
источников (delete + create). Это осознанный выбор: набор и состав
регионов уже сменился с 14 (старый GADM) на 20, а состав районов
Алматинской области — с 17 на 11 (после выделения Жетісу), поэтому
частичный upsert оставлял бы висящие устаревшие записи.
"""

import json
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from territories.models import Territory

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def to_valid_multipolygon(geojson_geometry: dict) -> MultiPolygon:
    """Приводит геометрию из GeoJSON к валидному MultiPolygon (SRID 4326).

    Автосборка мультиполигонов из OSM relation иногда даёт невалидную
    топологию (напр. "nested shells" на анклавах вроде городов внутри
    области) — чиним через make_valid() вместо ручного редактирования
    координат.
    """
    geom = GEOSGeometry(json.dumps(geojson_geometry), srid=4326)
    if not geom.valid:
        geom = geom.make_valid()

    if geom.geom_type == "Polygon":
        return MultiPolygon(geom, srid=4326)
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "GeometryCollection":
        # make_valid() иногда возвращает коллекцию; берём только полигоны.
        polys = [g for g in geom if isinstance(g, Polygon)]
        if not polys:
            raise CommandError("make_valid() не оставил ни одного полигона")
        return MultiPolygon(polys, srid=4326)
    raise CommandError(f"Неподдерживаемый тип геометрии: {geom.geom_type}")


class Command(BaseCommand):
    help = "Загружает границы регионов РК и районов выбранного региона (OSM)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--regions-file",
            default=str(DATA_DIR / "kz_regions_osm.geojson"),
            help="Путь к GeoJSON регионов (20 шт., уровень области)",
        )
        parser.add_argument(
            "--districts-file",
            default=str(DATA_DIR / "kz_almaty_districts_osm.geojson"),
            help="Путь к GeoJSON районов выбранного региона",
        )

    def handle(self, *args, **options):
        regions_path = Path(options["regions_file"])
        districts_path = Path(options["districts_file"])

        for path in (regions_path, districts_path):
            if not path.exists():
                raise CommandError(f"Файл не найден: {path}")

        with transaction.atomic():
            Territory.objects.all().delete()
            regions_by_iso = self._load_regions(regions_path)
            self._load_districts(districts_path, regions_by_iso)

        self.stdout.write(self.style.SUCCESS("Готово."))

    def _load_regions(self, path: Path) -> dict:
        """Создаёт регионы. Возвращает {iso3166_2: Territory}."""
        data = json.loads(path.read_text(encoding="utf-8"))
        by_iso = {}

        for feature in data["features"]:
            props = feature["properties"]
            iso = props["iso3166_2"]
            obj = Territory.objects.create(
                external_id=str(props["osm_relation_id"]),
                kato_code=props["kato_code"],
                name_ru=props["name_ru"],
                name_kz=props.get("name_kk", ""),
                level=Territory.Level.OBLAST,
                parent=None,
                geometry=to_valid_multipolygon(feature["geometry"]),
            )
            by_iso[iso] = obj

        self.stdout.write(f"Регионы: создано {len(by_iso)}")
        return by_iso

    def _load_districts(self, path: Path, regions_by_iso: dict):
        """Создаёт районы/города обл. значения выбранного региона."""
        data = json.loads(path.read_text(encoding="utf-8"))
        created = skipped = 0

        for feature in data["features"]:
            props = feature["properties"]
            parent = regions_by_iso.get(props["parent_iso3166_2"])
            if parent is None:
                skipped += 1
                continue

            Territory.objects.create(
                external_id=str(props["osm_relation_id"]),
                # КАТО районов сознательно не проставляем: в справочнике
                # tenderplus.kz/kato ветка региона ещё не отражает
                # реформу 2022 г. на уровне районов — см. SOURCE.md.
                kato_code=None,
                name_ru=props["name_ru"],
                name_kz=props.get("name_kk", ""),
                level=Territory.Level.RAYON,
                parent=parent,
                geometry=to_valid_multipolygon(feature["geometry"]),
            )
            created += 1

        msg = f"Районы: создано {created}"
        if skipped:
            msg += f", пропущено без региона-родителя {skipped}"
        self.stdout.write(msg)
