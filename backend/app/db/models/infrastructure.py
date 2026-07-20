"""Слой 8.6 — инфраструктурные и инвестиционные проекты.

Главное решение этой модели данных принято не из соображений удобства, а по
результату аудита: **в слое 8.6 две несвязанные популяции, и объединять их в
одну таблицу нельзя.**

Проверены все мыслимые кандидаты в общий ключ, и ни один не работает:

* БИН частного партнёра — 0 заполненных из 1014 в реестре поставщиков ГЧП;
* БИН в реестре экспертизы (заказчик, генпроектировщик) — 0 из 4842;
* пересечение нормализованных наименований проекта ГЧП и объекта экспертизы —
  0 совпадений на 1266 × 4781;
* поля «номер заключения» в реестре ГЧП нет, поля «идентификатор проекта ГЧП»
  в реестре экспертизы нет.

Единственная работающая связка лежит целиком внутри контура ГЧП:
`Конкурсы.contest_number` ↔ `Договоры.Номер конкурса`, 12 из 12. Она и
отражена — полем :attr:`PppProject.contest_number`.

Отсюда устройство: общий супертип :class:`ProjectEntity` даёт единый список
объектов слоя для карты, поиска и происхождения записи, а два подтипа —
:class:`PppProject` и :class:`ConstructionExpertiseObject` — живут каждый со
своим набором индикаторов (A1–A7 против B1–B6) и своим полным весом методики
(110 против 90). Супертип намеренно не содержит ни одного поля предметной
области, специфичного для одной из популяций: как только такое поле появится,
начнётся молчаливое склеивание двух разных сущностей.

Второе решение — про территорию. Проекты ГЧП имеют привязку только к области;
районной нет ни в одном из пяти исходных реестров. Поэтому у супертипа есть
:attr:`ProjectEntity.territory_precision`, и для типа A оно принудительно равно
«область». Придумывать координаты запрещено: 65 проектов Алматинской области
физически невозможно разложить по районам, и показать их на районной карте
значит соврать.
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


class ProjectEntityKind(StrEnum):
    """Тип объекта слоя 8.6.

    Значения — дискриминатор наследования. Третьего значения быть не должно:
    любая попытка добавить «общий» тип означает, что кто-то снова пытается
    свести две популяции в одну.
    """

    PPP_PROJECT = "ppp_project"
    """Проект ГЧП — договорная плоскость. 1323 записи, W_total = 110."""

    EXPERTISE_CONCLUSION = "expertise_conclusion"
    """Заключение экспертизы ПСД — проектно-экспертная плоскость. 4842, W_total = 90."""


class TerritoryPrecision(StrEnum):
    """До какого уровня известна территория объекта.

    Отдельное поле, а не «territory_id пуст — значит неизвестно»: разница между
    «район не указан в источнике» и «источник в принципе не содержит района»
    определяет, можно ли объект показывать на районной карте.
    """

    DISTRICT = "district"
    REGION = "region"
    """Известна только область. Штатное состояние всех проектов ГЧП."""

    NONE = "none"


class RiskAssessmentMixin:
    """Результат расчёта риска, сохранённый рядом с объектом.

    Балл хранится всегда, даже когда уровень серый. Это прямое требование
    заказчика: предварительный балл показывается рядом с серым уровнем, но
    официальным уровнем остаётся серый, и `risk_is_preliminary` — тот флаг, по
    которому фильтры и агрегаты обязаны отличать одно от другого.

    Версия модели пишется в строку, а не берётся из «текущей» конфигурации:
    правка веса администратором не должна задним числом переписывать историю
    оценок.
    """

    risk_model_code: Mapped[str | None] = mapped_column(String(32))
    risk_model_version: Mapped[str | None] = mapped_column(String(16))

    risk_raw_score: Mapped[float | None] = mapped_column(doc="S_raw = Σ(w×v) по измеренным.")
    risk_available_weight: Mapped[float | None] = mapped_column(doc="W_avail.")
    risk_normalized_score: Mapped[float | None] = mapped_column(doc="S_norm = 100·S_raw/W_avail.")
    risk_significance_k: Mapped[float | None] = mapped_column(
        doc="Коэффициент значимости K, 1.00–1.30."
    )
    risk_score: Mapped[float | None] = mapped_column(
        doc="Итоговый балл min(100; S_norm·K). NULL — не измерен ни один индикатор."
    )
    risk_completeness: Mapped[float | None] = mapped_column(doc="W_avail/W_total, доля [0,1].")

    risk_level: Mapped[str | None] = mapped_column(
        String(16), doc="low | medium | high | critical | unknown."
    )
    risk_is_preliminary: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc=(
            "True — балл посчитан, но полнота ниже порога. Уровень при этом "
            "серый, и в фильтрах по уровню объект относится к «нет данных»."
        ),
    )
    risk_override_applied: Mapped[str | None] = mapped_column(
        String(255), doc="Сработавшее жёсткое правило, если оно было."
    )
    risk_factors: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        doc=(
            "Расшифровка по индикаторам, включая неизмеренные. Раздел «не "
            "измерено» обязателен к показу: он объясняет низкую полноту."
        ),
    )
    risk_notes: Mapped[list[str] | None] = mapped_column(JSONB)


class ProjectEntity(Base, TimestampMixin, ProvenanceMixin, RiskAssessmentMixin):
    """Супертип объектов слоя 8.6.

    Содержит только то, что действительно общее у обеих популяций: имя,
    территориальная привязка с указанием её точности, оценка риска и
    происхождение записи. Всё предметное — в подтипах.
    """

    __tablename__ = "project_entities"
    # Тип объявлен широко намеренно: подтипы задают собственные наборы
    # ограничений, и без общего типа mypy считает переопределение несовместимым.
    __table_args__: tuple[Any, ...] = (
        Index("ix_project_entities_kind", "kind"),
        Index("ix_project_entities_territory", "territory_id"),
        Index("ix_project_entities_risk_level", "risk_level"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_project_entity_score_range",
        ),
        CheckConstraint(
            "risk_completeness IS NULL "
            "OR (risk_completeness >= 0 AND risk_completeness <= 1)",
            name="ck_project_entity_completeness_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    kind: Mapped[ProjectEntityKind] = mapped_column(String(32), nullable=False)

    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc=(
            "Наименование как в источнике. Хранится полностью: витрины книги "
            "обрезают его до 120–180 знаков, и на обрезанных значениях "
            "группировка объектов даёт 71 объект вместо 52."
        ),
    )

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="SET NULL"),
        doc="NULL — территория не определена. Это видимое пользователю состояние.",
    )
    territory_raw: Mapped[str | None] = mapped_column(
        Text, doc="Строка территории как в источнике, до сопоставления."
    )
    territory_precision: Mapped[TerritoryPrecision] = mapped_column(
        String(16),
        nullable=False,
        default=TerritoryPrecision.NONE,
        doc=(
            "Точность привязки. У проектов ГЧП всегда «region»: районной "
            "привязки нет ни в одном из пяти исходных реестров."
        ),
    )

    has_data_error: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc=(
            "Логическая ошибка в исходных данных, например окончание "
            "строительства раньше начала (5 проектов ГЧП). Такой объект "
            "получает серый уровень независимо от балла."
        ),
    )
    data_error_note: Mapped[str | None] = mapped_column(Text)

    # ruff требует для изменяемого атрибута класса аннотацию ClassVar, а mypy
    # её здесь запрещает: в DeclarativeBase `__mapper_args__` объявлен как
    # атрибут экземпляра, и ClassVar считается несовместимым переопределением.
    # Требования взаимоисключающие, поэтому правило отключается точечно —
    # значение всё равно читается SQLAlchemy один раз при построении маппера
    # и никогда не мутируется.
    __mapper_args__: dict[str, Any] = {  # noqa: RUF012
        "polymorphic_on": "kind",
        "polymorphic_identity": "project_entity",
    }

    def __repr__(self) -> str:
        return f"<ProjectEntity {self.kind} {self.title[:40]!r}>"


class PppProject(ProjectEntity):
    """Проект ГЧП — тип A.

    Единица анализа — проект, 1323 записи. Индикаторы A1–A7, полный вес
    методики 110.

    Про территорию. Поле `Регион` даёт только уровень области, причём с мусором
    («Республика Казахстан (Алматинская област» — обрезано на 40 знаках,
    «Область Абай » с хвостовым пробелом, две опечатки в названии страны).
    Поэтому сырое значение хранится отдельно от результата сопоставления, а
    :attr:`ProjectEntity.territory_precision` у этого подтипа всегда «region».

    Про партнёров. Имя частного партнёра — свободный текст, включая консорциумы
    из нескольких лиц через запятую и точку с запятой. Для индикаторов
    концентрации нужен устойчивый ключ, поэтому рядом с сырым значением лежит
    свёрнутое: только буквы и цифры, регистр снят. Именно такая свёртка
    воспроизводит значения A2 и A3 книги на всех 1323 строках без единого
    расхождения; сравнение по сырой строке даёт 12 и 4 расхождения
    соответственно.
    """

    __tablename__ = "ppp_projects"
    __table_args__ = (
        UniqueConstraint("registry_number", name="uq_ppp_project_registry_number"),
        Index("ix_ppp_projects_private_partner_key", "private_partner_key"),
        Index("ix_ppp_projects_government_partner_key", "government_partner_key"),
        Index("ix_ppp_projects_contest_number", "contest_number"),
    )
    # ruff требует для изменяемого атрибута класса аннотацию ClassVar, а mypy
    # её здесь запрещает: в DeclarativeBase `__mapper_args__` объявлен как
    # атрибут экземпляра, и ClassVar считается несовместимым переопределением.
    # Требования взаимоисключающие, поэтому правило отключается точечно —
    # значение всё равно читается SQLAlchemy один раз при построении маппера
    # и никогда не мутируется.
    __mapper_args__: dict[str, Any] = {  # noqa: RUF012
        "polymorphic_identity": ProjectEntityKind.PPP_PROJECT,
    }

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_entities.id", ondelete="CASCADE"), primary_key=True
    )

    registry_number: Mapped[int] = mapped_column(
        nullable=False, doc="№ п/п реестра проектов ГЧП — устойчивый ключ строки внутри книги."
    )

    region_raw: Mapped[str | None] = mapped_column(Text)
    project_level: Mapped[str | None] = mapped_column(
        String(32), doc="республиканский | местный — вход коэффициента значимости K."
    )
    sector: Mapped[str | None] = mapped_column(String(255))
    object_kind: Mapped[str | None] = mapped_column(String(255))

    status_raw: Mapped[str | None] = mapped_column(String(255))
    is_terminated: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc=(
            "Договор расторгнут. Регистр в источнике плавает: «Расторгнут» 150 "
            "и «расторгнут» 2, всего 152 из 1323."
        ),
    )

    initiative_kind: Mapped[str | None] = mapped_column(
        String(128), doc="Вид инициативы — вход индикатора A7."
    )
    contract_kind: Mapped[str | None] = mapped_column(String(255))
    capacity: Mapped[str | None] = mapped_column(
        String(255), doc="Мощность строкой: единицы измерения в источнике не разделены."
    )

    private_partner_raw: Mapped[str | None] = mapped_column(Text)
    private_partner_key: Mapped[str | None] = mapped_column(
        String(255), doc="Свёрнутое имя частного партнёра — ключ индикаторов A2 и A3."
    )
    government_partner_raw: Mapped[str | None] = mapped_column(Text)
    government_partner_key: Mapped[str | None] = mapped_column(
        String(255),
        doc=(
            "Имя госпартнёра как оно лежит в источнике, включая хвостовые "
            "пробелы. Свёртка здесь недопустима: книга группирует по сырой "
            "строке, и нормализация меняет значение A4 у проекта № 908."
        ),
    )

    contract_date: Mapped[date | None] = mapped_column(Date)
    construction_start: Mapped[date | None] = mapped_column(Date)
    construction_end: Mapped[date | None] = mapped_column(Date)
    operation_start: Mapped[date | None] = mapped_column(Date)
    operation_end: Mapped[date | None] = mapped_column(Date)

    cost_initial: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), doc="Первоначальная стоимость, тыс. тенге."
    )
    investments: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2),
        doc=(
            "Объём привлечённых инвестиций. Ноль в источнике означает «не "
            "заполнено», а не «инвестиций нет»: при нуле индикатор A6 "
            "недоступен, и именно так считает книга."
        ),
    )
    government_participation_form: Mapped[str | None] = mapped_column(Text)

    contest_number: Mapped[str | None] = mapped_column(
        String(32),
        doc=(
            "Номер конкурса — единственный работающий ключ внутри контура ГЧП "
            "(12 договоров из 12 нашли свой конкурс)."
        ),
    )
    source_url: Mapped[str | None] = mapped_column(Text)

    a1_terminated: Mapped[float | None] = mapped_column(doc="A1 — договор расторгнут, вес 25.")
    a2_partner_termination_history: Mapped[float | None] = mapped_column(doc="A2, вес 20.")
    a3_partner_region_concentration: Mapped[float | None] = mapped_column(doc="A3, вес 15.")
    a4_gov_partner_concentration: Mapped[float | None] = mapped_column(doc="A4, вес 15.")
    a5_construction_overdue: Mapped[float | None] = mapped_column(doc="A5, вес 15.")
    a6_investment_growth: Mapped[float | None] = mapped_column(doc="A6, вес 10.")
    a7_non_competitive: Mapped[float | None] = mapped_column(doc="A7, вес 10.")

    significance_top_quartile_cost: Mapped[bool | None] = mapped_column(
        doc="I_стоимость коэффициента K: стоимость в верхнем квартиле выборки."
    )
    significance_republican: Mapped[bool | None] = mapped_column(
        doc="I_уровень коэффициента K: проект республиканского уровня."
    )

    participants: Mapped[list[ProjectParticipant]] = relationship(
        primaryjoin="PppProject.id == foreign(ProjectParticipant.project_entity_id)",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<PppProject №{self.registry_number} {self.title[:40]!r}>"


class ConstructionExpertiseObject(ProjectEntity):
    """Заключение государственной экспертизы ПСД — тип B.

    Название класса говорит «объект», но единица анализа — **заключение**, и
    путать их нельзя. 4842 строки соответствуют меньшему числу физических
    объектов: строк с повторной экспертизой 111, а различных объектов за ними —
    52. В книге эта разница уже привела к ошибке вдвое, и повторять её в
    агрегатах нельзя. Поэтому у записи есть :attr:`object_identity_key` —
    свёртка «наименование + заказчик», по которой считается число объектов;
    считать объекты по числу строк неверно.

    Регистрационный номер хранится в канонической шестизначной форме. В витрине
    книги ведущие нули срезаны (`5617` вместо `005617`), и прямой джойн с сырым
    реестром даёт 0 совпадений из 4842; после дополнения нулями — 4842 из 4842.
    """

    __tablename__ = "construction_expertise_objects"
    __table_args__ = (
        UniqueConstraint("registration_number", name="uq_expertise_registration_number"),
        Index("ix_expertise_object_identity", "object_identity_key"),
        Index("ix_expertise_customer_key", "customer_key"),
        Index("ix_expertise_designer_key", "designer_key"),
        CheckConstraint(
            "registration_number ~ '^[0-9]{6}$'", name="ck_expertise_registration_six_digits"
        ),
    )
    # ruff требует для изменяемого атрибута класса аннотацию ClassVar, а mypy
    # её здесь запрещает: в DeclarativeBase `__mapper_args__` объявлен как
    # атрибут экземпляра, и ClassVar считается несовместимым переопределением.
    # Требования взаимоисключающие, поэтому правило отключается точечно —
    # значение всё равно читается SQLAlchemy один раз при построении маппера
    # и никогда не мутируется.
    __mapper_args__: dict[str, Any] = {  # noqa: RUF012
        "polymorphic_identity": ProjectEntityKind.EXPERTISE_CONCLUSION,
    }

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_entities.id", ondelete="CASCADE"), primary_key=True
    )

    registration_number: Mapped[str] = mapped_column(
        String(6),
        nullable=False,
        doc="Регистрационный номер ровно из 6 знаков, ведущие нули восстановлены.",
    )
    registration_number_raw: Mapped[str | None] = mapped_column(
        String(16), doc="Как записано в витрине книги — со срезанными нулями."
    )
    conclusion_number: Mapped[str | None] = mapped_column(String(32), doc="Формат «01-0144/26».")
    external_id: Mapped[int | None] = mapped_column(doc="ID сырого реестра, уникален.")
    issue_date: Mapped[date | None] = mapped_column(
        Date, doc="Дата выдачи заключения. В источнике строка «12.06.2026», не дата."
    )

    object_identity_key: Mapped[str | None] = mapped_column(
        String(512),
        doc=(
            "Свёртка «наименование + заказчик» — ключ, по которому объект "
            "отличается от заключения. Вход индикатора B2."
        ),
    )

    customer_raw: Mapped[str | None] = mapped_column(Text)
    customer_key: Mapped[str | None] = mapped_column(
        String(512), doc="Заказчик как в источнике — ключ индикаторов B5 и B6."
    )
    designer_raw: Mapped[str | None] = mapped_column(Text)
    designer_key: Mapped[str | None] = mapped_column(String(512))

    location_raw: Mapped[str | None] = mapped_column(
        Text,
        doc=(
            "Местоположение. Строки Алматинской области записаны коротким "
            "названием района, все прочие — полной строкой «Республика "
            "Казахстан, <область>, <район>;»."
        ),
    )

    work_kind: Mapped[str | None] = mapped_column(String(255))
    design_stage: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(512))
    object_kind: Mapped[str | None] = mapped_column(String(512))
    funding_source: Mapped[str | None] = mapped_column(String(255))
    expertise_place: Mapped[str | None] = mapped_column(String(255))

    capacity: Mapped[str | None] = mapped_column(String(64))
    capacity_unit: Mapped[str | None] = mapped_column(String(64))

    author_supervision_status: Mapped[str | None] = mapped_column(
        String(128), doc="Статус авторского договора — вход индикатора B3."
    )
    has_cost_estimate: Mapped[bool | None] = mapped_column(
        doc="«Имеется сметная документация?» — вход индикатора B4."
    )

    technological_complexity: Mapped[str | None] = mapped_column(String(128))
    responsibility_level: Mapped[str | None] = mapped_column(
        String(128), doc="Уровень ответственности — вход коэффициента K."
    )
    hazard_class: Mapped[str | None] = mapped_column(
        String(64), doc="Класс опасности — вход коэффициента K."
    )
    category: Mapped[str | None] = mapped_column(String(64))
    efficiency_class: Mapped[str | None] = mapped_column(
        String(64), doc="Заполнен у 4.1 % строк — на расчёт не влияет."
    )
    full_set_cost: Mapped[str | None] = mapped_column(
        String(64), doc="Стоимость полного комплекта строкой, заполнена у 39.5 %."
    )

    b1_design_correction: Mapped[float | None] = mapped_column(
        doc="B1 — корректировка ПСД, вес 20."
    )
    b2_repeated_expertise: Mapped[float | None] = mapped_column(doc="B2, вес 20.")
    b3_author_supervision: Mapped[float | None] = mapped_column(doc="B3, вес 15.")
    b4_no_cost_estimate: Mapped[float | None] = mapped_column(doc="B4, вес 15.")
    b5_designer_concentration: Mapped[float | None] = mapped_column(doc="B5, вес 10.")
    b6_customer_correction_share: Mapped[float | None] = mapped_column(doc="B6, вес 10.")

    significance_hazard_class: Mapped[bool | None] = mapped_column(
        doc="I_опасность коэффициента K: 1–2 класс опасности."
    )
    significance_responsibility: Mapped[bool | None] = mapped_column(
        doc="I_ответственность коэффициента K: 1 уровень ответственности."
    )

    participants: Mapped[list[ProjectParticipant]] = relationship(
        primaryjoin=(
            "ConstructionExpertiseObject.id == foreign(ProjectParticipant.project_entity_id)"
        ),
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<ConstructionExpertiseObject {self.registration_number} {self.title[:40]!r}>"


class ParticipantRole(StrEnum):
    """Роль участника в проекте.

    Роли двух популяций намеренно лежат в одном перечислении: участник — это
    единственное, что у них похоже по смыслу. Но совпадение ролей не делает
    объекты связанными, и на это нельзя опираться при джойне.
    """

    PRIVATE_PARTNER = "private_partner"
    GOVERNMENT_PARTNER = "government_partner"
    CUSTOMER = "customer"
    """Заказчик строительства — сторона заключения экспертизы."""

    GENERAL_DESIGNER = "general_designer"
    CONTEST_ORGANIZER = "contest_organizer"


class ProjectParticipant(Base, TimestampMixin, ProvenanceMixin):
    """Участник объекта слоя 8.6.

    Отдельная таблица, а не колонки в проекте: у проекта бывает несколько
    частных партнёров (консорциум записан одной строкой через запятую), и
    хранить их одним текстовым полем значит потерять возможность считать
    концентрацию.

    Про БИН. Внешнего ключа на организации слоя 8.7 здесь нет намеренно. БИН
    частного партнёра в источниках практически отсутствует: 0 из 1014 в реестре
    поставщиков, 5 из 1324 в реестре проектов, 0 из 4842 в реестре экспертизы.
    Жёсткая ссылка на организацию сделала бы импорт невозможным, а её
    «мягкая» подстановка по наименованию — недопустимой: сопоставление
    наименований дало 2 совпадения из 809 × 769, то есть шум. Поэтому БИН
    хранится как обычная строка и заполняется только там, где он действительно
    есть в источнике.
    """

    __tablename__ = "project_participants"
    __table_args__ = (
        Index("ix_project_participants_entity_role", "project_entity_id", "role"),
        Index("ix_project_participants_name_key", "name_key"),
        Index("ix_project_participants_bin", "bin"),
        CheckConstraint("bin IS NULL OR bin ~ '^[0-9]{12}$'", name="ck_participant_bin_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    project_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_entities.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[ParticipantRole] = mapped_column(String(32), nullable=False)

    name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    name_key: Mapped[str] = mapped_column(
        String(512), nullable=False, doc="Свёрнутое наименование для группировки."
    )

    bin: Mapped[str | None] = mapped_column(
        String(12),
        doc=(
            "БИН, если он есть в источнике. Заполнен у единиц записей — это "
            "признанный главный блокер слоя: без БИН аффилированность по "
            "ТЗ 9.3 недоказуема."
        ),
    )
    bin_source: Mapped[str | None] = mapped_column(
        String(64),
        doc="Откуда взят БИН: contest_organizer | contract_number | project_text.",
    )

    is_consortium_member: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc="True — участник выделен из перечисления нескольких лиц в одной ячейке.",
    )

    def __repr__(self) -> str:
        return f"<ProjectParticipant {self.role} {self.name_raw[:40]!r}>"


__all__ = [
    "ConstructionExpertiseObject",
    "ParticipantRole",
    "PppProject",
    "ProjectEntity",
    "ProjectEntityKind",
    "ProjectParticipant",
    "RiskAssessmentMixin",
    "TerritoryPrecision",
]
