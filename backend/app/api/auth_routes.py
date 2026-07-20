"""Вход, выход и сведения о текущем пользователе.

Ответы этого модуля устроены так, чтобы по ним нельзя было изучать систему.

**Одинаковый отказ на все причины.** Нет такого логина, неверный пароль,
учётная запись выключена — снаружи всегда 401 с фразой «Неверный логин или
пароль». Различающиеся ответы превратили бы форму входа в справочник
существующих учётных записей.

**Одинаковое время ответа.** Пароль проверяется даже тогда, когда пользователя
нет: Argon2 занимает десятки миллисекунд, и без этой холостой проверки
несуществующий логин отвечал бы заметно быстрее существующего. Разница в
задержке — такой же канал утечки, как и разница в тексте.

Единственное осознанное исключение — блокировка. О ней сообщается только тому,
кто **уже доказал знание пароля**: такой человек и так знает, что учётная
запись существует, а без объяснения он будет считать, что забыл пароль, и
продолжит попытки, продлевая блокировку.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core import security
from app.core.config import get_settings
from app.core.permissions import describe_permissions, granted_codes, sensitive_access_of
from app.db.base import utcnow
from app.db.models.access import AuditAction, Role, User
from app.services import audit

from .deps import CurrentUser, DbSession, RequestCtx, TokenPayloadDep

router = APIRouter(prefix="/auth", tags=["доступ"])

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Неверный логин или пароль",
    headers={"WWW-Authenticate": "Bearer"},
)


class LoginRequest(BaseModel):
    """Учётные данные.

    Пароль объявлен обычной строкой, но нигде не логируется и не возвращается.
    `repr` модели pydantic по умолчанию печатает поля, поэтому экземпляр этой
    модели не должен попадать в лог целиком — единственное место, где он
    существует, это тело обработчика ниже.
    """

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserProfile(BaseModel):
    """Профиль пользователя. Полей, связанных с паролем, здесь нет и быть не должно."""

    id: uuid.UUID
    login: str
    full_name: str
    email: str | None
    role: str
    role_title: str
    territory_id: uuid.UUID | None
    all_territories: bool = Field(
        description="True — доступ ко всем территориям (territory_id не задан)."
    )
    sensitive_data_access: str
    permissions: list[str]
    last_login_at: datetime | None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Срок жизни токена в секундах.")
    user: UserProfile


def _profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        email=user.email,
        role=str(user.role.code),
        role_title=user.role.title,
        territory_id=user.territory_id,
        all_territories=user.territory_id is None,
        sensitive_data_access=str(sensitive_access_of(user)),
        permissions=sorted(granted_codes(user)),
        last_login_at=user.last_login_at,
    )


def _is_locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        # Из базы значение приходит с зоной, но в тестах и при ручной правке
        # может оказаться наивным. Считаем такие отметки UTC, а не роняем вход.
        locked_until = locked_until.replace(tzinfo=UTC)
    return locked_until > datetime.now(tz=UTC)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Вход в систему",
    responses={
        401: {"description": "Неверный логин или пароль"},
        423: {"description": "Учётная запись временно заблокирована"},
    },
)
def login(payload: LoginRequest, session: DbSession, context: RequestCtx) -> LoginResponse:
    """Проверить учётные данные и выдать токен доступа."""
    settings = get_settings()

    user = session.execute(
        select(User)
        .options(selectinload(User.role).selectinload(Role.permissions))
        .where(User.login == payload.login)
    ).scalar_one_or_none()

    if user is None:
        # Холостая проверка ради равного времени ответа — см. docstring модуля.
        security.verify_dummy_password(payload.password)
        audit.record_login_failure(session, payload.login, "unknown_login", context)
        session.commit()
        raise _INVALID_CREDENTIALS

    password_ok = security.verify_password(payload.password, user.password_hash)

    if _is_locked(user):
        audit.record_login_failure(session, user.login, "locked", context, user=user)
        session.commit()
        if password_ok:
            retry_after = 0
            if user.locked_until is not None:
                locked_until = user.locked_until
                if locked_until.tzinfo is None:
                    locked_until = locked_until.replace(tzinfo=UTC)
                retry_after = max(1, int((locked_until - datetime.now(tz=UTC)).total_seconds()))
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Учётная запись временно заблокирована из-за неудачных попыток входа",
                headers={"Retry-After": str(retry_after)},
            )
        raise _INVALID_CREDENTIALS

    if not password_ok:
        user.failed_login_attempts += 1
        reason = "bad_password"
        if user.failed_login_attempts >= settings.login_max_attempts:
            user.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
            reason = "bad_password_locked"
        audit.record_login_failure(session, user.login, reason, context, user=user)
        session.commit()
        raise _INVALID_CREDENTIALS

    if not user.is_active:
        # Пароль верен, но запись выключена. Наружу — тот же 401: подтверждать
        # правильность пароля для выключенной записи незачем.
        audit.record_login_failure(session, user.login, "inactive", context, user=user)
        session.commit()
        raise _INVALID_CREDENTIALS

    # Счётчик неудач сбрасывается только при успешном входе: сбрасывать его по
    # времени значило бы позволить перебор со скоростью «N попыток на каждое
    # окно» бесконечно.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    token, token_payload = security.create_access_token(
        user_id=user.id, login=user.login, role=str(user.role.code)
    )

    audit.record_login_success(session, user, context)
    session.commit()

    return LoginResponse(
        access_token=token,
        expires_in=token_payload.expires_in_seconds,
        user=_profile(user),
    )


@router.post("/logout", summary="Выход из системы")
def logout(
    user: CurrentUser,
    token: TokenPayloadDep,
    session: DbSession,
    context: RequestCtx,
) -> dict[str, str]:
    """Отозвать текущий токен и записать выход в журнал.

    Токен отзывается по `jti`, а не просто забывается клиентом: выданный JWT
    остаётся действительным до `exp`, и «выход», ограниченный удалением токена
    в браузере, не защитил бы от копии токена, снятой с чужого устройства.
    """
    security.revoke_token(token)
    audit.record(AuditAction.LOGOUT, session=session, user=user, context=context)
    session.commit()
    return {"status": "ok"}


@router.get("/me", response_model=UserProfile, summary="Текущий пользователь")
def me(user: CurrentUser) -> UserProfile:
    """Профиль, роль, права и территория текущего пользователя.

    Интерфейс использует этот ответ, чтобы не показывать недоступные разделы.
    Скрытие в интерфейсе — удобство, а не защита: каждый маршрут проверяет
    права самостоятельно.
    """
    return _profile(user)


@router.get("/permissions", summary="Права текущего пользователя с описанием")
def my_permissions(user: CurrentUser) -> list[dict[str, str]]:
    """Права с названиями — для экрана «мой доступ»."""
    return describe_permissions(granted_codes(user))
