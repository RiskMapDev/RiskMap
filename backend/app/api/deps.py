"""Общие зависимости API: сессия, контекст запроса, текущий пользователь.

Здесь собирается всё, что маршрутам нужно до начала полезной работы. Главное
решение — **пользователь всегда достаётся из базы, а не из токена**. В токене
есть и логин, и роль, и соблазн сэкономить обращение к базе велик, но тогда
понижение роли, блокировка учётной записи и смена территории вступали бы в силу
только после истечения токена. Час работы с полномочиями, которых у человека
уже нет, — слишком дорогая плата за один запрос по первичному ключу.

Модуль намеренно ничего не импортирует из `app.core.permissions`: проверки прав
и территории живут там и опираются на собранного здесь пользователя. Импорт
строго односторонний, иначе получился бы цикл.

Второе: сообщения об ошибках аутентификации одинаковы для всех причин. Токена
нет, подпись не сошлась, срок истёк, пользователь удалён — снаружи это всегда
401 с одной и той же фразой. Подробная диагностика уходит в журнал, где её
увидит администратор, а не тот, кто подбирает доступ.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core import security
from app.db.models.access import Role, User
from app.db.session import get_db
from app.services import audit
from app.services.audit import RequestContext

# `auto_error=False` — обработку отсутствующего заголовка мы берём на себя:
# стандартное исключение FastAPI не даёт записать событие в журнал и отдаёт
# формулировку, отличающуюся от нашей, а по разнице формулировок тоже можно
# делать выводы о состоянии системы.
_bearer = HTTPBearer(auto_error=False, description="Токен доступа, полученный на /auth/login")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Требуется аутентификация",
    headers={"WWW-Authenticate": "Bearer"},
)

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_context(request: Request) -> RequestContext:
    """Собрать обстоятельства запроса для журнала.

    `X-Request-ID` читается из заголовка — тот же идентификатор проставляет
    middleware в ответ, и именно он связывает запись журнала со строками
    технического лога при разборе инцидента.
    """
    client_host = request.client.host if request.client else None
    return RequestContext(
        request_id=request.headers.get(REQUEST_ID_HEADER),
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
    )


DbSession = Annotated[Session, Depends(get_db)]
RequestCtx = Annotated[RequestContext, Depends(get_request_context)]


def get_current_user(
    session: DbSession,
    context: RequestCtx,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    """Текущий пользователь по токену доступа.

    Роль и её права подгружаются сразу (`selectinload`): они понадобятся любой
    проверке прав, а ленивая загрузка дала бы по отдельному запросу на каждое
    обращение к `user.role.permissions`.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED

    try:
        payload = security.decode_access_token(credentials.credentials)
    except security.TokenError as exc:
        raise _UNAUTHORIZED from exc

    user = session.execute(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .where(User.id == payload.subject)
    ).scalar_one_or_none()

    if user is None:
        # Токен подписан нами, но пользователя нет: учётную запись удалили,
        # пока токен был действителен. Событие стоит того, чтобы остаться
        # в журнале — само по себе оно означает, что кто-то работает с
        # доступом, который должен был исчезнуть.
        audit.record_permission_denied(
            None,
            None,
            required="authentication",
            context=context,
            details={"reason": "user_not_found", "subject": str(payload.subject)},
        )
        raise _UNAUTHORIZED

    if not user.is_active:
        audit.record_permission_denied(
            None,
            user,
            required="authentication",
            context=context,
            details={"reason": "inactive"},
        )
        raise _UNAUTHORIZED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> security.TokenPayload:
    """Разобранный токен — нужен выходу, чтобы отозвать конкретный `jti`."""
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED
    try:
        return security.decode_access_token(credentials.credentials)
    except security.TokenError as exc:
        raise _UNAUTHORIZED from exc


TokenPayloadDep = Annotated[security.TokenPayload, Depends(get_token_payload)]


__all__ = [
    "REQUEST_ID_HEADER",
    "CurrentUser",
    "DbSession",
    "RequestCtx",
    "TokenPayloadDep",
    "get_current_user",
    "get_db",
    "get_request_context",
    "get_token_payload",
]
