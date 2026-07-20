"""Тесты загрузки справочника территорий.

Разделены на две части. Первая разбирает файлы и не требует ни базы, ни
каталога исходников сверх того, что лежит в репозитории. Вторая помечена
`@pytest.mark.integration` и работает с живым PostGIS: проверить упрощение
геометрии, точку внутри полигона и починку через `ST_MakeValid` без движка
нельзя — а именно эти операции легче всего сломать незаметно.

Что здесь зафиксировано как факт, а не как проблема:

* коротких алиасов в таблице не появляется. «Талгарский р-н» сворачивается той
  же функцией нормализации к «талгарскии», что и «Талгарский район», а
  ограничение `uq_alias_normalized_territory` допускает одну строку на пару
  «свёрнутая форма + территория». Свёрнутые варианты сохраняются в `notes`;
* все прочерки книги населения разрешаются в ноль — но не потому, что так
  написано в аудите, а потому что этого требует арифметика каждой строки;
* КАТО остаётся пустым у 30 территорий из 32.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.source import DataQualityIssue, ImportJob, ImportStatus, IssueSeverity
from app.db.models.territory import (
    AliasKind,
    BoundaryVersion,
    PopulationStat,
    Territory,
    TerritoryAlias,
    TerritoryGeometry,
    TerritoryLevel,
)
from app.db.session import get_session_factory
from app.importers.territories import (
    ALMATY_SET,
    ATTRIBUTION_TEXT,
    COUNTRY_CODE,
    DOCUMENT_AREA_KM2,
    EXPECTED_ALMATY_UNITS,
    EXPECTED_POPULATION_ROWS,
    EXPECTED_REGIONS,
    LICENSE_NAME,
    POPULATION_AS_OF,
    POPULATION_FILE_NAME,
    REGION_CODES,
    REGIONS_SET,
    AliasCandidate,
    TerritoryFeature,
    TerritoryLoader,
    alias_candidates,
    book_alias_candidates,
    check_population_totals,
    classify_population_row,
    dedupe_aliases,
    load_territories,
    parse_almaty_units,
    parse_population,
    parse_regions,
    short_form,
)
from app.services.territory_resolver import TerritoryResolver, normalize_territory_name

# Опечатки и варианты написания из книги 8.3. Они обязаны попасть в справочник
# как есть: импорт связывает написание с территорией, но не правит источник.
BOOK_SPELLINGS_TO_KEEP = (
    "Западно-Казахстанкая область",
    "Мангыстауская область",
    "Северо-Казахстанкая область",
    "Туркистанская область",
)


# --- Фикстуры ----------------------------------------------------------------


@pytest.fixture(scope="module")
def boundaries_dir() -> Path:
    path = get_settings().data_dir / "boundaries"
    if not path.is_dir():
        pytest.skip(f"Каталог границ недоступен: {path}")
    return path


@pytest.fixture(scope="module")
def regions(boundaries_dir: Path) -> list[TerritoryFeature]:
    return parse_regions(boundaries_dir / REGIONS_SET.file_name)


@pytest.fixture(scope="module")
def almaty_units(boundaries_dir: Path) -> list[TerritoryFeature]:
    return parse_almaty_units(boundaries_dir / ALMATY_SET.file_name)


@pytest.fixture(scope="module")
def population_rows() -> list[Any]:
    from scripts.source_manifest import resolve_source

    source_dir = get_settings().source_data_dir
    if not source_dir.is_dir():
        pytest.skip(f"Каталог источников недоступен: {source_dir}")
    try:
        path = resolve_source(source_dir, POPULATION_FILE_NAME)
    except FileNotFoundError as error:
        pytest.skip(str(error))
    return parse_population(path)


# --- Границы: разбор файлов --------------------------------------------------


class TestРазборГраниц:
    def test_регионов_ровно_двадцать(self, regions: list[TerritoryFeature]) -> None:
        assert len(regions) == EXPECTED_REGIONS

    def test_единиц_области_одиннадцать(self, almaty_units: list[TerritoryFeature]) -> None:
        """9 районов + Конаев + Алатау. Сама область из этого файла не берётся."""
        assert len(almaty_units) == EXPECTED_ALMATY_UNITS

    def test_область_из_второго_файла_не_дублируется(
        self, almaty_units: list[TerritoryFeature]
    ) -> None:
        """relation/215718 есть в обоих наборах, но территория должна быть одна."""
        assert all(unit.osm_relation_id != 215718 for unit in almaty_units)

    def test_конаев_и_алатау_города_остальные_районы(
        self, almaty_units: list[TerritoryFeature]
    ) -> None:
        levels = {unit.code: unit.level for unit in almaty_units}
        assert levels["konaev-city"] is TerritoryLevel.CITY
        assert levels["alatau-city"] is TerritoryLevel.CITY
        districts = [code for code, level in levels.items() if level is TerritoryLevel.DISTRICT]
        assert len(districts) == 9

    def test_като_есть_только_у_области(self, almaty_units: list[TerritoryFeature]) -> None:
        """У районов кода КАТО нет ни в одном источнике — это норма, а не пропуск."""
        assert all(unit.kato_code is None for unit in almaty_units)

    def test_като_области_взят_из_источника(self, regions: list[TerritoryFeature]) -> None:
        by_code = {region.code: region for region in regions}
        assert by_code["almaty-oblast"].kato_code == "190000000"
        assert by_code["karaganda-oblast"].kato_code == "350000000"
        # Остальные 18 регионов — без КАТО, и достраивать его нельзя.
        assert sum(1 for region in regions if region.kato_code is None) == 18

    def test_все_родители_проставлены(
        self, regions: list[TerritoryFeature], almaty_units: list[TerritoryFeature]
    ) -> None:
        assert all(region.parent_code == COUNTRY_CODE for region in regions)
        assert all(unit.parent_code == "almaty-oblast" for unit in almaty_units)

    def test_геометрии_полигональные(
        self, regions: list[TerritoryFeature], almaty_units: list[TerritoryFeature]
    ) -> None:
        for feature in [*regions, *almaty_units]:
            assert feature.geometry["type"] in {"Polygon", "MultiPolygon"}


# --- Алиасы ------------------------------------------------------------------


class TestАлиасы:
    def test_короткая_форма_района(self) -> None:
        assert short_form("Талгарский район", TerritoryLevel.DISTRICT) == "Талгарский р-н"

    def test_короткая_форма_области(self) -> None:
        assert short_form("Алматинская область", TerritoryLevel.REGION) == "Алматинская обл."

    def test_короткая_форма_города(self) -> None:
        assert short_form("Конаев", TerritoryLevel.CITY) == "г. Конаев"

    def test_короткая_форма_сворачивается_к_официальной(self) -> None:
        """Именно поэтому отдельной строкой в таблице она не сохранится."""
        assert normalize_territory_name("Талгарский р-н") == normalize_territory_name(
            "Талгарский район"
        )

    def test_свёрнутые_варианты_попадают_в_примечание(self) -> None:
        rows = dedupe_aliases(
            [
                AliasCandidate("Талгарский район", AliasKind.OFFICIAL),
                AliasCandidate("Талгарский р-н", AliasKind.SHORT),
                AliasCandidate("Талғар ауданы", AliasKind.OFFICIAL),
            ]
        )
        assert len(rows) == 2
        official = next(row for row in rows if row.alias == "Талгарский район")
        assert official.notes is not None
        assert "Талгарский р-н" in official.notes

    def test_опечатки_книги_сохраняются_как_написания_источника(
        self, boundaries_dir: Path
    ) -> None:
        import json

        payload = json.loads(
            (boundaries_dir / "region-aliases-8-3.json").read_text(encoding="utf-8")
        )
        by_code = book_alias_candidates(payload)
        all_aliases = {
            candidate.alias for candidates in by_code.values() for candidate in candidates
        }
        for spelling in BOOK_SPELLINGS_TO_KEEP:
            assert spelling in all_aliases
        assert all(
            candidate.kind is AliasKind.SOURCE_SPELLING
            for candidates in by_code.values()
            for candidate in candidates
        )

    def test_опечатки_не_сворачиваются_к_правильному_написанию(self) -> None:
        """Иначе они бы исчезли из таблицы и перестали связывать строки книги."""
        assert normalize_territory_name("Западно-Казахстанкая область") != (
            normalize_territory_name("Западно-Казахстанская область")
        )
        assert normalize_territory_name("Мангыстауская область") != (
            normalize_territory_name("Мангистауская область")
        )
        assert normalize_territory_name("Туркистанская область") != (
            normalize_territory_name("Туркестанская область")
        )

    def test_кандидаты_включают_казахское_и_английское(
        self, almaty_units: list[TerritoryFeature]
    ) -> None:
        talgar = next(unit for unit in almaty_units if unit.code == "talgarskiy")
        aliases = {candidate.alias for candidate in alias_candidates(talgar)}
        assert "Талгарский район" in aliases
        assert "Талғар ауданы" in aliases
        assert "Talgar District" in aliases

    def test_прежние_названия_заводятся_историческими(
        self, almaty_units: list[TerritoryFeature]
    ) -> None:
        konaev = next(unit for unit in almaty_units if unit.code == "konaev-city")
        historical = {
            candidate.alias
            for candidate in alias_candidates(konaev)
            if candidate.kind is AliasKind.HISTORICAL
        }
        assert "Капшагай" in historical

    def test_справочник_не_даёт_неоднозначностей(
        self,
        regions: list[TerritoryFeature],
        almaty_units: list[TerritoryFeature],
        boundaries_dir: Path,
    ) -> None:
        """Главная проверка справочника: имя обязано вести к одной территории.

        Неоднозначное написание нельзя использовать для автоматического
        связывания — строка книги с таким названием повиснет без территории.
        """
        import json

        payload = json.loads(
            (boundaries_dir / "region-aliases-8-3.json").read_text(encoding="utf-8")
        )
        book = book_alias_candidates(payload)
        resolver = TerritoryResolver()
        for feature in [*regions, *almaty_units]:
            candidates = [*alias_candidates(feature), *book.get(feature.code, [])]
            for row in dedupe_aliases(candidates):
                resolver.add(row.alias, feature.code)
        assert resolver.ambiguous_names == ()


# --- Население ---------------------------------------------------------------


class TestНаселение:
    def test_уровень_определяется_по_тексту(self) -> None:
        assert classify_population_row("Республика Казахстан") == "country"
        assert classify_population_row("Алматинская") == "region"
        assert classify_population_row("Балхашский район") == "unit"
        # «г.а.» — городская администрация, единица второго уровня, а не центр.
        assert classify_population_row("Қонаев г.а.") == "unit"
        assert classify_population_row("город Қонаев") == "center"
        assert classify_population_row("с.Отеген Батыра") == "center"

    def test_единиц_второго_уровня_одиннадцать(self, population_rows: list[Any]) -> None:
        assert sum(1 for row in population_rows if row.kind == "unit") == EXPECTED_ALMATY_UNITS

    def test_контрольные_суммы_сходятся(self, population_rows: list[Any]) -> None:
        check = check_population_totals(population_rows)
        assert check["units_count"] == EXPECTED_ALMATY_UNITS
        assert check["all_columns_match"], check["per_column"]
        assert check["gender_mismatches"] == []
        assert check["settlement_mismatches"] == []

    def test_итог_области_совпадает_с_книгой(self, population_rows: list[Any]) -> None:
        oblast = next(row for row in population_rows if row.kind == "region")
        assert oblast.values["total"] == 1_606_365
        assert oblast.values["male"] + oblast.values["female"] == 1_606_365

    def test_прочерк_становится_нулём_только_под_расчёт(
        self, population_rows: list[Any]
    ) -> None:
        """Ноль ставится там, где «город + село = всё» сходится только при нуле.

        Это не доверие к аудиту, а проверка: Балхашский район целиком сельский,
        и его сельское население равно общему — значит городское строго ноль.
        """
        balkhash = next(row for row in population_rows if row.raw_name == "Балхашский район")
        assert balkhash.values["urban_total"] == 0
        assert balkhash.values["rural_total"] == balkhash.values["total"]
        assert balkhash.dash_decisions["urban_total"].startswith("0:")

    def test_все_прочерки_разобраны_в_ноль(self, population_rows: list[Any]) -> None:
        """В этом файле пропусков измерения нет — все прочерки структурные."""
        decisions = [
            decision for row in population_rows for decision in row.dash_decisions.values()
        ]
        assert decisions, "прочерки в книге есть, разбор обязан их увидеть"
        assert all(decision.startswith("0:") for decision in decisions)

    def test_неразрешимый_прочерк_даёт_null(self) -> None:
        """Если арифметика не сходится, прочерк — пропуск измерения, а не ноль."""
        from app.importers.territories import _resolve_dashes

        values: dict[str, int | None] = {
            "total": 100,
            "male": None,
            "female": None,
            "urban_total": None,
            "urban_male": None,
            "urban_female": None,
            "rural_total": 40,
            "rural_male": None,
            "rural_female": None,
        }
        resolved, decisions = _resolve_dashes(values, {"urban_total"})
        assert resolved["urban_total"] is None
        assert "NULL" in decisions["urban_total"]

    def test_центр_берётся_из_книги(self, population_rows: list[Any]) -> None:
        balkhash = next(row for row in population_rows if row.raw_name == "Балхашский район")
        assert balkhash.center_name == "с.Баканас"


# --- Площади -----------------------------------------------------------------


class TestПлощади:
    def test_заявленные_площади_известны_только_по_алматинской_области(self) -> None:
        """У остальных 19 регионов документа с площадями нет — поле останется NULL."""
        assert len(DOCUMENT_AREA_KM2) == EXPECTED_ALMATY_UNITS + 1
        assert "almaty-oblast" in DOCUMENT_AREA_KM2

    def test_лицензия_описана_полностью(self) -> None:
        assert LICENSE_NAME.startswith("Open Database License")
        assert ATTRIBUTION_TEXT == "© OpenStreetMap contributors, ODbL 1.0"


# --- Загрузка в базу ---------------------------------------------------------


@pytest.fixture
def session() -> Iterator[Session]:
    """Сессия, всегда откатываемая: тесты не должны менять состояние базы."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture(scope="module")
