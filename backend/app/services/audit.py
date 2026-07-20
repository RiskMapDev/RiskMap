"""Запись в журнал действий.

Журнал в этой системе — не отладочный лог, а свидетельство. Из этого следуют
три правила, реализованные здесь.

**Логин пишется строкой.** Ссылка на пользователя может обнулиться при удалении
учётной записи (`ON DELETE SET NULL`), и без дублирующей строки история
действий обезличилась бы ровно в тот момент, когда она нужнее всего.

**Персональные данные в журнал не попадают.** Запись фиксирует *факт*
обращения к ИИН, а не сам ИИН. Иначе журнал сам становится хранилищем
персональных данных — с теми же требованиями к защите и с гораздо более
широким кругом читателей. Санитайзер `_sanitize` вычищает опасные ключи из
`details` принудительно: полагаться на аккуратность вызывающего кода в вопросе,
где ошибка означает утечку, нельзя.

**Событие пишется даже тогда, когда запрос провалился.** Неудачный вход, отказ
в доступе, откат импорта — самое интересное для расследования происходит в
ветках с ошибкой. Поэтому `record` умеет писать в собственной транзакции,
не связанной с транзакцией запроса, которую вот-вот откатят.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models.access import AuditAction, AuditLogEntry, User
from app.db.session import get_session_factory

logger = logging.getLogger("riskmap.audit")

# Ключи, значения которых не должны оказаться в журнале ни при каких условиях.
# Список закрывает две категории: секреты (пароли, токены) и персональные
# данные (ИИН, БИН, дата рождения). Проверка идёт по вхождению подстроки,
# поэтому «new_password», «password_confirm» и «recipient_iin» тоже отсекаются.
_FORBIDDEN_DETAIL_KEYS: Final = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "iin",
    "bin",
    "birth_date",
    "birthdate",
)

_REDACTED: Final = "[скрыто]"

# Ограничение глубины разбора `details`. Защищает от рекурсивных структур и от
# того, что санитайзер станет самой дорогой частью обработки запроса.
_MAX_DEPTH: Final = 6


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Обстоятельства запроса, попадающие в запись журнала.

    Собирается на уровне API и передаётся вниз явным параметром. Альтернатива —
    хранить контекст в contextvars — избавляет от параметра, но делает
    невозможным написать тест, не поднимая запрос целиком, и прячет зависимость
    сервиса от HTTP-слоя.
    """

    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    @property
    def normalized_ip(self) -> str | None:
        """IP в виде, пригодном для колонки INET.

        Postgres отвергнет запись, если в INET положить не адрес. А положить
        туда можно что угодно: за прокси в `X-Forwarded-For` приходит
        произвольная строка от клиента, да и `TestClient` подставляет
        «testclient». Непарсящееся значение отбрасывается — потерять IP лучше,
        чем потерять из-за него всю запись журнала.
        """
        if not self.ip_address:
            return None
        try:
            return str(ipaddress.ip_address(self.ip_address))
        except ValueError:
            return None


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Рекурсивно вычистить из `details` секреты и персональные данные."""
    if depth > _MAX_DEPTH:
        return _REDACTED

    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered = key.casefold()
            if any(marker in lowered for marker in _FORBIDDEN_DETAIL_KEYS):
                cleaned[key] = _REDACTED
            else:
                cleaned[key] = _sanitize(raw_value, depth + 1)
        return cleaned

    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in value]

    if isinstance(value, uuid.UUID):
        return str(value)

    return value


def sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Публичная обёртка над санитайзером — вынесена ради тестов."""
    if details is None:
        return None
    result: dict[str, Any] = _sanitize(details)
    return result


def record(
    action: AuditAction,
    *,
    session: Session | None = None,
    user: User | None = None,
    user_login: str | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    context: RequestContext | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditLogEntry:
    """Записать событие в журнал.

    `session=None` означает «пиши в собственной транзакции»: так журналируются
    события, после которых транзакция запроса будет откачена. Если сессия
    передана, запись добавляется в неё и уходит в базу вместе с бизнес-данными —
    это правильно для успешных операций, где журнал и изменение должны быть
    зафиксированы вместе либо не зафиксированы вовсе.

    Логин берётся из пользователя, но может быть передан отдельно: при неудачном
    входе пользователя нет, а логин, под которым стучались, — самое ценное в
    записи.
    """
    entry = AuditLogEntry(
        occurred_at=utcnow(),
        user_id=user.id if user is not None else None,
        user_login=user_login if user_login is not None else (user.login if user else None),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        request_id=context.request_id if context else None,
        ip_address=context.normalized_ip if context else None,
        user_agent=context.user_agent if context else None,
        details=sanitize_details(details),
    )

    if session is not None:
        session.add(entry)
        session.flush()
        return entry

    # Собственная сессия: событие переживёт откат основной транзакции.
    with get_session_factory()() as own_session:
        own_session.add(entry)
        own_session.commit()
        # Объект отвязан от закрытой сессии, но `expire_on_commit=False`
        # оставляет значения атрибутов доступными вызывающему коду.
        return entry


def record_login_success(
    session: Session | None,
    user: User,
    context: RequestContext | None = None,
) -> AuditLogEntry:
    return record(
        AuditAction.LOGIN_SUCCESS,
        session=session,
        user=user,
        context=context,
        entity_type="user",
        entity_id=user.id,
    )


def record_login_failure(
    session: Session | None,
    login: str,
    reason: str,
    context: RequestContext | None = None,
    user: User | None = None,
) -> AuditLogEntry:
    """Неудачный вход.

    `reason` — короткий технический код («unknown_login», «bad_password»,
    «locked», «inactive»). Он нужен расследованию, но наружу в ответе API не
    отдаётся: пользователю сообщается одна и та же фраза, иначе ответ станет
    подсказкой перебирающему логины.
    """
    return record(
        AuditAction.LOGIN_FAILURE,
        session=session,
        user=user,
        user_login=login,
        context=context,
        details={"reason": reason},
    )


def record_permission_denied(
    session: Session | None,
    user: User | None,
    *,
    required: str,
    context: RequestContext | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    details: Mapping[str, Any] | None = None,
) -> AuditLogEntry:
    """Отказ в доступе.

    Журналируется по требованию ТЗ и по существу: единичный отказ — обычно
    ошибка навигации, а серия отказов подряд — разведка периметра, и увидеть её
    можно только если каждый отказ оставил след.
    """
    payload: dict[str, Any] = {"required": required}
    if details:
        payload.update(details)
    return record(
        AuditAction.PERMISSION_DENIED,
        session=session,
        user=user,
        context=context,
        entity_type=entity_type,
        entity_id=entity_id,
        details=payload,
    )


def record_sensitive_view(
    session: Session | None,
    user: User,
    *,
    field: str,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    count: int = 1,
    context: RequestContext | None = None,
) -> AuditLogEntry:
    """Просмотр незамаскированных персональных данных.

    В `details` уходят имя поля и количество раскрытых значений — но не сами
    значения. Этого достаточно, чтобы ответить на вопрос «кто и когда смотрел
    ИИН получателей субсидий», и недостаточно, чтобы журнал стал вторым местом
    хранения этих ИИН.
    """
    return record(
        AuditAction.SENSITIVE_VIEW,
        session=session,
        user=user,
        context=context,
        entity_type=entity_type,
        entity_id=entity_id,
        details={"field": field, "count": count},
    )


__all__ = [
    "RequestContext",
    "record",
    "record_login_failure",
    "record_login_success",
    "record_permission_denied",
    "record_sensitive_view",
    "sanitize_details",
]
