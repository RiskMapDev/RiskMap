"""Агрегаты аналитической панели.

Главное правило этого модуля: **показатель, которого нет в источниках, не
превращается в ноль**. Он возвращается со значением `None` и причиной, а
интерфейс печатает «нет данных». Ноль означал бы измеренное отсутствие —
например, что аналитических материалов ноль, — тогда как на деле такой
сущности в исходных данных не существует вовсе.

Второе правило: сводка по уровням риска всегда включает «нет данных». Убрать
серые объекты из кольцевой диаграммы значит показать картину благополучнее,
чем она есть.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.budget import BudgetMonthlyMetric
from app.db.models.infrastructure import ProjectEntity, ProjectEntityKind
from app.db.models.organization import Organization
from app.db.models.procurement import Contract
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory
from app.risk.core import RiskLevel


@dataclass(frozen=True, slots=True)
class Kpi:
    """Одна карточка показателя.

    `value is None` означает «показателя нет в данных», и это состояние
    обязано доходить до пользователя словами. Поэтому рядом лежит `reason` —
    без него «нет данных» выглядит как поломка интерфейса.
    """

    code: str
    title: str
    value: float | None
    unit: str
    caption: str
    """Уточнение под значением: «42 заказчика», «в реализации»."""

    definition: str
    """Что именно посчитано — для всплывающей подсказки. Требование ТЗ."""

    sources: tuple[str, ...]
    data_as_of: str | None
    reason: str = ""
    """Почему значения нет. Заполняется только когда `value is None`."""

    drill_down: dict[str, str] | None = None
    """Параметры выборки, в которую ведёт клик по карточке."""

    @property
    def is_available(self) -> bool:
        return self.value is not None


def _scoped(stmt: Any, column: Any, allowed: Collection[uuid.UUID] | None) -> Any:
    """Наложить территориальное ограничение пользователя."""
    if allowed is None:
        return stmt
    return stmt.where(column.in_(allowed))


def _money(session: Session, stmt: Any) -> float | None:
    value: Decimal | None = session.scalar(stmt)
    return float(value) if value is not None else None


def build_kpis(
    session: Session, *, allowed_territory_ids: Collection[uuid.UUID] | None = None
) -> list[Kpi]:
    """Восемь показателей аналитической панели."""
    kpis: list[Kpi] = []

    # --- Бюджет ---------------------------------------------------------------
    # Слой 8.3 общереспубликанский и живёт на уровне области. Территориальное
    # ограничение пользователя к нему применимо только через область.
    budget_rows = session.scalar(select(func.count()).select_from(BudgetMonthlyMetric)) or 0
    kpis.append(
        Kpi(
            code="budget",
            title="Бюджетные наблюдения",
            value=float(budget_rows) if budget_rows else None,
            unit="строк",
            caption="регион × месяц, 20 регионов",
            definition=(
                "Число расчётных строк бюджетного слоя. Единица наблюдения — "
                "регион за месяц. Абсолютного объёма бюджета в источнике нет: "
                "книга содержит показатели исполнения, а не суммы."
            ),
            sources=("Слой 8.3 «Бюджетные риски»",),
            data_as_of="2025",
            reason="" if budget_rows else "слой 8.3 не загружен",
            drill_down=None,
        )
    )

    # --- Госзакупки -----------------------------------------------------------
    contracts_stmt = _scoped(
        select(func.sum(func.coalesce(Contract.final_amount, Contract.planned_amount))),
        Contract.territory_id,
        allowed_territory_ids,
    )
    contracts_sum = _money(session, contracts_stmt)
    suppliers_count = session.scalar(
        _scoped(
            select(func.count(func.distinct(Contract.supplier_id))),
            Contract.territory_id,
            allowed_territory_ids,
        )
    )
    kpis.append(
        Kpi(
            code="procurement",
            title="Государственные закупки",
            value=contracts_sum,
            unit="₸",
            caption=f"{suppliers_count or 0} поставщиков",
            definition=(
                "Сумма договоров выборки слоя 8.4. Это целевой срез из "
                "355 договоров 26 поставщиков, а не все закупки региона: "
                "распространять выводы на регион целиком нельзя."
            ),
            sources=("Слой 8.4 «Госзакупки»",),
            data_as_of="2024",
            drill_down={"object_types": "contract"},
        )
    )

    # --- Субсидии -------------------------------------------------------------
    # Показатель озаглавлен «Алматинской области», поэтому в сумму входят только
    # получатели, привязанные к территории текущей области (territory_id задан).
    # Книга 8.5 использует ДОреформенную сетку из 24 районов, 11 из которых с
    # 2022 года отошли к области Жетысу; их получатели остаются без territory_id
    # (см. territory-reconciliation.md, § 4.1). Складывать их сумму в число,
    # подписанное текущей областью, значило бы завысить его на объём Жетысу.
    # Полнокнижный итог как проверка целостности загрузки — в тестах слоя 8.5.
    in_oblast = SubsidyRecipient.territory_id.is_not(None)
    subsidies_stmt = _scoped(
        select(func.sum(SubsidyRecipient.total_amount)).where(in_oblast),
        SubsidyRecipient.territory_id,
        allowed_territory_ids,
    )
    recipients_count = session.scalar(
        _scoped(
            select(func.count()).select_from(SubsidyRecipient).where(in_oblast),
            SubsidyRecipient.territory_id,
            allowed_territory_ids,
        )
    )
    kpis.append(
        Kpi(
            code="subsidies",
            title="Субсидии и господдержка",
            value=_money(session, subsidies_stmt),
            unit="₸",
            caption=f"{recipients_count or 0} получателей",
            definition=(
                "Сумма субсидий получателей текущей Алматинской области — тех, "
                "чей район опознан в справочнике. Получатели из районов, "
                "переданных в 2022 году в область Жетысу, и с неопознанным "
                "районом в этот показатель не входят: книга 8.5 ведётся по "
                "дореформенной сетке, и их включение завысило бы областную сумму."
            ),
            sources=("Слой 8.5 «Субсидии»",),
            data_as_of="2024",
            drill_down={"object_types": "subsidy_recipient"},
        )
    )

    # --- Инфраструктура -------------------------------------------------------
    projects_count = session.scalar(
        select(func.count())
        .select_from(ProjectEntity)
        .where(ProjectEntity.kind == ProjectEntityKind.PPP_PROJECT)
    )
    kpis.append(
        Kpi(
            code="infrastructure",
            title="Инфраструктурные проекты",
            value=float(projects_count) if projects_count else None,
            unit="",
            caption="проектов ГЧП",
            definition=(
                "Проекты государственно-частного партнёрства. Заключения "
                "строительной экспертизы считаются отдельно: это другая "
                "совокупность, общего ключа между ними нет."
            ),
            sources=("Слой 8.6 «Инфраструктурные проекты»",),
            data_as_of="2024",
            drill_down={"object_types": "ppp_project"},
        )
    )

    # --- Организации ----------------------------------------------------------
    orgs_count = session.scalar(select(func.count()).select_from(Organization))
    kpis.append(
        Kpi(
            code="organizations",
            title="Хозяйствующие субъекты",
            value=float(orgs_count) if orgs_count else None,
            unit="",
            caption="в реестре",
            definition=(
                "Организации слоя 8.7. Территориальной привязки у них в "
                "источнике нет, поэтому на карту они не выводятся и "
                "территориальным фильтром не ограничиваются."
            ),
            sources=("Слой 8.7 «Организации»",),
            data_as_of="2024",
            drill_down={"object_types": "organization"},
        )
    )

    # --- Высокий и критический риск -------------------------------------------
    high_critical = _count_by_levels(
        session, (RiskLevel.HIGH, RiskLevel.CRITICAL), allowed_territory_ids
    )
    kpis.append(
        Kpi(
            code="high_risk",
            title="Высокий и критический риск",
            value=float(high_critical),
            unit="",
            caption="объектов",
            definition=(
                "Объекты всех слоёв с уровнем «высокий» или «критический». "
                "Объекты без оценки сюда не входят — их отсутствие в этом "
                "числе не означает благополучия."
            ),
            sources=("Слои 8.3–8.7",),
            data_as_of=None,
            drill_down={"risk_levels": "high,critical"},
        )
    )

    # --- Сумма финансовых рисков ----------------------------------------------
    # Та же территориальная логика, что у суммы субсидий: экспозиция считается по
    # получателям текущей области, иначе величина включала бы объём Жетысу.
    exposure_stmt = _scoped(
        select(func.sum(SubsidyRecipient.risk_exposure)).where(
            SubsidyRecipient.territory_id.is_not(None)
        ),
        SubsidyRecipient.territory_id,
        allowed_territory_ids,
    )
    kpis.append(
        Kpi(
            code="risk_exposure",
            title="Сумма финансовых рисков",
            value=_money(session, exposure_stmt),
            unit="₸",
            caption="оценочно, по слою субсидий",
            definition=(
                "Риск-экспозиция: сумма выплат, взвешенная баллом риска "
                "получателя. Считается только по слою 8.5 — методики "
                "экспозиции для остальных слоёв в источниках нет, поэтому "
                "величина неполна и не является суммой по всем слоям."
            ),
            sources=("Слой 8.5 «Субсидии»",),
            data_as_of="2024",
            drill_down={"object_types": "subsidy_recipient"},
        )
    )

    # --- Аналитические материалы ----------------------------------------------
    # Этой сущности в приложенных источниках не существует. Показать ноль
    # значило бы утверждать, что материалов нет; на деле их учёт вообще не
    # ведётся в данных, которыми мы располагаем.
    kpis.append(
        Kpi(
            code="analytic_materials",
            title="Аналитические материалы и меры",
            value=None,
            unit="",
            caption="",
            definition=(
                "Аналитические материалы, меры реагирования и их статусы "
                "(«Превенция», «В ЕРДР», «Завершено») предусмотрены ТЗ и "
                "показаны на референсе, но ни в одном приложенном источнике "
                "не содержатся."
            ),
            sources=(),
            data_as_of=None,
            reason=(
                "в приложенных данных нет такой сущности — показатель появится "
                "после подключения источника учёта материалов и мер"
            ),
        )
    )

    return kpis


def _count_by_levels(
    session: Session,
    levels: tuple[RiskLevel, ...],
    allowed: Collection[uuid.UUID] | None,
) -> int:
    """Число объектов всех слоёв с указанными уровнями риска."""
    values = [level.value for level in levels]
    total = 0

    total += (
        session.scalar(
            _scoped(
                select(func.count())
                .select_from(Contract)
                .where(Contract.risk_level.in_(values)),
                Contract.territory_id,
                allowed,
            )
        )
        or 0
    )
    total += (
        session.scalar(
            _scoped(
                select(func.count())
                .select_from(SubsidyRecipient)
                .where(SubsidyRecipient.risk_level.in_(values)),
                SubsidyRecipient.territory_id,
                allowed,
            )
        )
        or 0
    )
    total += (
        session.scalar(
            _scoped(
                select(func.count())
                .select_from(ProjectEntity)
                .where(ProjectEntity.risk_level.in_(values)),
                ProjectEntity.territory_id,
                allowed,
            )
        )
        or 0
    )
    # Организации территориально не ограничиваются: привязки у них нет.
    if allowed is None:
        total += (
            session.scalar(
                select(func.count())
                .select_from(Organization)
                .where(Organization.risk_level_strict.in_(values))
            )
            or 0
        )

    return total


def level_distribution(
    session: Session, *, allowed_territory_ids: Collection[uuid.UUID] | None = None
) -> dict[str, int]:
    """Распределение объектов по уровням риска для кольцевой диаграммы.

    Уровень «нет данных» присутствует всегда, даже нулевой: его отсутствие в
    легенде читалось бы как «неизмеренных объектов не бывает».
    """
    counts = dict.fromkeys((level.value for level in RiskLevel), 0)

    for level in RiskLevel:
        counts[level.value] = _count_by_levels(session, (level,), allowed_territory_ids)

    return counts


def territory_ranking(
    session: Session,
    *,
    limit: int = 10,
    allowed_territory_ids: Collection[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Рейтинг территорий по числу объектов высокого и критического риска."""
    risky = (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value)

    stmt = (
        select(
            Territory.code,
            Territory.name_ru,
            func.count(SubsidyRecipient.id).label("risky_count"),
        )
        .join(SubsidyRecipient, SubsidyRecipient.territory_id == Territory.id)
        .where(SubsidyRecipient.risk_level.in_(risky))
        .group_by(Territory.code, Territory.name_ru)
        .order_by(func.count(SubsidyRecipient.id).desc())
        .limit(limit)
    )
    if allowed_territory_ids is not None:
        stmt = stmt.where(Territory.id.in_(allowed_territory_ids))

    return [
        {"code": code, "name": name, "risky_count": count}
        for code, name, count in session.execute(stmt).all()
    ]


def budget_dynamics(session: Session) -> list[dict[str, Any]]:
    """Помесячная динамика бюджетного риска.

    Динамику даёт только слой 8.3: он единственный содержит помесячную
    разбивку. У остальных слоёв периодов нет, и рисовать по ним линию значило
    бы выдумывать данные.
    """
    stmt = (
        select(
            BudgetMonthlyMetric.period,
            func.avg(BudgetMonthlyMetric.risk_score).label("avg_score"),
            func.count().label("rows"),
        )
        .group_by(BudgetMonthlyMetric.period)
        .order_by(BudgetMonthlyMetric.period)
    )

    return [
        {
            "period": period,
            "avg_score": float(avg) if avg is not None else None,
            "rows": rows,
        }
        for period, avg, rows in session.execute(stmt).all()
    ]


def data_freshness(session: Session) -> dict[str, Any]:
    """Когда данные загружались и на какую дату они актуальны."""
    latest: date | None = session.scalar(select(func.max(Territory.data_as_of)))
    return {
        "territories_as_of": latest.isoformat() if latest else None,
        "note": (
            "Даты актуальности различаются по слоям: население на 1 апреля "
            "2026 года, бюджет за 2025 год, остальные слои за 2024 год."
        ),
    }