def loaded() -> None:
    """Один боевой прогон импорта на весь модуль.

    Импорт идемпотентен, поэтому запускать его на живой базе безопасно:
    повторный прогон обновляет те же строки, а не добавляет новые.
    """
    settings = get_settings()
    if not settings.source_data_dir.is_dir():
        pytest.skip(f"Каталог источников недоступен: {settings.source_data_dir}")
    db = get_session_factory()()
    try:
        load_territories(
            db, data_dir=settings.data_dir, source_dir=settings.source_data_dir
        )
        db.commit()
    finally:
        db.close()


@pytest.mark.integration
@pytest.mark.usefixtures("loaded")
class TestЗагрузкаВБазу:
    def test_иерархия_собрана(self, session: Session) -> None:
        levels = dict(
            session.execute(
                select(Territory.level, func.count()).group_by(Territory.level)
            ).all()
        )
        assert levels[TerritoryLevel.COUNTRY] == 1
        assert levels[TerritoryLevel.REGION] == EXPECTED_REGIONS
        assert levels[TerritoryLevel.DISTRICT] == 9
        assert levels[TerritoryLevel.CITY] == 2

    def test_родители_проставлены(self, session: Session) -> None:
        country = session.scalars(
            select(Territory).where(Territory.code == COUNTRY_CODE)
        ).one()
        assert country.parent_id is None
        regions_with_parent = session.scalar(
            select(func.count())
            .select_from(Territory)
            .where(Territory.level == TerritoryLevel.REGION, Territory.parent_id == country.id)
        )
        assert regions_with_parent == EXPECTED_REGIONS

        oblast = session.scalars(
            select(Territory).where(Territory.code == REGION_CODES["KZ-19"])
        ).one()
        children = session.scalar(
            select(func.count()).select_from(Territory).where(Territory.parent_id == oblast.id)
        )
        assert children == EXPECTED_ALMATY_UNITS

    def test_версия_границ_несёт_лицензию(self, session: Session) -> None:
        """Без лицензии и атрибуции границы показывать нельзя — поля обязательные."""
        versions = session.scalars(select(BoundaryVersion)).all()
        assert len(versions) == 2
        for version in versions:
            assert version.license_name == LICENSE_NAME
            assert version.attribution_text == ATTRIBUTION_TEXT
            assert version.redistribution_allowed is True
            assert version.downloaded_at == date(2026, 7, 20)
            assert version.sha256 is not None and len(version.sha256) == 64

    def test_версии_хранят_хеш_своего_файла(self, session: Session) -> None:
        """Два файла — две версии: один sha256 не может описывать оба."""
        by_code = {
            version.code: version for version in session.scalars(select(BoundaryVersion)).all()
        }
        assert by_code[REGIONS_SET.code].sha256 == REGIONS_SET.sha256
        assert by_code[ALMATY_SET.code].sha256 == ALMATY_SET.sha256
        assert by_code[REGIONS_SET.code].sha256 != by_code[ALMATY_SET.code].sha256

    def test_геометрии_multipolygon_в_4326(self, session: Session) -> None:
        rows = session.execute(
            func.count().select().select_from(TerritoryGeometry)
        ).scalar_one()
        assert rows == EXPECTED_REGIONS + EXPECTED_ALMATY_UNITS

        bad = session.execute(
            select(func.count()).select_from(TerritoryGeometry).where(
                func.ST_GeometryType(TerritoryGeometry.geom) != "ST_MultiPolygon"
            )
        ).scalar_one()
        assert bad == 0

        wrong_srid = session.execute(
            select(func.count()).select_from(TerritoryGeometry).where(
                func.ST_SRID(TerritoryGeometry.geom) != 4326
            )
        ).scalar_one()
        assert wrong_srid == 0

    def test_все_геометрии_валидны(self, session: Session) -> None:
        invalid = session.execute(
            select(func.count()).select_from(TerritoryGeometry).where(
                ~func.ST_IsValid(TerritoryGeometry.geom)
            )
        ).scalar_one()
        assert invalid == 0

    def test_подпись_лежит_внутри_полигона(self, session: Session) -> None:
        """ST_PointOnSurface, а не ST_Centroid: у подковообразного района
        математический центроид оказывается вне его границ."""
        outside = session.execute(
            select(func.count()).select_from(TerritoryGeometry).where(
                ~func.ST_Within(TerritoryGeometry.centroid, TerritoryGeometry.geom)
            )
        ).scalar_one()
        assert outside == 0

    def test_упрощённые_варианты_легче_исходной(self, session: Session) -> None:
        rows = session.execute(
            select(
                func.ST_NPoints(TerritoryGeometry.geom),
                func.ST_NPoints(TerritoryGeometry.geom_simplified_mid),
                func.ST_NPoints(TerritoryGeometry.geom_simplified_low),
            )
        ).all()
        assert rows
        for full, mid, low in rows:
            assert 0 < low <= mid <= full

    def test_площадь_считается_геодезически(self, session: Session) -> None:
        """Площадь в градусах на широте 43° занижена примерно на четверть."""
        oblast = session.scalars(
            select(Territory).where(Territory.code == "almaty-oblast")
        ).one()
        assert oblast.area_km2_computed is not None
        assert 104_000 < float(oblast.area_km2_computed) < 105_500

    def test_заявленная_и_вычисленная_площади_раздельно(self, session: Session) -> None:
        """Расхождение — самостоятельный факт, а не повод переписать величину."""
        alatau = session.scalars(
            select(Territory).where(Territory.code == "alatau-city")
        ).one()
        assert alatau.area_km2 == 600
        assert alatau.area_km2_computed is not None
        assert float(alatau.area_km2_computed) > 800
        issue = session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.code == "area_mismatch_with_document"
            )
        ).first()
        assert issue is not None

    def test_като_только_у_двух_областей(self, session: Session) -> None:
        with_kato = session.scalars(
            select(Territory.code).where(Territory.kato_code.is_not(None))
        ).all()
        assert sorted(with_kato) == ["almaty-oblast", "karaganda-oblast"]

    def test_у_районов_като_пустой(self, session: Session) -> None:
        codes = session.scalars(
            select(Territory.kato_code).where(Territory.level == TerritoryLevel.DISTRICT)
        ).all()
        assert all(code is None for code in codes)

    def test_алиасы_содержат_опечатки_книги(self, session: Session) -> None:
        stored = set(session.scalars(select(TerritoryAlias.alias)).all())
        for spelling in BOOK_SPELLINGS_TO_KEEP:
            assert spelling in stored

    def test_опечатки_ведут_к_правильным_областям(self, session: Session) -> None:
        pairs = dict(
            session.execute(
                select(TerritoryAlias.alias, Territory.code).join(
                    Territory, Territory.id == TerritoryAlias.territory_id
                )
            ).all()
        )
        assert pairs["Западно-Казахстанкая область"] == "west-kazakhstan-oblast"
        assert pairs["Мангыстауская область"] == "mangistau-oblast"
        assert pairs["Северо-Казахстанкая область"] == "north-kazakhstan-oblast"
        assert pairs["Туркистанская область"] == "turkestan-oblast"

    def test_резолвер_без_неоднозначностей(self, session: Session) -> None:
        resolver = TerritoryResolver()
        rows = session.execute(
            select(TerritoryAlias.alias, Territory.code).join(
                Territory, Territory.id == TerritoryAlias.territory_id
            )
        ).all()
        resolver.add_many((str(alias), str(code)) for alias, code in rows)
        assert resolver.ambiguous_names == ()
        assert resolver.resolve("Талгарский р-н").territory_code == "talgarskiy"
        assert resolver.resolve("Қонаев г.а.").territory_code == "konaev-city"
        assert resolver.resolve("Алматинская").territory_code == "almaty-oblast"

    def test_население_двенадцать_строк(self, session: Session) -> None:
        count = session.scalar(select(func.count()).select_from(PopulationStat))
        assert count == EXPECTED_POPULATION_ROWS

    def test_население_на_первое_апреля(self, session: Session) -> None:
        dates = set(session.scalars(select(PopulationStat.as_of_date)).all())
        assert dates == {POPULATION_AS_OF}

    def test_сумма_единиц_равна_итогу_области(self, session: Session) -> None:
        oblast = session.scalars(
            select(Territory).where(Territory.code == "almaty-oblast")
        ).one()
        oblast_stat = session.scalars(
            select(PopulationStat).where(PopulationStat.territory_id == oblast.id)
        ).one()
        unit_ids = session.scalars(
            select(Territory.id).where(Territory.parent_id == oblast.id)
        ).all()
        units = session.scalars(
            select(PopulationStat).where(PopulationStat.territory_id.in_(unit_ids))
        ).all()
        assert len(units) == EXPECTED_ALMATY_UNITS
        for column in (
            "total",
            "male",
            "female",
            "urban_total",
            "urban_male",
            "urban_female",
            "rural_total",
            "rural_male",
            "rural_female",
        ):
            assert sum(getattr(stat, column) for stat in units) == getattr(oblast_stat, column)

    def test_у_населения_есть_происхождение(self, session: Session) -> None:
        stats = session.scalars(select(PopulationStat)).all()
        for stat in stats:
            assert stat.import_job_id is not None
            assert stat.source_dataset_id is not None
            assert stat.natural_key is not None
            assert stat.data_as_of == POPULATION_AS_OF
            assert stat.source_row_ref is not None and stat.source_row_ref.startswith("Sheet1!")

    def test_у_территорий_есть_происхождение(self, session: Session) -> None:
        territories = session.scalars(select(Territory)).all()
        for territory in territories:
            assert territory.import_job_id is not None
            assert territory.natural_key is not None
            assert territory.data_as_of is not None

    def test_задание_импорта_завершено_успешно(self, session: Session) -> None:
        job = session.scalars(
            select(ImportJob)
            .where(ImportJob.importer == "territories", ImportJob.is_dry_run.is_(False))
            .order_by(ImportJob.started_at.desc())
        ).first()
        assert job is not None
        # Колонка строковая, поэтому сравнение по значению, а не по тождеству.
        assert job.status == ImportStatus.SUCCEEDED
        assert job.finished_at is not None
        assert job.rows_read > 0
        assert job.reconciliation is not None
        assert job.reconciliation["population"]["all_columns_match"] is True

    def test_замечания_записаны(self, session: Session) -> None:
        codes = set(session.scalars(select(DataQualityIssue.code)).all())
        assert "kato_missing" in codes
        assert "dash_interpreted" in codes
        assert "duplicate_osm_object" in codes

    def test_ошибок_качества_нет(self, session: Session) -> None:
        errors = session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.severity == IssueSeverity.ERROR
            )
        ).all()
        assert errors == []


