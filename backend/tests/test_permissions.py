"""Права, роли и территориальное ограничение.

Тесты работают с живой базой: и каталог прав, и спуск по иерархии территорий
живут в PostgreSQL, и проверять их подменой в памяти означало бы проверять не ту
систему, которая поедет в эксплуатацию.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions as perms
from app.core.permissions import PermissionCode, TerritoryScope
from app.db.models.access import (
    AuditAction,
    AuditLogEntry,
    Permission,
    Role,
    RoleCode,
    SensitiveDataAccess,
)
from app.db.models.territory import Territory
from app.db.session import get_db
from app.main import create_app
from tests.conftest import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.integration


class TestKatalogPrav:
    def test_kazhdoe_pravo_opisano(self) -> None:
        """Администратор настраивает роли по названиям — безымянных прав быть не должно."""
        assert set(perms.PERMISSION_CATALOG) == set(PermissionCode)
        for title, description in perms.PERMISSION_CATALOG.values():
            assert title and description

    def test_opisany_vse_chetyre_roli(self) -> None:
        assert set(perms.DEFAULT_ROLE_PERMISSIONS) == set(RoleCode)
        assert set(perms.DEFAULT_ROLE_SENSITIVE_ACCESS) == set(RoleCode)

    def test_administrator_poluchaet_ves_katalog(self) -> None:
        """Право, не выданное администратору, не смог бы включить никто."""
        assert perms.DEFAULT_ROLE_PERMISSIONS[RoleCode.ADMIN] == frozenset(PermissionCode)

    def test_prosmotr_ne_mozhet_vygruzhat_i_pravit(self) -> None:
        viewer = perms.DEFAULT_ROLE_PERMISSIONS[RoleCode.VIEWER]
        assert PermissionCode.EXPORT_DATA not in viewer
        assert PermissionCode.DATA_EDIT not in viewer
        assert PermissionCode.SENSITIVE_VIEW not in viewer
        assert PermissionCode.RISK_MODEL_EDIT not in viewer

    def test_pravku_modeli_riska_imeet_tolko_administrator(self) -> None:
        """Веса меняют все оценки сразу — это полномочие не раздаётся."""
        for role, codes in perms.DEFAULT_ROLE_PERMISSIONS.items():
            if role is not RoleCode.ADMIN:
                assert PermissionCode.RISK_MODEL_EDIT not in codes


class TestSinkhronizatsiyaKataloga:
    def test_prava_i_roli_popadayut_v_bazu(self, db_session: Session) -> None:
        """Права хранятся в БД, а не в коде: администратор настраивает роли сам."""
        perms.sync_catalog(db_session)

        codes = {p.code for p in db_session.execute(select(Permission)).scalars()}
        assert codes >= {str(code) for code in PermissionCode}

        roles = {str(r.code) for r in db_session.execute(select(Role)).scalars()}
        assert roles >= {str(code) for code in RoleCode}

    def test_povtornyy_zapusk_ne_sozdayot_dubley(self, db_session: Session) -> None:
        perms.sync_catalog(db_session)
        pervyy = len(db_session.execute(select(Permission)).scalars().all())

        perms.sync_catalog(db_session)
        vtoroy = len(db_session.execute(select(Permission)).scalars().all())

        assert pervyy == vtoroy

    def test_stepen_dostupa_k_pdn_zadana_u_kazhdoy_roli(self, roles: dict[str, Role]) -> None:
        assert roles["admin"].sensitive_data_access == SensitiveDataAccess.FULL
        assert roles["analyst"].sensitive_data_access == SensitiveDataAccess.MASKED
        assert roles["manager"].sensitive_data_access == SensitiveDataAccess.MASKED
        assert roles["viewer"].sensitive_data_access == SensitiveDataAccess.HIDDEN


class TestPravaChitayutsyaIzBazy:
    def test_prava_polzovatelya_berutsya_cherez_rol(self, make_user: UserFactory) -> None:
        analyst = make_user(RoleCode.ANALYST)
        codes = perms.granted_codes(analyst)

        assert str(PermissionCode.DATA_IMPORT) in codes
        assert str(PermissionCode.USERS_MANAGE) not in codes

    def test_izmenenie_sostava_prav_roli_v_baze_menyaet_proverku(
        self, db_session: Session, roles: dict[str, Role], make_user: UserFactory
    ) -> None:
        """Ключевое требование ТЗ: права настраиваются, а не зашиты в коде.

        Администратор выдаёт роли «Просмотр» право на выгрузку прямо в базе —
        и проверка обязана это увидеть без правки исходников.
        """
        viewer = make_user(RoleCode.VIEWER)
        assert not perms.has_permission(viewer, PermissionCode.EXPORT_DATA)

        export = db_session.execute(
            select(Permission).where(Permission.code == str(PermissionCode.EXPORT_DATA))
        ).scalar_one()
        roles["viewer"].permissions.append(export)
        db_session.flush()
        db_session.refresh(viewer)

        assert perms.has_permission(viewer, PermissionCode.EXPORT_DATA)

    def test_stepen_dostupa_k_pdn_beryotsya_iz_roli(self, make_user: UserFactory) -> None:
        assert perms.sensitive_access_of(make_user(RoleCode.ADMIN)) is SensitiveDataAccess.FULL
        assert perms.sensitive_access_of(make_user(RoleCode.ANALYST)) is SensitiveDataAccess.MASKED
        assert perms.sensitive_access_of(make_user(RoleCode.VIEWER)) is SensitiveDataAccess.HIDDEN

    def test_musor_v_kolonke_traktuetsya_kak_samyy_strogiy_rezhim(
        self, db_session: Session, roles: dict[str, Role], make_user: UserFactory
    ) -> None:
        """При сомнении система закрывается, а не открывается."""
        user = make_user(RoleCode.ANALYST)
        roles["analyst"].sensitive_data_access = "неведомо что"  # type: ignore[assignment]
        db_session.flush()

        assert perms.sensitive_access_of(user) is SensitiveDataAccess.HIDDEN


class TestIerarkhiyaTerritoriy:
    def test_spusk_idyot_do_samogo_niza(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        """Доступ к области обязан давать доступ и к району, и к округу внутри него."""
        found = perms.descendant_territory_ids(db_session, territories["region"].id)

        assert found == {
            territories["region"].id,
            territories["karasay"].id,
            territories["talgar"].id,
            territories["okrug"].id,
        }

    def test_rayon_ne_tyanet_za_soboy_sosedey(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        found = perms.descendant_territory_ids(db_session, territories["karasay"].id)

        assert territories["talgar"].id not in found
        assert territories["region"].id not in found
        assert found == {territories["karasay"].id, territories["okrug"].id}


class TestOblastVidimosti:
    def test_bez_territorii_dostupno_vsyo(
        self, db_session: Session, make_user: UserFactory, territories: dict[str, Territory]
    ) -> None:
        """`territory_id IS NULL` — это «Все районы» из референса администрирования."""
        manager = make_user(RoleCode.MANAGER, territory_id=None)

        scope = perms.resolve_territory_scope(db_session, manager)

        assert scope.unrestricted
        assert scope.allows(territories["talgar"].id)
        assert scope.allows(uuid.uuid4())

    def test_analitik_oblasti_vidit_svoi_rayony(
        self, db_session: Session, make_user: UserFactory, territories: dict[str, Territory]
    ) -> None:
        analyst = make_user(RoleCode.ANALYST, territory_id=territories["region"].id)

        scope = perms.resolve_territory_scope(db_session, analyst)

        assert not scope.unrestricted
        assert scope.allows(territories["karasay"].id)
        assert scope.allows(territories["talgar"].id)

    def test_analitik_rayona_ne_vidit_sosedniy_rayon(
        self, db_session: Session, make_user: UserFactory, territories: dict[str, Territory]
    ) -> None:
        """Тот самый случай из ТЗ: Карасайский аналитик и Талгарский район."""
        karasay_analyst = make_user(RoleCode.ANALYST, territory_id=territories["karasay"].id)

        scope = perms.resolve_territory_scope(db_session, karasay_analyst)

        assert scope.allows(territories["karasay"].id)
        assert scope.allows(territories["okrug"].id)
        assert not scope.allows(territories["talgar"].id)
        assert not scope.allows(territories["region"].id)

    def test_zapis_bez_territorii_nedostupna_ogranichennomu_polzovatelyu(
        self, territories: dict[str, Territory]
    ) -> None:
        """Иначе через «неопределённые» строки утекали бы чужие районы."""
        scope = TerritoryScope(
            root_id=territories["karasay"].id, allowed_ids=frozenset({territories["karasay"].id})
        )
        assert not scope.allows(None)

    def test_pustoe_mnozhestvo_ne_ravno_dostupu_ko_vsemu(self) -> None:
        """Пустой список территорий — это «ничего», а не «всё»."""
        scope = TerritoryScope(root_id=uuid.uuid4(), allowed_ids=frozenset())
        assert not scope.unrestricted
        assert not scope.allows(uuid.uuid4())

    def test_require_brosaet_403(self, territories: dict[str, Territory]) -> None:
        scope = TerritoryScope(
            root_id=territories["karasay"].id, allowed_ids=frozenset({territories["karasay"].id})
        )
        with pytest.raises(HTTPException) as info:
            scope.require(territories["talgar"].id)
        assert info.value.status_code == 403


class TestOtkazZhurnaliruetsya:
    def test_chuzhaya_territoriya_pishetsya_v_zhurnal(
        self, db_session: Session, make_user: UserFactory, territories: dict[str, Territory]
    ) -> None:
        analyst = make_user(RoleCode.ANALYST, territory_id=territories["karasay"].id)
        scope = perms.resolve_territory_scope(db_session, analyst)

        with pytest.raises(HTTPException) as info:
            perms.assert_territory_allowed(
                scope,
                territories["talgar"].id,
                session=db_session,
                user=analyst,
                entity_type="territory",
            )

        assert info.value.status_code == 403
        zapis = db_session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.user_id == analyst.id)
            .where(AuditLogEntry.action == AuditAction.PERMISSION_DENIED)
        ).scalar_one()
        assert zapis.entity_id == str(territories["talgar"].id)
        assert zapis.user_login == analyst.login

    def test_razreshyonnaya_territoriya_zhurnal_ne_zasoryaet(
        self, db_session: Session, make_user: UserFactory, territories: dict[str, Territory]
    ) -> None:
        analyst = make_user(RoleCode.ANALYST, territory_id=territories["karasay"].id)
        scope = perms.resolve_territory_scope(db_session, analyst)

        perms.assert_territory_allowed(
            scope, territories["karasay"].id, session=db_session, user=analyst
        )

        otkazy = db_session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.user_id == analyst.id)
            .where(AuditLogEntry.action == AuditAction.PERMISSION_DENIED)
        ).all()
        assert otkazy == []


def _klient_s_zashchishchyonnym_marshrutom(
    db_session: Session, code: PermissionCode
) -> TestClient:
    """Приложение с маршрутом, закрытым правом `code`.

    Маршрут вешается до создания клиента: FastAPI разбирает зависимости
    обработчика при регистрации, и добавленный позже маршрут остаётся
    неразобранным.

    Проверять зависимость нужно именно так, настоящим запросом: сама функция
    проверки может быть безупречной, а на маршруте не оказаться — и снаружи
    это выглядит как открытая дверь.
    """
    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session

    # Право навешивается через `dependencies=`, а не параметром обработчика:
    # в этом модуле включён `from __future__ import annotations`, из-за чего
    # аннотация параметра стала бы строкой, которую FastAPI разбирает по
    # глобальным именам модуля — а `code` здесь локальная переменная.
    @application.get(
        "/probe/zashchishchyonno",
        dependencies=[Depends(perms.require_permission(code))],
    )
    def _obrabotchik() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(application)


class TestZavisimostProverkiPrav:
    """Проверка прав как зависимость FastAPI — на маршруте, а не в вакууме."""

    def test_prava_khvataet_marshrut_otkryt(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        klient = _klient_s_zashchishchyonnym_marshrutom(db_session, PermissionCode.EXPORT_DATA)
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = _voyti(klient, analyst.login)

        otvet = klient.get(
            "/probe/zashchishchyonno", headers={"Authorization": f"Bearer {token}"}
        )

        assert otvet.status_code == 200

    def test_prava_ne_khvataet_otkaz_i_zapis_v_zhurnale(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        klient = _klient_s_zashchishchyonnym_marshrutom(db_session, PermissionCode.EXPORT_DATA)
        viewer = make_user(RoleCode.VIEWER)
        db_session.commit()
        token = _voyti(klient, viewer.login)

        otvet = klient.get(
            "/probe/zashchishchyonno", headers={"Authorization": f"Bearer {token}"}
        )

        assert otvet.status_code == 403
        zapis = db_session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.user_id == viewer.id)
            .where(AuditLogEntry.action == AuditAction.PERMISSION_DENIED)
        ).scalar_one()
        assert zapis.details is not None
        assert zapis.details["required"] == str(PermissionCode.EXPORT_DATA)

    def test_bez_tokena_zashchishchyonnyy_marshrut_ne_otkryvaetsya(
        self, db_session: Session
    ) -> None:
        klient = _klient_s_zashchishchyonnym_marshrutom(db_session, PermissionCode.EXPORT_DATA)

        assert klient.get("/probe/zashchishchyonno").status_code == 401


def _voyti(client: TestClient, login: str) -> str:
    """Войти и вернуть токен — вспомогательная функция для проверок маршрутов."""
    otvet = client.post(
        "/api/v1/auth/login", json={"login": login, "password": TEST_PASSWORD}
    )
    assert otvet.status_code == 200, otvet.text
    return str(otvet.json()["access_token"])
