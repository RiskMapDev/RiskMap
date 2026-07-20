"""Модель риска слоя 8.5 — «Субсидии и господдержка» (животноводство).

Единица оценки — **получатель субсидии**, а не выплата. Так решено в самой
книге-источнике, и это правильно: один получатель может провести десятки
заявок, и риск концентрации или аффилированности виден только на уровне лица.

Три обстоятельства, которые определили устройство этого модуля.

**Веса живут в книге, а не в коде.** Ячейки `Методика!B9:B13` — «жёлтые», их
разрешено менять, и лист прямо обещает, что R пересчитается. Поэтому
`build_spec()` принимает веса аргументом, а `REFERENCE_WEIGHTS` — не источник
истины, а контрольное значение: если книга однажды приедет с другими весами,
тест это покажет, но код не сломается и не подменит их своими.

**Серого уровня в методике 8.5 нет.** В отличие от слоёв 8.6 и 8.7, книга не
задаёт правило полноты, поэтому `min_completeness=None`: выдумывать порог,
которого нет в методике, — значит менять смысл чужой модели.

**Пустая ячейка индикатора — не ноль.** У 66 получателей из 3413 не заполнены
район и `s1`, потому что район неизвестен, а не потому что концентрация
нулевая. Ядро расчёта нормирует балл на доступный вес, и такой получатель
получает честную оценку по четырём измеренным индикаторам. Книга же
суммирует пустую ячейку как ноль — Excel их не различает. Обе трактовки
нужны: первая для системы, вторая для сверки с книгой. Отсюда пара функций
`score()` и `score_as_book()`, обе — через `app.risk.core.evaluate`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.risk.core import (
    IndicatorSpec,
    IndicatorValue,
    RiskLevel,
    RiskModelSpec,
    RiskResult,
    Threshold,
    evaluate,
)

LAYER_CODE = "8.5"
MODEL_CODE = "subsidies-8.5"
MODEL_VERSION = "1.0"

METHODOLOGY_SHEET = "Методика"

#: Ячейки листа «Методика», из которых читаются веса. Порядок = порядок s1..s5.
WEIGHT_CELLS: Mapping[str, str] = MappingProxyType(
    {"s1": "B9", "s2": "B10", "s3": "B11", "s4": "B12", "s5": "B13"}
)

#: Ячейка контрольной суммы весов (`=SUM(B9:B13)`). Формула без кэша, читается
#: как None, поэтому сумма всегда пересчитывается нами.
WEIGHT_SUM_CELL = "B14"

#: Ячейки порогов. «Низкий» отдельной ячейки не имеет — это всё, что ниже B16.
THRESHOLD_CELLS: Mapping[RiskLevel, str] = MappingProxyType(
    {RiskLevel.MEDIUM: "B16", RiskLevel.HIGH: "B17", RiskLevel.CRITICAL: "B18"}
)

#: Контрольные значения весов по аудиту книги. Сравниваются с прочитанными
#: в тесте; кодом не используются.
REFERENCE_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {"s1": 0.30, "s2": 0.15, "s3": 0.20, "s4": 0.20, "s5": 0.15}
)

#: Контрольные значения порогов по аудиту книги (35 / 55 / 75).
REFERENCE_THRESHOLDS: Mapping[RiskLevel, float] = MappingProxyType(
    {RiskLevel.MEDIUM: 35.0, RiskLevel.HIGH: 55.0, RiskLevel.CRITICAL: 75.0}
)

WEIGHT_SUM_TOLERANCE = 1e-6
"""Допуск на сумму весов.