@pytest.mark.integration
class TestИдемпотентность:
    def test_повторный_прогон_не_создаёт_дублей(self) -> None:
        """Два прогона подряд обязаны дать одинаковое число строк.

        Это не украшение импорта, а условие его пригодности: справочник
        перезагружается при каждом обновлении границ, и второй запуск не должен
        удваивать территории.
        """
        settings = get_settings()
        if not settings.source_data_dir.is_dir():
            pytest.skip(f"Каталог источников недоступен: {settings.source_data_dir}")

        def snapshot() -> dict[str, int]:
            db = get_session_factory()()
            try:
                return {
                    "territories": db.scalar(select(func.count()).select_from(Territory)) or 0,
                    "geometries": db.scalar(
                        select(func.count()).select_from(TerritoryGeometry)
                    )
                    or 0,
                    "aliases": db.scalar(select(func.count()).select_from(TerritoryAlias)) or 0,
                    "population": db.scalar(select(func.count()).select_from(PopulationStat))
                    or 0,
                    "versions": db.scalar(select(func.count()).select_from(BoundaryVersion))
                    or 0,
                }
            finally:
                db.close()

        def run() -> None:
            db = get_session_factory()()
            try:
                load_territories(
                    db, data_dir=settings.data_dir, source_dir=settings.source_data_dir
                )
                db.commit()
            finally:
                db.close()

        run()
        first = snapshot()
        run()
        second = snapshot()
        assert first == second
        assert first["territories"] == EXPECTED_REGIONS + EXPECTED_ALMATY_UNITS + 1


