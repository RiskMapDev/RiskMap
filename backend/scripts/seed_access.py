"""Создание ролей, прав и демонстрационных учётных записей.

Запуск::

    python -m scripts.seed_access                 # создать недостающее
    python -m scripts.seed_access --reset-passwords   # выдать новые пароли
    python -m scripts.seed_access --dry-run       # показать план, ничего не менять

Пароли **генерируются** и печатаются один раз — при создании учётной записи.
В коде их нет и быть не может: одинаковый пароль во всех развёртываниях
переживает и демонстрацию, и приёмку, и оказывается в проде. Восстановить
напечатанный пароль позже нельзя — в базе лежит только хеш Argon2id; для этого
и существует `--reset-passwords`.

Скрипт идемпотентен: повторный запуск не создаёт дублей и не отзывает права,
которые администратор настроил вручную.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security
from app.core.permissions import sync_catalog
from app.db.base import utcnow
from app.db.models.access import Role, RoleCode, User
from app.db.models.territory import Territory
from app.db.session import session_scope
from app.services.territory_resolver import normalize_territory_name


@dataclass(frozen=True, slots=True)
class DemoUser:
    """Описание демонстрационной учётной записи."""

    login: str
    full_name: str
    role: RoleCode
    territory_name: str | None
    """None — доступ ко всем территориям (`territory_id` останется NULL)."""

    comment: str


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("admin", "Администратор системы", RoleCode.ADMIN, None, "все территории"),
    DemoUser("analyst", "Аналитик области", RoleCode.ANALYST, "Алматинская область", ""),
    DemoUser(
        "analyst.karasay",
        "Аналитик Карасайского района",
        RoleCode.ANALYST,
        "Карасайский район",
        "проверка территориального ограничения: Талгарский район недоступен",
    ),
    DemoUser("manager", "Руководитель", RoleCode.MANAGER, None, "все территории"),
    DemoUser("viewer", "Наблюдатель", RoleCode.VIEWER, "Алматинская область", ""),
)


def find_territory(session: Session, name: str) -> Territory | None:
    """Найти территорию по названию через ту же свёртку, что и импорт.

    Прямое сравнение строк здесь не годится: в справочнике название может быть
    записано как «Карасайский район», «Карасайский р-н» или «Қарасай ауданы».
    """
    target = normalize_territory_name(name)
    for territory in session.execute(select(Territory)).scalars():
        if normalize_territory_name(territory.name_ru) == target:
            return territory
        if territory.name_kk and normalize_territory_name(territory.name_kk) == target:
            return territory
    return None


def ensure_users(session: Session, *, reset_passwords: bool) -> list[tuple[str, str]]:
    """Создать демонстрационные учётные записи, вернуть выданные пароли.

    Существующим записям пароль не меняется без явного `--reset-passwords`:
    молчаливая перевыдача пароля при каждом прогоне выбила бы из системы всех,
    кто уже работает.
    """
    roles = {str(role.code): role for role in session.execute(select(Role)).scalars()}
    issued: list[tuple[str, str]] = []

    for spec in DEMO_USERS:
        role = roles.get(str(spec.role))
        if role is None:
            raise RuntimeError(
                f"Роль {spec.role} отсутствует в базе — сначала синхронизируйте каталог ролей"
            )

        territory = None
        if spec.territory_name:
            territory = find_territory(session, spec.territory_name)
            if territory is None:
                print(
                    f"  ! территория {spec.territory_name!r} не найдена — "
                    f"учётная запись {spec.login} получит доступ ко всем территориям",
                    file=sys.stderr,
                )

        user = session.execute(
            select(User).where(User.login == spec.login)
        ).scalar_one_or_none()

        if user is None:
            password = security.generate_password()
            session.add(
                User(
                    login=spec.login,
                    full_name=spec.full_name,
                    password_hash=security.hash_password(password),
                    role_id=role.id,
                    territory_id=territory.id if territory else None,
                    is_active=True,
                    password_changed_at=utcnow(),
                )
            )
            issued.append((spec.login, password))
            print(f"  + создан {spec.login} ({role.title})")
        else:
            # Роль и территория выравниваются по описанию: демонстрационный
            # стенд должен приходить в заявленное состояние, даже если его
            # успели поправить руками.
            user.role_id = role.id
            user.territory_id = territory.id if territory else None
            if reset_passwords:
                password = security.generate_password()
                user.password_hash = security.hash_password(password)
                user.password_changed_at = utcnow()
                user.failed_login_attempts = 0
                user.locked_until = None
                issued.append((spec.login, password))
                print(f"  ~ пароль перевыдан: {spec.login}")
            else:
                print(f"  = уже есть: {spec.login}")

    session.flush()
    return issued


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Роли, права и демонстрационные пользователи")
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="перевыдать пароли существующим учётным записям",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="показать, что будет сделано, и откатить транзакцию",
    )
    args = parser.parse_args(argv)

    try:
        with session_scope() as session:
            print("Каталог прав и ролей:")
            created_permissions, created_roles = sync_catalog(session)
            print(f"  прав создано: {created_permissions}, ролей создано: {created_roles}")

            print("Учётные записи:")
            issued = ensure_users(session, reset_passwords=args.reset_passwords)

            if args.dry_run:
                print("\n--dry-run: изменения откачены, пароли не сохранены.")
                session.rollback()
                return 0

        if issued:
            print("\nВыданные пароли — сохраните их сейчас, повторно они не покажутся:")
            width = max(len(login) for login, _ in issued)
            for login, password in issued:
                print(f"  {login:<{width}}  {password}")
            print("\nПароли выведены только в консоль и нигде не сохранены в открытом виде.")
        else:
            print("\nНовых паролей не выдано.")
    # CLI не должен показывать пользователю трассировку: сообщаем причину и
    # возвращаем ненулевой код, по которому запуск можно проверить в скрипте.
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
