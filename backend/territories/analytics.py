"""Единый модуль риска: пороги уровней и агрегация по территориям.

Один источник правды для порогов (ТЗ п.7.3) — им пользуются и импорт слоёв,
и API-эндпоинты, чтобы уровни не разъехались между расчётом и отдачей.

Ключевое решение (см. nedelya_subsidii_plan.md §1): риск территории —
ВЗВЕШЕННЫЙ ПО СУММЕ, а не простое среднее. Простое среднее уравняло бы
ИП с 300 тыс. ₸ и АО с 11 млрд ₸; взвешенное показывает реальную картину.
"""

# Порог -> уровень. Проверяется сверху вниз (ТЗ п.7.3).
RISK_BANDS = [(75, "critical"), (55, "high"), (35, "medium"), (0, "low")]
HIGH_LEVELS = {"high", "critical"}


def risk_level_for(score):
    """Числовой балл 0-100 -> уровень. None (нет данных) -> None (серый)."""
    if score is None:
        return None
    for threshold, level in RISK_BANDS:
        if score >= threshold:
            return level
    return "low"


def object_metrics(obj, year=None):
    """Метрики одного объекта под опциональным фильтром года.

    Возвращает (paid, score, level) либо None, если у объекта нет активности
    в этом году. Без года — берём итоговые поля объекта; с годом — срез
    attributes.by_year[year] (там своя сумма и свой пересчитанный риск).
    """
    attrs = obj.attributes or {}
    if year is None:
        paid = float(attrs.get("paid_total") or 0.0)
        score = float(obj.risk_score) if obj.risk_score is not None else None
        level = obj.risk_level or risk_level_for(score)
        return paid, score, level

    row = (attrs.get("by_year") or {}).get(str(year))
    if not row:
        return None
    paid = float(row.get("paid") or 0.0)
    raw_score = row.get("risk_score")
    score = float(raw_score) if raw_score is not None else None
    level = row.get("risk_level") or risk_level_for(score)
    return paid, score, level


def aggregate(objects, year=None, risk_levels=None):
    """Сводит объекты (получателей) в метрики территории.

    objects       — итерируемое GeoObject;
    year          — если задан, считаем по срезу года;
    risk_levels   — множество уровней-фильтр (объекты вне него не учитываем).

    Территория без подходящих объектов -> avg_risk_weighted и risk_level = None
    (фронт красит серым «нет данных»).
    """
    paid_total = 0.0
    weighted_num = 0.0
    exposure = 0.0
    count = 0
    by_level = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    for obj in objects:
        metrics = object_metrics(obj, year)
        if metrics is None:
            continue
        paid, score, level = metrics
        if risk_levels and level not in risk_levels:
            continue

        count += 1
        paid_total += paid
        if level in by_level:
            by_level[level] += 1
        if score is not None:
            weighted_num += score * paid
            exposure += score * paid / 100.0

    weighted = weighted_num / paid_total if paid_total > 0 else None

    return {
        "objects_count": count,
        "paid_total": round(paid_total, 2),
        "risk_exposure": round(exposure, 2),
        "avg_risk_weighted": round(weighted, 2) if weighted is not None else None,
        "risk_level": risk_level_for(weighted),
        "by_level": by_level,
        "high_risk_count": by_level["high"] + by_level["critical"],
    }
