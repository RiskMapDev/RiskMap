"""Слой 8.4 «Госзакупки»: заказчики, поставщики, объявления, лоты, договоры.

Шесть таблиц повторяют структуру источника, но с тремя поправками, каждая из
которых сделана против конкретного дефекта данных.

**БИН хранится строкой из 12 знаков.** В источниках он записан числом, из-за
чего у 763 организаций из 3 668 потеряны ведущие нули: `000440010133`
превращается в `440010133`. Числовой тип колонки увековечил бы эту потерю,
поэтому здесь `String(12)` с ограничением на длину, а восстановление
выполняется импортёром.

**Номер договора хранится строкой.** В расчётном листе книги он `str`, в
сырых листах — `int`. Тип выбран один, и приведение сделано на входе.

**Район поставщика — отдельное поле рядом со ссылкой на справочник.**
Геопривязка слоя выполняется по юридическому адресу поставщика (355 договоров
из 355), а не по заказчику (129 из 355) и не по месту поставки. Это решение
книги, и оно имеет цену: юридический адрес — место регистрации, а не место
исполнения договора. Поле `district_source_name` хранит то, что было
разобрано из адреса, чтобы это допущение оставалось видимым, а не растворялось
в ссылке на территорию.

Отдельно про `г. Алматы`. Это город республиканского значения, но в книге он
отнесён к Алматинской области — потому что так записан юридический адрес.
Модель это не «чинит»: конфликт с административным делением реален и должен
быть виден при построении хороплета.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, uuid_pk

_MONEY = Numeric(20, 2)
_RATIO = Numeric(10, 6)

BIN_LENGTH = 12


class Supplier(Base, TimestampMixin, ProvenanceMixin):
    """Поставщик — организация, с которой заключены договоры.

    Признаки профиля приходят из слоя 8.7 (`organization_profile`) и делятся
    на две неравные группы. `in_rnu_gz` и `in_lzhepred_list` — установленные
    юридические факты, дающие категорию A и критический уровень независимо от
    балла. Остальные (`no_physical_activity`, `mass_address`,
    `nominal_director`, `high_oked_diversity`) — расчётные признаки, питающие
    метрики B7 и B9. Смешивать их нельзя: первые не обсуждаются, вторые
    взвешиваются.
    """

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("bin", name="uq_supplier_bin"),
        Index("ix_suppliers_category_a", "in_rnu_gz", "in_lzhepred_list"),
        Index("ix_suppliers_territory", "territory_id"),
        CheckConstraint("length(bin) = 12", name="ck_supplier_bin_length"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    bin: Mapped[str] = mapped_column(
        String(BIN_LENGTH),
        nullable=False,
        doc="БИН из 12 знаков с восстановленными ведущими нулями.",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # --- категория A: юридические факты --------------------------------------

    in_rnu_gz: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="Реестр недобросовестных участников госзакупок — признак A1.",
    )
    in_lzhepred_list: Mapped[bool] = mapped_column(
        nullable=False, default=False, doc="Список лжепредприятий — признак A2."
    )

    # --- расчётные признаки профиля ------------------------------------------

    no_physical_activity: Mapped[bool] = mapped_column(nullable=False, default=False)
    high_oked_diversity: Mapped[bool] = mapped_column(nullable=False, default=False)
    mass_address: Mapped[bool] = mapped_column(nullable=False, default=False)
    nominal_director: Mapped[bool] = mapped_column(nullable=False, default=False)

    n_contracts: Mapped[int | None] = mapped_column(
        doc="Число договоров по слою 8.7. В источнике записано строкой вида «5.0»."
    )
    max_direct_one_customer: Mapped[int | None] = mapped_column()
    pct_terminated: Mapped[Decimal | None] = mapped_column(
        _RATIO, doc="Доля расторгнутых договоров. Пусто у 82 % организаций источника."
    )

    layer_8_7_points: Mapped[int | None] = mapped_column(
        doc="Балл слоя 8.7 — приходит готовым, здесь не пересчитывается."
    )
    layer_8_7_level: Mapped[str | None] = mapped_column(String(24))

    # --- геопривязка ---------------------------------------------------------

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="RESTRICT")
    )
    legal_address_raw: Mapped[str | None] = mapped_column(
        Text, doc="Юридический адрес строкой, как в реестре налогоплательщиков."
    )
    region_source_name: Mapped[str | None] = mapped_column(String(255))
    district_source_name: Mapped[str | None] = mapped_column(
        String(255),
        doc=(
            "Район, разобранный из юридического адреса. Это место регистрации, "
            "а не место исполнения договора — ограничение названо в книге."
        ),
    )

    contracts: Mapped[list[Contract]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )

    @property
    def is_category_a(self) -> bool:
        return self.in_rnu_gz or self.in_lzhepred_list

    def __repr__(self) -> str:
        return f"<Supplier {self.bin} {self.name[:40]!r} cat_a={self.is_category_a}>"


class Customer(Base, TimestampMixin, ProvenanceMixin):
    """Заказчик закупки.

    Имени заказчика в расчётном листе книги доверять нельзя: оно обрезано до
    60 знаков, из-за чего разные организации становятся неразличимы. Здесь
    хранится полное имя из листа `lots`, а `name_truncated` — то, что стояло в
    расчётном листе, чтобы сверка с книгой оставалась возможной.

    БИН заказчика известен не всегда: в `lots_details` он заполнен у 221 лота
    из 381 и у 45 из них потерял ведущие нули. Поэтому ключом служит имя, а
    БИН необязателен.
    """

    __tablename__ = "procurement_customers"
    __table_args__ = (
        UniqueConstraint("name", name="uq_customer_name"),
        Index("ix_customers_bin", "bin"),
        CheckConstraint("bin IS NULL OR length(bin) = 12", name="ck_customer_bin_length"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    name: Mapped[str] = mapped_column(Text, nullable=False, doc="Полное имя из листа lots.")
    name_truncated: Mapped[str | None] = mapped_column(
        String(64), doc="Имя в том усечённом виде, в каком оно стоит в расчётном листе."
    )
    bin: Mapped[str | None] = mapped_column(String(BIN_LENGTH))

    is_placeholder: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc=(
            "True для заглушки «—», стоящей у 131 договора без объявления. "
            "Это не заказчик, а отсутствие данных, и в группировки B3/B4 "
            "такие строки попадать не должны."
        ),
    )

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="RESTRICT")
    )

    def __repr__(self) -> str:
        return f"<Customer {self.name[:48]!r} bin={self.bin}>"


class Procurement(Base, TimestampMixin, ProvenanceMixin):
    """Объявление о закупке.

    Есть не у каждого договора: `announcement_number` пуст у 131 договора из
    355 — это закупки из одного источника и через электронный магазин, которые
    объявления не имеют. Отсутствие объявления делает недоступной метрику B2
    (число заявок), и это именно «не измерено», а не «конкуренция в норме».
    """

    __tablename__ = "procurements"
    __table_args__ = (
        UniqueConstraint("announcement_number", name="uq_procurement_announcement_number"),
        Index("ix_procurements_announcement_id", "announcement_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    announcement_id: Mapped[str] = mapped_column(String(32), nullable=False)
    announcement_number: Mapped[str] = mapped_column(
        String(32), nullable=False, doc="Формат «11456831-1»."
    )

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_customers.id", ondelete="RESTRICT")
    )
    customer: Mapped[Customer | None] = relationship()

    submitted_bids: Mapped[int | None] = mapped_column(
        doc=(
            "Число поданных заявок. Пусто у 27 % лотов — тогда B2 недоступна. "
            "Ноль заявок и отсутствие сведений о заявках — разные вещи."
        )
    )

    lots: Mapped[list[Lot]] = relationship(
        back_populates="procurement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Procurement {self.announcement_number} bids={self.submitted_bids}>"


class Lot(Base, TimestampMixin, ProvenanceMixin):
    """Лот объявления.

    Код КАТО места поставки в источнике склеен с адресом в одной ячейке
    (`'101010000, область Абай, г.Семей…'`) и заполнен у 191 лота из 381.
    В геопривязке слоя 8.4 он **не используется** — привязка идёт по адресу
    поставщика. Но сохраняется: это единственный официальный территориальный
    код во всей книге, и он понадобится, когда появится справочник КАТО.
    """

    __tablename__ = "procurement_lots"
    __table_args__ = (
        UniqueConstraint("procurement_id", "lot_number", name="uq_lot_procurement_number"),
        Index("ix_lots_delivery_kato", "delivery_kato"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    procurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurements.id", ondelete="CASCADE"), nullable=False
    )
    procurement: Mapped[Procurement] = relationship(back_populates="lots")

    lot_id: Mapped[str | None] = mapped_column(String(32))
    lot_number: Mapped[str | None] = mapped_column(String(64))
    lot_name: Mapped[str | None] = mapped_column(Text)
    lot_status: Mapped[str | None] = mapped_column(String(64))

    tru_code: Mapped[str | None] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal | None] = mapped_column(_MONEY)
    planned_sum: Mapped[Decimal | None] = mapped_column(_MONEY)

    delivery_kato: Mapped[str | None] = mapped_column(
        String(9), doc="Код КАТО места поставки, отделённый от адреса при импорте."
    )
    delivery_address: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Lot {self.lot_number} kato={self.delivery_kato}>"


class Contract(Base, TimestampMixin, ProvenanceMixin):
    """Договор — единица анализа слоя 8.4.

    Здесь же хранится результат расчёта риска, потому что единица анализа и
    единица оценки в этом слое совпадают. Сохраняются все промежуточные
    величины методики (`s_raw`, `w_avail`, `s_norm`, `k`), а не только итог:
    объяснить пользователю балл 67,1 без них невозможно, а пересчитывать их
    на лету — значит каждый раз поднимать доп. соглашения и профиль
    поставщика.

    Про `risk_level` и категорию A. Уровень «критический» в этой таблице
    получается двумя разными путями: по баллу (порог 75, на данных книги
    недостижим) и по категории A (48 договоров). `override_reason` хранит,
    каким именно, — иначе на карте нельзя будет отличить «посчитали
    критическим» от «признали критическим по реестру».
    """

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("contract_id", name="uq_contract_source_id"),
        Index("ix_contracts_supplier", "supplier_id"),
        Index("ix_contracts_customer", "customer_id"),
        Index("ix_contracts_level", "risk_level"),
        Index("ix_contracts_district", "district_source_name"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_contract_score_range",
        ),
        CheckConstraint(
            "w_avail IS NULL OR (w_avail >= 0 AND w_avail <= 100)",
            name="ck_contract_w_avail_range",
        ),
        CheckConstraint(
            "significance_multiplier IS NULL "
            "OR (significance_multiplier >= 1 AND significance_multiplier <= 1.3)",
            name="ck_contract_k_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    contract_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Номер договора строкой: в сырых листах он int, в расчётном — str.",
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    supplier: Mapped[Supplier] = relationship(back_populates="contracts")

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurement_customers.id", ondelete="RESTRICT")
    )
    customer: Mapped[Customer | None] = relationship()

    procurement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("procurements.id", ondelete="RESTRICT")
    )
    procurement: Mapped[Procurement | None] = relationship()

    # --- предмет и суммы -----------------------------------------------------

    brief_content_ru: Mapped[str | None] = mapped_column(Text)
    subject_type: Mapped[str | None] = mapped_column(
        String(32), doc="Товар / Работа / Услуга — входит в метрику B8."
    )

    planned_method: Mapped[str | None] = mapped_column(
        Text,
        doc=(
            "Способ закупки. У трёх договоров книги записан заглушкой 'nan' — "
            "это отсутствие сведений, и метрика B1 у них не измерена."
        ),
    )
    actual_method: Mapped[str | None] = mapped_column(Text)

    planned_amount: Mapped[Decimal | None] = mapped_column(_MONEY)
    final_amount: Mapped[Decimal | None] = mapped_column(
        _MONEY, doc="Сумма договора. В источнике записана строкой вида «11 953 000.00»."
    )
    actual_amount: Mapped[Decimal | None] = mapped_column(_MONEY)

    planned_exec_date: Mapped[date | None] = mapped_column(Date)
    actual_exec_date: Mapped[date | None] = mapped_column(Date)

    contract_status: Mapped[str | None] = mapped_column(String(64))
    is_terminated: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="Любой из статусов расторжения. 43 договора из 355; входит в коэффициент K.",
    )

    # --- геопривязка по поставщику -------------------------------------------

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="RESTRICT")
    )
    region_source_name: Mapped[str | None] = mapped_column(String(255))
    district_source_name: Mapped[str | None] = mapped_column(String(255))

    # --- результат расчёта ---------------------------------------------------

    model_code: Mapped[str] = mapped_column(String(16), nullable=False, default="8.4")
    model_version: Mapped[str] = mapped_column(String(16), nullable=False)

    s_raw: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3), doc="Взвешенная сумма по доступным метрикам."
    )
    w_avail: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), doc="Суммарный вес доступных метрик; полный вес модели — 100."
    )
    s_norm: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3), doc="Балл до умножения на коэффициент значимости."
    )
    significance_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), doc="Коэффициент K ∈ {1,00; 1,15; 1,30}."
    )
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    risk_level: Mapped[str | None] = mapped_column(String(16))

    completeness: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 5),
        doc="W_avail / 100. Ниже 0,5 уровень становится серым — если не сработала категория A.",
    )
    is_preliminary: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="Балл посчитан, но полноты не хватает: показывать с пометкой, выводов не делать.",
    )
    override_reason: Mapped[str | None] = mapped_column(
        String(255),
        doc="Чем именно переопределён уровень. Пусто — уровень получен по баллу.",
    )

    indicator_values: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, doc="Значения B1…B9; отсутствующий ключ означает «не измерено»."
    )
    factors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation_ru: Mapped[str | None] = mapped_column(Text)

    additions: Mapped[list[ContractAddition]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Contract {self.contract_id} score={self.risk_score} level={self.risk_level}>"


class ContractAddition(Base, TimestampMixin, ProvenanceMixin):
    """Дополнительное соглашение к договору.

    583 записи по 354 договорам. Все три даты в источнике — Excel-серийные
    числа (`45415.549363425926`), а не даты, причём в одной колонке смешаны
    int и float; в `contract_details` при этом даты настоящие. Преобразование
    выполняет импортёр, здесь уже нормальные `date`.

    `changes_term` определяется по вхождению слова «срок» в обоснование.
    Обоснование пусто у 355 записей из 583, и в этом случае признак не
    «отсутствует продление», а «неизвестно» — что и делает метрику B5
    заниженной по построению.
    """

    __tablename__ = "contract_additions"
    __table_args__ = (
        Index("ix_contract_additions_contract", "contract_id"),
        Index("ix_contract_additions_creation", "creation_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    contract: Mapped[Contract] = relationship(back_populates="additions")

    sequence_number: Mapped[int | None] = mapped_column(
        doc="Порядковый номер версии в хронологии по дате создания, начиная с 1."
    )

    creation_date: Mapped[date | None] = mapped_column(Date)
    conclusion_date: Mapped[date | None] = mapped_column(Date)
    planned_exec_date: Mapped[date | None] = mapped_column(Date)

    final_total_amount: Mapped[Decimal | None] = mapped_column(
        _MONEY, doc="Сумма договора в этой версии — основа метрики B6."
    )
    actual_total_amount: Mapped[Decimal | None] = mapped_column(_MONEY)

    justification: Mapped[str | None] = mapped_column(Text)
    changes_term: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="Обоснование содержит слово «срок». Пустое обоснование — не отрицание признака.",
    )

    def __repr__(self) -> str:
        return f"<ContractAddition {self.contract_id} #{self.sequence_number}>"


__all__ = [
    "Contract",
    "ContractAddition",
    "Customer",
    "Lot",
    "Procurement",
    "Supplier",
]
