"""Общие приспособления тестов доступа.

Тесты работают с живой базой, а не с подменой в памяти. Причина простая:
модели используют типы, которых нет вне PostgreSQL, — JSONB, INET, UUID,
геометрию PostGIS, а территориальное ограничение держится на рекурсивном CTE.
Проверять всё это на SQLite значило бы проверять другую систему.

Изоляция обеспечивается транзакцией: каждый тест получает сессию, привязанную к
одному соединению с открытой транзакцией, которая по завершении откатывается.
Даже `commit()` внутри кода приложения остаётся внутри этой транзакции —
`join_transaction_mode="create_savepoint"` превращает его в точку сохранения.
Поэтому тесты не оставляют следов в базе и не зависят от порядка запуска.

Отдельно перехватывается фабрика сессий журнала. Часть событий (отказ в
доступе, неудачный вход) пишется в собственной транзакции, чтобы пережить откат
транзакции запроса, — и без перехвата такие записи оставались бы в базе
насовсем. Перехват направляет их в то же соединение теста.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Protocol

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import security
from app.core.permissions import sync_catalog
from app.db.models.access import Role, RoleCode, User
from app.db.models.territory import BoundaryVersion, Territory, TerritoryLevel
from app.db.session import get_db, get_engine
from app.main import create_app

#: Пароль демонстрационных учётных записей в тестах. Длиннее минимальной длины
#: из настроек; в рабочие развёртывания не попадает — там пароли генерируются.
TEST_PASSWORD = "Тест-Пароль-2026!x"


class UserFactory(Protocol):
    """Тип приспособления `make_user` — чтобы вызовы проверялись анализатором."""

    def __call__(
        self,
        role: RoleCode | str,
        *,
        territory_id: uuid.UUID | None = None,
        password: str = TEST_PASSWORD,
        is_active: bool = True,
        login: str | None = None,
    ) -> User: ...


@pytest.fixture(scope="session")
def db_connection() -> Iterator[Connection]:
    """Одно соединение на весь прогон.

    Соединение переиспользуется, потому что установка нового обходится дороже
    самих проверок, а изоляция обеспечивается транзакцией, а не соединением.
    """
    connection = get_engine().connect()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def db_session(db_connection: Connection, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Сессия, все изменения которой откатываются после теста.

    Здесь же перехватывается фабрика сессий журнала: события, которые пишутся
    в собственной транзакции, иначе оставались бы в базе после отката теста.
    Приспособление не сделано автоматическим намеренно — тесты, не работающие
    с базой, не должны из-за него открывать соединение.
    """
    transaction = db_connection.begin()
    session = Session(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    audit_factory = sessionmaker(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.services.audit.get_session_factory", lambda: audit_factory)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()


@pytest.fixture
def roles(db_session: Session) -> dict[str, Role]:
    """Каталог прав и ролей, залитый в базу теста."""
    sync_catalog(db_session)
    return {str(role.code): role for role in db_session.execute(select(Role)).scalars()}


@pytest.fixture
def territories(db_session: Session) -> dict[str, Territory]:
    """Кусок иерархии: область и два района внутри неё.

    Именно та конфигурация, ради которой существует территориальное
    ограничение: аналитик Карасайского района не должен видеть Талгарский.
    """
    suffix = uuid.uuid4().hex[:8]
    version = BoundaryVersion(
        code=f"test-{suffix}",
        title="Тестовый набор границ",
        source_name="тест",
        license_name="CC-BY-4.0",
        attribution_text="тестовые данные",
        redistribution_allowed=True,
    )
    db_session.add(version)
    db_session.flush()

    region = Territory(
        code=f"almaty-oblast-{suffix}",
        name_ru="Алматинская область",
        level=TerritoryLevel.REGION,
        boundary_version_id=version.id,
    )
    db_session.add(region)
    db_session.flush()

    karasay = Territory(
        code=f"karasay-{suffix}",
        name_ru="Карасайский район",
        level=TerritoryLevel.DISTRICT,
        parent_id=region.id,
        boundary_version_id=version.id,
    )
    talgar = Territory(
        code=f"talgar-{suffix}",
        name_ru="Талгарский район",
        level=TerritoryLevel.DISTRICT,
        parent_id=region.id,
        boundary_version_id=version.id,
    )
    db_session.add_all([karasay, talgar])
    db_session.flush()

    # Сельский округ внутри района — нужен, чтобы проверить, что спуск по
    # иерархии не останавливается на первом уровне.
    okrug = Territory(
        code=f"karasay-okrug-{suffix}",
        name_ru="Иргелинский сельский округ",
        level=TerritoryLevel.RURAL_OKRUG,
        parent_id=karasay.id,
        boundary_version_id=version.id,
    )
    db_session.add(okrug)
    db_session.flush()

    return {"region": region, "karasay": karasay, "talgar": talgar, "okrug": okrug}


@pytest.fixture
def make_user(db_session: Session, roles: dict[str, Role]) -> UserFactory:
    """Фабрика учётных записей.

    Логин получает случайный суффикс: тесты идут в одной базе с уже
    существующими данными, и жёстко заданный логин рано или поздно столкнётся
    с ограничением уникальности.
    """

    def factory(
        role: RoleCode | str,
        *,
        territory_id: uuid.UUID | None = None,
        password: str = TEST_PASSWORD,
        is_active: bool = True,
        login: str | None = None,
    ) -> User:
        user = User(
            login=login or f"t.{role}.{uuid.uuid4().hex[:10]}",
            full_name=f"Тестовый {role}",
            password_hash=security.hash_password(password),
            role_id=roles[str(role)].id,
            territory_id=territory_id,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.flush()
        db_session.refresh(user)
        return user

    return factory


@pytest.fixture
def app(db_session: Session) -> Iterator[FastAPI]:
    """Приложение, работающее с сессией теста."""
    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """HTTP-клиент. Токены отзываются после теста, чтобы не течь между случаями."""
    with TestClient(app) as test_client:
        yield test_client
    security.clear_revoked_tokens()
