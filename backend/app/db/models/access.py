"""Пользователи, роли, права и журнал действий.

Разграничение доступа в этой системе двумерное, и это следует из ТЗ и из
референса администрирования: у пользователя есть **роль** (что он может делать)
и **территория** (где он это может делать). Аналитик Карасайского района не
должен видеть договоры Талгарского, хотя роль у него та же.

Второе, что определило устройство: **ИИН — персональные данные**. Он есть в
данных субсидий и в графе связей. Роль решает, видит ли пользователь его
целиком, в маске или не видит вовсе, а любой полный просмотр и любая выгрузка
попадают в журнал. Журнал пишется на стороне сервера и не зависит от того, что
покажет интерфейс: клиент — не источник истины о правах.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class RoleCode(StrEnum):
    """Роли по ТЗ, раздел 5."""

    ADMIN = "admin"
    ANALYST = "analyst"
    MANAGER = "manager"
    VIEWER = "viewer"

    @property
    def label_ru(self) -> str:
        return {
            RoleCode.ADMIN: "Администратор",
            RoleCode.ANALYST: "Аналитик",
            RoleCode.MANAGER: "Руководитель",
            RoleCode.VIEWER: "Просмотр",
        }[self]


class SensitiveDataAccess(StrEnum):
    """Что роль видит в поле с персональными данными."""

    FULL = "full"
    """Полное значение. Каждый такой просмотр журналируется."""

    MASKED = "masked"
    """Частично скрытое значение: 8407******12."""

    HIDDEN = "hidden"
    """Значение не отдаётся вовсе, вместо него признак наличия."""


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base, TimestampMixin):
    """Атомарное право.

    Права заданы списком, а не выводятся из роли в коде: администратор по ТЗ
    настраивает роли, и захардкоженный набор пришлось бы менять правкой кода.
    """

    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permission_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Permission {self.code}>"


class Role(Base, TimestampMixin):
    """Роль пользователя."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("code", name="uq_role_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[RoleCode] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    sensitive_data_access: Mapped[SensitiveDataAccess] = mapped_column(
        String(16),
        default=SensitiveDataAccess.HIDDEN,
        nullable=False,
        doc="Значение по умолчанию — самое строгое: право видеть ИИН выдаётся явно.",
    )

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions)
    users: Mapped[list[User]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


class User(Base, TimestampMixin):
    """Учётная запись."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("login", name="uq_user_login"),
        Index("ix_users_role", "role_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    login: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Argon2id. Пароль в открытом виде не хранится и не логируется нигде.",
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[Role] = relationship(back_populates="users")

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="SET NULL"),
        doc=(
            "Территория, которой ограничен доступ. NULL — доступ ко всем "
            "территориям; так настроен «Руководитель» на референсе «Все районы»."
        ),
    )

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        doc="Блокировка после серии неудачных входов — требование ТЗ по безопасности.",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<User {self.login} role={self.role_id}>"


class AuditAction(StrEnum):
    """Что именно журналируется.

    Перечень закрыт по ТЗ: входы, изменения, импорты, экспорты. Отдельно —
    просмотр персональных данных: он не меняет ничего, но должен оставлять след.
    """

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

    IMPORT_STARTED = "import_started"
    IMPORT_FINISHED = "import_finished"
    IMPORT_ROLLED_BACK = "import_rolled_back"

    EXPORT = "export"
    REPORT_GENERATED = "report_generated"

    SENSITIVE_VIEW = "sensitive_view"
    """Просмотр незамаскированных персональных данных."""

    RISK_MODEL_CHANGED = "risk_model_changed"
    """Правка весов или порогов. Меняет оценки, поэтому журналируется отдельно."""

    PERMISSION_DENIED = "permission_denied"


class AuditLogEntry(Base):
    """Запись журнала действий.

    Таблица только на запись: изменение и удаление записей журнала не
    предусмотрены ни интерфейсом, ни API. Журнал, который можно
    отредактировать, не является доказательством.

    `TimestampMixin` намеренно не подмешан: у записи журнала есть момент
    события, и второе поле «когда обновлено» создавало бы ложное впечатление,
    что запись вообще может обновляться.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred", "occurred_at"),
        Index("ix_audit_log_user_action", "user_id", "action"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        doc="NULL у неудачного входа с несуществующим логином — события, которого стоит бояться.",
    )
    user_login: Mapped[str | None] = mapped_column(
        String(64),
        doc=(
            "Логин строкой на момент события. Дублирует ссылку намеренно: "
            "удаление учётной записи не должно обезличивать историю её действий."
        ),
    )

    action: Mapped[AuditAction] = mapped_column(String(32), nullable=False)

    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))

    request_id: Mapped[str | None] = mapped_column(
        String(64), doc="Сквозной идентификатор запроса — связывает журнал с логами."
    )
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        doc=(
            "Подробности события. Персональные данные сюда не пишутся: журнал "
            "фиксирует факт обращения к ним, а не сами значения."
        ),
    )

    def __repr__(self) -> str:
        return f"<AuditLogEntry {self.occurred_at:%Y-%m-%d %H:%M} {self.action} {self.user_login}>"


class SavedView(Base, TimestampMixin):
    """Сохранённая подборка: фильтры, сортировка, выбранный слой.

    Хранится тем же представлением, что уходит в URL, — иначе сохранённая
    ссылка и сохранённая подборка начнут расходиться при первой же правке
    фильтров.
    """

    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_saved_view_owner_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    query_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    is_shared: Mapped[bool] = mapped_column(default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<SavedView {self.name!r}>"
