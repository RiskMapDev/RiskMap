"""Мастер импорта: приём файла, сопоставление, проверки, версии, откат.

Проверки идут по требованиям ТЗ (раздел 15) и по трём принципам проекта,
которые мастер обязан соблюдать: импорт идемпотентен, откат ничего не удаляет,
исходные книги остаются неизменными.

Тесты работают с живой базой — как и остальные тесты доступа: целевые таблицы
используют JSONB и UUID, а идемпотентность держится на `ON CONFLICT` PostgreSQL,
которого нет ни в одной подмене в памяти.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import security
from app.core.config import get_settings
from app.db.models.access import AuditAction, AuditLogEntry, RoleCode
from app.db.models.organization import Organization
from app.db.models.procurement import Contract, Supplier
from app.db.models.source import DataQualityIssue, ImportJob, ImportStatus, SourceFile
from app.db.models.territory import AliasKind, Territory, TerritoryAlias
from app.services import import_wizard
from app.services.import_wizard import DataKind, FieldType, ImportWizardError
from app.services.territory_resolver import normalize_territory_name
from tests.conftest import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.integration


# --- Приспособления ----------------------------------------------------------


@pytest.fixture(autouse=True)
def uploads_tmp(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Каталог загрузок на время теста.

    Подменяется целиком: рабочий каталог проекта не должен обрастать файлами
    после прогона тестов, а комплект книг ДЭР вообще открыт только на чтение.
    """
    directory = tmp_path / "uploads"
    directory.mkdir()
    monkeypatch.setattr(import_wizard, "uploads_dir", lambda: directory)
    return directory


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    """Клиент с подключённым роутером импорта.

    Роутер подключается здесь, а не в `create_app`: точка входа приложения в
    этой задаче не правится, а проверить маршруты всё равно нужно.
    """
    from app.api.import_routes import router

    app.include_router(router, prefix=get_settings().api_prefix)
    with TestClient(app) as client:
        yield client
    security.clear_revoked_tokens()


@pytest.fixture
def alias_territories(
    db_session: Session, territories: dict[str, Territory]
) -> dict[str, Territory]:
    """Территории с алиасами: без них сопоставитель не знает ни одного названия.

    Алиасом служит код территории, а не её название: база теста та же, что
    рабочая, и настоящий «Карасайский район» в справочнике уже есть. Алиас с
    тем же написанием сделал бы название неоднозначным, и резолвер — правильно —
    отказался бы выбирать между двумя территориями.
    """
    for territory in territories.values():
        db_session.add(
            TerritoryAlias(
                territory_id=territory.id,
                alias=territory.code,
                normalized=normalize_territory_name(territory.code),
                kind=AliasKind.SOURCE_SPELLING,
            )
        )
    db_session.flush()
    return territories


