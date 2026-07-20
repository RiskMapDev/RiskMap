"""Модели риска слоя 8.6 — инфраструктурные и инвестиционные проекты.

**Здесь две модели, а не одна, и это не оформительское решение.** Аудит книги
показал, что в слое 8.6 лежат две несвязанные популяции без общего ключа:
проекты ГЧП (договорная плоскость) и заключения строительной экспертизы
(проектно-экспертная плоскость). У них разные индикаторы (A1–A7 против B1–B6),
разный полный вес методики (110 против 90), разная единица анализа и разная
точность территориальной привязки. Общая модель заставила бы половину
индикаторов быть «недоступными» у каждой половины выборки и обрушила бы полноту
у всех 6165 объектов до неинформативных 45–55 %.

Устройство расчёта одинаково у обеих моделей и повторяет лист «Методика
Risk Score» дословно:

    S_raw   = Σ (w_i × v_i)        по измеренным индикаторам
    W_avail = Σ (w_i)              по измеренным индикаторам
    S_norm  = 100 × S_raw / W_avail
    K       = 1.00 + 0.15×I₁ + 0.15×I₂        диапазон 1.00 … 1.30
    Score   = min(100 ; S_norm × K)
    полнота = W_avail / W_total    (110 для типа A, 90 для типа B)

Пороги уровней — 25/50/75, серый при полноте ниже 50 %. Это не те же пороги,
что в слое 8.5 (35/55/75), и приводить их к общему виду нельзя: несогласованность
порогов между слоями — зафиксированный факт, а не разнобой в коде.

Веса — черновые, назначены экспертно и до калибровки на размеченной выборке
остаются параметром администратора, а не константой кода. Версия модели
записывается в каждую оценку, чтобы правка веса не переписывала историю.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import cache

from app.risk.core import (
    IndicatorSpec,
    IndicatorValue,
    RiskLevel,
    RiskModelSpec,
    RiskResult,
    evaluate,
)

# --- Общие константы методики -----------------------------------------------

THRESHOLDS_8_6: tuple[tuple[float, RiskLevel], ...] = (
    (0.0, RiskLevel.LOW),
    (25.0, RiskLevel.MEDIUM),
    (50.0, RiskLevel.HIGH),
    (75.0, RiskLevel.CRITICAL),
)

MIN_COMPLETENESS_8_6 = 0.5
"""Полнота ниже половины — уровень серый, балл остаётся предварительным."""

DATA_ERROR_REASON = "ошибка в данных: окончание строительства раньше начала"
"""Пять проектов ГЧП имеют окончание раньше начала.