@pytest.mark.integration
class TestСухойПрогон:
    def test_ничего_не_записывает(self) -> None:
        settings = get_settings()
        if not settings.source_data_dir.is_dir():
            pytest.skip(f"Каталог источников недоступен: {settings.source_data_dir}")

        db = get_session_factory()()
        try:
            before = db.scalar(select(func.count()).select_from(ImportJob)) or 0
            report = load_territories(
                db,
                data_dir=settings.data_dir,
                source_dir=settings.source_data_dir,
                dry_run=True,
            )
            db.commit()
        finally:
            db.close()

        assert report.dry_run is True
        assert report.territories_total == EXPECTED_REGIONS + EXPECTED_ALMATY_UNITS + 1

        db = get_session_factory()()
        try:
            after = db.scalar(select(func.count()).select_from(ImportJob)) or 0
            dry_jobs = db.scalar(
                select(func.count()).select_from(ImportJob).where(ImportJob.is_dry_run.is_(True))
            )
        finally:
            db.close()
        assert after == before
        assert dry_jobs == 0


@pytest.mark.integration
class TestПочинкаГеометрии:
    """Невалидных геометрий в наборах нет, но обработчик обязан работать.

    Проверяется на заведомо битом полигоне-«бабочке»: путь исправления иначе
    останется непроверенным до первого сбоя в проде, где его цена — молча
    искажённая граница.
    """

    def test_битая_геометрия_чинится_и_объясняется(self, session: Session) -> None:
        settings = get_settings()
        loader = TerritoryLoader(
            session,
            data_dir=settings.data_dir,
            source_dir=settings.source_data_dir,
        )
        loader._start_job()
        version = BoundaryVersion(
            code=f"test-{uuid.uuid4().hex[:8]}",
            title="Тестовая версия",
            source_name="test",
            license_name=LICENSE_NAME,
            attribution_text=ATTRIBUTION_TEXT,
            redistribution_allowed=False,
        )
        session.add(version)
        session.flush()
        territory = Territory(
            code="test-bowtie",
            boundary_version_id=version.id,
            name_ru="Тест",
            level=TerritoryLevel.DISTRICT,
        )
        session.add(territory)
        session.flush()

        bowtie = TerritoryFeature(
            code="test-bowtie",
            level=TerritoryLevel.DISTRICT,
            parent_code=None,
            name_ru="Тест",
            name_kk=None,
            name_en=None,
            name_osm=None,
            int_name=None,
            old_names=(),
            iso3166_2=None,
            kato_code=None,
            osm_relation_id=0,
            osm_ref="test",
            area_km2_osm=None,
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [[76.0, 43.0], [77.0, 44.0], [77.0, 43.0], [76.0, 44.0], [76.0, 43.0]]
                ],
            },
            source_row_ref="test",
        )
        loader._write_geometry(territory, bowtie)

        assert loader.report.geometries_repaired == 1
        stored = session.scalars(
            select(TerritoryGeometry).where(TerritoryGeometry.territory_id == territory.id)
        ).one()
        # Признак относится к ИСХОДНОЙ геометрии: она пришла битой.
        assert stored.is_valid is False
        assert stored.validity_note is not None
        assert "ST_MakeValid" in stored.validity_note
        assert "Self-intersection" in stored.validity_note
        # А сохранена уже исправленная — иначе её нельзя ни показать, ни измерить.
        is_valid_now = session.scalar(func.ST_IsValid(stored.geom))
        assert is_valid_now is True
        assert territory.area_km2_computed is not None and territory.area_km2_computed > 0
        session.rollback()