def xlsx_bytes(rows: Sequence[Sequence[Any]], *, title: str = "Лист1") -> bytes:
    """Книга Excel в памяти. Первая строка — заголовок."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def csv_bytes(
    rows: Sequence[Sequence[Any]], *, delimiter: str = ";", encoding: str = "utf-8"
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue().encode(encoding)


#: Организации — самый простой тип: два обязательных поля и одна целевая таблица.
ORG_HEADER = ["БИН", "Наименование", "Дата регистрации", "Численность"]
ORG_MAPPING = {
    "bin": "БИН",
    "name": "Наименование",
    "reg_date": "Дата регистрации",
    "employees_count": "Численность",
}


def org_rows(count: int = 2, *, prefix: str = "1010") -> list[list[Any]]:
    """Заведомо тестовые БИН и названия.

    Правдоподобные реквизиты в тестах опасны: их копируют в демонстрацию, и
    выдуманная организация начинает выглядеть как настоящая запись реестра.
    """
    return [
        [f"{prefix}{index:08d}", f"ТЕСТОВАЯ ОРГАНИЗАЦИЯ {index}", "01.02.2001", 10 + index]
        for index in range(1, count + 1)
    ]


def upload_org_file(
    session: Session, *, rows: Sequence[Sequence[Any]] | None = None, name: str = "orgs.xlsx"
) -> import_wizard.UploadResult:
    content = xlsx_bytes([ORG_HEADER, *(rows if rows is not None else org_rows())])
    return import_wizard.accept_upload(
        session, file_name=name, content=content, kind=DataKind.ORGANIZATIONS
    )


# --- Шаг 1: приём файла ------------------------------------------------------


class TestPriyomFayla:
    def test_prinimaet_knigu_i_chitaet_strukturu(self, db_session: Session) -> None:
        result = upload_org_file(db_session)

        assert result.table.columns == ORG_HEADER
        assert len(result.table.rows) == 2
        assert result.size_bytes > 0

    def test_fayl_registriruetsya_kak_zagruzhennyy(self, db_session: Session) -> None:
        """origin=upload отличает загрузку от книги immutable-комплекта."""
        result = upload_org_file(db_session)

        source = db_session.get(SourceFile, result.source_file_id)
        assert source is not None
        assert source.origin == "upload"
        assert source.sha256 == result.sha256

    def test_fayl_lozhitsya_v_katalog_zagruzok_a_ne_k_istochnikam(
        self, db_session: Session, uploads_tmp: Any
    ) -> None:
        """Комплект книг ДЭР неизменяем — мастер не имеет права туда писать."""
        result = upload_org_file(db_session)

        assert result.stored_path.parent == uploads_tmp
        assert result.stored_path.exists()
        assert get_settings().source_data_dir not in result.stored_path.parents

    def test_imya_fayla_v_khranilishche_eto_ego_khesh(self, db_session: Session) -> None:
        """Имя-по-содержимому исключает затирание чужой загрузки одноимённой."""
        result = upload_org_file(db_session)

        assert result.stored_path.stem == result.sha256

    def test_povtornaya_zagruzka_ne_dublirouet_zapis_istochnika(
        self, db_session: Session
    ) -> None:
        first = upload_org_file(db_session)
        second = upload_org_file(db_session, name="другое-имя.xlsx")

        assert first.sha256 == second.sha256
        assert first.source_file_id == second.source_file_id
        count = db_session.execute(
            select(func.count()).select_from(SourceFile).where(SourceFile.sha256 == first.sha256)
        ).scalar_one()
        assert count == 1

    def test_neizvestnoe_rasshirenie_otklonyaetsya(self, db_session: Session) -> None:
        with pytest.raises(ImportWizardError) as info:
            import_wizard.accept_upload(
                db_session, file_name="данные.docx", content=b"x", kind=DataKind.ORGANIZATIONS
            )
        assert info.value.code == "unsupported_format"

    def test_pustoy_fayl_otklonyaetsya(self, db_session: Session) -> None:
        with pytest.raises(ImportWizardError) as info:
            import_wizard.accept_upload(
                db_session, file_name="пусто.csv", content=b"", kind=DataKind.ORGANIZATIONS
            )
        assert info.value.code == "empty_file"

    def test_fayl_bolshe_predela_otklonyaetsya(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Предел берётся из настроек, а не зашит в мастере."""
        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_mb", 1)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.accept_upload(
                db_session,
                file_name="большой.csv",
                content=b"a" * (2 * 1024 * 1024),
                kind=DataKind.ORGANIZATIONS,
            )
        assert info.value.code == "file_too_large"

    def test_predel_sovpadaet_s_referensom(self) -> None:
        assert get_settings().max_upload_mb == 50

    def test_shest_plitok_pervogo_shaga(self) -> None:
        """На референсе ровно шесть типов загружаемых данных."""
        kinds = import_wizard.describe_kinds()

        assert len(kinds) == 6
        assert {item["code"] for item in kinds} == {str(kind) for kind in DataKind}

    def test_forma_perechislyaet_formaty_iz_tz(self) -> None:
        assert {".xlsx", ".xls", ".csv", ".json", ".geojson"} <= import_wizard.ACCEPTED_EXTENSIONS


class TestChteniyeFormatov:
    def test_csv_s_tochkoy_s_zapyatoy(self) -> None:
        table = import_wizard.read_table(
            csv_bytes([ORG_HEADER, *org_rows(1)]), "данные.csv"
        )
        assert table.columns == ORG_HEADER
        assert len(table.rows) == 1

    def test_csv_v_cp1251(self) -> None:
        """Выгрузки из старых систем приходят в cp1251 — это не ошибка."""
        table = import_wizard.read_table(
            csv_bytes([["Наименование"], ["ТЕСТОВОЕ ЗНАЧЕНИЕ"]], encoding="cp1251"),
            "данные.csv",
        )
        assert table.rows[0]["Наименование"] == "ТЕСТОВОЕ ЗНАЧЕНИЕ"

    def test_json_massiv_obyektov(self) -> None:
        payload = json.dumps([{"БИН": "101000000001", "Наименование": "ТЕСТ"}])
        table = import_wizard.read_table(payload.encode(), "данные.json")
        assert table.columns == ["БИН", "Наименование"]

    def test_geojson_chitaetsya_po_svoystvam_obyektov(self) -> None:
        payload = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"Наименование": "ТЕСТОВЫЙ ОБЪЕКТ"},
                        "geometry": {"type": "Point", "coordinates": [76.9, 43.2]},
                    }
                ],
            }
        )
        table = import_wizard.read_table(payload.encode(), "объекты.geojson")

        assert table.rows[0]["Наименование"] == "ТЕСТОВЫЙ ОБЪЕКТ"
        assert len(table.geometries) == 1

    def test_bityy_json_soobshchaet_pozitsiyu(self) -> None:
        with pytest.raises(ImportWizardError) as info:
            import_wizard.read_table("{не json".encode(), "данные.json")
        assert info.value.code == "invalid_json"

    def test_zagolovok_ne_v_pervoy_stroke(self) -> None:
        """В книге 8.4 заголовок третий — мастер обязан это переживать."""
        content = xlsx_bytes(
            [
                ["Отчёт по организациям", None, None, None],
                [None, None, None, None],
                ORG_HEADER,
                *org_rows(1),
            ]
        )
        table = import_wizard.read_table(content, "книга.xlsx")

        assert table.columns == ORG_HEADER
        assert len(table.rows) == 1

    def test_povtoryayushchiysya_zagolovok_ne_slivaetsya(self) -> None:
        """Слить две одноимённые колонки в одну значило бы потерять данные."""
        table = import_wizard.read_table(
            csv_bytes([["Сумма", "Сумма"], ["1", "2"]]), "данные.csv"
        )
        assert table.columns == ["Сумма", "Сумма (2)"]

    def test_adres_stroki_soderzhit_nomer(self) -> None:
        table = import_wizard.read_table(xlsx_bytes([ORG_HEADER, *org_rows(1)]), "книга.xlsx")
        # Заголовок первый, значит данные начинаются со второй строки книги.
        assert "2" in table.row_refs[0]


