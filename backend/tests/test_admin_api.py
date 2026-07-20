"""Администрирование: пользователи, справочники, критерии риска, журнал действий.

Четыре вкладки референса и три требования, которые здесь проверяются построчно:
права проверяются на сервере, правка весов риска журналируется и версионируется,
а журнал действий доступен только на чтение.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models.access import AuditAction, AuditLogEntry, Role, RoleCode, User
from app.db.models.procurement import Contract
from app.db.models.territory import Territory
from app.services import audit
from tests.conftest import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.integration

PREFIX = get_settings().api_prefix
USERS_URL = f"{PREFIX}/admin/users"
REFERENCE_URL = f"{PREFIX}/admin/reference"
MODELS_URL = f"{PREFIX}/admin/risk-models"
AUDIT_URL = f"{PREFIX}/admin/audit"

#: Пароль тестовых учётных записей, создаваемых через API. Длиннее минимума
#: из настроек; в рабочие развёртывания не попадает.
NEW_PASSWORD = "Новый-Пароль-2026!x"


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    """Клиент с подключённым роутером администрирования.

    Роутер подключается здесь, а не в `create_app`: точка входа приложения в
    этой задаче не правится, а маршруты проверить нужно.
    """
    from app.api.admin_routes import router

    app.include_router(router, prefix=PREFIX)
    with TestClient(app) as client:
        yield client
    security.clear_revoked_tokens()


def token_for(api: TestClient, login: str) -> dict[str, str]:
    response = api.post(
        f"{PREFIX}/auth/login", json={"login": login, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(
    api: TestClient, db_session: Session, make_user: UserFactory
) -> dict[str, str]:
    admin = make_user(RoleCode.ADMIN)
    db_session.commit()
    return token_for(api, admin.login)


# --- Вкладка «Пользователи» --------------------------------------------------


class TestSpisokPolzovateley:
    def test_kolonki_referensa_prisutstvuyut(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Ф.И.О., логин, роль, территория, последний вход, статус."""
        response = api.get(USERS_URL, headers=admin_headers)

        assert response.status_code == 200
        row = response.json()[0]
        assert {
            "full_name",
            "login",
            "role",
            "role_title",
            "territory",
            "last_login_at",
            "is_active",
        } <= set(row)

    def test_bez_territorii_pishetsya_vse_rayony(
        self, api: TestClient, admin_headers: dict[str, str], make_user: UserFactory,
        db_session: Session,
    ) -> None:
        """Пустая ячейка читалась бы как «не заполнено», а смысл обратный."""
        user = make_user(RoleCode.MANAGER, territory_id=None)
        db_session.commit()

        rows = api.get(USERS_URL, headers=admin_headers).json()
        found = next(item for item in rows if item["login"] == user.login)

        assert found["territory"] == "Все районы"

    def test_territoriya_polzovatelya_pokazyvaetsya_nazvaniem(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        make_user: UserFactory,
        db_session: Session,
        territories: dict[str, Territory],
    ) -> None:
        user = make_user(RoleCode.ANALYST, territory_id=territories["karasay"].id)
        db_session.commit()

        rows = api.get(USERS_URL, headers=admin_headers).json()
        found = next(item for item in rows if item["login"] == user.login)

        assert found["territory"] == territories["karasay"].name_ru

    def test_bez_prava_upravleniya_ne_puskaet(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Клиент не источник истины о правах — проверка на сервере."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.get(USERS_URL, headers=token_for(api, analyst.login))

        assert response.status_code == 403

    def test_bez_tokena_ne_puskaet(self, api: TestClient) -> None:
        assert api.get(USERS_URL).status_code == 401

    def test_v_otvete_net_khesha_parolya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        raw = api.get(USERS_URL, headers=admin_headers).text

        assert "password" not in raw
        assert "argon2" not in raw


class TestSozdaniePolzovatelya:
    def _body(self, **overrides: Any) -> dict[str, Any]:
        body = {
            "login": f"t.новый.{uuid.uuid4().hex[:8]}",
            "full_name": "Тестовый Пользователь",
            "password": NEW_PASSWORD,
            "role_code": "analyst",
        }
        body.update(overrides)
        return body

    def test_uchyotnaya_zapis_sozdayotsya(
        self, api: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        body = self._body()

        response = api.post(USERS_URL, headers=admin_headers, json=body)

        assert response.status_code == 201, response.text
        assert response.json()["login"] == body["login"]
        created = db_session.scalars(select(User).where(User.login == body["login"])).one()
        assert created.password_hash != body["password"]

    def test_parol_ne_vozvrashchaetsya_i_ne_popadaet_v_zhurnal(
        self, api: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        body = self._body()

        raw = api.post(USERS_URL, headers=admin_headers, json=body).text

        assert NEW_PASSWORD not in raw
        entries = db_session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.action == AuditAction.CREATE)
        ).all()
        assert all(NEW_PASSWORD not in str(entry.details) for entry in entries)

    def test_sozdanie_zhurnaliruetsya(
        self, api: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        body = self._body()

        created = api.post(USERS_URL, headers=admin_headers, json=body).json()

        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.CREATE,
                AuditLogEntry.entity_id == created["id"],
            )
        ).one()
        assert entry.details is not None
        assert entry.details["role"] == "analyst"

    def test_korotkiy_parol_otvergaetsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.post(USERS_URL, headers=admin_headers, json=self._body(password="кор"))

        assert response.status_code == 422

    def test_zanyatyy_login_otvergaetsya(
        self, api: TestClient, admin_headers: dict[str, str], make_user: UserFactory,
        db_session: Session,
    ) -> None:
        existing = make_user(RoleCode.VIEWER)
        db_session.commit()

        response = api.post(
            USERS_URL, headers=admin_headers, json=self._body(login=existing.login)
        )

        assert response.status_code == 409

    def test_nesushchestvuyushchaya_territoriya_otvergaetsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.post(
            USERS_URL, headers=admin_headers, json=self._body(territory_id=str(uuid.uuid4()))
        )

        assert response.status_code == 400

    def test_analitik_ne_mozhet_zavodit_polzovateley(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.post(
            USERS_URL, headers=token_for(api, analyst.login), json=self._body()
        )

        assert response.status_code == 403


class TestPravkaPolzovatelya:
    def test_smena_roli(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        user = make_user(RoleCode.VIEWER)
        db_session.commit()

        response = api.patch(
            f"{USERS_URL}/{user.id}", headers=admin_headers, json={"role_code": "analyst"}
        )

        assert response.status_code == 200
        assert response.json()["role"] == "analyst"

    def test_zhurnal_khranit_bylo_i_stalo(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        """Запись «пользователя изменили» без подробностей ничего не объясняет."""
        user = make_user(RoleCode.VIEWER)
        db_session.commit()

        api.patch(
            f"{USERS_URL}/{user.id}", headers=admin_headers, json={"role_code": "manager"}
        )

        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.UPDATE,
                AuditLogEntry.entity_id == str(user.id),
            )
        ).one()
        assert entry.details is not None
        assert entry.details["changes"]["role"] == ["viewer", "manager"]

    def test_blokirovka_uchyotnoy_zapisi(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.patch(
            f"{USERS_URL}/{user.id}", headers=admin_headers, json={"is_active": False}
        )

        assert response.json()["is_active"] is False

    def test_snyatie_blokirovki_posle_neudachnykh_vkhodov(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        user.locked_until = utcnow() + timedelta(minutes=10)
        user.failed_login_attempts = 5
        db_session.commit()

        response = api.patch(
            f"{USERS_URL}/{user.id}", headers=admin_headers, json={"reset_lockout": True}
        )

        assert response.status_code == 200
        assert response.json()["is_locked"] is False
        db_session.expire_all()
        refreshed = db_session.get(User, user.id)
        assert refreshed is not None
        assert refreshed.failed_login_attempts == 0

    def test_pravka_bez_izmeneniy_ne_zasoryaet_zhurnal(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        """Журнал из пустых записей перестают читать, и он теряет смысл."""
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        api.patch(f"{USERS_URL}/{user.id}", headers=admin_headers, json={})

        entries = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.UPDATE,
                AuditLogEntry.entity_id == str(user.id),
            )
        ).all()
        assert entries == []

    def test_nesushchestvuyushchiy_polzovatel(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.patch(
            f"{USERS_URL}/{uuid.uuid4()}", headers=admin_headers, json={"is_active": False}
        )
        assert response.status_code == 404


# --- Вкладка «Справочники» ---------------------------------------------------


class TestSpravochniki:
    def test_otdayutsya_odnim_otvetom(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.get(REFERENCE_URL, headers=admin_headers)

        assert response.status_code == 200
        body = response.json()
        assert {"territories", "roles", "risk_levels", "sensitive_access_levels"} <= set(body)

    def test_roli_soderzhat_rasshifrovannye_prava(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Администратор должен понимать, что выдаёт, без чтения исходников."""
        body = api.get(REFERENCE_URL, headers=admin_headers).json()

        analyst = next(role for role in body["roles"] if role["code"] == "analyst")
        codes = {permission["code"] for permission in analyst["permissions"]}
        assert "data.import" in codes
        assert all(permission["title"] for permission in analyst["permissions"])

    def test_uroven_dostupa_k_personalnym_dannym_viden(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        body = api.get(REFERENCE_URL, headers=admin_headers).json()

        viewer = next(role for role in body["roles"] if role["code"] == "viewer")
        assert viewer["sensitive_data_access"] == "hidden"

    def test_uroven_net_dannykh_polnopravnyy(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """«Нет данных» — уровень, а не служебное состояние."""
        body = api.get(REFERENCE_URL, headers=admin_headers).json()

        codes = {level["code"] for level in body["risk_levels"]}
        assert "unknown" in codes

    def test_territorii_soderzhat_kazakhskoe_nazvanie(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        territories: dict[str, Territory],
        db_session: Session,
    ) -> None:
        db_session.commit()
        body = api.get(REFERENCE_URL, headers=admin_headers).json()

        row = next(
            item for item in body["territories"] if item["code"] == territories["karasay"].code
        )
        assert "name_kk" in row
        assert row["level"] == "district"


# --- Вкладка «Критерии риска» ------------------------------------------------


def model_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "version": "9.9-тест",
        "weights": [],
        "thresholds": [
            {"from_score": 0, "level": "low"},
            {"from_score": 25, "level": "medium"},
            {"from_score": 50, "level": "high"},
            {"from_score": 75, "level": "critical"},
        ],
        "comment": "Тестовая редакция",
    }
    body.update(overrides)
    return body


class TestKriteriiRiska:
    def test_vesa_i_porogi_otdayutsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.get(MODELS_URL, headers=admin_headers)

        assert response.status_code == 200
        models = response.json()
        assert models
        first = models[0]
        assert first["indicators"]
        assert all("weight" in indicator for indicator in first["indicators"])
        assert first["thresholds"]

    def test_pravit_mozhet_tolko_administrator(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Требование ТЗ: веса и пороги редактирует только администратор."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.put(
            f"{MODELS_URL}/8.4",
            headers=token_for(api, analyst.login),
            json=model_body(),
        )

        assert response.status_code == 403

    def test_rukovoditel_tozhe_ne_pravit(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        manager = make_user(RoleCode.MANAGER)
        db_session.commit()

        response = api.put(
            f"{MODELS_URL}/8.4", headers=token_for(api, manager.login), json=model_body()
        )

        assert response.status_code == 403

    def test_pravka_zhurnaliruetsya_otdelnym_deystviem(
        self, api: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        """RISK_MODEL_CHANGED, а не общий UPDATE: правка меняет все оценки сразу."""
        response = api.put(f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body())

        assert response.status_code == 200, response.text
        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.RISK_MODEL_CHANGED,
                AuditLogEntry.entity_id == "8.4",
            )
        ).one()
        assert entry.details is not None
        assert entry.details["version"] == "9.9-тест"
        assert entry.details["comment"] == "Тестовая редакция"

    def test_versiya_popadaet_v_istoriyu(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        api.put(f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body())

        models = api.get(MODELS_URL, headers=admin_headers).json()
        procurement = next(item for item in models if item["code"] == "8.4")

        assert procurement["version"] == "9.9-тест"
        assert procurement["base_version"] == "1.0"
        assert procurement["history"][0]["based_on"] == "1.0"

    def test_proshlye_otsenki_ne_perepisyvayutsya(
        self, api: TestClient, admin_headers: dict[str, str], db_session: Session
    ) -> None:
        """Старые оценки обязаны остаться воспроизводимыми после правки весов."""
        contract = db_session.scalars(select(Contract).limit(1)).first()
        if contract is None:
            pytest.skip("В базе нет договоров: нечего проверять на неизменность")
        before = (contract.model_version, contract.risk_score, contract.risk_level)

        api.put(f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body())

        db_session.expire_all()
        after_row = db_session.get(Contract, contract.id)
        assert after_row is not None
        assert (after_row.model_version, after_row.risk_score, after_row.risk_level) == before

    def test_ta_zhe_versiya_otvergaetsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Иначе старые оценки стали бы неотличимы от новых."""
        response = api.put(
            f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body(version="1.0")
        )

        assert response.status_code == 409

    def test_neizvestnyy_indikator_otvergaetsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.put(
            f"{MODELS_URL}/8.4",
            headers=admin_headers,
            json=model_body(weights=[{"code": "НЕТ-ТАКОГО", "weight": 1}]),
        )

        assert response.status_code == 400
        assert "НЕТ-ТАКОГО" in response.json()["detail"]

    def test_porogi_ne_po_vozrastaniyu_otvergayutsya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.put(
            f"{MODELS_URL}/8.4",
            headers=admin_headers,
            json=model_body(
                thresholds=[
                    {"from_score": 50, "level": "high"},
                    {"from_score": 25, "level": "medium"},
                ]
            ),
        )

        assert response.status_code == 400

    def test_neizvestnaya_model_dayot_404(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        response = api.put(f"{MODELS_URL}/нет-такой", headers=admin_headers, json=model_body())
        assert response.status_code == 404

    def test_dve_pravki_dayut_dve_versii(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        api.put(f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body(version="2.0"))
        api.put(f"{MODELS_URL}/8.4", headers=admin_headers, json=model_body(version="3.0"))

        models = api.get(MODELS_URL, headers=admin_headers).json()
        procurement = next(item for item in models if item["code"] == "8.4")

        assert procurement["version"] == "3.0"
        assert [item["version"] for item in procurement["history"][:2]] == ["3.0", "2.0"]
        assert procurement["history"][0]["based_on"] == "2.0"


# --- Вкладка «Журнал действий» -----------------------------------------------


class TestZhurnalDeystviy:
    def test_zapisi_otdayutsya_s_perevodom_deystviya(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Интерфейс по ТЗ русскоязычный, включая служебные разделы."""
        response = api.get(AUDIT_URL, headers=admin_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["items"]
        assert body["items"][0]["action_title"]
        assert any(item["code"] == "login_success" for item in body["actions"])

    def test_filtr_po_polzovatelyu(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        target = make_user(RoleCode.ANALYST)
        audit.record(
            AuditAction.EXPORT, session=db_session, user=target, entity_type="проверка"
        )
        db_session.commit()

        body = api.get(
            AUDIT_URL, headers=admin_headers, params={"user_login": target.login}
        ).json()

        assert body["total"] >= 1
        assert all(item["user_login"] == target.login for item in body["items"])

    def test_filtr_po_deystviyu(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        target = make_user(RoleCode.ANALYST)
        audit.record(AuditAction.REPORT_GENERATED, session=db_session, user=target)
        db_session.commit()

        body = api.get(
            AUDIT_URL, headers=admin_headers, params={"action": "report_generated"}
        ).json()

        assert body["items"]
        assert all(item["action"] == "report_generated" for item in body["items"])

    def test_filtr_po_periodu_vklyuchaet_ves_posledniy_den(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        """Граница «по 5 июля» означает конец пятого июля, а не его начало."""
        target = make_user(RoleCode.ANALYST)
        audit.record(AuditAction.EXPORT, session=db_session, user=target)
        db_session.commit()
        today = utcnow().date().isoformat()

        body = api.get(
            AUDIT_URL,
            headers=admin_headers,
            params={"user_login": target.login, "date_from": today, "date_to": today},
        ).json()

        assert body["total"] >= 1

    def test_period_v_proshlom_nichego_ne_nakhodit(
        self,
        api: TestClient,
        admin_headers: dict[str, str],
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        target = make_user(RoleCode.ANALYST)
        audit.record(AuditAction.EXPORT, session=db_session, user=target)
        db_session.commit()

        body = api.get(
            AUDIT_URL,
            headers=admin_headers,
            params={
                "user_login": target.login,
                "date_from": "2001-01-01",
                "date_to": "2001-01-02",
            },
        ).json()

        assert body["total"] == 0

    def test_stranitsy(self, api: TestClient, admin_headers: dict[str, str]) -> None:
        body = api.get(AUDIT_URL, headers=admin_headers, params={"page_size": 2}).json()

        assert len(body["items"]) <= 2
        assert body["page"] == 1
        assert body["page_size"] == 2

    def test_zhurnal_tolko_na_chtenie(
        self, api: TestClient, admin_headers: dict[str, str]
    ) -> None:
        """Журнал, который можно отредактировать, не является доказательством."""
        assert api.post(AUDIT_URL, headers=admin_headers, json={}).status_code == 405
        assert api.delete(AUDIT_URL, headers=admin_headers).status_code == 405
        assert api.put(AUDIT_URL, headers=admin_headers, json={}).status_code == 405

    def test_rukovoditel_chitaet_zhurnal(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Руководитель контролирует работу с данными — журнал ему открыт."""
        manager = make_user(RoleCode.MANAGER)
        db_session.commit()

        response = api.get(AUDIT_URL, headers=token_for(api, manager.login))

        assert response.status_code == 200

    def test_analitik_zhurnal_ne_chitaet(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        response = api.get(AUDIT_URL, headers=token_for(api, analyst.login))

        assert response.status_code == 403

    def test_otkaz_v_dostupe_sam_popadaet_v_zhurnal(
        self, api: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Серия отказов подряд — разведка периметра, и её видно только в журнале."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        api.get(AUDIT_URL, headers=token_for(api, analyst.login))

        entry = db_session.scalars(
            select(AuditLogEntry).where(
                AuditLogEntry.action == AuditAction.PERMISSION_DENIED,
                AuditLogEntry.user_id == analyst.id,
            )
        ).first()
        assert entry is not None
        assert entry.details is not None
        assert entry.details["required"] == "audit.view"


class TestRoliSootvetstvuyutTZ:
    def test_pravo_pravki_modeli_tolko_u_administratora(
        self, db_session: Session, roles: dict[str, Role]
    ) -> None:
        """Проверка исходной раскладки прав — она и делает вкладку админской."""
        for code, role in roles.items():
            granted = {permission.code for permission in role.permissions}
            assert ("risk.model.edit" in granted) == (code == "admin")
