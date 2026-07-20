"""Слой 8.7 — хозяйствующие субъекты (организации).

Единица анализа — юридическое лицо, ключ — БИН. 3668 записей.

Три обстоятельства определили устройство этих таблиц.

**Территориальной привязки нет вообще.** Ни района, ни адреса, ни КАТО, ни
координат — ни на одном из десяти листов книги. Поэтому `territory_id` и
`address_id` остаются пустыми, и это не дефект импорта, а состояние данных,
которое обязано быть видно пользователю. Поле
:attr:`Organization.territory_status` существует ровно затем, чтобы «территория
не определена» было явным значением, а не выводом из пустого поля. Придумывать
координаты запрещено: слой в текущем виде на карту не выводится.

**БИН хранится в источнике как целое число.** 763 значения из 3668 (20.8 %)
потеряли ведущие нули: `90340012684` вместо `090340012684`. Джойн с другими
слоями без восстановления нулей теряет пятую часть связей. Поэтому БИН здесь —
строка ровно из 12 знаков с ограничением на уровне БД, а сырое значение
сохраняется отдельно в :class:`Identifier`, чтобы расхождение можно было
показать, а не замолчать.

**Модель обеспечена данными на 41 %.** Из тринадцати индикаторов ТЗ 9.4 реально
считаются четыре. Поля неподключённых индикаторов в модели есть и остаются
пустыми — прятать их нельзя: именно они объясняют, почему у всей выборки
полнота ниже порога серого.

Состав полей сверен с JSON-схемой (draft 2020-12) и листом `Data dictionary`
самой книги.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum
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


class GeocodePrecision(StrEnum):
    """Точность геокодирования адреса.

    Обязательное поле по спецификации UI книги. Если точность — район, точка
    ставится в центроид района и помечается приблизительной. Иначе карта врёт:
    тридцать компаний в центре района выглядят как реальный кластер.
    """

    EXACT = "exact"
    STREET = "street"
    SETTLEMENT = "settlement"
    DISTRICT = "district"
    NONE = "none"


class TerritoryStatus(StrEnum):
    """Состояние территориальной привязки организации."""

    RESOLVED = "resolved"
    NOT_DETERMINED = "not_determined"
    """Штатное состояние всех 3668 организаций: источник не содержит адреса."""

    AMBIGUOUS = "ambiguous"


class KgdUnreliableList(StrEnum):
    """Списки неблагонадёжных налогоплательщиков КГД.

    Перечисление взято из JSON-схемы книги. Ни один из списков сейчас не
    подключён — у portal.kgd.gov.kz нет публичного API. Значения объявлены
    заранее, чтобы при подключении источника не менять схему хранения.
    """

    LZHEPREDPRIYATIE = "lzhepredpriyatie"
    OTSUTSTVUET_PO_ADRESU = "otsutstvuet_po_adresu"
    BANKROT = "bankrot"
    BEZDEYSTVUYUSHCHIY = "bezdeystvuyushchiy"
    REGISTRACIYA_NEDEYSTVITELNA = "registraciya_nedeystvitelna"
    REORGANIZOVAN_S_NARUSHENIEM = "reorganizovan_s_narusheniem"
    NALOGOVAYA_ZADOLZHENNOST = "nalogovaya_zadolzhennost"


class LicenseStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class PersonRoleKind(StrEnum):
    DIRECTOR = "director"
    FOUNDER = "founder"


class IdentifierKind(StrEnum):
    """Вид идентификатора.

    Отдельная сущность нужна из-за ведущих нулей. Идентификаторы приходят из
    источников то строкой, то числом, и «потерянный ноль» — это факт о данных,
    который должен храниться, а не исправляться молча.
    """

    BIN = "bin"
    IIN = "iin"
    KATO = "kato"
    OKED = "oked"
    PARTICIPANT_NUMBER = "participant_number"
    REGISTRATION_NUMBER = "registration_number"


class Address(Base, TimestampMixin, ProvenanceMixin):
    """Адрес регистрации организации.

    Адрес регистрации — не место деятельности, и смешивать их нельзя. Для слоя
    8.7 это не дефект, а суть: индикатор «массовая регистрация по одному
    адресу» работает именно по юридическому адресу.

    Таблица пока остаётся пустой: выгрузки адресов из первоисточника нет, а
    геокодер не выбран. Она создана заранее, потому что от неё зависит
    единственный по-настоящему пространственный индикатор слоя.
    """

    __tablename__ = "addresses"
    __table_args__ = (
        UniqueConstraint("addr_norm", name="uq_address_norm"),
        Index("ix_addresses_territory", "territory_id"),
        CheckConstraint(
            "kato_code IS NULL OR kato_code ~ '^[0-9]{9}$'", name="ck_address_kato_format"
        ),
        CheckConstraint(
            "lat IS NULL OR (lat >= 40.0 AND lat <= 56.0)", name="ck_address_lat_range"
        ),
        CheckConstraint(
            "lon IS NULL OR (lon >= 46.0 AND lon <= 88.0)", name="ck_address_lon_range"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    raw: Mapped[str] = mapped_column(Text, nullable=False, doc="Юридический адрес как в источнике.")
    addr_norm: Mapped[str] = mapped_column(
        String(512), nullable=False, doc="Нормализованный адрес — ключ индикатора B3."
    )

    kato_code: Mapped[str | None] = mapped_column(
        String(9),
        doc=(
            "Код КАТО территории регистрации. В книге слова «КАТО» встречаются "
            "только в проектной документации — самих кодов нет."
        ),
    )
    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="SET NULL")
    )

    lat: Mapped[float | None] = mapped_column()
    lon: Mapped[float | None] = mapped_column()
    geocode_precision: Mapped[GeocodePrecision] = mapped_column(
        String(16),
        nullable=False,
        default=GeocodePrecision.NONE,
        doc="Точность обязательна: без неё приблизительная точка неотличима от точной.",
    )

    organization_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        doc=(
            "Число организаций по этому addr_norm. Это и вход индикатора B3, и "
            "то, что рисуется на карте агрегированным маркером: массовый адрес "
            "виден сам по себе."
        ),
    )

    organizations: Mapped[list[Organization]] = relationship(back_populates="address")

    def __repr__(self) -> str:
        return f"<Address {self.addr_norm[:48]!r} орг.={self.organization_count}>"


class Person(Base, TimestampMixin, ProvenanceMixin):
    """Физическое лицо — руководитель или учредитель.

    Отдельная сущность, а не поле «ФИО директора» в организации: весь смысл
    индикаторов номинального руководства и связей через директора в том, чтобы
    одно и то же лицо было одной записью для всех его организаций.

    ИИН — персональные данные. Он нужен как ключ связей, но показывать его в
    интерфейсе нельзя, и поле помечено соответствующим образом.
    """

    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("iin", name="uq_person_iin"),
        Index("ix_persons_full_name", "full_name"),
        CheckConstraint("iin IS NULL OR iin ~ '^[0-9]{12}$'", name="ck_person_iin_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    iin: Mapped[str | None] = mapped_column(
        String(12),
        doc="ИИН, 12 знаков с ведущими нулями. Персональные данные — не для показа.",
    )
    full_name: Mapped[str | None] = mapped_column(String(512))

    company_count: Mapped[int | None] = mapped_column(
        doc="Число организаций у этого ИИН — вход индикатора B8."
    )
    in_lzhepred_list: Mapped[bool | None] = mapped_column(
        doc=(
            "Директор в списке лжепредпринимателей — категория A4. NULL, а не "
            "False: источник не подключён, и «нет данных» ≠ «не состоит»."
        )
    )

    roles: Mapped[list[OrganizationPersonRole]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Person {self.full_name!r}>"


class Organization(Base, TimestampMixin, ProvenanceMixin):
    """Юридическое лицо — объект слоя 8.7.

    Про уровни риска. Книга даёт два уровня, и оба сохраняются: предварительный
    (по баллу) и строгий (по ТЗ 7.3, с учётом полноты). Официальным считается
    строгий. Предварительный балл показывается рядом с серым уровнем, но в
    фильтрах и агрегатах по уровню такая организация относится к «нет данных»,
    а не к уровню, который подсказывает балл. Именно поэтому уровня два, а не
    один: свести их в одно поле значит потерять либо честность, либо
    информативность.

    Максимальная полнота во всей выборке — 40.9 %, что ниже порога серого в
    50 %. Строгий результат поэтому такой: серых 3645, критических 23. Это не
    ошибка расчёта, а состояние источников.
    """

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("bin", name="uq_organization_bin"),
        Index("ix_organizations_address", "address_id"),
        Index("ix_organizations_risk_level_strict", "risk_level_strict"),
        Index("ix_organizations_category_a", "is_category_a"),
        CheckConstraint("bin ~ '^[0-9]{12}$'", name="ck_organization_bin_format"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_organization_score_range",
        ),
        CheckConstraint(
            "risk_completeness IS NULL "
            "OR (risk_completeness >= 0 AND risk_completeness <= 1)",
            name="ck_organization_completeness_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    bin: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        doc=(
            "БИН ровно из 12 знаков. В источнике хранится числом, 763 значения "
            "потеряли ведущие нули — они восстановлены при импорте."
        ),
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    reg_date: Mapped[date | None] = mapped_column(Date)

    address_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("addresses.id", ondelete="SET NULL"),
        doc="NULL у всех 3668 организаций: адреса в источнике нет.",
    )
    address: Mapped[Address | None] = relationship(back_populates="organizations")

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="SET NULL")
    )
    territory_status: Mapped[TerritoryStatus] = mapped_column(
        String(24),
        nullable=False,
        default=TerritoryStatus.NOT_DETERMINED,
        doc=(
            "Явное состояние привязки. Значение по умолчанию — «не "
            "определена»: у слоя 8.7 нет ни адреса, ни района, ни КАТО, ни "
            "координат, и пользователь должен видеть это прямо."
        ),
    )

    oked_main: Mapped[str | None] = mapped_column(String(5))
    oked_sections: Mapped[list[str] | None] = mapped_column(
        JSONB, doc="Секции ОКЭД, латинские A–U. Вход индикатора B6."
    )
    krp_code: Mapped[int | None] = mapped_column(doc="Код размерности предприятия (КРП).")

    employees_count: Mapped[int | None] = mapped_column()
    tax_paid_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    tax_burden_ratio: Mapped[float | None] = mapped_column(
        doc="Коэффициент налоговой нагрузки — вход B1. Источник КГД не подключён."
    )
    vat_registered: Mapped[bool | None] = mapped_column()

    licenses: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, doc="Лицензии из elicense.kz — вход B9. Источник не подключён."
    )

    address_company_count: Mapped[int | None] = mapped_column(
        doc="Число организаций по одному addr_norm — измеренный вход B3."
    )
    director_company_count: Mapped[int | None] = mapped_column(
        doc="Число организаций у одного ИИН руководителя — измеренный вход B8."
    )
    oked_sections_count: Mapped[int | None] = mapped_column(
        doc=(
            "Число секций ОКЭД — измеренный вход B6. Пусто у 763 организаций, "
            "и именно эти строки дают W_avail = 35 вместо 45."
        )
    )
    no_physical_activity: Mapped[bool | None] = mapped_column(
        doc="Признак отсутствия физической деятельности — измеренный вход B5."
    )
    inactive_kkm_only: Mapped[bool | None] = mapped_column(
        doc="Только неактивный ККМ — промежуточная градация B5 со значением 0.5."
    )

    in_rnu_gz: Mapped[bool | None] = mapped_column(
        doc="В реестре недобросовестных участников госзакупок — категория A1. Подключён."
    )
    rnu_start_date: Mapped[date | None] = mapped_column(Date)
    rnu_end_date: Mapped[date | None] = mapped_column(
        Date, doc="Срок нахождения в РНУ — 24 месяца; «в РНУ на дату» считается по нему."
    )
    in_rnu_quasi: Mapped[bool | None] = mapped_column(
        doc="Категория A2. NULL — источник /rnu_quasi не подключён, колонка пуста."
    )
    in_lzhepred_list: Mapped[bool | None] = mapped_column(
        doc="Категория A3. NULL — у portal.kgd.gov.kz нет публичного API."
    )
    director_in_lzhepred: Mapped[bool | None] = mapped_column(
        doc="Категория A4. NULL — источник не подключён."
    )
    kgd_unreliable_lists: Mapped[list[str] | None] = mapped_column(JSONB)

    is_category_a: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc=(
            "Хотя бы один юридически подтверждённый факт категории A. Делает "
            "уровень критическим независимо от балла — в выборке таких 23, из "
            "них три с баллом 0."
        ),
    )
    category_a_reasons: Mapped[list[str] | None] = mapped_column(
        JSONB, doc="Коды сработавших фактов категории A: A1..A4."
    )

    risk_model_code: Mapped[str | None] = mapped_column(String(32))
    risk_model_version: Mapped[str | None] = mapped_column(String(16))

    risk_raw_score: Mapped[float | None] = mapped_column(doc="S_raw = Σ(w×v).")
    risk_available_weight: Mapped[float | None] = mapped_column(
        doc="W_avail: 45 у 2904 организаций, 35 у 764."
    )
    risk_score: Mapped[float | None] = mapped_column(
        doc="Балл 0–100. Показывается и тогда, когда уровень серый."
    )
    risk_completeness: Mapped[float | None] = mapped_column(
        doc="W_avail/W_total, доля [0,1]. Максимум по выборке — 0.409."
    )

    risk_level_preliminary: Mapped[str | None] = mapped_column(
        String(16),
        doc=(
            "Уровень по одному лишь баллу, без учёта полноты. Информативен, но "
            "не является основанием для вывода."
        ),
    )
    risk_level_strict: Mapped[str | None] = mapped_column(
        String(16),
        doc=(
            "Официальный уровень по ТЗ 7.3. Именно он участвует в фильтрах и "
            "агрегатах; при низкой полноте это «unknown»."
        ),
    )
    risk_is_preliminary: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc="True — балл посчитан, но официальный уровень серый.",
    )
    risk_override_applied: Mapped[str | None] = mapped_column(String(255))
    risk_factors: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        doc=(
            "Расшифровка, включая раздел «не измерено». Для слоя 8.7 он "
            "обязателен: девять индикаторов из тринадцати не подключены, и "
            "пользователь должен видеть, что именно не измерено и почему."
        ),
    )
    risk_notes: Mapped[list[str] | None] = mapped_column(JSONB)

    person_roles: Mapped[list[OrganizationPersonRole]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    identifiers: Mapped[list[Identifier]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.bin} {self.name[:40]!r}>"


class OrganizationPersonRole(Base, TimestampMixin, ProvenanceMixin):
    """Связь «организация — физическое лицо» с ролью.

    Отдельная таблица со сроком действия, а не пара колонок в организации:
    индикатор частой смены руководителей считается именно по истории ролей, и
    перезапись роли поверх старой уничтожила бы данные, ради которых индикатор
    и существует.
    """

    __tablename__ = "organization_person_roles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "person_id", "role", "valid_from", name="uq_org_person_role_period"
        ),
        Index("ix_org_person_roles_person", "person_id"),
        CheckConstraint(
            "share_percent IS NULL OR (share_percent >= 0 AND share_percent <= 100)",
            name="ck_org_person_share_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    organization: Mapped[Organization] = relationship(back_populates="person_roles")

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE"), nullable=False
    )
    person: Mapped[Person] = relationship(back_populates="roles")

    role: Mapped[PersonRoleKind] = mapped_column(String(16), nullable=False)
    share_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), doc="Доля в уставном капитале для учредителя."
    )

    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(
        Date, doc="NULL — роль действует. Смена руководителя закрывает период, а не удаляет строку."
    )

    def __repr__(self) -> str:
        return f"<OrganizationPersonRole {self.role} org={self.organization_id}>"


class Identifier(Base, TimestampMixin, ProvenanceMixin):
    """Идентификатор в том виде, в каком он пришёл из источника, и в каноническом.

    Эта таблица существует ради одной ловушки. Числовые идентификаторы теряют
    ведущие нули при выгрузке: 763 БИН из 3668 в слое 8.7 и все 4842
    регистрационных номера экспертизы в слое 8.6. Восстановление тривиально, но
    молчаливое: после `zfill` уже не видно, что данные приходили испорченными.
    Здесь видно — :attr:`leading_zeros_restored` фиксирует факт, а
    :attr:`raw_value` сохраняет исходное написание.
    """

    __tablename__ = "identifiers"
    __table_args__ = (
        UniqueConstraint("kind", "normalized_value", "organization_id", name="uq_identifier_value"),
        Index("ix_identifiers_normalized", "kind", "normalized_value"),
        CheckConstraint(
            "organization_id IS NOT NULL OR person_id IS NOT NULL",
            name="ck_identifier_has_owner",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[IdentifierKind] = mapped_column(String(24), nullable=False)

    raw_value: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="Значение как в источнике, включая потерянные нули."
    )
    normalized_value: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="Каноническая форма: БИН и ИИН — 12 знаков, КАТО — 9."
    )
    leading_zeros_restored: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc="True — исходное значение было короче канонического.",
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    organization: Mapped[Organization | None] = relationship(back_populates="identifiers")

    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="CASCADE")
    )

    def __repr__(self) -> str:
        return f"<Identifier {self.kind}={self.normalized_value}>"


__all__ = [
    "Address",
    "GeocodePrecision",
    "Identifier",
    "IdentifierKind",
    "KgdUnreliableList",
    "LicenseStatus",
    "Organization",
    "OrganizationPersonRole",
    "Person",
    "PersonRoleKind",
    "TerritoryStatus",
]