# --- Шаг 2: сопоставление ----------------------------------------------------


class TestSopostavleniyeKolonok:
    def test_tochnoe_sovpadenie_po_nazvaniyu_polya(self) -> None:
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)
        mapping = import_wizard.suggest_mapping(spec, ORG_HEADER)

        assert mapping["bin"] == "БИН"
        assert mapping["name"] == "Наименование"

    def test_sovpadenie_po_alliasu(self) -> None:
        spec = import_wizard.kind_spec(DataKind.SUBSIDIES)
        mapping = import_wizard.suggest_mapping(spec, ["ИИН/БИН", "Получатель", "Сумма"])

        assert mapping["xin"] == "ИИН/БИН"
        assert mapping["name"] == "Получатель"
        assert mapping["total_amount"] == "Сумма"

    def test_odna_kolonka_ne_dostayotsya_dvum_polyam(self) -> None:
        """Иначе одно и то же значение молча попало бы в два разных поля."""
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)
        mapping = import_wizard.suggest_mapping(spec, ["Наименование"])

        assert list(mapping.values()).count("Наименование") == 1

    def test_neizvestnye_kolonki_ne_sopostavlyayutsya(self) -> None:
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)
        mapping = import_wizard.suggest_mapping(spec, ["Совершенно посторонняя колонка"])

        assert mapping == {}

    def test_nesopostavlennoe_obyazatelnoe_pole_otvergaetsya(self) -> None:
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.validate_mapping(spec, {"bin": "БИН"}, ORG_HEADER)

        assert info.value.code == "required_field_unmapped"
        assert "Наименование" in info.value.message

    def test_ssylka_na_nesushchestvuyushchuyu_kolonku_otvergaetsya(self) -> None:
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.validate_mapping(
                spec, {"bin": "БИН", "name": "Нет такой"}, ORG_HEADER
            )

        assert info.value.code == "unknown_column"

    def test_neizvestnoe_pole_sistemy_otvergaetsya(self) -> None:
        spec = import_wizard.kind_spec(DataKind.ORGANIZATIONS)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.validate_mapping(
                spec, {"bin": "БИН", "name": "Наименование", "выдумка": "БИН"}, ORG_HEADER
            )

        assert info.value.code == "unknown_field"


