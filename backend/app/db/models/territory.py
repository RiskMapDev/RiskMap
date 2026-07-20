"""Территории, их границы, алиасы названий и демография.

Три обстоятельства определили устройство этих таблиц.

**Кода КАТО в данных нет.** Ни в одной книге-источнике и ни в одном геонаборе
нет кода КАТО у районов — он есть только у области целиком. Единственный
официальный ключ стыковки недоступен, поэтому связывание идёт по названиям
через `TerritoryAlias`. Поле `kato_code` в модели есть и обязано заполняться,
когда справочник появится, но пустое оно — норма, а не ошибка импорта.

**Названия пишутся по-разному.** «Талгарский район» и «Талгарский р-н»,
«Сарканский» и «Саркандский», «Қонаев Г.А.» и «Конаев» — всё это встречается в
разных книгах для одних и тех же территорий. Поэтому алиас — полноценная
сущность с указанием источника, а не колонка «синоним».

**Границы имеют версию и лицензию.** Административное деление менялось в 2022
году, и смешивать старую и новую нарезку молча нельзя. `BoundaryVersion`
хранит версию набора вместе с лицензией и требуемой атрибуцией: без этого
границы нельзя ни отобразить, ни распространить законно.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    pass


class TerritoryLevel(StrEnum):
    """Уровень административной иерархии.

    Уровни заданы явно, а не числом: числовой `admin_level` из OSM удобен для
    выгрузки, но в предметной области «район» и «город областного значения» —
    равноправные единицы второго уровня, и путать их не следует.
    """

    COUNTRY = "country"
    REGION = "region"
    """Область или город республиканского значения."""

    DISTRICT = "district"
    """Район области."""

    CITY = "city"
    """Город областного значения — единица того же уровня, что и район."""

    RURAL_OKRUG = "rural_okrug"
    SETTLEMENT = "settlement"


class Territory(Base, TimestampMixin, ProvenanceMixin):
    """Административно-территориальная единица."""

    __tablename__ = "territories"
    __table_args__ = (
        UniqueConstraint("code", "boundary_version_id", name="uq_territory_code_version"),
        Index("ix_territories_parent", "parent_id"),
        Index("ix_territories_level", "level"),
        Index("ix_territories_kato", "kato_code"),
        CheckConstraint(
            "area_km2 IS NULL OR area_km2 > 0", name="ck_territory_area_positive"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Внутренний устойчивый код, например «almaty-oblast» или «talgarskiy».",
    )
    kato_code: Mapped[str | None] = mapped_column(
        String(9),
        doc=(
            "Код КАТО. У районов в наличных источниках отсутствует — пустое "
            "значение штатно и не должно трактоваться как ошибка."
        ),
    )
    iso3166_2: Mapped[str | None] = mapped_column(String(16))
    osm_relation_id: Mapped[int | None] = mapped_column(doc="Идентификатор отношения OSM.")

    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    name_kk: Mapped[str | None] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))

    level: Mapped[TerritoryLevel] = mapped_column(String(24), nullable=False)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="RESTRICT")
    )
    parent: Mapped[Territory | None] = relationship(
        remote_side="Territory.id", back_populates="children"
    )
    children: Mapped[list[Territory]] = relationship(
        back_populates="parent", cascade="save-update"
    )

    boundary_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boundary_versions.id", ondelete="RESTRICT"), nullable=False
    )
    boundary_version: Mapped[BoundaryVersion] = relationship(back_populates="territories")

    admin_center_name: Mapped[str | None] = mapped_column(String(255))
    area_km2: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), doc="Площадь по документу-источнику, если она заявлена."
    )
    area_km2_computed: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        doc=(
            "Площадь, вычисленная по геометрии на эллипсоиде. Хранится отдельно "
            "от заявленной: расхождения между ними — самостоятельный факт, "
            "а не повод переписать одну из величин."
        ),
    )

    is_current: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        doc="False у единиц, упразднённых или переданных в другую область.",
    )
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    notes: Mapped[str | None] = mapped_column(Text)

    aliases: Mapped[list[TerritoryAlias]] = relationship(
        back_populates="territory", cascade="all, delete-orphan"
    )
    geometry: Mapped[TerritoryGeometry | None] = relationship(
        back_populates="territory", cascade="all, delete-orphan", uselist=False
    )
    population_stats: Mapped[list[PopulationStat]] = relationship(
        back_populates="territory", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Territory {self.code} {self.name_ru!r} {self.level}>"


class BoundaryVersion(Base, TimestampMixin):
    """Версия набора границ: источник, дата, лицензия.

    Без лицензии и атрибуции набор границ нельзя показывать пользователю и тем
    более распространять. Поэтому поля лицензии обязательные, а не справочные:
    забыть их — значит получить юридическую проблему на этапе внедрения.
    """

    __tablename__ = "boundary_versions"
    __table_args__ = (UniqueConstraint("code", name="uq_boundary_version_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    downloaded_at: Mapped[date | None] = mapped_column(Date)

    license_name: Mapped[str] = mapped_column(String(128), nullable=False)
    license_url: Mapped[str | None] = mapped_column(Text)
    attribution_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Формулировка, обязательная к показу рядом с картой.",
    )
    redistribution_allowed: Mapped[bool] = mapped_column(
        nullable=False,
        doc=(
            "False — набор нельзя распространять. Такие версии допустимы только "
            "для сверки и не должны отдаваться клиенту."
        ),
    )

    administrative_division_as_of: Mapped[date | None] = mapped_column(
        Date,
        doc="На какую дату актуально отражённое административное деление.",
    )
    is_current: Mapped[bool] = mapped_column(default=False, nullable=False)

    sha256: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    territories: Mapped[list[Territory]] = relationship(back_populates="boundary_version")

    def __repr__(self) -> str:
        return f"<BoundaryVersion {self.code} ({self.license_name})>"


class TerritoryGeometry(Base, TimestampMixin):
    """Геометрия территории.

    Оригинал и упрощённые варианты хранятся раздельно: упрощение нужно карте
    для скорости, но оно необратимо искажает границу, и подменять им исходную
    геометрию при расчёте площадей или пространственных запросов нельзя.
    """

    __tablename__ = "territory_geometries"

    id: Mapped[uuid.UUID] = uuid_pk()

    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    territory: Mapped[Territory] = relationship(back_populates="geometry")

    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
        nullable=False,
        doc="Исходная геометрия в EPSG:4326.",
    )
    geom_simplified_mid: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        doc="Упрощение для средних масштабов.",
    )
    geom_simplified_low: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        doc="Упрощение для обзорных масштабов.",
    )
    centroid: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        doc="Точка внутри полигона для подписи и зума, не математический центроид.",
    )

    is_valid: Mapped[bool] = mapped_column(default=True, nullable=False)
    validity_note: Mapped[str | None] = mapped_column(
        Text, doc="Что именно было невалидно и как исправлено."
    )


class AliasKind(StrEnum):
    OFFICIAL = "official"
    SHORT = "short"
    """«Талгарский р-н» вместо «Талгарский район»."""

    HISTORICAL = "historical"
    """Прежнее название единицы."""

    TRANSLITERATION = "transliteration"
    SOURCE_SPELLING = "source_spelling"
    """Написание, встреченное в конкретной книге, включая опечатки."""


class TerritoryAlias(Base, TimestampMixin):
    """Вариант написания названия территории.

    `normalized` — свёрнутая форма для сопоставления. Свёртка выполняется
    функцией `app.services.territory_resolver.normalize_territory_name`, и
    хранить результат в таблице нужно для того, чтобы поиск шёл по индексу,
    а не пересчитывал свёртку на каждой строке.
    """

    __tablename__ = "territory_aliases"
    __table_args__ = (
        UniqueConstraint("normalized", "territory_id", name="uq_alias_normalized_territory"),
        Index("ix_territory_aliases_normalized", "normalized"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="CASCADE"), nullable=False
    )
    territory: Mapped[Territory] = relationship(back_populates="aliases")

    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[AliasKind] = mapped_column(String(24), nullable=False)

    source_layer: Mapped[str | None] = mapped_column(
        String(64), doc="В каком слое встречено это написание, например «8.5»."
    )
    is_ambiguous: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc=(
            "True — написание совпадает у нескольких территорий. Такие алиасы "
            "не годятся для автоматического связывания и требуют разбора."
        ),
    )
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<TerritoryAlias {self.alias!r} → {self.territory_id}>"


class PopulationStat(Base, TimestampMixin, ProvenanceMixin):
    """Численность населения территории на дату.

    Разбивка город/село и мужчины/женщины хранится ровно так, как в источнике.
    Прочерк в книге означает «показателя нет», и при импорте он отображается в
    ноль только там, где источник действительно фиксирует отсутствие населения
    соответствующей категории, а не пропуск измерения.
    """

    __tablename__ = "population_stats"
    __table_args__ = (
        UniqueConstraint("territory_id", "as_of_date", name="uq_population_territory_date"),
        CheckConstraint("total >= 0", name="ck_population_total_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    territory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="CASCADE"), nullable=False
    )
    territory: Mapped[Territory] = relationship(back_populates="population_stats")

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    total: Mapped[int] = mapped_column(nullable=False)
    male: Mapped[int | None] = mapped_column()
    female: Mapped[int | None] = mapped_column()

    urban_total: Mapped[int | None] = mapped_column()
    urban_male: Mapped[int | None] = mapped_column()
    urban_female: Mapped[int | None] = mapped_column()

    rural_total: Mapped[int | None] = mapped_column()
    rural_male: Mapped[int | None] = mapped_column()
    rural_female: Mapped[int | None] = mapped_column()

    def __repr__(self) -> str:
        return f"<PopulationStat {self.territory_id} на {self.as_of_date}: {self.total}>"
