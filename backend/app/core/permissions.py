"""Права, роли и территориальная область видимости.

Доступ здесь двумерный, и обе оси проверяются на сервере.

**Что можно — роль.** Права атомарные и лежат в таблице `permissions`, а не в
константах кода. Так требует ТЗ: администратор настраивает роли сам, и если бы
набор прав роли выводился в коде, каждая правка полномочий превращалась бы в
релиз. Перечень ниже — это *исходное состояние* каталога и *исходная* раскладка
по ролям, которую seed-скрипт заливает в базу. Дальше источником истины
становится база: проверка `has_permission` смотрит на связи роли в БД, а не на
словарь `DEFAULT_ROLE_PERMISSIONS`.

**Где можно — территория.** У пользователя есть `territory_id`; NULL означает
доступ ко всем территориям. Ограничение наследуется вниз по иерархии: аналитик,
привязанный к области, видит все её районы, а аналитик Карасайского района не
видит Талгарский, хотя роль у них одна. Спуск по дереву считает рекурсивный
CTE — один запрос вместо обхода в приложении.

Про зависимость от `app.api.deps`: фабрики зависимостей внизу файла — это
HTTP-край модели доступа, и им нужен уже аутентифицированный пользователь,
которого собирает слой API. Импорт направлен из `core` в `api`, что необычно, и
альтернатива рассматривалась: разнести каталог прав и проверки прав по разным
модулям. Она отвергнута — правило «какое право нужно» и его проверка суть одна
вещь, и разлучать их значит гарантировать расхождение. Цикла при этом нет:
`app.api.deps` намеренно ничего не берёт из этого модуля.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Final

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, RequestCtx
from app.db.models.access import Permission, Role, RoleCode, SensitiveDataAccess, User
from app.db.models.territory import Territory
from app.services import audit
from app.services.audit import RequestContext


class PermissionCode(StrEnum):
    """Атомарные права.

    Дробность выбрана по границам ответственности, а не по эндпоинтам: право
    «смотреть данные» и право «выгружать данные» разделены, потому что выгрузка
    выносит данные за периметр системы, и разрешать её нужно отдельно от
    просмотра. По той же причине разведены импорт и откат импорта.
    """

    MAP_VIEW = "map.view"
    RISK_VIEW = "risk.view"
    RISK_EXPLAIN = "risk.explain"
    RISK_MODEL_EDIT = "risk.model.edit"

    DATA_VIEW = "data.view"
    DATA_EDIT = "data.edit"
    DATA_IMPORT = "data.import"
    DATA_IMPORT_ROLLBACK = "data.import.rollback"

    EXPORT_DATA = "export.data"
    REPORT_GENERATE = "report.generate"

    SENSITIVE_VIEW = "sensitive.view"

    VIEWS_SAVE = "views.save"
    VIEWS_SHARE = "views.share"

    AUDIT_VIEW = "audit.view"
    USERS_MANAGE = "users.manage"
    ROLES_MANAGE = "roles.manage"
    TERRITORY_MANAGE = "territory.manage"
    SOURCE_MANAGE = "source.manage"


# Человекочитаемые названия и пояснения — они попадают в таблицу `permissions`
# и дальше в интерфейс настройки ролей. Администратор должен понимать, что он
# выдаёт, без чтения исходников.
PERMISSION_CATALOG: Final[dict[PermissionCode, tuple[str, str]]] = {
    PermissionCode.MAP_VIEW: (
        "Просмотр карты",
        "Открывать карту рисков и переключать слои.",
    ),
    PermissionCode.RISK_VIEW: (
        "Просмотр оценок риска",
        "Видеть интегральный индекс и оценки по слоям.",
    ),
    PermissionCode.RISK_EXPLAIN: (
        "Просмотр обоснования оценки",
        "Раскрывать вклад показателей в итоговую оценку.",
    ),
    PermissionCode.RISK_MODEL_EDIT: (
        "Правка модели риска",
        "Менять веса и пороги. Каждое изменение журналируется отдельно.",
    ),
    PermissionCode.DATA_VIEW: (
        "Просмотр данных",
        "Читать таблицы договоров, субсидий, бюджета и объектов.",
    ),
    PermissionCode.DATA_EDIT: (
        "Изменение данных",
        "Править записи вручную, вне процедуры импорта.",
    ),
    PermissionCode.DATA_IMPORT: (
        "Импорт данных",
        "Загружать книги источников и запускать обработку.",
    ),
    PermissionCode.DATA_IMPORT_ROLLBACK: (
        "Откат импорта",
        "Снимать актуальность с загруженной версии данных.",
    ),
    PermissionCode.EXPORT_DATA: (
        "Выгрузка данных",
        "Сохранять выборки в файл. Выносит данные за периметр системы.",
    ),
    PermissionCode.REPORT_GENERATE: (
        "Формирование отчётов",
        "Собирать аналитические отчёты по территориям и периодам.",
    ),
    PermissionCode.SENSITIVE_VIEW: (
        "Раскрытие персональных данных",
        "Запрашивать незамаскированные ИИН и БИН. Каждый просмотр журналируется.",
    ),
    PermissionCode.VIEWS_SAVE: (
        "Сохранённые подборки",
        "Сохранять свои наборы фильтров.",
    ),
    PermissionCode.VIEWS_SHARE: (
        "Публикация подборок",
        "Делать сохранённую подборку доступной коллегам.",
    ),
    PermissionCode.AUDIT_VIEW: (
        "Просмотр журнала действий",
        "Читать журнал. Изменять и удалять записи журнала нельзя никому.",
    ),
    PermissionCode.USERS_MANAGE: (
        "Управление пользователями",
        "Создавать учётные записи, назначать роли и территории.",
    ),
    PermissionCode.ROLES_MANAGE: (
        "Настройка ролей",
        "Менять состав прав у роли.",
    ),
    PermissionCode.TERRITORY_MANAGE: (
        "Справочник территорий",
        "Править территории, алиасы названий и границы.",
    ),
    PermissionCode.SOURCE_MANAGE: (
        "Источники данных",
        "Регистрировать наборы источников и их версии.",
    ),
}


# Исходная раскладка прав по ролям. Повторим: это стартовое состояние базы,
# а не правило, действующее в рантайме.
DEFAULT_ROLE_PERMISSIONS: Final[dict[RoleCode, frozenset[PermissionCode]]] = {
    # Администратор получает весь каталог: любое право, не выданное ему,
    # означало бы функцию, которую в системе не может включить никто.
    RoleCode.ADMIN: frozenset(PermissionCode),
    RoleCode.ANALYST: frozenset(
        {
            PermissionCode.MAP_VIEW,
            PermissionCode.RISK_VIEW,
            PermissionCode.RISK_EXPLAIN,
            PermissionCode.DATA_VIEW,
            PermissionCode.DATA_EDIT,
            PermissionCode.DATA_IMPORT,
            PermissionCode.DATA_IMPORT_ROLLBACK,
            PermissionCode.EXPORT_DATA,
            PermissionCode.REPORT_GENERATE,
            PermissionCode.VIEWS_SAVE,
            PermissionCode.VIEWS_SHARE,
        }
    ),
    # Руководитель не правит данные, но контролирует работу с ними, поэтому
    # ему открыт журнал.
    RoleCode.MANAGER: frozenset(
        {
            PermissionCode.MAP_VIEW,
            PermissionCode.RISK_VIEW,
            PermissionCode.RISK_EXPLAIN,
            PermissionCode.DATA_VIEW,
            PermissionCode.EXPORT_DATA,
            PermissionCode.REPORT_GENERATE,
            PermissionCode.VIEWS_SAVE,
            PermissionCode.VIEWS_SHARE,
            PermissionCode.AUDIT_VIEW,
        }
    ),
    # «Просмотр» — минимум: посмотреть карту и оценки. Ни выгрузки, ни
    # обоснования, ни персональных данных.
    RoleCode.VIEWER: frozenset(
        {
            PermissionCode.MAP_VIEW,
            PermissionCode.RISK_VIEW,
            PermissionCode.DATA_VIEW,
            PermissionCode.VIEWS_SAVE,
        }
    ),
}


# Степень доступа к персональным данным — свойство роли, а не отдельное право:
# это не «можно/нельзя», а «насколько», и трёхзначность плохо ложится на
# булеву связь роли с правом. Право SENSITIVE_VIEW при этом остаётся — оно
# закрывает эндпоинты раскрытия, степень же определяет вид самого значения.
DEFAULT_ROLE_SENSITIVE_ACCESS: Final[dict[RoleCode, SensitiveDataAccess]] = {
    RoleCode.ADMIN: SensitiveDataAccess.FULL,
    RoleCode.ANALYST: SensitiveDataAccess.MASKED,
    RoleCode.MANAGER: SensitiveDataAccess.MASKED,
    RoleCode.VIEWER: SensitiveDataAccess.HIDDEN,
}

ROLE_DESCRIPTIONS: Final[dict[RoleCode, str]] = {
    RoleCode.ADMIN: "Полный доступ, настройка ролей и пользователей, просмотр журнала.",
    RoleCode.ANALYST: "Работа с данными и импортом в пределах своей территории.",
    RoleCode.MANAGER: "Просмотр аналитики и отчётов, контроль журнала.",
    RoleCode.VIEWER: "Только просмотр карты и оценок.",
}


def granted_codes(user: User) -> frozenset[str]:
    """Права пользователя — из базы, через его роль.

    Читается по связи `role.permissions`, а не из `DEFAULT_ROLE_PERMISSIONS`:
    администратор мог изменить состав прав роли, и код обязан это увидеть.
    """
    return frozenset(permission.code for permission in user.role.permissions)


def has_permission(user: User, code: PermissionCode | str) -> bool:
    return str(code) in granted_codes(user)


def sensitive_access_of(user: User) -> SensitiveDataAccess:
    """Степень доступа роли к персональным данным.

    Нераспознанное значение трактуется как самое строгое. Мусор в колонке не
    должен превращаться в раскрытие персональных данных — при сомнении система
    закрывается, а не открывается.
    """
    try:
        return SensitiveDataAccess(str(user.role.sensitive_data_access))
    except ValueError:
        return SensitiveDataAccess.HIDDEN


def sync_catalog(session: Session) -> tuple[int, int]:
    """Привести каталог прав и ролей в базе к описанному здесь исходному виду.

    Идемпотентна: существующие записи обновляются по коду, новые создаются.
    Права у роли **дополняются**, а не заменяются, и ничего не отзывается —
    иначе повторный прогон seed-скрипта откатил бы настройки, сделанные
    администратором вручную, что как раз и нарушило бы требование ТЗ о
    настраиваемых ролях.

    Возвращает число созданных прав и ролей.
    """
    existing_permissions = {
        permission.code: permission for permission in session.execute(select(Permission)).scalars()
    }

    created_permissions = 0
    for code, (title, description) in PERMISSION_CATALOG.items():
        permission = existing_permissions.get(str(code))
        if permission is None:
            permission = Permission(code=str(code), title=title, description=description)
            session.add(permission)
            existing_permissions[str(code)] = permission
            created_permissions += 1
        else:
            permission.title = title
            permission.description = description

    session.flush()

    existing_roles = {str(role.code): role for role in session.execute(select(Role)).scalars()}

    created_roles = 0
    for role_code, codes in DEFAULT_ROLE_PERMISSIONS.items():
        role = existing_roles.get(str(role_code))
        if role is None:
            role = Role(
                code=role_code,
                title=role_code.label_ru,
                description=ROLE_DESCRIPTIONS[role_code],
                sensitive_data_access=DEFAULT_ROLE_SENSITIVE_ACCESS[role_code],
            )
            session.add(role)
            session.flush()
            existing_roles[str(role_code)] = role
            created_roles += 1

        assigned = {permission.code for permission in role.permissions}
        for code in sorted(codes):
            if str(code) not in assigned:
                role.permissions.append(existing_permissions[str(code)])

    session.flush()
    return created_permissions, created_roles


@dataclass(frozen=True, slots=True)
class TerritoryScope:
    """Территории, доступные пользователю.

    `allowed_ids is None` — доступ ко всем территориям. Это не то же самое, что
    пустое множество: пустое множество означает «территория назначена, но у неё
    нет ни одной записи в справочнике», и открывать по нему всё было бы
    опасной подменой смысла.
    """

    root_id: uuid.UUID | None
    allowed_ids: frozenset[uuid.UUID] | None

    @property
    def unrestricted(self) -> bool:
        return self.allowed_ids is None

    def allows(self, territory_id: uuid.UUID | None) -> bool:
        allowed = self.allowed_ids
        if allowed is None:
            return True
        if territory_id is None:
            # Запись без территории не принадлежит ничьей зоне ответственности,
            # и ограниченному пользователю она не показывается: иначе через
            # «неопределённые» строки утекали бы чужие районы.
            return False
        return territory_id in allowed

    def require(self, territory_id: uuid.UUID | None) -> None:
        """Бросить 403, если территория вне зоны доступа."""
        if not self.allows(territory_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Территория вне зоны вашего доступа",
            )


def descendant_territory_ids(session: Session, root_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """Территория и все её потомки одним рекурсивным запросом.

    Доступ к области обязан давать доступ к её районам — иначе привязка
    пользователя к области была бы бессмысленной. Обход дерева в Python
    потребовал бы запроса на уровень; CTE укладывается в один.
    """
    scope = (
        select(Territory.id.label("id"))
        .where(Territory.id == root_id)
        .cte("territory_scope", recursive=True)
    )
    scope = scope.union_all(
        select(Territory.id).where(Territory.parent_id == scope.c.id)
    )
    rows = session.execute(select(scope.c.id)).scalars().all()
    return frozenset(rows)


def resolve_territory_scope(session: Session, user: User) -> TerritoryScope:
    """Построить область видимости пользователя."""
    if user.territory_id is None:
        return TerritoryScope(root_id=None, allowed_ids=None)
    return TerritoryScope(
        root_id=user.territory_id,
        allowed_ids=descendant_territory_ids(session, user.territory_id),
    )


def require_permission(*codes: PermissionCode) -> Callable[..., User]:
    """Зависимость FastAPI: у пользователя должны быть все перечисленные права.

    Отказ журналируется здесь, а не в обработчике: обработчик до отказа не
    доходит, и если не записать событие в самой проверке, серия попыток
    обращения к закрытому разделу нигде не отразится.
    """
    required = tuple(str(code) for code in codes)

    def dependency(user: CurrentUser, session: DbSession, context: RequestCtx) -> User:
        granted = granted_codes(user)
        missing = [code for code in required if code not in granted]
        if missing:
            audit.record_permission_denied(
                None,
                user,
                required=",".join(missing),
                context=context,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этой операции",
            )
        return user

    return dependency


def require_any_permission(*codes: PermissionCode) -> Callable[..., User]:
    """Зависимость FastAPI: достаточно любого из перечисленных прав."""
    accepted = tuple(str(code) for code in codes)

    def dependency(user: CurrentUser, session: DbSession, context: RequestCtx) -> User:
        if not granted_codes(user).intersection(accepted):
            audit.record_permission_denied(
                None,
                user,
                required="|".join(accepted),
                context=context,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этой операции",
            )
        return user

    return dependency


def get_territory_scope(session: DbSession, user: CurrentUser) -> TerritoryScope:
    """Зависимость FastAPI: область видимости текущего пользователя.

    Обработчики должны фильтровать выборки по ней, а не полагаться на то, что
    клиент пришлёт «правильный» фильтр территории. Клиент — не источник истины
    о правах, и запрос с чужим `territory_id` обязан упереться в сервер.
    """
    return resolve_territory_scope(session, user)


#: Готовая аннотация для обработчиков: `scope: CurrentTerritoryScope`.
CurrentTerritoryScope = Annotated[TerritoryScope, Depends(get_territory_scope)]


def assert_territory_allowed(
    scope: TerritoryScope,
    territory_id: uuid.UUID | None,
    *,
    session: Session | None,
    user: User,
    context: RequestContext | None = None,
    entity_type: str | None = None,
) -> None:
    """Проверить территорию и записать отказ в журнал.

    Отдельная функция, а не метод `TerritoryScope.require`: у области видимости
    нет ни сессии, ни знания о пользователе, и тащить их в неё значило бы
    смешать структуру данных с побочными эффектами.
    """
    if scope.allows(territory_id):
        return
    audit.record_permission_denied(
        session,
        user,
        required="territory",
        context=context,
        entity_type=entity_type,
        entity_id=territory_id,
        details={"scope_root": str(scope.root_id) if scope.root_id else None},
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Территория вне зоны вашего доступа",
    )


def all_permission_codes() -> tuple[str, ...]:
    return tuple(sorted(str(code) for code in PermissionCode))


def default_codes_for(role: RoleCode | str) -> frozenset[PermissionCode]:
    """Исходный набор прав роли. Используется seed-скриптом и тестами."""
    return DEFAULT_ROLE_PERMISSIONS.get(RoleCode(str(role)), frozenset())


def describe_permissions(codes: Iterable[str]) -> list[dict[str, str]]:
    """Права в виде, пригодном для ответа API и экрана настройки ролей."""
    described: list[dict[str, str]] = []
    for code in sorted(codes):
        try:
            title, description = PERMISSION_CATALOG[PermissionCode(code)]
        except ValueError:
            # Право, добавленное администратором вне каталога, — показываем
            # как есть, а не прячем: иначе оно будет невидимо в интерфейсе.
            title, description = code, ""
        described.append({"code": code, "title": title, "description": description})
    return described


__all__ = [
    "DEFAULT_ROLE_PERMISSIONS",
    "DEFAULT_ROLE_SENSITIVE_ACCESS",
    "PERMISSION_CATALOG",
    "ROLE_DESCRIPTIONS",
    "CurrentTerritoryScope",
    "PermissionCode",
    "TerritoryScope",
    "all_permission_codes",
    "assert_territory_allowed",
    "default_codes_for",
    "descendant_territory_ids",
    "describe_permissions",
    "get_territory_scope",
    "granted_codes",
    "has_permission",
    "require_any_permission",
    "require_permission",
    "resolve_territory_scope",
    "sensitive_access_of",
    "sync_catalog",
]