class TestShablonySopostavleniya:
    def test_shablon_sokhranyaetsya_i_chitaetsya(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)

        import_wizard.save_mapping_template(
            db_session,
            name="Выгрузка ГБД ЮЛ",
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
            source_file_id=upload.source_file_id,
        )

        templates = import_wizard.list_mapping_templates(db_session, DataKind.ORGANIZATIONS)
        assert any(item["name"] == "Выгрузка ГБД ЮЛ" for item in templates)
        saved = next(item for item in templates if item["name"] == "Выгрузка ГБД ЮЛ")
        assert saved["mapping"] == ORG_MAPPING

    def test_povtornoe_sokhraneniye_obnovlyaet_a_ne_dublirouet(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(db_session)
        for mapping in (ORG_MAPPING, {"bin": "БИН", "name": "Наименование"}):
            import_wizard.save_mapping_template(
                db_session,
                name="Шаблон",
                kind=DataKind.ORGANIZATIONS,
                mapping=mapping,
                source_file_id=upload.source_file_id,
            )

        templates = [
            item
            for item in import_wizard.list_mapping_templates(db_session, DataKind.ORGANIZATIONS)
            if item["name"] == "Шаблон"
        ]
        assert len(templates) == 1
        assert templates[0]["mapping"] == {"bin": "БИН", "name": "Наименование"}

    def test_shablon_bez_nazvaniya_otvergaetsya(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.save_mapping_template(
                db_session,
                name="   ",
                kind=DataKind.ORGANIZATIONS,
                mapping=ORG_MAPPING,
                source_file_id=upload.source_file_id,
            )
        assert info.value.code == "invalid_template_name"


# --- Приведение значений -----------------------------------------------------


class TestPrivedeniyeZnacheniy:
    @pytest.mark.parametrize(
        "raw",
        ["01.02.2001", "2001-02-01", "01/02/2001", "01-02-2001"],
    )
    def test_daty_v_raznykh_napisaniyakh(self, raw: str) -> None:
        value, note = import_wizard.convert_value(raw, FieldType.DATE)
        assert value == date(2001, 2, 1)
        assert note is None

    def test_data_chislom_iz_excel(self) -> None:
        """Неразмеченная ячейка отдаёт дату числом — это не мусор."""
        value, _ = import_wizard.convert_value(36923, FieldType.DATE)
        assert value == date(2001, 2, 1)

    def test_neponyatnaya_data_soobshchaet_ozhidaemyy_format(self) -> None:
        with pytest.raises(Exception) as info:
            import_wizard.convert_value("позавчера", FieldType.DATE)
        assert "ДД.ММ.ГГГГ" in str(info.value)

    def test_summa_s_probelami_i_valyutoy(self) -> None:
        value, _ = import_wizard.convert_value("1 234 567,89 ₸", FieldType.MONEY)
        assert value == Decimal("1234567.89")

    def test_summa_ostayotsya_decimal_a_ne_float(self) -> None:
        """Через float сумма договора теряет тиын на больших значениях."""
        value, _ = import_wizard.convert_value("12345678901.23", FieldType.MONEY)
        assert isinstance(value, Decimal)
        assert value == Decimal("12345678901.23")

    def test_vedushchie_nuli_iin_vosstanavlivayutsya_s_predupryezhdeniem(self) -> None:
        """Ноль теряется при открытии книги в Excel; молчать об этом нельзя."""
        value, note = import_wizard.convert_value(101000000001, FieldType.XIN)

        assert value == "101000000001"
        value, note = import_wizard.convert_value(12345678901, FieldType.XIN)
        assert value == "012345678901"
        assert note is not None
        assert "нул" in note.casefold()

    def test_slishkom_dlinnyy_iin_otvergaetsya(self) -> None:
        with pytest.raises(Exception, match="12"):
            import_wizard.convert_value("1234567890123", FieldType.XIN)

    def test_pustoe_znachenie_eto_none_a_ne_nol(self) -> None:
        """Пустая ячейка означает «не измерено», а не ноль."""
        for raw in (None, "", "   "):
            value, _ = import_wizard.convert_value(raw, FieldType.MONEY)
            assert value is None

    def test_shirota_vne_diapazona_otvergaetsya(self) -> None:
        with pytest.raises(Exception) as info:
            import_wizard.convert_value(120.0, FieldType.LATITUDE)
        assert "диапазон" in str(info.value)

    def test_dolgota_v_diapazone_prinimaetsya(self) -> None:
        value, _ = import_wizard.convert_value(76.9, FieldType.LONGITUDE)
        assert value == pytest.approx(76.9)

    def test_drobnoe_tam_gde_tseloe_otvergaetsya(self) -> None:
        with pytest.raises(Exception, match="дробное"):
            import_wizard.convert_value("10,5", FieldType.INTEGER)


# --- Построчная проверка -----------------------------------------------------


def validate_org_file(
    session: Session, rows: Sequence[Sequence[Any]], mapping: dict[str, str] | None = None
) -> import_wizard.ValidationOutcome:
    table = import_wizard.read_table(xlsx_bytes([ORG_HEADER, *rows]), "книга.xlsx")
    return import_wizard.validate_rows(
        session,
        spec=import_wizard.kind_spec(DataKind.ORGANIZATIONS),
        mapping=mapping or ORG_MAPPING,
        table=table,
    )


class TestPostrochnayaProverka:
    def test_zamechanie_ukazyvaet_stroku_i_kolonku(self, db_session: Session) -> None:
        """ТЗ требует ровно этого: без адреса замечание бесполезно."""
        outcome = validate_org_file(
            db_session, [["101000000001", "ТЕСТ", "позавчера", 10]]
        )

        issue = next(item for item in outcome.issues if item.code == "invalid_date")
        assert issue.source_row_ref is not None
        assert "2" in issue.source_row_ref
        assert issue.column_name == "Дата регистрации"
        assert issue.raw_value == "позавчера"

    def test_pustoe_obyazatelnoe_pole_eto_oshibka(self, db_session: Session) -> None:
        outcome = validate_org_file(db_session, [["101000000001", None, "01.02.2001", 10]])

        assert any(item.code == "required_field_missing" for item in outcome.issues)
        assert outcome.rows_failed == 1

    def test_stroka_s_oshibkoy_ne_popadaet_v_zapis(self, db_session: Session) -> None:
        outcome = validate_org_file(
            db_session,
            [["101000000001", "ХОРОШАЯ", "01.02.2001", 10], ["101000000002", None, None, None]],
        )

        assert len(outcome.valid_rows) == 1
        assert outcome.valid_rows[0].values["name"] == "ХОРОШАЯ"

    def test_odna_bityaya_stroka_ne_ronyaet_ves_fayl(self, db_session: Session) -> None:
        outcome = validate_org_file(db_session, [*org_rows(5), ["нет-бина", None, None, None]])

        assert outcome.rows_read == 6
        assert len(outcome.valid_rows) == 5

    def test_dublikat_vnutri_fayla_zamechaetsya(self, db_session: Session) -> None:
        rows = org_rows(1) * 2
        outcome = validate_org_file(db_session, rows)

        assert outcome.duplicates_in_file == 1
        issue = next(item for item in outcome.issues if item.code == "duplicate_in_file")
        assert "уже встречался" in issue.message

    def test_logicheskoe_protivorechie_zamechaetsya(self, db_session: Session) -> None:
        """Дата регистрации в будущем — противоречие, а не опечатка формата."""
        outcome = validate_org_file(
            db_session, [["101000000001", "ТЕСТ", "01.02.2999", 10]]
        )

        issue = next(item for item in outcome.issues if item.code == "logical_contradiction")
        assert "будущем" in issue.message
        assert outcome.rows_failed == 1

    def test_predupryezhdeniye_ne_otbrasyvaet_stroku(
        self, db_session: Session, alias_territories: dict[str, Territory]
    ) -> None:
        """Расхождение разбивки населения на единицу — повод предупредить, не терять."""
        table = import_wizard.read_table(
            csv_bytes(
                [
                    ["Территория", "Дата", "Всего", "Мужчины", "Женщины"],
                    [alias_territories["karasay"].code, "01.01.2024", "100", "51", "50"],
                ]
            ),
            "население.csv",
        )
        outcome = import_wizard.validate_rows(
            db_session,
            spec=import_wizard.kind_spec(DataKind.SOCIOECONOMIC),
            mapping={
                "territory_name": "Территория",
                "as_of_date": "Дата",
                "total": "Всего",
                "male": "Мужчины",
                "female": "Женщины",
            },
            table=table,
        )

        assert any(item.code == "logical_contradiction" for item in outcome.issues)
        assert len(outcome.valid_rows) == 1

    def test_neopoznannaya_territoriya_otbrasyvaet_stroku(
        self, db_session: Session, alias_territories: dict[str, Territory]
    ) -> None:
        """Угадывать территорию запрещено: показатель некуда привязать."""
        table = import_wizard.read_table(
            csv_bytes(
                [["Территория", "Дата", "Всего"], ["Несуществующий район", "01.01.2024", "100"]]
            ),
            "население.csv",
        )
        outcome = import_wizard.validate_rows(
            db_session,
            spec=import_wizard.kind_spec(DataKind.SOCIOECONOMIC),
            mapping={"territory_name": "Территория", "as_of_date": "Дата", "total": "Всего"},
            table=table,
        )

        assert outcome.valid_rows == []
        assert any(item.code == "territory_not_resolved" for item in outcome.issues)

    def test_koordinaty_vne_diapazona_eto_oshibka(self, db_session: Session) -> None:
        payload = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"БИН": "101000000001", "Наименование": "ТЕСТ"},
                        "geometry": {"type": "Point", "coordinates": [200.0, 43.2]},
                    }
                ],
            }
        )
        table = import_wizard.read_table(payload.encode(), "объекты.geojson")
        outcome = import_wizard.validate_rows(
            db_session,
            spec=import_wizard.kind_spec(DataKind.ORGANIZATIONS),
            mapping={"bin": "БИН", "name": "Наименование"},
            table=table,
        )

        assert any(item.code == "invalid_coordinates" for item in outcome.issues)
        assert outcome.valid_rows == []

    def test_koordinaty_za_ramkoy_strany_eto_predupryezhdeniye(
        self, db_session: Session
    ) -> None:
        """Точка вне рамки обычно означает перепутанные широту и долготу."""
        payload = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"БИН": "101000000001", "Наименование": "ТЕСТ"},
                        "geometry": {"type": "Point", "coordinates": [43.2, 76.9]},
                    }
                ],
            }
        )
        table = import_wizard.read_table(payload.encode(), "объекты.geojson")
        outcome = import_wizard.validate_rows(
            db_session,
            spec=import_wizard.kind_spec(DataKind.ORGANIZATIONS),
            mapping={"bin": "БИН", "name": "Наименование"},
            table=table,
        )

        assert any(item.code == "coordinates_outside_country" for item in outcome.issues)
        assert len(outcome.valid_rows) == 1


