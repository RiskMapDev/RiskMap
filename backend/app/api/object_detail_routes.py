"""Эндпоинт карточки объекта с расшифровкой оценки риска."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession
from app.api.queryspec import ObjectType
from app.core.permissions import (
    PermissionCode,
    TerritoryScope,
    get_territory_scope,
    require_permission,
)
from app.services import object_detail

router = APIRouter(prefix="/objects", tags=["объекты"])

ScopeDep = Annotated[TerritoryScope, Depends(get_territory_scope)]


@router.get(
    "/{object_type}/{object_id}",
    summary="Карточка объекта",
    dependencies=[Depends(require_permission(PermissionCode.RISK_EXPLAIN))],
)
def object_card(
    object_type: ObjectType,
    object_id: str,
    session: DbSession,
    scope: ScopeDep,
) -> dict[str, Any]:
    """Карточка с расшифровкой оценки.

    Расшифровка обязательна по ТЗ: пользователь должен видеть, какие факторы
    повысили риск, какие не повлияли и какие не были измерены. Балл без
    объяснения — число, которому остаётся либо верить на слово, либо не
    верить, и для принятия решений не годится ни то ни другое.
    """
    detail = object_detail.load_detail(session, object_type, object_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Объект {object_type}/{object_id} не найден",
        )

    # Территориальное ограничение проверяется после загрузки, и отказ выглядит
    # как «не найден», а не «нет доступа»: иначе перебором выясняется, какие
    # объекты существуют за пределами доступа пользователя.
    #
    # Объект без территории (организации слоя 8.7) ограниченному пользователю
    # не отдаётся: подтвердить его право на такой объект нечем.
    if scope.allowed_ids is not None and not scope.allows(detail.territory_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Объект {object_type}/{object_id} не найден",
        )

    def factor_payload(row: object_detail.FactorRow) -> dict[str, Any]:
        return {
            "code": row.code,
            "name": row.name,
            "weight": row.weight,
            "value": row.value,
            "contribution": row.contribution,
            "measured": row.measured,
            "effect": row.effect,
            "note": row.note,
            "source": row.source,
        }

    return {
        "object_type": detail.object_type,
        "object_id": detail.object_id,
        "title": detail.title,
        "source_layer": detail.source_layer,
        "territory": {
            "code": detail.territory_code,
            "name": detail.territory_name,
            "note": detail.territory_note,
        },
        "risk": {
            "score": detail.risk_score,
            "level": detail.risk_level,
            "is_preliminary": detail.risk_is_preliminary,
            "completeness": detail.risk_completeness,
            "model_code": detail.risk_model_code,
            "model_version": detail.risk_model_version,
            "override_reason": detail.override_reason,
            "explanation": detail.explanation,
            "notes": list(detail.notes),
        },
        "factors": {
            "measured": [factor_payload(row) for row in detail.measured_factors],
            # Неизмеренные факторы — обязательный раздел: именно они
            # объясняют низкую полноту и серый уровень.
            "unmeasured": [factor_payload(row) for row in detail.unmeasured_factors],
        },
        "fields": {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in detail.fields.items()
        },
        "provenance": {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in detail.provenance.items()
        },
    }