Методика книги отправляет такие строки в серый уровень до сравнения балла с
порогами. Балл при этом посчитан, но опираться на него нельзя: сроки, из
которых он выведен, противоречивы.
"""

GradedScale = tuple[tuple[float, float], ...]
"""Градуированная шкала «порог → значение v», пороги по убыванию."""


def graded(value: float | None, scale: GradedScale) -> float | None:
    """Привести измеренную величину к безразмерному v ∈ [0;1] по порогам.

    `None` на входе даёт `None` на выходе, а не ноль: неизмеренная величина не
    должна превращаться в «риска нет». Это то самое различие, ради которого
    существует всё ядро расчёта.
    """
    if value is None:
        return None
    for bound, v in scale:
        if value >= bound:
            return v
    return 0.0


# --- Тип A: проекты ГЧП ------------------------------------------------------

A2_SCALE: GradedScale = ((0.5, 1.0), (0.3, 0.6))
"""Доля расторгнутых договоров у частного партнёра при не менее чем 3 проектах."""

A3_SCALE: GradedScale = ((0.3, 1.0), (0.15, 0.5))
"""Доля проектов партнёра среди всех проектов региона."""

A4_SCALE: GradedScale = ((0.7, 1.0), (0.5, 0.5))
"""Доля топ-1 частного партнёра у госпартнёра при не менее чем 3 проектах."""

A6_SCALE: GradedScale = ((1.5, 1.0), (1.2, 0.5))
"""Отношение привлечённых инвестиций к первоначальной стоимости."""

A5_OVERDUE_DAYS_CRITICAL = 365
"""Просрочка строительства свыше года — v = 1.0, любая просрочка — v = 0.5."""

PPP_INDICATORS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        code="A1",
        name="Договор ГЧП расторгнут",
        weight=25.0,
        description="Статус проекта — «Расторгнут». Бинарный признак.",
        source="Данные Проекты ГЧП: Статус",
    ),
    IndicatorSpec(
        code="A2",
        name="Партнёр с историей расторжений",
        weight=20.0,
        description="Доля расторгнутых договоров у частного партнёра при ≥3 проектах.",
        source="Данные Проекты ГЧП: Частный партнер + Статус",
    ),
    IndicatorSpec(
        code="A3",
        name="Концентрация партнёра в регионе",
        weight=15.0,
        description="Доля проектов партнёра среди проектов региона.",
        source="Данные Проекты ГЧП: Регион + Частный партнер",
    ),
    IndicatorSpec(
        code="A4",
        name="Концентрация партнёров у госпартнёра",
        weight=15.0,
        description="Доля топ-1 частного партнёра у госпартнёра при ≥3 проектах.",
        source="Данные Проекты ГЧП: Государственный партнер + Частный партнер",
    ),
    IndicatorSpec(
        code="A5",
        name="Просрочка строительства",
        weight=15.0,
        description="Плановое окончание строительства в прошлом при статусе не «эксплуатация».",
        source="Данные Проекты ГЧП: Период реализации + Статус",
    ),
    IndicatorSpec(
        code="A6",
        name="Рост инвестзатрат к первоначальной стоимости",
        weight=10.0,
        description="Отношение привлечённых инвестиций к первоначальной стоимости.",
        source="Данные Проекты ГЧП: Стоимость проекта + Объем привлеченных инвестиций",
    ),
    IndicatorSpec(
        code="A7",
        name="Внеконкурсная процедура",
        weight=10.0,
        description="Прямые переговоры — 1.0, частная финансовая инициатива — 0.5.",
        source="Данные Проекты ГЧП: Вид инициативы",
    ),
)

PPP_MODEL = RiskModelSpec(
    code="8.6-ppp",
    version="1.0",
    title="Слой 8.6, тип A — проекты ГЧП",
    indicators=PPP_INDICATORS,
    thresholds=THRESHOLDS_8_6,
    min_completeness=MIN_COMPLETENESS_8_6,
    notes=(
        "1323 проекта. Районной привязки нет ни в одном из пяти исходных "
        "реестров — только уровень области, поэтому тип A не выводится на "
        "районную карту. Веса черновые (ТЗ п.14, п.98)."
    ),
)


def ppp_significance_k(*, top_quartile_cost: bool, republican_level: bool) -> float:
    """Коэффициент значимости K для проекта ГЧП.

    Верхний квартиль стоимости считается по всей выборке проектов, а не по
    региону: методика книги сравнивает проект со страной целиком.
    """
    return round(1.0 + 0.15 * top_quartile_cost + 0.15 * republican_level, 2)


# --- Тип B: заключения строительной экспертизы -------------------------------

B2_SCALE: GradedScale = ((3.0, 1.0), (2.0, 0.6))
"""Число заключений по одному объекту. Считается по объектам, а не по строкам."""

B5_SCALE: GradedScale = ((0.7, 1.0), (0.5, 0.5))
"""Доля топ-1 генпроектировщика у заказчика при не менее чем 3 объектах."""

B6_SCALE: GradedScale = ((0.5, 1.0), (0.3, 0.5))
"""Доля объектов с корректировкой ПСД у заказчика при не менее чем 5 объектах."""

B3_ABSENT_VALUE = 1.0
"""«Отсутствует согласование с автором проекта» — согласования нет вовсе."""

B3_NOT_AGREED_VALUE = 0.7
"""«Не согласован» — процедура шла, но не завершилась."""

EXPERTISE_INDICATORS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        code="B1",
        name="Корректировка ПСД",
        weight=20.0,
        description="Наименование объекта содержит «Корректировка». Бинарный признак.",
        source="Данные Экспертиза: Наименование объекта",
    ),
    IndicatorSpec(
        code="B2",
        name="Неоднократная экспертиза объекта",
        weight=20.0,
        description="Три и более заключений по объекту — 1.0, два — 0.6.",
        source="Данные Экспертиза: Наименование объекта + Заказчик строительства",
    ),
    IndicatorSpec(
        code="B3",
        name="Авторский надзор не согласован",
        weight=15.0,
        description="Согласование отсутствует — 1.0, не согласован — 0.7.",
        source="Данные Экспертиза: Статус авторского договора",
    ),
    IndicatorSpec(
        code="B4",
        name="Отсутствует сметная документация",
        weight=15.0,
        description="Бинарный признак по полю «Имеется сметная документация?».",
        source="Данные Экспертиза: Имеется сметная документация?",
    ),
    IndicatorSpec(
        code="B5",
        name="Концентрация проектировщика у заказчика",
        weight=10.0,
        description="Доля топ-1 генпроектировщика у заказчика при ≥3 объектах.",
        source="Данные Экспертиза: Заказчик строительства + Генеральный проектировщик",
    ),
    IndicatorSpec(
        code="B6",
        name="Заказчик с аномальной долей корректировок",
        weight=10.0,
        description="Доля объектов с корректировкой у заказчика при ≥5 объектах.",
        source="Данные Экспертиза: Заказчик строительства",
    ),
)

EXPERTISE_MODEL = RiskModelSpec(
    code="8.6-expertise",
    version="1.0",
    title="Слой 8.6, тип B — заключения строительной экспертизы",
    indicators=EXPERTISE_INDICATORS,
    thresholds=THRESHOLDS_8_6,
    min_completeness=MIN_COMPLETENESS_8_6,
    notes=(
        "4842 заключения. Единица анализа — заключение, а не объект: строк с "
        "повторной экспертизой 111, а различных объектов за ними 52. Веса "
        "черновые (ТЗ п.14, п.98)."
    ),
)


def expertise_significance_k(*, hazard_class_1_2: bool, responsibility_level_1: bool) -> float:
    """Коэффициент значимости K для заключения экспертизы."""
    return round(1.0 + 0.15 * hazard_class_1_2 + 0.15 * responsibility_level_1, 2)


# --- Применение моделей ------------------------------------------------------


def _constant_multiplier(k: float) -> Callable[[RiskResult], float]:
    """Замыкание вместо лямбды — чтобы множитель был виден в трассировке."""

    def multiplier(_: RiskResult) -> float:
        return k

    return multiplier


def _data_error_override(_: RiskResult) -> tuple[RiskLevel, str]:
    return RiskLevel.UNKNOWN, DATA_ERROR_REASON


@cache
def _spec_variant(
    base: RiskModelSpec, significance_k: float, has_data_error: bool
) -> RiskModelSpec:
    """Вариант модели с конкретным K и признаком ошибки в данных.

    Коэффициент значимости зависит от строки, а не от модели, но ядро принимает
    его как свойство спецификации. Вариантов немного — K принимает три значения
    (1.00, 1.15, 1.30), — поэтому они кэшируются, и на 6165 объектов создаётся
    не более шести спецификаций. Код и версия модели при этом не меняются:
    оценка ссылается на ту же модель, что и все остальные.
    """
    spec = replace(base, score_multiplier=_constant_multiplier(significance_k))
    if has_data_error:
        spec = replace(spec, override=_data_error_override)
    return spec


def evaluate_ppp_project(
    values: Mapping[str, IndicatorValue],
    *,
    significance_k: float = 1.0,
    has_data_error: bool = False,
) -> RiskResult:
    """Посчитать риск одного проекта ГЧП.

    `has_data_error` отправляет объект в серый уровень до сравнения с порогами.
    Балл при этом сохраняется и виден пользователю — но как признак того, что с
    данными что-то не так, а не как оценка.
    """
    return evaluate(_spec_variant(PPP_MODEL, significance_k, has_data_error), values)


def evaluate_expertise_conclusion(
    values: Mapping[str, IndicatorValue],
    *,
    significance_k: float = 1.0,
) -> RiskResult:
    """Посчитать риск одного заключения экспертизы."""
    return evaluate(_spec_variant(EXPERTISE_MODEL, significance_k, False), values)


def preliminary_level(spec: RiskModelSpec, result: RiskResult) -> RiskLevel:
    """Уровень по одному лишь баллу, без учёта полноты.

    Нужен затем, чтобы показать предварительную оценку рядом с серым уровнем.
    Официальным уровнем остаётся `result.level`.
    """
    if result.score is None:
        return RiskLevel.UNKNOWN
    return spec.level_for(result.score)


__all__ = [
    "A2_SCALE",
    "A3_SCALE",
    "A4_SCALE",
    "A5_OVERDUE_DAYS_CRITICAL",
    "A6_SCALE",
    "B2_SCALE",
    "B3_ABSENT_VALUE",
    "B3_NOT_AGREED_VALUE",
    "B5_SCALE",
    "B6_SCALE",
    "DATA_ERROR_REASON",
    "EXPERTISE_INDICATORS",
    "EXPERTISE_MODEL",
    "MIN_COMPLETENESS_8_6",
    "PPP_INDICATORS",
    "PPP_MODEL",
    "THRESHOLDS_8_6",
    "GradedScale",
    "evaluate_expertise_conclusion",
    "evaluate_ppp_project",
    "expertise_significance_k",
    "graded",
    "ppp_significance_k",
    "preliminary_level",
]
