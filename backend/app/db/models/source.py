"""Источники данных, задания импорта и журнал качества.

Эти таблицы отвечают на четыре вопроса о любой цифре в системе: откуда она,
когда попала, что при этом пошло не так и как всё это откатить.

Импорт устроен идемпотентно: повторный запуск того же файла не создаёт дублей,
потому что записи сопоставляются по естественному ключу. Откат не удаляет
данные, а снимает признак актуальности с логической версии — так остаётся
возможность объяснить, на основании чего была построена вчерашняя оценка.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid_pk


class SourceFile(Base, TimestampMixin):
    """Физический файл-источник, зафиксированный по хешу.

    Хеш обязателен: он единственный надёжный способ убедиться, что книга не
    менялась между импортами. Имя файла для этого не годится — часть имён
    хранится в Unicode NFD и совпадает с NFC-вариантом только после свёртки.
    """

    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("sha256", name="uq_source_file_sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()

    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        doc="Имя в NFC + casefold — ключ поиска, устойчивый к NFD.",
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    origin: Mapped[str] = mapped_column(
        String(64),
        default="source_data_dir",
        nullable=False,
        doc="source_data_dir — файл из immutable-комплекта; upload — загружен через мастер.",
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    datasets: Mapped[list[SourceDataset]] = relationship(back_populates="source_file")

    def __repr__(self) -> str:
        return f"<SourceFile {self.file_name!r} {self.sha256[:12]}>"


class SourceDataset(Base, TimestampMixin):
    """Логический набор данных внутри файла — как правило, лист книги.

    Роль листа фиксируется явно, потому что смешивать сырьё с методикой нельзя:
    лист «Методика» описывает, как считать, а не что показывать. Строки из него
    не должны превращаться в объекты на карте.
    """

    __tablename__ = "source_datasets"
    __table_args__ = (
        UniqueConstraint("source_file_id", "sheet_name", name="uq_dataset_file_sheet"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False
    )
    source_file: Mapped[SourceFile] = relationship(back_populates="datasets")

    layer_code: Mapped[str | None] = mapped_column(
        String(16), doc="Код слоя по ТЗ: 8.3, 8.4, 8.5, 8.6, 8.7."
    )
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="raw | model_config | reconciliation | presentation — роль листа.",
    )

    row_count: Mapped[int | None] = mapped_column()
    header_row: Mapped[int | None] = mapped_column(
        doc="Номер строки заголовка. В книге 8.4 он третий, а не первый."
    )
    data_as_of: Mapped[date | None] = mapped_column(Date)
    columns_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<SourceDataset {self.layer_code} {self.sheet_name!r} role={self.role}>"


class ImportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DRY_RUN = "dry_run"
    """Прогон без записи: показать, что произойдёт, ничего не меняя."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ImportJob(Base, TimestampMixin):
    """Одно задание импорта."""

    __tablename__ = "import_jobs"
    __table_args__ = (Index("ix_import_jobs_status_started", "status", "started_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()

    source_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_files.id", ondelete="SET NULL")
    )
    layer_code: Mapped[str | None] = mapped_column(String(16))
    importer: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[ImportStatus] = mapped_column(
        String(24), default=ImportStatus.PENDING, nullable=False
    )
    is_dry_run: Mapped[bool] = mapped_column(default=False, nullable=False)

    data_version: Mapped[int] = mapped_column(default=1, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows_read: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_created: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(default=0, nullable=False)

    territory_match_report: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        doc="Сводка сопоставления территорий: сколько не опознано и почему.",
    )
    reconciliation: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        doc="Сверка с контрольными значениями книги: ожидалось / получено / расхождение.",
    )

    started_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    issues: Mapped[list[DataQualityIssue]] = relationship(
        back_populates="import_job", cascade="all, delete-orphan"
    )

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def __repr__(self) -> str:
        return f"<ImportJob {self.importer} {self.status} v{self.data_version}>"


class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DataQualityIssue(Base, TimestampMixin):
    """Замечание к конкретной строке источника.

    Отдельная таблица, а не поле в записи: у одной строки бывает несколько
    проблем, и каждую нужно показать пользователю построчно в мастере импорта.
    Замечания не мешают загрузке данных — они делают неполноту видимой.
    """

    __tablename__ = "data_quality_issues"
    __table_args__ = (
        Index("ix_dq_issues_job_severity", "import_job_id", "severity"),
        Index("ix_dq_issues_code", "code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    import_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False
    )
    import_job: Mapped[ImportJob] = relationship(back_populates="issues")

    severity: Mapped[IssueSeverity] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Машинный код: territory_not_resolved, leading_zeros_lost, и т. п.",
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    source_row_ref: Mapped[str | None] = mapped_column(String(255))
    column_name: Mapped[str | None] = mapped_column(String(255))
    raw_value: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<DataQualityIssue {self.severity} {self.code} {self.source_row_ref}>"
