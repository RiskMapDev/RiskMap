"""Слой 8.5 — субсидии животноводству и государственная поддержка.

Три таблицы: программа субсидирования, получатель и выплата. Разделение
повторяет устройство книги-источника, где витрина риска считается по
получателям, а сырьё лежит по выплатам, и склеивать их в одну таблицу нельзя:
у получателя 21 521 выплата на 3413 лиц, и агрегаты — самостоятельный факт с
собственным происхождением.

Почему территория допускает NULL. У 66 получателей из 3413 и у 96 выплат из
21 521 район в источнике не указан. Это не брак импорта и не повод отбросить
строку: деньги выплачены, получатель существует, неизвестен только район.
Обязательный внешний ключ вынудил бы либо выбросить эти записи из системы,
либо приписать им «прочее» — оба варианта искажают картину сильнее, чем
честный NULL, который видно в фильтре «территория не определена».

Почему БИН/ИИН — строка ровно из 12 символов. У 70 получателей идентификатор
начинается с нуля. Числовой тип съедает ведущий ноль, и такой получатель
перестаёт связываться с другими слоями — теряется пятая часть связей. Ограничение
длины стоит на уровне БД, чтобы обрезанный идентификатор не доехал до витрины.

Почему баллов два. `risk_score` — оценка по методике проекта: незаполненный
индикатор не измерен, и балл нормируется на доступный вес. `book_risk_score` —
воспроизведение семантики Excel, где пустая ячейка суммируется как ноль. Второй
нужен только для сверки с контрольными числами книги и хранится рядом, а не
вместо: расхождение между ними — это ровно та цена, которую книга платит за
неразличение пустоты и нуля, и её нужно видеть, а не прятать.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, uuid_pk
from app.db.models.territory import Territory

XIN_LENGTH = 12
"""Длина БИН/ИИН. Ровно 12 знаков во всех 3413 записях книги 8.5."""

MONEY = Numeric(18, 2)
"""Деньги. Суммарные субсидии — 67.5 млрд ₸, запас по разрядности трёхкратный."""

SHARE = Numeric(9, 6)
"""Доли и коэффициенты источника: хранятся как есть, без округления."""


class SubsidyProgram(Base, TimestampMixin, ProvenanceMixin):
    """Программа субсидирования — значение поля `SubsidiesName`.

    Отдельная таблица, потому что наименование программы в источнике длиной до
    321 символа и повторяется в каждой из 21 521 выплаты. Вид животноводства
    привязан к программе однозначно (проверено: ни одна из 46 программ не
    встречается с двумя разными `AnimalType`), поэтому он живёт здесь, а не в
    выплате.
    """

    __tablename__ = "subsidy_programs"
    __table_args__ = (
        UniqueConstraint("code", name="uq_subsidy_program_code"),
        Index("ix_subsidy_programs_animal_type", "animal_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Устойчивый код программы: усечённый sha256 наименования из источника.",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, doc="SubsidiesName как в книге.")
    animal_type: Mapped[str | None] = mapped_column(
        String(128), doc="AnimalType: вид субсидируемого животноводства."
    )

    payments: Mapped[list[SubsidyPayment]] = relationship(back_populates="program")

    def __repr__(self) -> str:
        return f"<SubsidyProgram {self.code} {self.name[:40]!r}>"


class SubsidyRecipient(Base, TimestampMixin, ProvenanceMixin):
    """Получатель субсидий — единица оценки риска слоя 8.5.

    Хранит и входы индикаторов (доли, счётчики), и сами нормированные значения
    s1..s5, и результат. Входы нужны затем, чтобы объяснить пользователю балл
    словами источника, а не только числом.
    """

    __tablename__ = "subsidy_recipients"
    __table_args__ = (
        UniqueConstraint("xin", "data_version", name="uq_subsidy_recipient_xin_version"),
        CheckConstraint(f"char_length(xin) = {XIN_LENGTH}", name="ck_subsidy_recipient_xin_len"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_subsidy_recipient_score_range",
        ),
        Index("ix_subsidy_recipients_territory", "territory_id"),
        Index("ix_subsidy_recipients_level", "risk_level"),
        Index("ix_subsidy_recipients_xin", "xin"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    xin: Mapped[str] = mapped_column(
        String(XIN_LENGTH),
        nullable=False,
        doc="БИН/ИИН, ровно 12 знаков. Ведущие нули значимы и обязаны сохраняться.",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    director_name: Mapped[str | None] = mapped_column(
        String(255), doc="Руководитель — ключ индикатора аффилированности s3."
    )

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="RESTRICT"),
        doc="NULL — район в источнике не указан либо название не опознано.",
    )
    territory: Mapped[Territory | None] = relationship("Territory")
    territory_name_raw: Mapped[str | None] = mapped_column(
        String(255), doc="Название района дословно из книги — для разбора несопоставленных."
    )
    territory_resolution: Mapped[str] = mapped_column(
        String(24),
        default="resolved",
        nullable=False,
        doc="resolved | not_found | ambiguous | empty — итог сопоставления названия.",
    )

    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payments_count: Mapped[int] = mapped_column(nullable=False)
    programs_count: Mapped[int] = mapped_column(nullable=False)
    animal_types_count: Mapped[int | None] = mapped_column()

    district_share: Mapped[Decimal | None] = mapped_column(
        SHARE, doc="Доля получателя в субсидиях района. NULL — район неизвестен."
    )
    oblast_share: Mapped[Decimal | None] = mapped_column(SHARE)
    affiliated_count: Mapped[int | None] = mapped_column(
        doc="Сколько получателей у того же руководителя."
    )
    anomalous_payment_share: Mapped[Decimal | None] = mapped_column(SHARE)
    amount_outlier_share: Mapped[Decimal | None] = mapped_column(SHARE)

    # Нормированные индикаторы. NULL — «не измерено», и это не то же самое,
    # что 0.0: см. модульный docstring и app/risk/core.py.
    s1_concentration: Mapped[float | None] = mapped_column(Float)
    s2_repetition: Mapped[float | None] = mapped_column(Float)
    s3_affiliation: Mapped[float | None] = mapped_column(Float)
    s4_process_anomaly: Mapped[float | None] = mapped_column(Float)
    s5_amount_outlier: Mapped[float | None] = mapped_column(Float)

    model_code: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="Версия модели на момент расчёта: правка весов не должна переписывать историю.",
    )

    risk_score: Mapped[float | None] = mapped_column(
        Float, doc="R по методике проекта, 0..100. Пересчитан, а не прочитан из книги."
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_completeness: Mapped[float] = mapped_column(
        Float, nullable=False, doc="Доля измеренного веса, 0..1."
    )
    risk_exposure: Mapped[Decimal | None] = mapped_column(
        MONEY, doc="Сумма × R / 100 — материальность риска в тенге."
    )

    book_risk_score: Mapped[float | None] = mapped_column(
        Float, doc="R в семантике Excel (пустая ячейка = 0). Только для сверки с книгой."
    )
    book_risk_level: Mapped[str | None] = mapped_column(String(16))
    book_risk_exposure: Mapped[Decimal | None] = mapped_column(MONEY)
    book_rank: Mapped[int | None] = mapped_column(
        doc="Номер строки в книге: она отсортирована по убыванию R."
    )

    factors: Mapped[dict[str, Any] | None] = mapped_column(
        doc="Расшифровка вклада каждого индикатора — то, что видит пользователь в карточке."
    )

    payments: Mapped[list[SubsidyPayment]] = relationship(
        back_populates="recipient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SubsidyRecipient {self.xin} R={self.risk_score} {self.risk_level}>"


class SubsidyPayment(Base, TimestampMixin, ProvenanceMixin):
    """Одна выплата (заявка) — строка листа «Данные».

    Даты хранятся без часового пояса: в источнике это строки вида
    `2022-12-18T17:39:13` без зоны, и приписывать им UTC значило бы выдумать
    сведения, которых в книге нет.
    """

    __tablename__ = "subsidy_payments"
    __table_args__ = (
        UniqueConstraint("bid_number", "data_version", name="uq_subsidy_payment_bid_version"),
        CheckConstraint("amount_total >= 0", name="ck_subsidy_payment_amount_non_negative"),
        Index("ix_subsidy_payments_recipient", "recipient_id"),
        Index("ix_subsidy_payments_territory", "territory_id"),
        Index("ix_subsidy_payments_program", "program_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subsidy_recipients.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient: Mapped[SubsidyRecipient] = relationship(back_populates="payments")

    program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subsidy_programs.id", ondelete="RESTRICT")
    )
    program: Mapped[SubsidyProgram | None] = relationship(back_populates="payments")

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="RESTRICT"),
        doc="NULL — DistrictName пуст (96 записей) либо название не опознано.",
    )
    territory: Mapped[Territory | None] = relationship("Territory")
    territory_name_raw: Mapped[str | None] = mapped_column(String(255))

    bid_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="BidNumber, 12 или 14 знаков. У 21 179 записей есть ведущий ноль — строка обязательна.",
    )
    bid_status: Mapped[str | None] = mapped_column(
        String(64),
        doc="BidStatus. Всегда «Исполнена» — в модель риска не входит (примечание методики).",
    )
    animal_type: Mapped[str | None] = mapped_column(String(128))

    positive_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    local_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    republic_payment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), doc="Заполнено у 3 записей из 21 521."
    )

    subsidies_norm: Mapped[Decimal | None] = mapped_column(MONEY)
    amount_local: Mapped[Decimal | None] = mapped_column(MONEY)
    amount_republic: Mapped[Decimal | None] = mapped_column(MONEY)
    amount_owed: Mapped[Decimal | None] = mapped_column(MONEY)
    amount_total: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, doc="Local + Republic — расчётная колонка книги."
    )

    decision_to_payment_days: Mapped[int | None] = mapped_column(
        doc="Дней «решение → выплата». Диапазон в источнике −1 … 333."
    )
    flag_paid_before_decision: Mapped[bool] = mapped_column(
        default=False, nullable=False, doc="Вход индикатора s4. Взведён у 1209 записей."
    )
    flag_abnormal_lag: Mapped[bool] = mapped_column(
        default=False, nullable=False, doc="Лаг > 170 дней. Взведён у 1052 записей."
    )
    flag_amount_outlier: Mapped[bool] = mapped_column(
        default=False, nullable=False, doc="Вход индикатора s5. Взведён у 882 записей."
    )

    def __repr__(self) -> str:
        return f"<SubsidyPayment {self.bid_number} {self.amount_total}>"


__all__ = [
    "MONEY",
    "SHARE",
    "XIN_LENGTH",
    "SubsidyPayment",
    "SubsidyProgram",
    "SubsidyRecipient",
]
