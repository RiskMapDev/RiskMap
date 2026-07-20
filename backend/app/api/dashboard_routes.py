"""Эндпоинты аналитической панели."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import DbSession
from app.core.permissions import (
    PermissionCode,
    TerritoryScope,
    get_territory_scope,
    require_permission,
)
from app.risk.core import RiskLevel
from app.services import dashboard

router = APIRouter(prefix="/dashboard", tags=["дашборд"])

ScopeDep = Annotated[TerritoryScope, Depends(get_territory_scope)]


@router.get(
    "",
    summary="Показатели аналитической панели",
    # Отдельного права на панель нет: она показывает те же данные, что список
    # и карта, только в свёрнутом виде. Заводить для неё собственное право
    # значило бы позволить настройку, при которой человек видит сводку, но не
    # может открыть объекты, из которых она сложена.
    dependencies=[Depends(require_permission(PermissionCode.DATA_VIEW))],
)
def dashboard_payload(session: DbSession, scope: ScopeDep) -> dict[str, Any]:
    """Всё, что нужно панели, одним запросом.

    Виджеты панели связаны общим периодом и территорией, и отдавать их
    четырьмя запросами значило бы допустить состояние, в котором KPI уже
    обновились, а диаграмма ещё нет.
    """
    kpis = dashboard.build_kpis(session, allowed_territory_ids=scope.allowed_ids)
    distribution = dashboard.level_distribution(session, allowed_territory_ids=scope.allowed_ids)

    return {
        "kpis": [
            {
                "code": kpi.code,
                "title": kpi.title,
                "value": kpi.value,
                "unit": kpi.unit,
                "caption": kpi.caption,
                "definition": kpi.definition,
                "sources": list(kpi.sources),
                "data_as_of": kpi.data_as_of,
                "available": kpi.is_available,
                "reason": kpi.reason,
                "drill_down": kpi.drill_down,
            }
            for kpi in kpis
        ],
        "risk_distribution": {
            "counts": distribution,
            "labels": {level.value: level.label_ru for level in RiskLevel},
            "total": sum(distribution.values()),
            # Пользователь, ограниченный территорией, видит в распределении
            # меньше объектов, чем в карточках показателей: объекты без
            # территориальной привязки подтвердить его правом не на чем.
            # Без этого пояснения расхождение между «3 668 организаций» в
            # карточке и их отсутствием в диаграмме выглядит как ошибка.
            "scope_note": (
                "Учтены только объекты доступных вам территорий. Организации "
                "слоя 8.7 не имеют территориальной привязки и в распределение "
                "не входят."
                if scope.allowed_ids is not None
                else "Учтены объекты всех слоёв, включая организации без территориальной привязки."
            ),
        },
        "territory_ranking": dashboard.territory_ranking(
            session, allowed_territory_ids=scope.allowed_ids
        ),
        "budget_dynamics": dashboard.budget_dynamics(session),
        "freshness": dashboard.data_freshness(session),
    }