Сумма обязана быть единицей: формула R = 100·Σ(wₖ·sₖ) без нормировки на Σw
даёт осмысленный балл только при Σw = 1. Ядро всё равно поделит на доступный
вес, но пороги 35/55/75 калиброваны именно под единичную сумму.
"""


@dataclass(frozen=True, slots=True)
class IndicatorMeta:
    """Паспорт индикатора: то, что книга говорит о нём словами.

    Хранится отдельно от веса, потому что вес — параметр администратора и
    меняется, а смысл индикатора и его нормировка — нет.
    """

    code: str
    name: str
    description: str
    normalization: str
    source_column: str
    """Колонка листа «Риск_получатели», откуда берётся готовое значение sₖ."""

    input_columns: tuple[str, ...]
    """Колонки-входы, по которым книга получила sₖ, — для объяснения оценки."""


INDICATOR_META: tuple[IndicatorMeta, ...] = (
    IndicatorMeta(
        code="s1",
        name="Концентрация",
        description="Доминирование получателя в районе и в области (ТЗ 9.2)",
        normalization="max((доля_в_районе−0.05)/0.45; доля_в_области/0.10), clamp[0;1]",
        source_column="O",
        input_columns=("Доля в районе", "Доля в области"),
    ),
    IndicatorMeta(
        code="s2",
        name="Повторность",
        description="Множественность выплат и программ у одного получателя (ТЗ 9.2)",
        normalization="0.5·(программ−1)/5 + 0.5·(ln(выплат)−ln3)/(ln100−ln3)",
        source_column="P",
        input_columns=("Выплат", "Программ"),
    ),
    IndicatorMeta(
        code="s3",
        name="Аффилированность",
        description="Один руководитель у нескольких получателей (ТЗ 9.2/9.4)",
        normalization="(размер_кластера−1)/2, clamp[0;1]",
        source_column="Q",
        input_columns=("Аффил.(получ. у рук.)",),
    ),
    IndicatorMeta(
        code="s4",
        name="Процессные аномалии",
        description="Выплаты раньше решения либо аномальный лаг (ТЗ 15.3)",
        normalization="доля_аномальных_выплат / 0.30, clamp[0;1]",
        source_column="R",
        input_columns=("Аном. выплат, доля",),
    ),
    IndicatorMeta(
        code="s5",
        name="Выбросы сумм",
        description="Суммы-выбросы против медианы «вид × программа» (ТЗ 9.2)",
        normalization="доля_выплат-выбросов / 0.20, clamp[0;1]",
        source_column="S",
        input_columns=("Выбросов сумм, доля",),
    ),
)

INDICATOR_CODES: tuple[str, ...] = tuple(meta.code for meta in INDICATOR_META)

BOOK_EMPTY_CELL_NOTE = "в книге ячейка пуста; семантика Excel засчитывает её как ноль"
NOT_MEASURED_NOTE = "значение не рассчитано в книге: район получателя неизвестен"


def build_thresholds(bounds: Mapping[RiskLevel, float]) -> tuple[Threshold, ...]:
    """Собрать пороги для ядра из границ, прочитанных в книге.

    Нижняя граница «низкого» добавляется явным нулём: в книге её нет, потому
    что «низкий» там определён как «всё остальное», а ядру нужен полный набор
    пар «граница → уровень».
    """
    missing = [level for level in (RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL)
               if level not in bounds]
    if missing:
        raise ValueError(f"Слой {LAYER_CODE}: в методике не заданы пороги {missing}")

    ordered = (
        (0.0, RiskLevel.LOW),
        (float(bounds[RiskLevel.MEDIUM]), RiskLevel.MEDIUM),
        (float(bounds[RiskLevel.HIGH]), RiskLevel.HIGH),
        (float(bounds[RiskLevel.CRITICAL]), RiskLevel.CRITICAL),
    )
    return ordered


def build_spec(
    weights: Mapping[str, float],
    thresholds: Mapping[RiskLevel, float],
    *,
    version: str = MODEL_VERSION,
) -> RiskModelSpec:
    """Собрать модель слоя 8.5 из весов и порогов, прочитанных в книге.

    Веса приходят аргументом намеренно: лист «Методика» разрешает их менять, и
    зашитая в код копия рано или поздно разойдётся с книгой молча.
    """
    unknown = set(weights) - set(INDICATOR_CODES)
    if unknown:
        raise ValueError(f"Слой {LAYER_CODE}: неизвестные индикаторы в весах {sorted(unknown)}")
    absent = set(INDICATOR_CODES) - set(weights)
    if absent:
        raise ValueError(f"Слой {LAYER_CODE}: не прочитаны веса индикаторов {sorted(absent)}")

    total = sum(weights[code] for code in INDICATOR_CODES)
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"Слой {LAYER_CODE}: сумма весов {total!r} ≠ 1. "
            f"Пороги 35/55/75 калиброваны под единичную сумму, "
            f"считать по такой методике нельзя."
        )

    indicators = tuple(
        IndicatorSpec(
            code=meta.code,
            name=meta.name,
            weight=float(weights[meta.code]),
            description=meta.description,
            source=f"Риск_получатели!{meta.source_column} ← {', '.join(meta.input_columns)}",
        )
        for meta in INDICATOR_META
    )

    return RiskModelSpec(
        code=MODEL_CODE,
        version=version,
        title="Субсидии и господдержка (слой 8.5)",
        indicators=indicators,
        thresholds=build_thresholds(thresholds),
        scale=100.0,
        # Серого уровня методика 8.5 не предусматривает — см. модульный docstring.
        min_completeness=None,
        notes=(
            "Веса и пороги прочитаны из листа «Методика» книги "
            "«Риск_субсидии_Алматинская.xlsx». Формулы R, «Уровень» и "
            "«Риск-экспозиция» в книге не имеют кэша и пересчитываются здесь."
        ),
    )


def indicator_values(measurements: Mapping[str, float | None]) -> dict[str, IndicatorValue]:
    """Значения индикаторов в семантике проекта.

    Пустая ячейка означает «не измерено»: ядро исключит индикатор из числителя
    и знаменателя, а не спишет получателю нулевой риск концентрации только
    потому, что его район неизвестен.
    """
    return {
        code: IndicatorValue(
            code=code,
            value=None if measurements.get(code) is None else float(measurements[code] or 0.0),
            raw_value=measurements.get(code),
            note="" if measurements.get(code) is not None else NOT_MEASURED_NOTE,
        )
        for code in INDICATOR_CODES
    }


def book_indicator_values(measurements: Mapping[str, float | None]) -> dict[str, IndicatorValue]:
    """Значения индикаторов в семантике книги: пустая ячейка = ноль.

    Нужны исключительно для сверки с контрольными числами аудита. В расчёт,
    который видит пользователь, эта трактовка не идёт: она занижает балл тем
    получателям, о которых у нас меньше всего сведений.
    """
    return {
        code: IndicatorValue(
            code=code,
            value=float(measurements.get(code) or 0.0),
            raw_value=measurements.get(code),
            note="" if measurements.get(code) is not None else BOOK_EMPTY_CELL_NOTE,
        )
        for code in INDICATOR_CODES
    }


def score(spec: RiskModelSpec, measurements: Mapping[str, float | None]) -> RiskResult:
    """Оценка получателя по методике проекта."""
    return evaluate(spec, indicator_values(measurements))


def score_as_book(spec: RiskModelSpec, measurements: Mapping[str, float | None]) -> RiskResult:
    """Оценка получателя ровно так, как её посчитал бы Excel.

    Отдельная функция, а не флаг: две трактовки должны быть видны в коде как
    два разных решения, иначе «как в книге» незаметно станет умолчанием.
    """
    return evaluate(spec, book_indicator_values(measurements))


def risk_exposure(amount: float | None, risk_score: float | None) -> float | None:
    """Риск-экспозиция = сумма × R / 100 (примечание методики, ячейка A22).

    `None` при неизвестном балле: ноль здесь означал бы «денег под риском нет»,
    что противоположно истине «мы не смогли оценить риск».
    """
    if amount is None or risk_score is None:
        return None
    return amount * risk_score / 100.0


__all__ = [
    "BOOK_EMPTY_CELL_NOTE",
    "INDICATOR_CODES",
    "INDICATOR_META",
    "LAYER_CODE",
    "METHODOLOGY_SHEET",
    "MODEL_CODE",
    "MODEL_VERSION",
    "NOT_MEASURED_NOTE",
    "REFERENCE_THRESHOLDS",
    "REFERENCE_WEIGHTS",
    "THRESHOLD_CELLS",
    "WEIGHT_CELLS",
    "WEIGHT_SUM_CELL",
    "IndicatorMeta",
    "book_indicator_values",
    "build_spec",
    "build_thresholds",
    "indicator_values",
    "risk_exposure",
    "score",
    "score_as_book",
]
