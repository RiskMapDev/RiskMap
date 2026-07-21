"""Сведение риска объектов к уровню риска территории.

Карта красит полигон одним цветом, а внутри полигона лежат сотни объектов со
своими оценками. Правило сведения выбрано так: **территория получает максимум
из измеренных уровней своих объектов**.

Почему максимум, а не доля высоких и критических. Доля кажется информативнее,
но она разваливается на малых выборках: в Балхашском районе три получателя
субсидий, и один высокий даёт «33 % высокого риска» — цифру, которая выглядит
катастрофой и не значит ничего. Максимум не занижает риск никогда, а это
единственная безопасная сторона ошибки для карты рисков: пропустить проблемный
район дороже, чем перепроверить спокойный.

Чтобы максимум не превращал карту в «везде критический», рядом с цветом всегда
отдаётся распределение по уровням. Пользователь видит и худший объект, и то,
один он там или половина района.

Про «не измерено». Территория без единого измеренного объекта получает
:data:`RiskLevel.UNKNOWN` — серый. Это не низкий риск: мы про неё ничего не
знаем. Объекты серого уровня не поднимают уровень территории, но и не
исчезают — они попадают в распределение.

Про географическую точность. Объект, у которого источник знает только область,
не имеет права красить район: приписать проект ГЧП конкретному району значило
бы выдумать данные. Такие объекты не попадают в агрегат районной карты и
считаются отдельно — как непривязанные. Их число показывается пользователю,
иначе район, покрытый на четверть, выглядит как покрытый полностью.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.budget import BudgetMonthlyMetric
from app.db.models.infrastructure import ProjectEntity, ProjectEntityKind
from app.db.models.procurement import Contract
from app.db.models.subsidy import SubsidyRecipient
from app.risk.core import RiskLevel


@dataclass(frozen=True, slots=True)
class TerritoryRisk:
    """Оценка одной территории по одному слою."""

    level: RiskLevel
    counts: dict[RiskLevel, int] = field(default_factory=dict)
    total: int = 0

    @property
    def measured(self) -> int:
        """Сколько объектов территории реально оценено."""
        return sum(count for level, count in self.counts.items() if level.is_measured)


@dataclass(frozen=True, slots=True)
class LayerCoverage:
    """Слой целиком: оценки территорий и то, что на карту не попало."""

    by_territory: dict[uuid.UUID, TerritoryRisk]
    total: int
    """Всего объектов слоя."""

    unplaced: int
    """Объектов без территориальной привязки — они не на карте, но существуют."""

    def risk_for(self, territory_id: uuid.UUID) -> TerritoryRisk:
        """Оценка территории. Отсутствие записей — серый уровень, а не низкий."""
        return self.by_territory.get(territory_id, TerritoryRisk(level=RiskLevel.UNKNOWN))


def _to_level(raw: str | None) -> RiskLevel:
    """Уровень из базы. Неизвестное значение — серый, а не исключение.

    Строка приходит из колонки, а не из перечисления: если импорт когда-нибудь
    запишет туда неизвестное значение, карта обязана показать «нет данных», а
    не упасть целиком.
    """
    try:
        return RiskLevel(raw) if raw else RiskLevel.UNKNOWN
    except ValueError:
        return RiskLevel.UNKNOWN


def _summarize(counts: dict[RiskLevel, int]) -> TerritoryRisk:
    """Свести распределение к одному уровню — максимуму измеренных."""
    measured = [level for level, count in counts.items() if level.is_measured and count > 0]
    level = max(measured, key=lambda item: item.order) if measured else RiskLevel.UNKNOWN
    return TerritoryRisk(level=level, counts=dict(counts), total=sum(counts.values()))


def _grouped(
    session: Session,
    territory_column: Any,
    level_column: Any,
    *,
    where: Any | None = None,
) -> LayerCoverage:
    """Агрегат «территория × уровень» одним запросом.

    Считается на стороне базы: выборки слоёв доходят до 4842 записей, тянуть их
    в память ради подсчёта нечего.
    """
    stmt = select(territory_column, level_column, func.count()).group_by(
        territory_column, level_column
    )
    if where is not None:
        stmt = stmt.where(where)

    counts: dict[uuid.UUID, dict[RiskLevel, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    unplaced = 0

    for territory_id, raw_level, count in session.execute(stmt).all():
        total += count
        if territory_id is None:
            unplaced += count
            continue
        counts[territory_id][_to_level(raw_level)] += count

    return LayerCoverage(
        by_territory={tid: _summarize(dict(levels)) for tid, levels in counts.items()},
        total=total,
        unplaced=unplaced,
    )


def _budget_coverage(session: Session) -> LayerCoverage:
    """Бюджетный слой — по последнему периоду каждой территории.

    Здесь строки таблицы не разные объекты, а один и тот же регион в разные
    месяцы. Максимум по месяцам ответил бы на вопрос «был ли когда-нибудь
    провал», а карта отвечает на вопрос «как дела сейчас», поэтому берётся
    свежий период. Максимум по времени остаётся доступен в карточке региона.
    """
    stmt = select(
        BudgetMonthlyMetric.territory_id,
        BudgetMonthlyMetric.period,
        BudgetMonthlyMetric.risk_level,
    )

    latest: dict[uuid.UUID, tuple[Any, RiskLevel]] = {}
    total = 0
    unplaced = 0

    for territory_id, period, raw_level in session.execute(stmt).all():
        total += 1
        if territory_id is None:
            unplaced += 1
            continue
        known = latest.get(territory_id)
        if known is None or period > known[0]:
            latest[territory_id] = (period, _to_level(raw_level))

    return LayerCoverage(
        by_territory={
            tid: TerritoryRisk(level=level, counts={level: 1}, total=1)
            for tid, (_, level) in latest.items()
        },
        total=total,
        unplaced=unplaced,
    )


def _procurement(session: Session) -> LayerCoverage:
    return _grouped(session, Contract.territory_id, Contract.risk_level)


def _subsidies(session: Session) -> LayerCoverage:
    return _grouped(session, SubsidyRecipient.territory_id, SubsidyRecipient.risk_level)


def _project_entities(session: Session, kind: ProjectEntityKind) -> LayerCoverage:
    return _grouped(
        session,
        ProjectEntity.territory_id,
        ProjectEntity.risk_level,
        where=ProjectEntity.kind == kind,
    )


def _ppp(session: Session) -> LayerCoverage:
    return _project_entities(session, ProjectEntityKind.PPP_PROJECT)


def _expertise(session: Session) -> LayerCoverage:
    return _project_entities(session, ProjectEntityKind.EXPERTISE_CONCLUSION)


_LOADERS = {
    "budget": _budget_coverage,
    "procurement": _procurement,
    "subsidies": _subsidies,
    "infrastructure_ppp": _ppp,
    "infrastructure_expertise": _expertise,
}

RISK_LAYERS: frozenset[str] = frozenset(_LOADERS) | {"risk_summary"}
"""Слои, у которых есть оценка риска. Остальные рисуются без заливки по риску."""


def _summary_coverage(session: Session) -> LayerCoverage:
    """Сводный слой — максимум по всем слоям с оценкой.

    Территория, не измеренная ни одним слоем, остаётся серой. Слой, у которого
    на этом уровне нет данных, просто не участвует: его отсутствие не делает
    территорию благополучной.
    """
    merged: dict[uuid.UUID, dict[RiskLevel, int]] = defaultdict(lambda: defaultdict(int))
    total = 0
    unplaced = 0

    for load in _LOADERS.values():
        coverage = load(session)
        total += coverage.total
        unplaced += coverage.unplaced
        for territory_id, risk in coverage.by_territory.items():
            for level, count in risk.counts.items():
                merged[territory_id][level] += count

    return LayerCoverage(
        by_territory={tid: _summarize(dict(levels)) for tid, levels in merged.items()},
        total=total,
        unplaced=unplaced,
    )


def layer_coverage(session: Session, layer_code: str) -> LayerCoverage:
    """Оценки территорий по коду слоя.

    Слой без риска (административный, население, связи) возвращает пустое
    покрытие: карта покажет его без заливки по риску, а не серым «нет данных»,
    которое означало бы неизмеренный риск там, где риска и не считают.
    """
    if layer_code == "risk_summary":
        return _summary_coverage(session)

    load = _LOADERS.get(layer_code)
    if load is None:
        return LayerCoverage(by_territory={}, total=0, unplaced=0)
    return load(session)
