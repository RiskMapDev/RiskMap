"""Эндпоинты администрирования: пользователи, справочники, критерии риска, журнал.

Четыре вкладки референса — четыре группы маршрутов, и у каждой своё право.
Разные права здесь не формальность: руководитель читает журнал, но не заводит
учётные записи, а правка весов риска доступна только администратору, потому что
она меняет оценку каждого объекта в системе.

**Критерии риска versioned by design.** Веса и пороги живут в коде
(`app/risk/layers/*`) как исходная конфигурация модели, а правки хранятся
записями журнала действий с действием `RISK_MODEL_CHANGED`. Журнал в этой
системе — таблица только на запись, и это делает его точной моделью реестра
версий: запись нельзя ни отредактировать, ни удалить, поэтому цепочка версий
не может быть подделана задним числом. Отдельная таблица конфигураций дала бы
ровно то же самое плюс необходимость отдельно журналировать изменения в ней.

Прошлые оценки правкой весов **не переписываются**. В каждой оценке уже лежит
`model_version`, и пересчёт задним числом сделал бы старые отчёты
невоспроизводимыми: цифра в справке от прошлого месяца перестала бы
подтверждаться данными. Новая версия действует на будущие расчёты.

**Журнал действий доступен только на чтение.** Ни одного маршрута записи или
удаления здесь нет и быть не должно: журнал, который можно отредактировать, не
является доказательством.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DbSession, RequestCtx
from app.core import security
from app.core.config import get_settings
from app.core.permissions import (
    PermissionCode,
    describe_permissions,
    require_any_permission,
    require_permission,
)
from app.db.base import utcnow
from app.db.models.access import (
    AuditAction,
    AuditLogEntry,
    Role,
    RoleCode,
    SensitiveDataAccess,
    User,
)
from app.db.models.territory import Territory
from app.risk.core import RiskLevel, RiskModelSpec
from app.risk.layers.budget import BUDGET_8_3
from app.risk.layers.infrastructure import EXPERTISE_MODEL, PPP_MODEL
from app.risk.layers.organizations import ORGANIZATION_MODEL
from app.risk.layers.procurement import PROCUREMENT_8_4
from app.services import audit

router = APIRouter(prefix="/admin", tags=["администрирование"])

_REQUIRE_USERS = Depends(require_permission(PermissionCode.USERS_MANAGE))
_REQUIRE_AUDIT = Depends(require_permission(PermissionCode.AUDIT_VIEW))
_REQUIRE_MODEL_EDIT = Depends(require_permission(PermissionCode.RISK_MODEL_EDIT))
_REQUIRE_REFERENCE = Depends(
    require_any_permission(
        PermissionCode.TERRITORY_MANAGE,
        PermissionCode.USERS_MANAGE,
        PermissionCode.DATA_VIEW,
    )
)
_REQUIRE_MODEL_VIEW = Depends(
    require_any_permission(PermissionCode.RISK_MODEL_EDIT, PermissionCode.RISK_EXPLAIN)
)

UsersAdmin = Annotated[User, _REQUIRE_USERS]
AuditReader = Annotated[User, _REQUIRE_AUDIT]
ModelEditor = Annotated[User, _REQUIRE_MODEL_EDIT]
ReferenceReader = Annotated[User, _REQUIRE_REFERENCE]
ModelReader = Annotated[User, _REQUIRE_MODEL_VIEW]


# --- Вкладка «Пользователи» --------------------------------------------------


class UserCreateBody(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    password: str
    role_code: RoleCode
    territory_id: uuid.UUID | None = None
    email: str | None = None


class UserUpdateBody(BaseModel):
    """Правка учётной записи.

    Пароль здесь отсутствует намеренно: смена чужого пароля — отдельная
    операция с отдельным журналированием, и смешивать её с правкой роли значит
    прятать самое чувствительное действие внутри рутинного.
    """

    full_name: str | None = Field(default=None, max_length=255)
    role_code: RoleCode | None = None
    territory_id: uuid.UUID | None = None
    is_active: bool | None = None
    reset_lockout: bool = False


def _territory_names(session: Session) -> dict[uuid.UUID, str]:
    rows = session.execute(select(Territory.id, Territory.name_ru)).all()
    return {row[0]: str(row[1]) for row in rows}


def _user_payload(user: User, territories: dict[uuid.UUID, str]) -> dict[str, Any]:
    """Строка таблицы пользователей — ровно колонки референса.

    Территория выводится словом «Все районы», а не пустым местом: пустая
    ячейка читается как «не заполнено», хотя означает противоположное —
    доступ ко всем территориям.
    """
    return {
        "id": str(user.id),
        "login": user.login,
        "full_name": user.full_name,
        "email": user.email,
        "role": str(user.role.code),
        "role_title": user.role.title,
        "territory_id": str(user.territory_id) if user.territory_id else None,
        "territory": (
            territories.get(user.territory_id, "Территория удалена")
            if user.territory_id
            else "Все районы"
        ),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "is_active": user.is_active,
        "is_locked": bool(user.locked_until and user.locked_until > utcnow()),
        "failed_login_attempts": user.failed_login_attempts,
    }


@router.get("/users", summary="Пользователи системы")
def list_users(session: DbSession, _: UsersAdmin) -> list[dict[str, Any]]:
    users = session.scalars(
        select(User).options(selectinload(User.role)).order_by(User.full_name)
    ).all()
    territories = _territory_names(session)
    return [_user_payload(user, territories) for user in users]


@router.post("/users", summary="Завести учётную запись", status_code=201)
def create_user(
    session: DbSession,
    admin: UsersAdmin,
    context: RequestCtx,
    body: UserCreateBody,
) -> dict[str, Any]:
    """Создать пользователя.

    Пароль хешируется здесь же и нигде не сохраняется в открытом виде; в
    журнал уходит факт создания и роль, но не пароль — санитайзер журнала
    вычистил бы его и сам, однако полагаться на это как на единственную защиту
    нельзя.
    """
    settings = get_settings()
    if len(body.password) < settings.password_min_length:
        raise HTTPException(
            # Числовой код, а не константа Starlette: имя константы 422 меняется
            # между версиями библиотеки, а само число — нет.
            status_code=422,
            detail=f"Пароль короче {settings.password_min_length} символов",
        )

    exists = session.scalars(select(User).where(User.login == body.login)).one_or_none()
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Такой логин уже занят"
        )

    role = session.scalars(select(Role).where(Role.code == body.role_code)).one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Роль не найдена")

    if body.territory_id is not None and session.get(Territory, body.territory_id) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Территория не найдена"
        )

    user = User(
        login=body.login,
        full_name=body.full_name,
        email=body.email,
        password_hash=security.hash_password(body.password),
        role_id=role.id,
        territory_id=body.territory_id,
        password_changed_at=utcnow(),
    )
    session.add(user)
    session.flush()

    audit.record(
        AuditAction.CREATE,
        session=session,
        user=admin,
        context=context,
        entity_type="user",
        entity_id=user.id,
        details={"login": body.login, "role": str(body.role_code)},
    )
    session.commit()
    return _user_payload(user, _territory_names(session))


@router.patch("/users/{user_id}", summary="Изменить учётную запись")
def update_user(
    session: DbSession,
    admin: UsersAdmin,
    context: RequestCtx,
    user_id: uuid.UUID,
    body: UserUpdateBody,
) -> dict[str, Any]:
    """Правка роли, территории и состояния учётной записи.

    В журнал уходит, что именно изменилось: «было → стало». Запись «пользователя
    изменили» без подробностей не отвечает на единственный вопрос, ради которого
    журнал и ведётся.
    """
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")

    changes: dict[str, Any] = {}

    if body.full_name is not None and body.full_name != user.full_name:
        changes["full_name"] = [user.full_name, body.full_name]
        user.full_name = body.full_name

    if body.role_code is not None and str(body.role_code) != str(user.role.code):
        role = session.scalars(select(Role).where(Role.code == body.role_code)).one_or_none()
        if role is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Роль не найдена")
        changes["role"] = [str(user.role.code), str(body.role_code)]
        user.role_id = role.id

    if body.territory_id != user.territory_id:
        if body.territory_id is not None and session.get(Territory, body.territory_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Территория не найдена"
            )
        changes["territory"] = [
            str(user.territory_id) if user.territory_id else None,
            str(body.territory_id) if body.territory_id else None,
        ]
        user.territory_id = body.territory_id

    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active

    if body.reset_lockout and user.locked_until is not None:
        changes["lockout"] = ["locked", "released"]
        user.locked_until = None
        user.failed_login_attempts = 0

    session.flush()

    if changes:
        audit.record(
            AuditAction.UPDATE,
            session=session,
            user=admin,
            context=context,
            entity_type="user",
            entity_id=user.id,
            details={"login": user.login, "changes": changes},
        )
    session.commit()
    session.refresh(user)
    return _user_payload(user, _territory_names(session))


# --- Вкладка «Справочники» ---------------------------------------------------


@router.get("/reference", summary="Справочники системы")
def reference(session: DbSession, _: ReferenceReader) -> dict[str, Any]:
    """Справочники, на которые опираются остальные экраны.

    Отдаются одним ответом: вкладка показывает их вместе, а четыре отдельных
    запроса дали бы состояние, в котором территории уже обновились, а роли ещё
    нет, и администратор увидел бы несогласованную картину.
    """
    territories = session.execute(
        select(
            Territory.id,
            Territory.code,
            Territory.name_ru,
            Territory.name_kk,
            Territory.level,
            Territory.parent_id,
            Territory.is_current,
        ).order_by(Territory.level, Territory.name_ru)
    ).all()

    roles = session.scalars(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.code)
    ).all()

    user_counts: dict[uuid.UUID, int] = {
        row[0]: int(row[1])
        for row in session.execute(select(User.role_id, func.count()).group_by(User.role_id)).all()
    }

    return {
        "territories": [
            {
                "id": str(row.id),
                "code": row.code,
                "name_ru": row.name_ru,
                "name_kk": row.name_kk,
                "level": str(row.level),
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "is_current": row.is_current,
            }
            for row in territories
        ],
        "roles": [
            {
                "code": str(role.code),
                "title": role.title,
                "description": role.description,
                "sensitive_data_access": str(role.sensitive_data_access),
                "users_count": int(user_counts.get(role.id, 0)),
                "permissions": describe_permissions(
                    permission.code for permission in role.permissions
                ),
            }
            for role in roles
        ],
        "sensitive_access_levels": [
            {"code": str(level), "title": title}
            for level, title in (
                (SensitiveDataAccess.FULL, "Полное значение"),
                (SensitiveDataAccess.MASKED, "Маска"),
                (SensitiveDataAccess.HIDDEN, "Скрыто"),
            )
        ],
        "risk_levels": [
            {"code": str(level), "title": level.label_ru} for level in RiskLevel
        ],
    }


# --- Вкладка «Критерии риска» ------------------------------------------------

#: Модели риска по слоям. Ключ — код модели, он же попадает в каждую оценку.
RISK_MODELS: dict[str, RiskModelSpec] = {
    BUDGET_8_3.code: BUDGET_8_3,
    PROCUREMENT_8_4.code: PROCUREMENT_8_4,
    PPP_MODEL.code: PPP_MODEL,
    EXPERTISE_MODEL.code: EXPERTISE_MODEL,
    ORGANIZATION_MODEL.code: ORGANIZATION_MODEL,
}


class WeightItem(BaseModel):
    code: str
    weight: float = Field(ge=0)


class ThresholdItem(BaseModel):
    """Нижняя граница балла и соответствующий ей уровень."""

    from_score: float
    level: RiskLevel


class RiskModelBody(BaseModel):
    """Новая редакция весов и порогов."""

    version: str = Field(min_length=1, max_length=16)
    weights: list[WeightItem] = Field(default_factory=list)
    thresholds: list[ThresholdItem] = Field(default_factory=list)
    comment: str = Field(default="", max_length=500)


def _model_versions(session: Session, model_code: str) -> list[dict[str, Any]]:
    """История редакций модели — из журнала действий.

    Журнал только на запись, поэтому цепочка версий в нём неизменяема. Это и
    делает его подходящим реестром: удалить неудобную редакцию нельзя.
    """
    entries = session.scalars(
        select(AuditLogEntry)
        .where(
            AuditLogEntry.action == AuditAction.RISK_MODEL_CHANGED,
            AuditLogEntry.entity_type == "risk_model",
            AuditLogEntry.entity_id == model_code,
        )
        .order_by(AuditLogEntry.occurred_at.desc())
    ).all()

    versions: list[dict[str, Any]] = []
    for entry in entries:
        details = entry.details or {}
        versions.append(
            {
                "version": details.get("version"),
                "based_on": details.get("based_on"),
                "comment": details.get("comment", ""),
                "weights": details.get("weights", []),
                "thresholds": details.get("thresholds", []),
                "changed_by": entry.user_login,
                "changed_at": entry.occurred_at.isoformat(),
            }
        )
    return versions


def _model_payload(session: Session, spec: RiskModelSpec) -> dict[str, Any]:
    history = _model_versions(session, spec.code)
    effective = history[0] if history else None
    return {
        "code": spec.code,
        "title": spec.title,
        # Действующая версия — последняя редакция, если она есть, иначе
        # исходная из кода. Оценки, посчитанные до правки, продолжают ссылаться
        # на свою версию и остаются воспроизводимыми.
        "version": (effective or {}).get("version") or spec.version,
        "base_version": spec.version,
        "scale": spec.scale,
        "min_completeness": spec.min_completeness,
        "notes": spec.notes,
        "indicators": [
            {
                "code": indicator.code,
                "name": indicator.name,
                "weight": indicator.weight,
                "direction": str(indicator.direction),
                "source": indicator.source,
            }
            for indicator in spec.indicators
        ],
        "thresholds": [
            {"from_score": bound, "level": str(level), "title": level.label_ru}
            for bound, level in spec.thresholds
        ],
        "history": history,
    }


@router.get("/risk-models", summary="Критерии риска по слоям")
def risk_models(session: DbSession, _: ModelReader) -> list[dict[str, Any]]:
    """Веса, пороги и история редакций каждой модели."""
    return [_model_payload(session, spec) for spec in RISK_MODELS.values()]


@router.put("/risk-models/{model_code}", summary="Изменить веса и пороги")
def update_risk_model(
    session: DbSession,
    admin: ModelEditor,
    context: RequestCtx,
    model_code: str,
    body: RiskModelBody,
) -> dict[str, Any]:
    """Записать новую редакцию модели.

    Три свойства этой операции заданы требованиями и держатся здесь.

    Первое: редактировать может только администратор — право
    `risk.model.edit` по умолчанию есть лишь у него.

    Второе: изменение журналируется действием `RISK_MODEL_CHANGED` вместе с
    полным содержанием редакции. Запись журнала и есть версия.

    Третье: прошлые оценки не трогаются. Ни одной строки с посчитанным риском
    этот маршрут не изменяет — и это проверяется тестом.
    """
    spec = RISK_MODELS.get(model_code)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Модель риска не найдена"
        )

    known = {indicator.code for indicator in spec.indicators}
    unknown = sorted({item.code for item in body.weights} - known)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"У модели нет индикаторов: {', '.join(unknown)}",
        )

    bounds = [item.from_score for item in body.thresholds]
    if bounds != sorted(bounds):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пороги должны идти по возрастанию нижней границы",
        )

    history = _model_versions(session, model_code)
    current_version = (history[0]["version"] if history else None) or spec.version
    if body.version == current_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Версия совпадает с действующей. Новая редакция обязана иметь "
                "новый номер, иначе старые оценки станут неотличимы от новых."
            ),
        )

    # Ключи в подробностях журнала — фиксированные («code», «weight»), а не
    # коды индикаторов: санитайзер журнала чистит подозрительные *ключи*, и
    # индикатор с кодом вроде «bin_share» оказался бы вычищен как персональные
    # данные.
    audit.record(
        AuditAction.RISK_MODEL_CHANGED,
        session=session,
        user=admin,
        context=context,
        entity_type="risk_model",
        entity_id=model_code,
        details={
            "version": body.version,
            "based_on": current_version,
            "comment": body.comment,
            "weights": [{"code": item.code, "weight": item.weight} for item in body.weights],
            "thresholds": [
                {"from_score": item.from_score, "level": str(item.level)}
                for item in body.thresholds
            ],
        },
    )
    session.commit()
    return _model_payload(session, spec)


# --- Вкладка «Журнал действий» -----------------------------------------------

#: Человекочитаемые названия действий. Журнал читает не разработчик, и строка
#: «import_rolled_back» в колонке «Действие» требует перевода на русский —
#: интерфейс по ТЗ русскоязычный, включая служебные разделы.
ACTION_TITLES: dict[AuditAction, str] = {
    AuditAction.LOGIN_SUCCESS: "Вход в систему",
    AuditAction.LOGIN_FAILURE: "Неудачная попытка входа",
    AuditAction.LOGOUT: "Выход из системы",
    AuditAction.CREATE: "Создание записи",
    AuditAction.UPDATE: "Изменение записи",
    AuditAction.DELETE: "Удаление записи",
    AuditAction.IMPORT_STARTED: "Импорт начат",
    AuditAction.IMPORT_FINISHED: "Импорт завершён",
    AuditAction.IMPORT_ROLLED_BACK: "Импорт откачен",
    AuditAction.EXPORT: "Выгрузка данных",
    AuditAction.REPORT_GENERATED: "Формирование отчёта",
    AuditAction.SENSITIVE_VIEW: "Просмотр персональных данных",
    AuditAction.RISK_MODEL_CHANGED: "Изменение модели риска",
    AuditAction.PERMISSION_DENIED: "Отказ в доступе",
}


@router.get("/audit", summary="Журнал действий")
def audit_log(
    session: DbSession,
    _: AuditReader,
    user_login: Annotated[str | None, Query(description="Фильтр по логину.")] = None,
    action: Annotated[AuditAction | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Чтение журнала с фильтрами по пользователю, действию и периоду.

    `date_to` включает весь указанный день: пользователь, задавший «по 5 июля»,
    имеет в виду конец пятого июля, а не его начало, и граница «меньше 5 июля
    00:00» молча теряла бы целые сутки событий.
    """
    stmt = select(AuditLogEntry)
    count_stmt = select(func.count()).select_from(AuditLogEntry)

    conditions: list[Any] = []
    if user_login:
        conditions.append(AuditLogEntry.user_login.ilike(f"%{user_login}%"))
    if action is not None:
        conditions.append(AuditLogEntry.action == action)
    if date_from is not None:
        conditions.append(
            AuditLogEntry.occurred_at >= datetime.combine(date_from, time.min, tzinfo=UTC)
        )
    if date_to is not None:
        conditions.append(
            AuditLogEntry.occurred_at <= datetime.combine(date_to, time.max, tzinfo=UTC)
        )

    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = int(session.execute(count_stmt).scalar_one())
    rows = session.scalars(
        stmt.order_by(AuditLogEntry.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(entry.id),
                "occurred_at": entry.occurred_at.isoformat(),
                "user_login": entry.user_login,
                "action": str(entry.action),
                "action_title": ACTION_TITLES.get(entry.action, str(entry.action)),
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "ip_address": str(entry.ip_address) if entry.ip_address else None,
                "request_id": entry.request_id,
                "details": entry.details,
            }
            for entry in rows
        ],
        "actions": [
            {"code": str(item), "title": ACTION_TITLES.get(item, str(item))}
            for item in AuditAction
        ],
    }


__all__ = ["router"]
