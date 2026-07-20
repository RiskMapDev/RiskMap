"""Пароли и токены доступа.

Два решения определили содержимое этого модуля.

**Argon2id, а не bcrypt и тем более не SHA.** Argon2id устойчив и к GPU-перебору
(за счёт памяти), и к атакам по побочным каналам — это победитель Password
Hashing Competition и рекомендация OWASP. Параметры заданы явно и хранятся
внутри самой строки хеша, поэтому их можно ужесточить позже, не ломая уже
выданные учётные записи: `needs_rehash` покажет, какие хеши устарели.

**Пароль в открытом виде не покидает этот модуль.** Он не пишется в логи, не
попадает в `repr`, не возвращается в ответах API и не сохраняется ни в одном
поле. Единственное, что уходит наружу, — строка хеша.

Отдельного внимания стоит `verify_dummy_password`. Без неё вход с несуществующим
логином отвечал бы мгновенно, а с существующим — через десятки миллисекунд,
которые тратит Argon2. Разница видна по секундомеру, и перебором логинов
злоумышленник получил бы список учётных записей ещё до подбора паролей. Поэтому
на несуществующем логине мы всё равно проверяем пароль — против заведомо чужого
хеша.
"""

from __future__ import annotations

import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Final

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# Параметры Argon2id. Ориентир — рекомендация OWASP (19 МиБ памяти, 2 прохода):
# память здесь важнее числа проходов, потому что именно она обесценивает
# перебор на видеокартах. Значения заданы константами, а не берутся из
# настроек: изменение параметров должно быть осознанным решением с
# перехешированием, а не побочным эффектом правки переменной окружения.
_TIME_COST: Final = 3
_MEMORY_COST_KIB: Final = 64 * 1024
_PARALLELISM: Final = 4
_HASH_LEN: Final = 32
_SALT_LEN: Final = 16

_hasher: Final = PasswordHasher(
    time_cost=_TIME_COST,
    memory_cost=_MEMORY_COST_KIB,
    parallelism=_PARALLELISM,
    hash_len=_HASH_LEN,
    salt_len=_SALT_LEN,
    type=Type.ID,
)

# Алфавит для генерации паролей. Похожие друг на друга символы (0/O, 1/l/I)
# исключены: пароли из seed-скрипта людям придётся переписывать глазами, и
# неразличимые знаки превращаются в поток обращений в поддержку.
_PASSWORD_ALPHABET: Final = (
    "".join(c for c in string.ascii_letters if c not in "lIO")
    + "".join(c for c in string.digits if c not in "01")
    + "!@#$%^&*-_=+?"
)


class PasswordPolicyError(ValueError):
    """Пароль не удовлетворяет политике.

    Наследуется от `ValueError`, потому что это ошибка значения, а не сбой:
    вызывающий код обязан её обработать и показать пользователю причину.
    """


def hash_password(password: str) -> str:
    """Захешировать пароль Argon2id.

    Соль генерируется библиотекой на каждый вызов, поэтому один и тот же пароль
    даёт разные хеши — радужные таблицы против такой схемы бесполезны.
    """
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Проверить пароль. Возвращает результат, а не бросает исключение.

    Все исключения argon2 сведены к `False` намеренно: битый хеш в базе и
    неверный пароль для вызывающего кода — одно и то же событие «вход не
    удался». Различать их в ответе API нельзя, иначе ответ начнёт рассказывать
    о состоянии учётной записи.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Хеш заведомо недоступного пароля — эталон стоимости проверки.

    Считается один раз за процесс и от случайного значения: если бы здесь была
    константа, её хеш можно было бы узнать по исходникам и отличить «пустую»
    проверку от настоящей по содержимому памяти.
    """
    return hash_password(secrets.token_urlsafe(32))


def verify_dummy_password(password: str) -> bool:
    """Потратить столько же времени, сколько заняла бы настоящая проверка.

    Вызывается там, где пользователя с таким логином нет. Всегда возвращает
    `False`; результат возвращается, а не игнорируется, чтобы вызов не выглядел
    мёртвым кодом и не был вырезан при рефакторинге.
    """
    return verify_password(password, _dummy_hash())


def password_needs_rehash(password_hash: str) -> bool:
    """Нужно ли перехешировать пароль под текущие параметры Argon2id."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        # Нераспознанный хеш — точно устаревший формат, его надо заменить.
        return True


def validate_password(password: str) -> None:
    """Проверить пароль на соответствие политике.

    Проверяется только длина из настроек: требования вида «одна заглавная и
    один спецсимвол» повышают предсказуемость паролей (пользователь дописывает
    «A1!» в конец) и по действующим рекомендациям NIST не применяются. Длина же
    работает всегда.

    Сам пароль ни в сообщении об ошибке, ни в логе не появляется.
    """
    minimum = get_settings().password_min_length
    if len(password) < minimum:
        raise PasswordPolicyError(f"Пароль короче минимальной длины: требуется {minimum} символов")


