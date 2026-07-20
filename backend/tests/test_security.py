"""Хеширование паролей и токены доступа."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.config import get_settings


class TestKheshirovaniePorolya:
    def test_ispolzuetsya_argon2id(self) -> None:
        """Именно id-вариант: он устойчив и к перебору на GPU, и к side-channel."""
        assert security.hash_password("Длинный-Пароль-42").startswith("$argon2id$")

    def test_odin_parol_dayot_raznye_kheshi(self) -> None:
        """Соль на каждый вызов — иначе радужные таблицы работают."""
        password = "Длинный-Пароль-42"
        assert security.hash_password(password) != security.hash_password(password)

    def test_parol_ne_soderzhitsya_v_kheshe(self) -> None:
        """Очевидное, но проверяемое: хеш не должен содержать исходный пароль."""
        password = "SekretnyyParol2026"
        assert password not in security.hash_password(password)

    def test_vernyy_parol_prokhodit(self) -> None:
        password = "Длинный-Пароль-42"
        assert security.verify_password(password, security.hash_password(password))

    def test_nevernyy_parol_ne_prokhodit(self) -> None:
        password_hash = security.hash_password("Длинный-Пароль-42")
        assert not security.verify_password("Длинный-Пароль-43", password_hash)

    def test_bityy_khesh_ne_ronyaet_proverku(self) -> None:
        """Мусор в колонке — это «вход не удался», а не исключение на весь запрос."""
        assert not security.verify_password("любой", "не-хеш-вовсе")

    def test_perekheshirovanie_ne_trebuetsya_svezhemu_kheshu(self) -> None:
        assert not security.password_needs_rehash(security.hash_password("Длинный-Пароль-42"))

    def test_perekheshirovanie_trebuetsya_chuzhomu_formatu(self) -> None:
        assert security.password_needs_rehash("$2b$12$устаревший-bcrypt")


class TestKholostayaProverka:
    def test_vsegda_otritsatelna(self) -> None:
        assert not security.verify_dummy_password("что угодно")

    def test_stoit_stolko_zhe_skolko_nastoyashchaya(self) -> None:
        """Ради этого она и существует: без неё несуществующий логин отвечал бы
        мгновенно, и перебор выдал бы список учётных записей."""
        password_hash = security.hash_password("Длинный-Пароль-42")

        started = time.perf_counter()
        security.verify_password("Длинный-Пароль-43", password_hash)
        real = time.perf_counter() - started

        started = time.perf_counter()
        security.verify_dummy_password("Длинный-Пароль-43")
        dummy = time.perf_counter() - started

        # Границы широкие: на общей машине разброс велик, а поймать нужно
        # разницу на порядки — именно она измерима снаружи.
        assert 0.2 < dummy / real < 5.0


class TestPolitikaParolya:
    def test_korotkiy_parol_otklonyaetsya(self) -> None:
        minimum = get_settings().password_min_length
        with pytest.raises(security.PasswordPolicyError):
            security.validate_password("x" * (minimum - 1))

    def test_parol_minimalnoy_dliny_prinimaetsya(self) -> None:
        security.validate_password("x" * get_settings().password_min_length)

    def test_soobshchenie_ob_oshibke_ne_soderzhit_parol(self) -> None:
        """Текст ошибки уходит в ответ и в лог — пароля в нём быть не может."""
        secret = "kk" * 3
        with pytest.raises(security.PasswordPolicyError) as info:
            security.validate_password(secret)
        assert secret not in str(info.value)

    def test_sgenerirovannyy_parol_udovletvoryaet_politike(self) -> None:
        security.validate_password(security.generate_password())

    def test_sgenerirovannye_paroli_raznye(self) -> None:
        assert security.generate_password() != security.generate_password()

    def test_dlina_ne_menshe_minimalnoy_dazhe_esli_poprosili_menshe(self) -> None:
        minimum = get_settings().password_min_length
        assert len(security.generate_password(4)) >= minimum


class TestTokenDostupa:
    def test_soderzhimoe_vozvrashchaetsya_obratno(self) -> None:
        user_id = uuid.uuid4()
        token, _ = security.create_access_token(user_id=user_id, login="analyst", role="analyst")

        payload = security.decode_access_token(token)

        assert payload.subject == user_id
        assert payload.login == "analyst"
        assert payload.role == "analyst"

    def test_srok_zhizni_beryotsya_iz_nastroek(self) -> None:
        ttl = get_settings().access_token_ttl_minutes
        _, payload = security.create_access_token(
            user_id=uuid.uuid4(), login="analyst", role="analyst"
        )
        ozhidaemo = payload.issued_at + timedelta(minutes=ttl)
        assert abs((payload.expires_at - ozhidaemo).total_seconds()) < 2

    def test_kazhdyy_token_imeet_svoy_identifikator(self) -> None:
        """Без `jti` выход не отзывал бы конкретный токен."""
        _, first = security.create_access_token(user_id=uuid.uuid4(), login="a", role="admin")
        _, second = security.create_access_token(user_id=uuid.uuid4(), login="a", role="admin")
        assert first.token_id != second.token_id

    def test_istyokshiy_token_otvergaetsya(self) -> None:
        token, _ = security.create_access_token(
            user_id=uuid.uuid4(), login="analyst", role="analyst", ttl_minutes=-1
        )
        with pytest.raises(security.TokenExpiredError):
            security.decode_access_token(token)

    def test_poddelannyy_token_otvergaetsya(self) -> None:
        """Меняем один знак подписи — токен обязан перестать приниматься."""
        token, _ = security.create_access_token(
            user_id=uuid.uuid4(), login="analyst", role="analyst"
        )
        head, _, signature = token.rpartition(".")
        podmena = "A" if signature[0] != "A" else "B"
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(f"{head}.{podmena}{signature[1:]}")

    def test_izmenyonnaya_nagruzka_otvergaetsya(self) -> None:
        """Повышение роли правкой тела токена не проходит: подпись не сойдётся."""
        token, _ = security.create_access_token(
            user_id=uuid.uuid4(), login="viewer", role="viewer"
        )
        chuzhoy = jwt.encode(
            {
                **jwt.decode(token, options={"verify_signature": False}),
                "role": "admin",
            },
            "не тот секрет",
            algorithm="HS256",
        )
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(chuzhoy)

    def test_token_podpisannyy_chuzhim_sekretom_otvergaetsya(self) -> None:
        chuzhoy = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "jti": uuid.uuid4().hex,
                "iat": int(datetime.now(tz=UTC).timestamp()),
                "exp": int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp()),
            },
            "секрет-злоумышленника",
            algorithm="HS256",
        )
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(chuzhoy)

    def test_token_bez_podpisi_otvergaetsya(self) -> None:
        """Классическая атака `alg: none`. Список алгоритмов задан явно."""
        bez_podpisi = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "jti": uuid.uuid4().hex,
                "iat": int(datetime.now(tz=UTC).timestamp()),
                "exp": int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp()),
            },
            key="",
            algorithm="none",
        )
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(bez_podpisi)

    def test_musor_vmesto_tokena_otvergaetsya(self) -> None:
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token("совсем.не.токен")

    def test_token_bez_obyazatelnykh_poley_otvergaetsya(self) -> None:
        settings = get_settings()
        nepolnyy = jwt.encode(
            {"sub": str(uuid.uuid4())},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(nepolnyy)


class TestOtzyvTokenov:
    def setup_method(self) -> None:
        security.clear_revoked_tokens()

    def teardown_method(self) -> None:
        security.clear_revoked_tokens()

    def test_otozvannyy_token_bolshe_ne_prinimaetsya(self) -> None:
        token, payload = security.create_access_token(
            user_id=uuid.uuid4(), login="analyst", role="analyst"
        )
        assert security.decode_access_token(token).login == "analyst"

        security.revoke_token(payload)

        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(token)

    def test_otzyv_ne_zatragivaet_drugie_tokeny(self) -> None:
        first_token, first_payload = security.create_access_token(
            user_id=uuid.uuid4(), login="a", role="admin"
        )
        second_token, _ = security.create_access_token(
            user_id=uuid.uuid4(), login="b", role="admin"
        )

        security.revoke_token(first_payload)

        assert security.decode_access_token(second_token).login == "b"
        with pytest.raises(security.InvalidTokenError):
            security.decode_access_token(first_token)

    def test_spisok_ne_khranit_istyokshie_zapisi(self) -> None:
        """Иначе список отозванных токенов растёт неограниченно."""
        denylist = security.TokenDenylist()
        denylist.revoke("staryy", datetime.now(tz=UTC) - timedelta(seconds=1))
        assert not denylist.is_revoked("staryy")
