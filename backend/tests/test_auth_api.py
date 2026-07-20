"""Вход, выход, журнал действий и защита маршрутов."""

from __future__ import annotations

import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models.access import AuditAction, AuditLogEntry, RoleCode, User
from app.services import audit
from app.services.audit import RequestContext
from tests.conftest import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.integration

LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"


def _zapisi(session: Session, user_id: uuid.UUID, action: AuditAction) -> list[AuditLogEntry]:
    return list(
        session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.user_id == user_id)
            .where(AuditLogEntry.action == action)
        )
        .scalars()
        .all()
    )


class TestUspeshnyyVkhod:
    def test_vydayotsya_token_i_profil(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": analyst.login, "password": TEST_PASSWORD})

        assert otvet.status_code == 200
        telo = otvet.json()
        assert telo["token_type"] == "bearer"
        assert telo["user"]["login"] == analyst.login
        assert telo["user"]["role"] == "analyst"
        assert "data.import" in telo["user"]["permissions"]

    def test_srok_zhizni_tokena_iz_nastroek(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        telo = client.post(
            LOGIN_URL, json={"login": analyst.login, "password": TEST_PASSWORD}
        ).json()

        ozhidaemo = get_settings().access_token_ttl_minutes * 60
        assert abs(telo["expires_in"] - ozhidaemo) < 10

    def test_v_otvete_net_ni_parolya_ni_khesha(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Главная проверка на утечку: в ответе не должно быть ни того, ни другого."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        syroy_otvet = client.post(
            LOGIN_URL, json={"login": analyst.login, "password": TEST_PASSWORD}
        ).text

        assert TEST_PASSWORD not in syroy_otvet
        assert "password" not in syroy_otvet
        assert analyst.password_hash not in syroy_otvet
        assert "argon2" not in syroy_otvet

    def test_vkhod_pishetsya_v_zhurnal(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        # Значения заголовков — только ASCII: этого требует HTTP, и httpx
        # отвергает кириллицу ещё до отправки запроса.
        client.post(
            LOGIN_URL,
            json={"login": analyst.login, "password": TEST_PASSWORD},
            headers={"X-Request-ID": "vkhod-1", "User-Agent": "TestBrowser/1.0"},
        )

        zapisi = _zapisi(db_session, analyst.id, AuditAction.LOGIN_SUCCESS)
        assert len(zapisi) == 1
        assert zapisi[0].request_id == "vkhod-1"
        assert zapisi[0].user_agent == "TestBrowser/1.0"

    def test_login_khranitsya_strokoy(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Удаление учётной записи не должно обезличивать историю её действий."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        client.post(LOGIN_URL, json={"login": analyst.login, "password": TEST_PASSWORD})

        zapis = _zapisi(db_session, analyst.id, AuditAction.LOGIN_SUCCESS)[0]

        assert zapis.user_login == analyst.login

    def test_parol_ne_popadaet_v_zhurnal(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()

        client.post(LOGIN_URL, json={"login": analyst.login, "password": TEST_PASSWORD})
        client.post(LOGIN_URL, json={"login": analyst.login, "password": "не тот пароль"})

        vse = db_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.user_id == analyst.id)
        ).scalars()
        for zapis in vse:
            assert TEST_PASSWORD not in str(zapis.details)
            assert "не тот пароль" not in str(zapis.details)

    def test_schyotchik_neudach_sbrasyvaetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        user.failed_login_attempts = 2
        db_session.commit()

        client.post(LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD})

        db_session.refresh(user)
        assert user.failed_login_attempts == 0
        assert user.last_login_at is not None


class TestNeudachnyyVkhod:
    def test_nevernyy_parol_otklonyaetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        assert otvet.status_code == 401
        assert otvet.json()["detail"] == "Неверный логин или пароль"

    def test_neudacha_pishetsya_v_zhurnal_s_prichinoy(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        zapisi = _zapisi(db_session, user.id, AuditAction.LOGIN_FAILURE)
        assert len(zapisi) == 1
        assert zapisi[0].details is not None
        assert zapisi[0].details["reason"] == "bad_password"

    def test_nesushchestvuyushchiy_login_dayot_tot_zhe_otvet(self, client: TestClient) -> None:
        """Различающийся ответ превратил бы форму входа в справочник логинов."""
        otvet = client.post(LOGIN_URL, json={"login": "нет-такого", "password": "Пароль-12345"})

        assert otvet.status_code == 401
        assert otvet.json()["detail"] == "Неверный логин или пароль"

    def test_nesushchestvuyushchiy_login_tozhe_zhurnaliruetsya(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Событие, которого стоит бояться: пользователя нет, а логин — есть."""
        client.post(LOGIN_URL, json={"login": "чужой.логин", "password": "Пароль-12345"})

        zapis = db_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.user_login == "чужой.логин")
        ).scalar_one()
        assert zapis.action == AuditAction.LOGIN_FAILURE
        assert zapis.user_id is None
        assert zapis.details is not None
        assert zapis.details["reason"] == "unknown_login"

    def test_vyklyuchennaya_uchyotnaya_zapis_ne_puskaetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST, is_active=False)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD})

        assert otvet.status_code == 401
        zapisi = _zapisi(db_session, user.id, AuditAction.LOGIN_FAILURE)
        assert zapisi[0].details is not None
        assert zapisi[0].details["reason"] == "inactive"

    def test_proverka_parolya_vypolnyaetsya_i_dlya_neizvestnogo_logina(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Без холостой проверки несуществующий логин отвечал бы заметно быстрее.

        Проверяется детерминированно — фактом вызова, а не секундомером:
        измерение времени на общей машине само по себе доказательством не является.
        """
        vyzovy: list[str] = []
        nastoyashchaya = security.verify_dummy_password

        def shpion(password: str) -> bool:
            vyzovy.append("холостая проверка")
            return nastoyashchaya(password)

        monkeypatch.setattr("app.api.auth_routes.security.verify_dummy_password", shpion)

        client.post(LOGIN_URL, json={"login": "нет-такого", "password": "Пароль-12345"})

        assert vyzovy == ["холостая проверка"]

    @pytest.mark.slow
    def test_vremya_otveta_sopostavimo(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Секундомером — грубо, но именно так атакующий и перебирает логины."""
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        def zamer(login: str) -> float:
            zamery = []
            for _ in range(3):
                nachalo = time.perf_counter()
                client.post(LOGIN_URL, json={"login": login, "password": "Неверный-Пароль1"})
                zamery.append(time.perf_counter() - nachalo)
            return statistics.median(zamery)

        sushchestvuyushchiy = zamer(user.login)
        nesushchestvuyushchiy = zamer("нет-такого-логина")

        # Ловим разницу на порядки — она и видна снаружи. Узкие границы здесь
        # означали бы мигающий тест, а не более строгую проверку.
        assert 0.2 < nesushchestvuyushchiy / sushchestvuyushchiy < 5.0


class TestBlokirovka:
    def test_blokirovka_posle_serii_neudach(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        nastroyki = get_settings()
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        for _ in range(nastroyki.login_max_attempts):
            client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        db_session.refresh(user)
        assert user.failed_login_attempts == nastroyki.login_max_attempts
        assert user.locked_until is not None

    def test_srok_blokirovki_iz_nastroek(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        nastroyki = get_settings()
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        for _ in range(nastroyki.login_max_attempts):
            client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        db_session.refresh(user)
        assert user.locked_until is not None
        ostalos = (user.locked_until - datetime.now(tz=UTC)).total_seconds() / 60
        assert nastroyki.login_lockout_minutes - 1 < ostalos <= nastroyki.login_lockout_minutes

    def test_do_poslednej_popytki_blokirovki_net(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Блокировка наступает на N-й неудаче, а не раньше."""
        nastroyki = get_settings()
        user = make_user(RoleCode.ANALYST)
        db_session.commit()

        for _ in range(nastroyki.login_max_attempts - 1):
            client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        db_session.refresh(user)
        assert user.locked_until is None

    def test_zablokirovannyy_ne_vkhodit_dazhe_s_vernym_parolem(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        user.locked_until = utcnow() + timedelta(minutes=10)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD})

        assert otvet.status_code == 423
        assert "Retry-After" in otvet.headers

    def test_zablokirovannomu_s_nevernym_parolem_o_blokirovke_ne_soobshchayut(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Иначе перебор паролей заодно подтверждал бы существование логина."""
        user = make_user(RoleCode.ANALYST)
        user.locked_until = utcnow() + timedelta(minutes=10)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": user.login, "password": "Неверный-Пароль1"})

        assert otvet.status_code == 401
        assert otvet.json()["detail"] == "Неверный логин или пароль"

    def test_popytka_pri_blokirovke_zhurnaliruetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        user.locked_until = utcnow() + timedelta(minutes=10)
        db_session.commit()

        client.post(LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD})

        zapisi = _zapisi(db_session, user.id, AuditAction.LOGIN_FAILURE)
        assert zapisi[0].details is not None
        assert zapisi[0].details["reason"] == "locked"

    def test_istyokshaya_blokirovka_ne_meshaet(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ANALYST)
        user.locked_until = utcnow() - timedelta(minutes=1)
        db_session.commit()

        otvet = client.post(LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD})

        assert otvet.status_code == 200


class TestTekushchiyPolzovatel:
    def _voyti(self, client: TestClient, login: str) -> str:
        otvet = client.post(LOGIN_URL, json={"login": login, "password": TEST_PASSWORD})
        assert otvet.status_code == 200, otvet.text
        return str(otvet.json()["access_token"])

    def test_profil_otdayotsya_po_tokenu(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)

        otvet = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 200
        assert otvet.json()["login"] == analyst.login
        assert otvet.json()["sensitive_data_access"] == "masked"

    def test_v_profile_net_khesha_parolya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)

        syroy = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).text

        assert "argon2" not in syroy
        assert TEST_PASSWORD not in syroy

    def test_bez_tokena_ne_otdayotsya(self, client: TestClient) -> None:
        assert client.get(ME_URL).status_code == 401

    def test_musornyy_token_otvergaetsya(self, client: TestClient) -> None:
        otvet = client.get(ME_URL, headers={"Authorization": "Bearer sovsem.ne.token"})
        assert otvet.status_code == 401

    def test_poddelannyy_token_otvergaetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)
        head, _, signature = token.rpartition(".")
        podmena = "A" if signature[0] != "A" else "B"

        otvet = client.get(
            ME_URL, headers={"Authorization": f"Bearer {head}.{podmena}{signature[1:]}"}
        )

        assert otvet.status_code == 401

    def test_istyokshiy_token_otvergaetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token, _ = security.create_access_token(
            user_id=analyst.id, login=analyst.login, role="analyst", ttl_minutes=-1
        )

        otvet = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 401

    def test_token_udalyonnogo_polzovatelya_otvergaetsya(self, client: TestClient) -> None:
        """Токен подписан нами, но учётной записи уже нет."""
        token, _ = security.create_access_token(
            user_id=uuid.uuid4(), login="призрак", role="admin"
        )

        otvet = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 401

    def test_vyklyuchennyy_polzovatel_teryaet_dostup_srazu(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Права проверяются по базе, а не по токену: выключение действует немедленно."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)
        assert client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 200

        analyst.is_active = False
        db_session.commit()

        otvet = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 401


class TestVykhod:
    def _voyti(self, client: TestClient, login: str) -> str:
        otvet = client.post(LOGIN_URL, json={"login": login, "password": TEST_PASSWORD})
        assert otvet.status_code == 200, otvet.text
        return str(otvet.json()["access_token"])

    def test_vykhod_zhurnaliruetsya(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)

        otvet = client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 200
        assert len(_zapisi(db_session, analyst.id, AuditAction.LOGOUT)) == 1

    def test_posle_vykhoda_token_ne_rabotaet(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        """Выход, ограниченный забыванием токена на клиенте, ничего не защищает."""
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = self._voyti(client, analyst.login)
        client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {token}"})

        otvet = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})

        assert otvet.status_code == 401

    def test_vykhod_ne_zatragivaet_drugie_sessii(
        self, client: TestClient, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)
        db_session.commit()
        pervyy = self._voyti(client, analyst.login)
        vtoroy = self._voyti(client, analyst.login)

        client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {pervyy}"})

        assert client.get(ME_URL, headers={"Authorization": f"Bearer {vtoroy}"}).status_code == 200

    def test_vykhod_bez_tokena_ne_proydyot(self, client: TestClient) -> None:
        assert client.post(LOGOUT_URL).status_code == 401


class TestZhurnalPokryvaetVseDeystviya:
    """ТЗ перечисляет события, которые обязаны попадать в журнал."""

    @pytest.mark.parametrize(
        "action",
        [
            AuditAction.CREATE,
            AuditAction.UPDATE,
            AuditAction.DELETE,
            AuditAction.IMPORT_STARTED,
            AuditAction.IMPORT_FINISHED,
            AuditAction.IMPORT_ROLLED_BACK,
            AuditAction.EXPORT,
            AuditAction.REPORT_GENERATED,
            AuditAction.RISK_MODEL_CHANGED,
            AuditAction.SENSITIVE_VIEW,
            AuditAction.PERMISSION_DENIED,
            AuditAction.LOGIN_SUCCESS,
            AuditAction.LOGIN_FAILURE,
            AuditAction.LOGOUT,
        ],
    )
    def test_lyuboe_perechislennoe_deystvie_zapisyvaetsya(
        self,
        action: AuditAction,
        db_session: Session,
        make_user: UserFactory,
    ) -> None:
        user = make_user(RoleCode.ADMIN)

        audit.record(
            action,
            session=db_session,
            user=user,
            entity_type="проверка",
            entity_id="1",
            context=RequestContext(request_id="r-1", ip_address="127.0.0.1", user_agent="тест"),
        )

        zapisi = _zapisi(db_session, user.id, action)
        assert len(zapisi) == 1
        assert zapisi[0].user_login == user.login
        assert zapisi[0].request_id == "r-1"

    def test_pravka_vesov_riska_otdelnoe_sobytie(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Правка весов меняет все оценки сразу и потому журналируется отдельно."""
        admin = make_user(RoleCode.ADMIN)

        audit.record(
            AuditAction.RISK_MODEL_CHANGED,
            session=db_session,
            user=admin,
            entity_type="risk_model",
            details={"weight_before": 0.3, "weight_after": 0.5, "layer": "8.4"},
        )

        zapis = _zapisi(db_session, admin.id, AuditAction.RISK_MODEL_CHANGED)[0]
        assert zapis.details is not None
        assert zapis.details["weight_after"] == 0.5


class TestZhurnalNeKhranitLishnego:
    def test_parol_iz_podrobnostey_vychishchaetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Опечатка вызывающего кода не должна оборачиваться утечкой в журнал."""
        admin = make_user(RoleCode.ADMIN)

        audit.record(
            AuditAction.UPDATE,
            session=db_session,
            user=admin,
            details={"password": "СекретныйПароль1", "new_password": "Другой2", "login": "ivanov"},
        )

        zapis = _zapisi(db_session, admin.id, AuditAction.UPDATE)[0]
        assert zapis.details is not None
        assert zapis.details["password"] == "[скрыто]"
        assert zapis.details["new_password"] == "[скрыто]"
        assert zapis.details["login"] == "ivanov"

    def test_personalnye_dannye_iz_podrobnostey_vychishchayutsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)

        audit.record(
            AuditAction.EXPORT,
            session=db_session,
            user=admin,
            details={"recipient_iin": "840712300112", "bin": "081040008218", "rows": 10},
        )

        zapis = _zapisi(db_session, admin.id, AuditAction.EXPORT)[0]
        assert zapis.details is not None
        assert zapis.details["recipient_iin"] == "[скрыто]"
        assert zapis.details["bin"] == "[скрыто]"
        assert zapis.details["rows"] == 10

    def test_vlozhennye_struktury_tozhe_chistyatsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)

        audit.record(
            AuditAction.UPDATE,
            session=db_session,
            user=admin,
            details={"было": {"iin": "840712300112"}, "стало": [{"token": "abc"}]},
        )

        zapis = _zapisi(db_session, admin.id, AuditAction.UPDATE)[0]
        assert "840712300112" not in str(zapis.details)
        assert "abc" not in str(zapis.details)

    def test_nekorrektnyy_ip_ne_ronyaet_zapis(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """За прокси в заголовке приходит что угодно; колонка INET этого не примет."""
        admin = make_user(RoleCode.ADMIN)

        audit.record(
            AuditAction.EXPORT,
            session=db_session,
            user=admin,
            context=RequestContext(ip_address="testclient"),
        )

        zapis = _zapisi(db_session, admin.id, AuditAction.EXPORT)[0]
        assert zapis.ip_address is None


class TestZapisZhurnalaPerezhivaetOtkat:
    def test_sobytie_v_svoey_tranzaktsii_ne_teryaetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Самое интересное для расследования происходит в ветках с ошибкой.

        Событие, записанное без переданной сессии, идёт в собственной
        транзакции и потому переживает откат транзакции запроса.
        """
        admin = make_user(RoleCode.ADMIN)
        db_session.commit()

        audit.record(AuditAction.PERMISSION_DENIED, user=admin, details={"required": "export.data"})

        nayden = db_session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.user_id == admin.id)
            .where(AuditLogEntry.action == AuditAction.PERMISSION_DENIED)
        ).scalar_one()
        assert nayden.user_login == admin.login


class TestBazaIstochnikIstiny:
    def test_ponizhenie_roli_deystvuet_bez_perevypuska_tokena(
        self,
        client: TestClient,
        db_session: Session,
        make_user: UserFactory,
        roles: dict[str, object],
    ) -> None:
        """Права берутся из базы на каждый запрос, а не из выданного токена."""
        user = make_user(RoleCode.ANALYST)
        db_session.commit()
        token = client.post(
            LOGIN_URL, json={"login": user.login, "password": TEST_PASSWORD}
        ).json()["access_token"]

        do = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).json()
        assert "data.import" in do["permissions"]

        zapis = db_session.execute(select(User).where(User.id == user.id)).scalar_one()
        zapis.role_id = roles["viewer"].id  # type: ignore[attr-defined]
        db_session.commit()
        # В рабочем режиме каждый запрос получает свою сессию и видит базу
        # заново. Здесь приложение делит сессию с тестом, поэтому объект нужно
        # признать устаревшим вручную — иначе проверялся бы кэш, а не база.
        db_session.expire_all()

        posle = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"}).json()

        assert posle["role"] == "viewer"
        assert "data.import" not in posle["permissions"]
