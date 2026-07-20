"""Конфигурация приложения.

Всё, что зависит от среды, читается из переменных окружения или `.env`.
Секретов в коде нет и быть не должно: `JWT_SECRET` обязателен и не имеет
безопасного значения по умолчанию в рабочем режиме.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Настройки, читаемые из окружения."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Режим ---------------------------------------------------------------

    environment: Literal["dev", "test", "prod"] = "dev"
    debug: bool = False

    # --- База данных ---------------------------------------------------------

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://postgres@127.0.0.1:5433/riskmap"),
        description=(
            "Локальный кластер развёрнут из ZIP-бинарников на порту 5433, "
            "см. docs/audit/07-lokalnyy-postgis.md"
        ),
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Исходные данные -----------------------------------------------------

    source_data_dir: Path = Field(
        default=Path(r"C:\Users\erbot\Downloads\ДЭР"),
        description="Каталог immutable-исходников. Приложение только читает его.",
    )
    data_dir: Path = Field(
        default=REPO_ROOT / "data",
        description="Рабочий каталог проекта: манифест, границы, выгрузки.",
    )

    # --- Безопасность --------------------------------------------------------

    jwt_secret: str = Field(default="", description="Обязателен вне dev/test.")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    """Тайм-аут сессии. ТЗ требует ограниченного времени жизни сессии."""

    password_min_length: int = 12

    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    """Блокировка после серии неудачных входов — требование ТЗ по безопасности."""

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- API -----------------------------------------------------------------

    api_prefix: str = "/api/v1"
    max_upload_mb: int = 50
    """Совпадает с ограничением, заявленным в мастере импорта на референсе."""

    max_page_size: int = 200
    """Верхняя граница server-side пагинации: клиент не может запросить всё разом."""

    @field_validator("source_data_dir", "data_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()

    @model_validator(mode="after")
    def _check_secret(self) -> Settings:
        """В prod пустой секрет — отказ старта, в dev — временный на процесс.

        Молчаливая подстановка постоянного значения по умолчанию была бы
        худшим вариантом: она превращает забытую переменную в уязвимость,
        которую никто не заметит.
        """
        if not self.jwt_secret:
            if self.environment == "prod":
                raise ValueError(
                    "JWT_SECRET обязателен при ENVIRONMENT=prod. "
                    "Сгенерируйте: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            object.__setattr__(self, "jwt_secret", secrets.token_urlsafe(48))
        return self

    @property
    def sqlalchemy_url(self) -> str:
        return str(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Синглтон настроек. Кэш сбрасывается в тестах через `get_settings.cache_clear()`."""
    return Settings()
