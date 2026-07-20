"""Базовый класс моделей и общие миксины.

Ключевое соглашение всего проекта: **у каждой бизнес-записи есть происхождение**.
Откуда пришла строка, из какого файла и какой строки, когда импортирована, на
какую дату актуальны данные и прошла ли запись валидацию — без этого нельзя ни
объяснить пользователю оценку риска, ни повторить импорт, ни откатить версию.
Поэтому `ProvenanceMixin` подмешивается во все таблицы фактов.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Общий декларативный базовый класс."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[str]: JSONB,
    }


class TimestampMixin:
    """Технические отметки времени строки."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=utcnow,
        nullable=False,
    )


class ProvenanceMixin:
    """Происхождение бизнес-записи.

    `natural_key` — устойчивый ключ записи в терминах источника (номер договора,
    БИН+период и т. п.). Именно по нему выполняется upsert, что делает импорт
    идемпотентным: повторный запуск не создаёт дублей.

    `data_as_of` — дата, на которую актуальны сами данные, а не дата загрузки.
    Их постоянно путают, и из-за этого в отчёт попадает «свежая» цифра
    полугодовой давности. Поэтому поля разведены.
    """

    # `use_alter` разрывает цикл в графе таблиц. Территории несут происхождение
    # и потому ссылаются на задание импорта; задание ссылается на пользователя,
    # запустившего его; пользователь ограничен территорией. Ни одну из трёх
    # связей нельзя убрать по существу, поэтому ограничение навешивается
    # отдельным ALTER после создания таблиц, а не встраивается в CREATE TABLE.
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_datasets.id", ondelete="SET NULL", use_alter=True),
        index=True,
    )
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("import_jobs.id", ondelete="SET NULL", use_alter=True),
        index=True,
    )
    source_row_ref: Mapped[str | None] = mapped_column(
        String(255),
        doc="Адрес исходной строки, например «Расчёт по договорам!A42», для точной трассировки.",
    )
    natural_key: Mapped[str | None] = mapped_column(String(255), index=True)

    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    data_as_of: Mapped[date | None] = mapped_column(Date)

    validation_status: Mapped[str] = mapped_column(
        String(24),
        default="ok",
        nullable=False,
        doc="ok | warning | error — результат проверок строки при импорте.",
    )
    validation_notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    data_version: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
        doc="Логическая версия данных. Откат версии не удаляет строки, а снимает актуальность.",
    )
    is_current: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        doc="False у строк, вытесненных более новой логической версией.",
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """Первичный ключ-UUID.

    UUID, а не автоинкремент: импорт идёт партиями из нескольких источников, и
    генерировать ключи независимо от порядка вставки удобнее и безопаснее.
    """
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


__all__ = ["Base", "Index", "ProvenanceMixin", "TimestampMixin", "utcnow", "uuid_pk"]