def generate_password(length: int | None = None) -> str:
    """Сгенерировать стойкий пароль.

    Используется seed-скриптом. Пароли демо-учётных записей не зашиты в код
    именно поэтому: одинаковый пароль во всех развёртываниях — это уязвимость,
    которая переживает и демонстрацию, и приёмку.
    """
    minimum = get_settings().password_min_length
    size = max(length or minimum, minimum)
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(size))


class TokenError(Exception):
    """Токен не принят."""


class TokenExpiredError(TokenError):
    """Срок жизни токена истёк."""


class InvalidTokenError(TokenError):
    """Подпись не сходится, структура не та или токен отозван."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Разобранное содержимое токена доступа.

    Роль и логин продублированы в токене ради экономии обращений к базе на
    вспомогательных проверках. Источником истины они не являются: права
    считаются из базы на каждый запрос, иначе выданный вчера токен носил бы
    вчерашние полномочия и после понижения роли.
    """

    subject: uuid.UUID
    login: str
    role: str
    token_id: str
    issued_at: datetime
    expires_at: datetime

    @property
    def expires_in_seconds(self) -> int:
        return max(0, int((self.expires_at - datetime.now(tz=UTC)).total_seconds()))


def create_access_token(
    *,
    user_id: uuid.UUID,
    login: str,
    role: str,
    ttl_minutes: int | None = None,
) -> tuple[str, TokenPayload]:
    """Выпустить токен доступа.

    Срок жизни берётся из настроек: ТЗ требует ограниченного времени сессии, и
    зашитая в код константа сделала бы это требование ненастраиваемым.

    `jti` нужен, чтобы конкретный токен можно было отозвать при выходе. Без него
    logout остаётся жестом вежливости: токен, лежащий у клиента, продолжал бы
    работать до истечения срока.
    """
    settings = get_settings()
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(minutes=ttl_minutes or settings.access_token_ttl_minutes)
    token_id = uuid.uuid4().hex

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "login": login,
        "role": role,
        "jti": token_id,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    payload = TokenPayload(
        subject=user_id,
        login=login,
        role=role,
        token_id=token_id,
        issued_at=now,
        expires_at=expires_at,
    )
    return token, payload


def decode_access_token(token: str) -> TokenPayload:
    """Проверить подпись и срок, вернуть содержимое.

    Список алгоритмов задан явно одним значением. Это защита от подмены
    алгоритма: библиотека, которой разрешено «доверять полю `alg`», примет
    токен с `alg: none` или подписанный публичным ключом как HMAC-секретом.
    """
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Срок действия токена истёк") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Токен не прошёл проверку") from exc

    try:
        subject = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("В токене нет корректного идентификатора пользователя") from exc

    token_id = str(claims["jti"])
    if is_token_revoked(token_id):
        raise InvalidTokenError("Токен отозван")

    return TokenPayload(
        subject=subject,
        login=str(claims.get("login", "")),
        role=str(claims.get("role", "")),
        token_id=token_id,
        issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
        expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
    )


class TokenDenylist:
    """Отозванные токены.

    Хранение в памяти процесса — сознательное упрощение уровня одного
    экземпляра приложения, и оно честно ограничено: при нескольких воркерах
    список должен переехать в общее хранилище (Redis), иначе выход,
    обработанный одним процессом, не будет виден остальным.

    Записи держатся до истечения срока токена и не дольше: после `exp` токен
    отвергается проверкой подписи, и помнить о нём незачем — иначе список
    растёт неограниченно и сам становится проблемой.
    """

    def __init__(self) -> None:
        self._revoked: dict[str, datetime] = {}

    def revoke(self, token_id: str, expires_at: datetime) -> None:
        self._purge()
        self._revoked[token_id] = expires_at

    def is_revoked(self, token_id: str) -> bool:
        self._purge()
        return token_id in self._revoked

    def clear(self) -> None:
        """Полная очистка. Нужна тестам, чтобы не протекать между случаями."""
        self._revoked.clear()

    def _purge(self) -> None:
        now = datetime.now(tz=UTC)
        expired = [key for key, moment in self._revoked.items() if moment <= now]
        for key in expired:
            del self._revoked[key]


_denylist: Final = TokenDenylist()


def revoke_token(payload: TokenPayload) -> None:
    """Отозвать токен — вызывается при выходе."""
    _denylist.revoke(payload.token_id, payload.expires_at)


def is_token_revoked(token_id: str) -> bool:
    return _denylist.is_revoked(token_id)


def clear_revoked_tokens() -> None:
    _denylist.clear()


__all__ = [
    "InvalidTokenError",
    "PasswordPolicyError",
    "TokenDenylist",
    "TokenError",
    "TokenExpiredError",
    "TokenPayload",
    "clear_revoked_tokens",
    "create_access_token",
    "decode_access_token",
    "generate_password",
    "hash_password",
    "is_token_revoked",
    "password_needs_rehash",
    "revoke_token",
    "validate_password",
    "verify_dummy_password",
    "verify_password",
]
