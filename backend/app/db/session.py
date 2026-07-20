"""Подключение к базе и выдача сессий."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Ленивое создание engine.

    Создаётся при первом обращении, а не на импорте модуля: иначе любой импорт
    приложения требовал бы живой базы, и тесты без БД падали бы на сборе.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.sqlalchemy_url,
            echo=settings.db_echo,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            future=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_session_params(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
            """Единые параметры сессии БД.

            `statement_timeout` — предохранитель: тяжёлый географический запрос
            не должен держать соединение бесконечно и утаскивать за собой
            требование ТЗ «фильтры ≤ 5 секунд».
            """
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '30s'")
                cursor.execute("SET timezone = 'UTC'")

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


def get_db() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на запрос."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Транзакция для скриптов импорта: коммит при успехе, откат при исключении."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Сбросить engine и фабрику — нужно тестам, меняющим настройки."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