# --- Шаг 3: сухой прогон -----------------------------------------------------


def organizations_count(session: Session, bins: Sequence[str]) -> int:
    return int(
        session.execute(
            select(func.count()).select_from(Organization).where(Organization.bin.in_(bins))
        ).scalar_one()
    )


class TestSukhoyProgon:
    def test_nichego_ne_zapisyvaet(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        bins = [str(row[0]) for row in org_rows()]

        import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert organizations_count(db_session, bins) == 0

    def test_zadanie_sozdayotsya_so_statusom_sukhogo_progona(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(db_session)

        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert job.status == ImportStatus.DRY_RUN
        assert job.is_dry_run is True
        assert job.rows_read == 2

    def test_svodka_soderzhit_chisla_dlya_podtverzhdeniya(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(db_session, rows=[*org_rows(2), ["x", None, None, None]])

        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        summary = (job.reconciliation or {})["summary"]
        assert summary["rows_read"] == 3
        assert summary["rows_valid"] == 2
        assert summary["rows_failed"] == 1

    def test_zamechaniya_sokhranyayutsya_i_dostupny_po_zadaniyu(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(
            db_session, rows=[["101000000001", "ТЕСТ", "позавчера", 10]]
        )

        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        issues = db_session.scalars(
            select(DataQualityIssue).where(DataQualityIssue.import_job_id == job.id)
        ).all()
        assert any(item.code == "invalid_date" for item in issues)

    def test_progon_zhurnaliruetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        upload = upload_org_file(db_session)

        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
            user=analyst,
        )

        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.IMPORT_STARTED,
                AuditLogEntry.entity_id == str(job.id),
            )
        ).one()
        assert entry.details is not None
        assert entry.details["mode"] == "dry_run"


# --- Шаг 3: подтверждение ----------------------------------------------------


class TestPodtverzhdeniye:
    def test_zapisyvaet_stroki(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        bins = [str(row[0]) for row in org_rows()]

        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert result.created == 2
        assert organizations_count(db_session, bins) == 2

    def test_import_idempotenten(self, db_session: Session) -> None:
        """Главный принцип: повторный запуск не создаёт дублей."""
        upload = upload_org_file(db_session)
        bins = [str(row[0]) for row in org_rows()]

        first = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        second = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert first.created == 2
        assert second.created == 0
        assert second.updated == 2
        assert organizations_count(db_session, bins) == 2

    def test_tot_zhe_fayl_ostayotsya_toy_zhe_versiey(self, db_session: Session) -> None:
        """Иначе повторное подтверждение плодило бы версии-близнецы."""
        upload = upload_org_file(db_session)

        first = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        second = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert first.job.data_version == second.job.data_version

    def test_novoe_soderzhimoe_podnimaet_versiyu(self, db_session: Session) -> None:
        first_upload = upload_org_file(db_session, rows=org_rows(1))
        first = import_wizard.confirm(
            db_session,
            upload_id=first_upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        second_upload = upload_org_file(db_session, rows=org_rows(2))
        second = import_wizard.confirm(
            db_session,
            upload_id=second_upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        assert second.job.data_version == first.job.data_version + 1

    def test_stroki_nesut_proiskhozhdenie(self, db_session: Session) -> None:
        """Без происхождения цифру нечем объяснить — требование ТЗ."""
        upload = upload_org_file(db_session, rows=org_rows(1))

        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        row = db_session.scalars(
            select(Organization).where(Organization.import_job_id == result.job.id)
        ).one()
        assert row.natural_key == str(org_rows(1)[0][0])
        assert row.source_row_ref is not None
        assert row.source_dataset_id is not None
        assert row.is_current is True

    def test_nesopostavlennye_kolonki_ne_zatirayutsya(self, db_session: Session) -> None:
        """Загрузка двух колонок не должна обнулять всё остальное в строке."""
        upload = upload_org_file(db_session, rows=org_rows(1))
        import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        organization = db_session.scalars(
            select(Organization).where(Organization.bin == str(org_rows(1)[0][0]))
        ).one()
        assert organization.employees_count == 11

        narrow = upload_org_file(
            db_session, rows=[[org_rows(1)[0][0], "НОВОЕ НАЗВАНИЕ", None, None]]
        )
        import_wizard.confirm(
            db_session,
            upload_id=narrow.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping={"bin": "БИН", "name": "Наименование"},
        )

        db_session.expire_all()
        organization = db_session.scalars(
            select(Organization).where(Organization.bin == str(org_rows(1)[0][0]))
        ).one()
        assert organization.name == "НОВОЕ НАЗВАНИЕ"
        assert organization.employees_count == 11

    def test_zavisimye_tablitsy_pishutsya_v_poryadke_svyazey(
        self, db_session: Session
    ) -> None:
        """Договор ссылается на поставщика — поставщик обязан появиться первым."""
        header = ["ID договора", "БИН поставщика", "Поставщик", "Сумма"]
        content = xlsx_bytes(
            [header, ["ТЕСТ-ДОГОВОР-1", "101000000001", "ТЕСТОВЫЙ ПОСТАВЩИК", 1000]]
        )
        upload = import_wizard.accept_upload(
            db_session,
            file_name="договоры.xlsx",
            content=content,
            kind=DataKind.PROCUREMENT,
        )

        import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.PROCUREMENT,
            mapping={
                "contract_id": "ID договора",
                "supplier_bin": "БИН поставщика",
                "supplier_name": "Поставщик",
                "final_amount": "Сумма",
            },
        )

        contract = db_session.scalars(
            select(Contract).where(Contract.contract_id == "ТЕСТ-ДОГОВОР-1")
        ).one()
        supplier = db_session.get(Supplier, contract.supplier_id)
        assert supplier is not None
        assert supplier.bin == "101000000001"
        assert contract.final_amount == Decimal("1000")

    def test_zadanie_zavershaetsya_uspekhom_i_zhurnaliruetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        upload = upload_org_file(db_session)

        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
            user=analyst,
        )

        assert result.job.status == ImportStatus.SUCCEEDED
        assert result.job.started_by_id == analyst.id
        entries = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.IMPORT_FINISHED,
                AuditLogEntry.entity_id == str(result.job.id),
            )
        ).all()
        assert len(entries) == 1

    def test_svodka_zadaniya_pokazyvaet_status_ok(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        payload = import_wizard.job_payload(db_session, result.job)
        assert payload["badge"] == "ok"
        assert payload["can_rollback"] is True

    def test_svodka_zadaniya_s_zamechaniyami_pokazyvaet_predupryezhdeniye(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(
            db_session, rows=[["101000000001", "ТЕСТ", "позавчера", 10]]
        )
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        payload = import_wizard.job_payload(db_session, result.job)
        assert payload["badge"] == "warning"


# --- Откат -------------------------------------------------------------------


class TestOtkat:
    def test_otkat_snimayet_aktualnost_no_ne_udalyaet(self, db_session: Session) -> None:
        """Главный принцип отката: история оценок должна его пережить."""
        upload = upload_org_file(db_session)
        bins = [str(row[0]) for row in org_rows()]
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        import_wizard.rollback(db_session, job_id=result.job.id)
        db_session.expire_all()

        rows = db_session.scalars(
            select(Organization).where(Organization.bin.in_(bins))
        ).all()
        assert len(rows) == 2
        assert all(row.is_current is False for row in rows)

    def test_zadanie_perekhodit_v_status_otkacheno(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        job = import_wizard.rollback(db_session, job_id=result.job.id, reason="ошибка оператора")

        assert job.status == ImportStatus.ROLLED_BACK
        assert job.error_message == "ошибка оператора"

    def test_zamechaniya_i_zadanie_ostayutsya_posle_otkata(
        self, db_session: Session
    ) -> None:
        upload = upload_org_file(
            db_session, rows=[["101000000001", "ТЕСТ", "позавчера", 10]]
        )
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        job_id = result.job.id

        import_wizard.rollback(db_session, job_id=job_id)

        assert db_session.get(ImportJob, job_id) is not None
        remaining = db_session.execute(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.import_job_id == job_id)
        ).scalar_one()
        assert remaining > 0

    def test_otkat_zhurnaliruetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        import_wizard.rollback(db_session, job_id=result.job.id, user=admin)

        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.IMPORT_ROLLED_BACK,
                AuditLogEntry.entity_id == str(result.job.id),
            )
        ).one()
        assert entry.details is not None
        assert entry.details["rows_deactivated"] == 2

    def test_povtornyy_otkat_otvergaetsya(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        import_wizard.rollback(db_session, job_id=result.job.id)

        with pytest.raises(ImportWizardError) as info:
            import_wizard.rollback(db_session, job_id=result.job.id)
        assert info.value.code == "already_rolled_back"

    def test_sukhoy_progon_otkatyvat_nechego(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        with pytest.raises(ImportWizardError) as info:
            import_wizard.rollback(db_session, job_id=job.id)
        assert info.value.code == "dry_run_rollback"

    def test_otkat_nesushchestvuyushchego_zadaniya(self, db_session: Session) -> None:
        with pytest.raises(ImportWizardError) as info:
            import_wizard.rollback(db_session, job_id=uuid.uuid4())
        assert info.value.code == "job_not_found"

    def test_povtornaya_zagruzka_vozvrashchaet_aktualnost(
        self, db_session: Session
    ) -> None:
        """Откат отзывает версию, но не запрещает загрузить её заново."""
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        import_wizard.rollback(db_session, job_id=result.job.id)

        import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        db_session.expire_all()

        rows = db_session.scalars(
            select(Organization).where(
                Organization.bin.in_([str(row[0]) for row in org_rows()])
            )
        ).all()
        assert all(row.is_current is True for row in rows)


# --- Фоновая обработка -------------------------------------------------------


class TestFonovayaObrabotka:
    def test_progress_zapisyvaetsya_v_zadanie(self, db_session: Session) -> None:
        upload = upload_org_file(db_session)
        job = import_wizard.dry_run(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )

        import_wizard.write_progress(db_session, job, 3, 10)

        assert (job.reconciliation or {})["progress"] == {
            "processed": 3,
            "total": 10,
            "percent": 30,
        }

    def test_fonovaya_obrabotka_pishet_dannye(
        self, db_session: Session, db_connection: Connection, make_user: UserFactory
    ) -> None:
        """Фоновый путь работает в собственной сессии — проверяем именно его."""
        analyst = make_user(RoleCode.ANALYST)
        upload = upload_org_file(db_session)
        db_session.flush()

        factory = sessionmaker(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        job_id = import_wizard.confirm_in_background(
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
            user_id=analyst.id,
            session_factory=factory,
        )

        db_session.expire_all()
        job = db_session.get(ImportJob, job_id)
        assert job is not None
        assert job.status == ImportStatus.SUCCEEDED
        assert organizations_count(db_session, [str(row[0]) for row in org_rows()]) == 2

    def test_bolshoy_fayl_soprovozhdaetsya_podskazkoy(self, db_session: Session) -> None:
        """Мастер советует фоновый режим, но решение оставляет человеку."""
        upload = upload_org_file(db_session, rows=org_rows(3))

        assert upload.as_dict()["background_recommended"] is False
        assert import_wizard.BACKGROUND_ROW_THRESHOLD > 3


# --- Маршруты ----------------------------------------------------------------


def token_for(api: TestClient, login: str) -> dict[str, str]:
    response = api.post(
        f"{get_settings().api_prefix}/auth/login",
        json={"login": login, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestMarshruty:
    def test_perechen_tipov_dannykh(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.get(
            f"{get_settings().api_prefix}/imports/kinds", headers=token_for(api, analyst.login)
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["kinds"]) == 6
        assert body["max_upload_mb"] == 50

    def test_zagruzka_cherez_formu(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.post(
            f"{get_settings().api_prefix}/imports/upload",
            headers=token_for(api, analyst.login),
            data={"data_kind": "organizations"},
            files={"file": ("orgs.xlsx", xlsx_bytes([ORG_HEADER, *org_rows(1)]))},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["columns"] == ORG_HEADER
        assert body["suggested_mapping"]["bin"] == "БИН"
        assert len(body["preview"]) == 1

    def test_ves_marshrut_mastera(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Три шага подряд: загрузка → сухой прогон → подтверждение."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        headers = token_for(api, analyst.login)
        prefix = get_settings().api_prefix

        uploaded = api.post(
            f"{prefix}/imports/upload",
            headers=headers,
            data={"data_kind": "organizations"},
            files={"file": ("orgs.xlsx", xlsx_bytes([ORG_HEADER, *org_rows(1)]))},
        ).json()

        body = {
            "upload_id": uploaded["upload_id"],
            "data_kind": "organizations",
            "mapping": ORG_MAPPING,
        }

        dry = api.post(f"{prefix}/imports/dry-run", headers=headers, json=body)
        assert dry.status_code == 200, dry.text
        assert dry.json()["is_dry_run"] is True
        assert dry.json()["summary"]["rows_valid"] == 1

        confirmed = api.post(f"{prefix}/imports/confirm", headers=headers, json=body)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "succeeded"
        assert confirmed.json()["rows_created"] == 1

    def test_istoriya_zagruzok_otdayotsya_so_statusami(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        upload = upload_org_file(db_session)
        import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        db_session.commit()

        response = api.get(
            f"{get_settings().api_prefix}/imports/jobs?limit=5",
            headers=token_for(api, analyst.login),
        )

        assert response.status_code == 200
        items = response.json()
        assert items
        assert {"file_name", "badge", "rows_read", "status"} <= set(items[0])

    def test_otkat_trebuet_otdelnogo_prava(
        self, api: TestClient, db_session: Session, make_user: UserFactory, roles: dict[str, Any]
    ) -> None:
        """Право на загрузку не означает права отозвать опубликованную версию."""
        viewer = make_user(RoleCode.VIEWER)
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        db_session.commit()

        response = api.post(
            f"{get_settings().api_prefix}/imports/jobs/{result.job.id}/rollback",
            headers=token_for(api, viewer.login),
            json={"reason": "попытка"},
        )

        assert response.status_code == 403

    def test_otkat_cherez_api(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)
        upload = upload_org_file(db_session)
        result = import_wizard.confirm(
            db_session,
            upload_id=upload.sha256,
            kind=DataKind.ORGANIZATIONS,
            mapping=ORG_MAPPING,
        )
        db_session.commit()

        response = api.post(
            f"{get_settings().api_prefix}/imports/jobs/{result.job.id}/rollback",
            headers=token_for(api, admin.login),
            json={"reason": "ошибка в источнике"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rolled_back"

    def test_bez_prava_importa_ne_puskaet(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        viewer = make_user(RoleCode.VIEWER)
        db_session.commit()

        response = api.get(
            f"{get_settings().api_prefix}/imports/kinds",
            headers=token_for(api, viewer.login),
        )

        assert response.status_code == 403

    def test_bez_tokena_ne_puskaet(self, api: TestClient) -> None:
        assert api.get(f"{get_settings().api_prefix}/imports/kinds").status_code == 401

    def test_nesopostavlennoe_obyazatelnoe_pole_dayot_400_s_kodom(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        upload = upload_org_file(db_session)
        db_session.commit()

        response = api.post(
            f"{get_settings().api_prefix}/imports/dry-run",
            headers=token_for(api, analyst.login),
            json={
                "upload_id": upload.sha256,
                "data_kind": "organizations",
                "mapping": {"bin": "БИН"},
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "required_field_unmapped"

    def test_neizvestnyy_fayl_dayot_404(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.post(
            f"{get_settings().api_prefix}/imports/dry-run",
            headers=token_for(api, analyst.login),
            json={
                "upload_id": "0" * 64,
                "data_kind": "organizations",
                "mapping": ORG_MAPPING,
            },
        )

        assert response.status_code == 404
