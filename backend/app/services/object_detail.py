"""Карточка объекта: сведения, происхождение, расшифровка риска.

Главное, ради чего эта карточка существует, — **объяснимость оценки**. ТЗ
требует показать, какие факторы повысили риск, какие не повлияли и какие не
были измерены, с указанием веса, значения, источника и даты. Балл без
расшифровки — это число, которому пользователь либо верит на слово, либо не
верит вовсе; ни то ни другое не годится для принятия решений.

Слои хранят расшифровку по-разному: где-то список факторов, где-то словарь
значений индикаторов. Здесь всё приводится к одному виду, чтобы карточка была
одинаковой независимо от того, из какого слоя объект.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.queryspec import ObjectType
from app.db.models.infrastructure import ProjectEntity
from app.db.models.organization import Organization
from app.db.models.procurement import Contract
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory
from app.risk.core import RiskLevel


@dataclass(frozen=True, slots=True)
class FactorRow:
    """Один фактор в расшифровке."""

    code: str
    name: str
    weight: float | None
    value: float | None
    contribution: float | None
    measured: bool
    note: str = ""
    source: str = ""

    @property
    def effect(self) -> str:
        """Как фактор повлиял — словами, а не знаком числа."""
        if not self.measured:
            return "не измерено"
        if not self.contribution:
            return "не повлиял"
        return "повысил риск"


@dataclass(frozen=True, slots=True)
class ObjectDetail:
    """Карточка объекта."""

    object_type: ObjectType
    object_id: str
    title: str
    source_layer: str

    territory_code: str | None
    territory_name: str | None
    territory_id: uuid.UUID | None = None
    """Нужен для проверки территориального доступа, наружу не отдаётся."""

    territory_note: str = ""
    """Почему территории нет, если её нет."""

    risk_score: float | None = None
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    risk_is_preliminary: bool = False
    risk_completeness: float | None = None
    risk_model_code: str | None = None
    risk_model_version: str | None = None
    override_reason: str = ""
    explanation: str = ""

    factors: tuple[FactorRow, ...] = ()
    notes: tuple[str, ...] = ()

    fields: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def measured_factors(self) -> tuple[FactorRow, ...]:
        return tuple(f for f in self.factors if f.measured)

    @property
    def unmeasured_factors(self) -> tuple[FactorRow, ...]:
        """Неизмеренные факторы — обязательный раздел карточки.

        Именно они объясняют низкую полноту. Спрятать их значит оставить
        пользователя с необъяснённым серым уровнем.
        """
        return tuple(f for f in self.factors if not f.measured)


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal | int | float):
        return float(value)
    return None


def _factors_from_list(raw: list[dict[str, Any]] | None) -> tuple[FactorRow, ...]:
    """Расшифровка, сохранённая списком (слои 8.6 и 8.7)."""
    if not raw:
        return ()

    return tuple(
        FactorRow(
            code=str(item.get("code", "")),
            name=str(item.get("name", item.get("code", ""))),
            weight=_as_float(item.get("weight")),
            value=_as_float(item.get("value")),
            contribution=_as_float(item.get("contribution")),
            measured=bool(item.get("measured", item.get("value") is not None)),
            note=str(item.get("note", "")),
            source=str(item.get("source", "")),
        )
        for item in raw
    )


def _factors_from_mapping(raw: dict[str, Any] | None) -> tuple[FactorRow, ...]:
    """Расшифровка из словаря вида «код индикатора → значение».

    Такой вид встречается в колонке `indicator_values`: там лежат только
    измеренные значения без описаний.
    """
    if not raw:
        return ()

    rows: list[FactorRow] = []
    for code, item in raw.items():
        value = _as_float(item)
        rows.append(
            FactorRow(
                code=code,
                name=code,
                weight=None,
                value=value,
                contribution=None,
                measured=value is not None,
                note="" if value is not None else "значение отсутствует в источнике",
            )
        )

    return tuple(rows)


# Ключи обёртки, в которую слои кладут расшифровку рядом с самой расшифровкой.
# Они описывают оценку целиком, а не отдельный индикатор, и попадать в список
# факторов не должны.
_WRAPPER_KEYS = frozenset({"level", "model", "model_version", "notes", "score", "factors"})


def _extract_factors(raw: object) -> tuple[FactorRow, ...]:
    """Достать расшифровку независимо от того, как слой её сохранил.

    Встречаются три вида:

    * обёртка `{"level": …, "score": …, "factors": [ … ]}` — слои 8.3–8.5;
    * готовый список факторов — слои 8.6 и 8.7;
    * плоский словарь «код → значение» — колонка `indicator_values`.

    Ключи обёртки в список факторов не попадают. Раньше попадали, и карточка
    договора писала «не измерено индикаторов: 4», показывая при этом шесть
    строк, три из которых были служебными. Пользователь, считающий строки,
    получал неверное представление о полноте данных.
    """
    if raw is None:
        return ()

    if isinstance(raw, list):
        return _factors_from_list(raw)

    if isinstance(raw, dict):
        nested = raw.get("factors")
        if isinstance(nested, list):
            return _factors_from_list(nested)

        payload = {key: value for key, value in raw.items() if key not in _WRAPPER_KEYS}
        return _factors_from_mapping(payload)

    return ()


def _territory(session: Session, territory_id: Any) -> tuple[str | None, str | None]:
    if territory_id is None:
        return None, None
    territory = session.get(Territory, territory_id)
    return (territory.code, territory.name_ru) if territory else (None, None)


def load_contract(session: Session, contract_id: str) -> ObjectDetail | None:
    contract = session.scalar(select(Contract).where(Contract.contract_id == contract_id))
    if contract is None:
        return None

    code, name = _territory(session, contract.territory_id)

    return ObjectDetail(
        object_type=ObjectType.CONTRACT,
        object_id=contract.contract_id,
        title=contract.brief_content_ru or contract.contract_id,
        source_layer="8.4",
        territory_code=code,
        territory_name=name,
        territory_id=contract.territory_id,
        territory_note=(
            ""
            if code
            else (
                "территория определяется по юридическому адресу поставщика; "
                "в источнике не опознана"
            )
        ),
        risk_score=_as_float(contract.risk_score),
        risk_level=RiskLevel(contract.risk_level) if contract.risk_level else RiskLevel.UNKNOWN,
        risk_is_preliminary=contract.is_preliminary,
        risk_completeness=_as_float(contract.completeness),
        risk_model_code=contract.model_code,
        risk_model_version=contract.model_version,
        override_reason=contract.override_reason or "",
        explanation=contract.explanation_ru or "",
        factors=_extract_factors(contract.factors or contract.indicator_values),
        fields={
            "Номер договора": contract.contract_id,
            "Плановая сумма": _as_float(contract.planned_amount),
            "Итоговая сумма": _as_float(contract.final_amount),
            "Способ закупки": contract.planned_method,
            "Статус": contract.contract_status,
            "Расторгнут": contract.is_terminated,
            "Плановый срок": contract.planned_exec_date,
            "Фактический срок": contract.actual_exec_date,
        },
        provenance={
            "source_layer": "8.4",
            "source_row_ref": contract.source_row_ref,
            "natural_key": contract.natural_key,
            "imported_at": contract.imported_at,
            "data_as_of": contract.data_as_of,
        },
    )


def load_subsidy_recipient(session: Session, key: str) -> ObjectDetail | None:
    recipient = session.scalar(
        select(SubsidyRecipient).where(SubsidyRecipient.natural_key == key)
    )
    if recipient is None:
        return None

    code, name = _territory(session, recipient.territory_id)

    return ObjectDetail(
        object_type=ObjectType.SUBSIDY_RECIPIENT,
        object_id=recipient.natural_key or key,
        title=recipient.name,
        source_layer="8.5",
        territory_code=code,
        territory_name=name,
        territory_id=recipient.territory_id,
        territory_note="" if code else "район не указан в источнике",
        risk_score=_as_float(recipient.risk_score),
        risk_level=RiskLevel(recipient.risk_level),
        risk_completeness=_as_float(recipient.risk_completeness),
        factors=_extract_factors(recipient.factors),
        fields={
            "Сумма субсидий": _as_float(recipient.total_amount),
            "Риск-экспозиция": _as_float(recipient.risk_exposure),
        },
        provenance={
            "source_layer": "8.5",
            "source_row_ref": recipient.source_row_ref,
            "natural_key": recipient.natural_key,
            "imported_at": recipient.imported_at,
            "data_as_of": recipient.data_as_of,
        },
    )


def load_project_entity(session: Session, object_id: str) -> ObjectDetail | None:
    project = session.scalar(select(ProjectEntity).where(ProjectEntity.id == object_id))
    if project is None:
        return None

    code, name = _territory(session, project.territory_id)
    is_ppp = project.kind == "ppp_project"

    return ObjectDetail(
        object_type=ObjectType.PPP_PROJECT if is_ppp else ObjectType.EXPERTISE_OBJECT,
        object_id=str(project.id),
        title=project.title,
        source_layer="8.6",
        territory_code=code,
        territory_name=name,
        territory_id=project.territory_id,
        territory_note=(
            "у проектов ГЧП в источнике указана только область, района нет"
            if is_ppp
            else ("" if code else "территория в источнике не опознана")
        ),
        risk_score=project.risk_score,
        risk_level=RiskLevel(project.risk_level) if project.risk_level else RiskLevel.UNKNOWN,
        risk_is_preliminary=project.risk_is_preliminary,
        risk_completeness=project.risk_completeness,
        risk_model_code=project.risk_model_code,
        risk_model_version=project.risk_model_version,
        override_reason=project.risk_override_applied or "",
        factors=_extract_factors(project.risk_factors),
        notes=tuple(project.risk_notes or ()),
        fields={"Территория в источнике": project.territory_raw},
        provenance={
            "source_layer": "8.6",
            "source_row_ref": project.source_row_ref,
            "natural_key": project.natural_key,
            "imported_at": project.imported_at,
            "data_as_of": project.data_as_of,
        },
    )


def load_organization(session: Session, bin_code: str) -> ObjectDetail | None:
    organization = session.scalar(select(Organization).where(Organization.bin == bin_code))
    if organization is None:
        return None

    strict = organization.risk_level_strict or RiskLevel.UNKNOWN.value

    return ObjectDetail(
        object_type=ObjectType.ORGANIZATION,
        object_id=organization.bin,
        title=organization.name,
        source_layer="8.7",
        territory_code=None,
        territory_name=None,
        territory_note=(
            "в источнике слоя 8.7 нет ни района, ни адреса, ни координат, ни КАТО — "
            "территорию определить не по чему"
        ),
        risk_score=organization.risk_score,
        risk_level=RiskLevel(strict),
        # Официальный уровень — строгий. Предварительный балл показывается
        # рядом, но не подменяет уровень: так решено заказчиком.
        risk_is_preliminary=strict == RiskLevel.UNKNOWN.value,
        risk_completeness=organization.risk_completeness,
        factors=_extract_factors(organization.risk_factors),
        notes=tuple(organization.risk_notes or ()),
        fields={
            "БИН": organization.bin,
            "Предварительный уровень": organization.risk_level_preliminary,
        },
        provenance={
            "source_layer": "8.7",
            "source_row_ref": organization.source_row_ref,
            "natural_key": organization.natural_key,
            "imported_at": organization.imported_at,
            "data_as_of": organization.data_as_of,
        },
    )


_LOADERS = {
    ObjectType.CONTRACT: load_contract,
    ObjectType.SUBSIDY_RECIPIENT: load_subsidy_recipient,
    ObjectType.PPP_PROJECT: load_project_entity,
    ObjectType.EXPERTISE_OBJECT: load_project_entity,
    ObjectType.ORGANIZATION: load_organization,
}


def load_detail(
    session: Session, object_type: ObjectType, object_id: str
) -> ObjectDetail | None:
    """Карточка объекта по типу и идентификатору."""
    loader = _LOADERS.get(object_type)
    if loader is None:
        return None
    return loader(session, object_id)
