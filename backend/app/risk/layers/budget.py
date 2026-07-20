"""Слой 8.3 «Бюджетные риски»: модель, нормировка, расчёт строки.

Единица анализа — **область × месяц**, 240 строк (20 областей × 12 месяцев
2025 года). Это общереспубликанский слой: `geo_level` всегда `REGION`, районов
в нём нет вовсе. Путать его со слоем 8.4, где разрезаются 9 районов одной
Алматинской области, нельзя — совпадает только шкала уровней.

Устройство методики (лист `Параметры` книги 8.3):

* 15 индикаторов R01–R15 с весами, дающими в сумме ровно 100;
* у каждого два порога — «без риска» (0 баллов) и «критический» (100 баллов),
  между ними линейная интерполяция, за пределами — отсечка 0/100;
* направление `LOW` означает, что риск растёт при **падении** показателя
  (недобор доходов), `HIGH` — при росте;
* итог: `MAX( Σ wᵢ×Sᵢ/100 ; переопределение )`.

Два места, где легко ошибиться, и потому они разобраны явно.

**Переопределение — это пол балла, а не замена уровня.** В книге написано
`MAX(взвешенная сумма; 75)`, то есть при срабатывании условия итог не
заменяется на «критический», а поднимается до 75 — и уже 75 попадает в
критический диапазон по границе `>= 75`. Разница видна на единственной
сработавшей строке: её балл равен ровно 75,0, а не 100. Поэтому здесь
используется `score_floor` ядра, а не `override`.

**Полнота данных в 8.3 — не то же самое, что полнота ядра.** Ядро считает
полноту как долю измеренного веса, и в этом слое она всегда равна 1: все 15
индикаторов измерены на всех 240 строках. Книга же называет «полнотой»
величину `1 − флаги_качества/3`, которая описывает качество исходной
агрегации, а не покрытие индикаторов. Это разные вещи, и вторая живёт в
`BudgetRowResult.data_completeness` отдельно. На уровень риска она в этом слое
не влияет — «серого» уровня в методике 8.3 нет (`min_completeness=None`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from app.risk.core import (
    IndicatorDirection,
    IndicatorSpec,
    IndicatorValue,
    RiskLevel,
    RiskModelSpec,
    RiskResult,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class NormalizationBand:
    """Пара порогов одного индикатора: «без риска» → 0, «критический» → 100.

    Хранятся именно так, как в листе `Параметры`, включая случай `no_risk >
    critical` у направления `LOW` (например R01: 0,98 → 0 баллов, 0,80 → 100).
    Переставлять их «по возрастанию» нельзя — направление задаётся отдельно и
    перестановка молча инвертирует смысл индикатора.
    """

    no_risk: float
    critical: float
    direction: IndicatorDirection

    def score(self, raw: float) -> float:
        """Балл 0–100 по сырому показателю.

        Дословный перенос двух формул листа `Расчет_месяц`:

            LOW  = MAX(0; MIN(100; (порог_без_риска − x) / (без_риска − крит.) × 100))
            HIGH = MAX(0; MIN(100; (x − порог_без_риска) / (крит. − без_риска) × 100))
        """
        span = self.no_risk - self.critical
        if self.direction is IndicatorDirection.LOWER_IS_RISKIER:
            if span == 0:
                # Пороги совпали: интерполировать не по чему. Любое значение
                # ниже порога — сразу максимум риска, иначе ноль.
                return 100.0 if raw < self.no_risk else 0.0
            return max(0.0, min(100.0, (self.no_risk - raw) / span * 100.0))

        if span == 0:
            return 100.0 if raw > self.no_risk else 0.0
        return max(0.0, min(100.0, (raw - self.no_risk) / -span * 100.0))


_LOW = IndicatorDirection.LOWER_IS_RISKIER
_HIGH = IndicatorDirection.HIGHER_IS_RISKIER

# Веса, пороги и направления — лист «Параметры», строки 5–19. Сумма весов 100
# проверяется тестом: книга объявляет это правилом управления моделью.
BANDS: Final[dict[str, NormalizationBand]] = {
    "R01": NormalizationBand(0.98, 0.80, _LOW),
    "R02": NormalizationBand(0.95, 0.75, _LOW),
    "R03": NormalizationBand(1.05, 1.20, _HIGH),
    "R04": NormalizationBand(0.03, 0.20, _HIGH),
    "R05": NormalizationBand(0.05, 0.30, _HIGH),
    "R06": NormalizationBand(0.02, 0.12, _HIGH),
    "R07": NormalizationBand(1.00, 0.25, _LOW),
    "R08": NormalizationBand(2.00, 5.00, _HIGH),
    "R09": NormalizationBand(0.02, 0.15, _HIGH),
    "R10": NormalizationBand(0.05, 0.20, _HIGH),
    "R11": NormalizationBand(0.02, 0.12, _HIGH),
    "R12": NormalizationBand(0.10, 0.50, _HIGH),
    "R13": NormalizationBand(0.18, 0.40, _HIGH),
    "R14": NormalizationBand(0.01, 0.08, _HIGH),
    "R15": NormalizationBand(0.0, 3.0, _HIGH),
}

# Индикаторы, дающие 0 баллов на всех 240 строках книги. Это факт данных, а не
# дефект модели: пороги «перерасход периода», «отставание обязательств» и
# «ширина недоисполнения» в выборке 2025 года не достигаются ни разу.
# Суммарно 14 % веса модели не работает, и R11 (средний балл 81) фактически
# доминирует. Индикаторы намеренно оставлены в модели: их вырожденность —
# результат, который нужно показывать, а не прятать удалением из методики.
DEGENERATE_INDICATORS: Final[frozenset[str]] = frozenset({"R03", "R10", "R12"})

INDICATORS: Final[tuple[IndicatorSpec, ...]] = (
    IndicatorSpec("R01", "Недобор доходов", 13.0, _LOW,
                  "sumrg / plgp по разделу I. ДОХОДЫ", "Расчет_месяц!AT"),
    IndicatorSpec("R02", "Недоисполнение расходов", 15.0, _LOW,
                  "sumrg / plgp по разделу II. ЗАТРАТЫ", "Расчет_месяц!AU"),
    IndicatorSpec("R03", "Перерасход периода", 4.0, _HIGH,
                  "тот же показатель, что R02, но в обратную сторону", "Расчет_месяц!AU"),
    IndicatorSpec("R04", "Интенсивность уточнений", 8.0, _HIGH,
                  "среднее |utch − utv| / |utv| по доходам и затратам", "Расчет_месяц!AV"),
    IndicatorSpec("R05", "Ошибка месячного профиля", 6.0, _HIGH,
                  "среднее |Δфакт − Δплан| / |Δплан|", "Расчет_месяц!AW"),
    IndicatorSpec("R06", "Отклонение бюджетного сальдо", 10.0, _HIGH,
                  "|факт сальдо − план сальдо| / |план затрат периода|", "Расчет_месяц!AX"),
    IndicatorSpec("R07", "Недостаточный кассовый буфер", 5.0, _LOW,
                  "конечный остаток / (годовой план затрат / 12), в месяцах", "Расчет_месяц!AY"),
    IndicatorSpec("R08", "Избыточные неиспользуемые остатки", 4.0, _HIGH,
                  "тот же показатель, что R07 — двойной счёт ликвидности", "Расчет_месяц!AZ"),
    IndicatorSpec("R09", "Давление остатка к освоению", 9.0, _HIGH,
                  "max(0; plgp − sumrg) / max(plg − plgp; 1)", "Расчет_месяц!BA"),
    IndicatorSpec("R10", "Отставание принятия обязательств", 6.0, _HIGH,
                  "max(0; месяц/12 − obz/plgo)", "Расчет_месяц!BB"),
    IndicatorSpec("R11", "Нагрузка неоплаченных обязательств", 6.0, _HIGH,
                  "max(0; obzsumrg) / |plg|", "Расчет_месяц!BC"),
    IndicatorSpec("R12", "Ширина функционального недоисполнения", 4.0, _HIGH,
                  "доля функций расходов с исполнением ниже 85 %", "Расчет_месяц!BD"),
    IndicatorSpec("R13", "Концентрация расходов (HHI)", 2.0, _HIGH,
                  "Σ(доля факта функции)²", "Расчет_месяц!BE"),
    IndicatorSpec("R14", "Отклонение финансовых операций", 4.0, _HIGH,
                  "(|Δкредитование| + |Δфин. активы|) / |план затрат|", "Расчет_месяц!BF"),
    IndicatorSpec("R15", "Качество данных", 4.0, _HIGH,
                  "число флагов качества на строке", "Расчет_месяц!BG"),
)

THRESHOLDS: Final[tuple[tuple[float, RiskLevel], ...]] = (
    (0.0, RiskLevel.LOW),
    (25.0, RiskLevel.MEDIUM),
    (50.0, RiskLevel.HIGH),
    (75.0, RiskLevel.CRITICAL),
)

OVERRIDE_FLOOR: Final[float] = 75.0
"""Пол балла при срабатывании критического условия."""

BUDGET_8_3: Final[RiskModelSpec] = RiskModelSpec(
    code="8.3",
    version="1.0",
    title="Бюджетные риски (область × месяц)",
    indicators=INDICATORS,
    thresholds=THRESHOLDS,
    scale=100.0,
    # Серого уровня в методике 8.3 нет: неполнота учитывается баллом R15,
    # а не отдельным визуальным статусом.
    min_completeness=None,
    # Пол балла привязывается построчно в `spec_for_row()`. На уровне модели
    # его задать нельзя: одно из четырёх условий — отрицательный конечный
    # остаток — не является индикатором и в `values` не попадает.
    score_floor=None,
    notes=(
        "Переопределение реализовано как пол в 75 баллов, а не как замена "
        "уровня. Индикаторы R03, R10, R12 вырождены на всех 240 строках "
        "книги 2025 года."
    ),
)


@dataclass(frozen=True, slots=True)
class BudgetRawIndicators:
    """Сырые показатели одной строки «область × месяц» (колонки AT…BG книги).

    Отдельный тип, а не словарь: имена показателей — часть методики, и опечатка
    в ключе должна ломаться на этапе типизации, а не превращаться в молчаливое
    «индикатор не измерен».
    """

    r01_dohody_ispolnenie: float
    r02_zatraty_ispolnenie: float
    r04_intensivnost_utochneniy: float
    r05_oshibka_profilya: float
    r06_otklonenie_saldo: float
    r07_kassovyy_bufer: float
    r08_izbytochnye_ostatki: float
    r09_davlenie_ostatka: float
    r10_otstavanie_obyazatelstv: float
    r11_neoplachennye_obyazatelstva: float
    r12_shirina_nedoispolneniya: float
    r13_hhi: float
    r14_finansovye_operatsii: float
    r15_flagi_kachestva: float

    def as_mapping(self) -> dict[str, float]:
        """Сырые значения по кодам индикаторов.

        R02 и R03 считаются от одного и того же показателя (исполнение
        расходов), но нормируются в разные стороны, — как в книге, где обе
        колонки ссылаются на `AU`. То же у R07 и R08 относительно `AY`.
        """
        return {
            "R01": self.r01_dohody_ispolnenie,
            "R02": self.r02_zatraty_ispolnenie,
            "R03": self.r02_zatraty_ispolnenie,
            "R04": self.r04_intensivnost_utochneniy,
            "R05": self.r05_oshibka_profilya,
            "R06": self.r06_otklonenie_saldo,
            "R07": self.r07_kassovyy_bufer,
            "R08": self.r08_izbytochnye_ostatki,
            "R09": self.r09_davlenie_ostatka,
            "R10": self.r10_otstavanie_obyazatelstv,
            "R11": self.r11_neoplachennye_obyazatelstva,
            "R12": self.r12_shirina_nedoispolneniya,
            "R13": self.r13_hhi,
            "R14": self.r14_finansovye_operatsii,
            "R15": self.r15_flagi_kachestva,
        }


@dataclass(frozen=True, slots=True)
class BudgetRowInputs:
    """Всё, что нужно для оценки одной строки «область × месяц»."""

    territory_id: str
    territory_name: str
    month: int
    period: str
    """Период в исходном виде `MM.YYYY` — в книге это строка, а не дата."""

    raw: BudgetRawIndicators
    closing_balance: float
    """Конечный остаток бюджетных средств (колонка AD). Участвует только в
    условии переопределения, собственного индикатора у него нет."""

    @property
    def key(self) -> str:
        """Ключ «территория-месяц» вида `REG-001-01` (колонка CD книги)."""
        return f"{self.territory_id}-{self.month:02d}"


def override_triggered(inputs: BudgetRowInputs) -> bool:
    """Сработало ли критическое переопределение.

    Дословно из книги (`Расчет_месяц`, CE2):

        =IF(OR(AT2<0.7; AU2<0.6; AD2<0; BG2>=3); 1; 0)

    То есть: исполнение доходов ниже 70 %, либо исполнение расходов ниже 60 %,
    либо конечный остаток отрицателен, либо набралось три и более флагов
    качества данных.
    """
    return (
        inputs.raw.r01_dohody_ispolnenie < 0.7
        or inputs.raw.r02_zatraty_ispolnenie < 0.6
        or inputs.closing_balance < 0
        or inputs.raw.r15_flagi_kachestva >= 3
    )


def data_completeness(flags: float) -> float:
    """Полнота данных строки по книге: `MAX(0; 1 − MIN(1; флаги/3))`.

    Это оценка качества исходной агрегации, а не покрытия индикаторов, и на
    уровень риска в слое 8.3 она не влияет. 32 строки книги имеют полноту
    0,667 — у них отсутствует раздел «IV. Сальдо по операциям с финансовыми
    активами», из-за чего R14 посчитан на неполных данных.
    """
    return max(0.0, 1.0 - min(1.0, flags / 3.0))


def indicator_values(raw: BudgetRawIndicators) -> dict[str, IndicatorValue]:
    """Нормировать сырые показатели в значения индикаторов [0, 1].

    Ядро работает со значениями [0, 1], книга — с баллами 0–100. Делим на 100
    здесь, а не в ядре: `weight × value` в ядре и `wᵢ × Sᵢ / 100` в книге —
    это одна и та же величина, и делить надо ровно один раз.
    """
    values: dict[str, IndicatorValue] = {}
    for code, raw_value in raw.as_mapping().items():
        band = BANDS[code]
        values[code] = IndicatorValue(
            code=code,
            value=band.score(raw_value) / 100.0,
            raw_value=raw_value,
        )
    return values


def spec_for_row(inputs: BudgetRowInputs) -> RiskModelSpec:
    """Модель с привязанным к строке полом балла.

    Пол зависит от конечного остатка, который индикатором не является, поэтому
    замыкание строится на строку. Версия модели при этом не меняется: правило
    пола — часть методики версии 1.0, а не отдельная её редакция.
    """
    floor = OVERRIDE_FLOOR if override_triggered(inputs) else None
    return replace(BUDGET_8_3, score_floor=lambda _values: floor)


@dataclass(frozen=True, slots=True)
class BudgetRowResult:
    """Оценка одной строки «область × месяц»."""

    key: str
    territory_id: str
    territory_name: str
    month: int
    period: str

    risk: RiskResult
    data_completeness: float
    """Полнота по книге (`1 − флаги/3`) — не путать с `risk.completeness`,
    которая измеряет покрытие индикаторов и в этом слое всегда равна 1."""

    override_triggered: bool

    @property
    def score(self) -> float:
        """Итоговый балл. В слое 8.3 он всегда посчитан: все 15 индикаторов
        измерены на каждой строке, поэтому `None` здесь невозможен."""
        score = self.risk.score
        if score is None:  # pragma: no cover — недостижимо при полном наборе
            raise ValueError(f"Строка {self.key}: балл не посчитан")
        return score

    @property
    def level(self) -> RiskLevel:
        return self.risk.level


def evaluate_row(inputs: BudgetRowInputs) -> BudgetRowResult:
    """Посчитать риск одной строки «область × месяц»."""
    values = indicator_values(inputs.raw)
    result = evaluate(spec_for_row(inputs), values)
    return BudgetRowResult(
        key=inputs.key,
        territory_id=inputs.territory_id,
        territory_name=inputs.territory_name,
        month=inputs.month,
        period=inputs.period,
        risk=result,
        data_completeness=data_completeness(inputs.raw.r15_flagi_kachestva),
        override_triggered=override_triggered(inputs),
    )


def rank_within_month(results: list[BudgetRowResult]) -> dict[str, int]:
    """Ранг территории внутри каждого месяца, 1 — самый рискованный.

    Тай-брейк по `territory_id`, как в книге (`Расчет_месяц`, BY2): при равных
    баллах выше идёт территория с меньшим кодом. Без явного тай-брейка ранги
    поехали бы от порядка строк во входных данных.
    """
    ranks: dict[str, int] = {}
    by_month: dict[int, list[BudgetRowResult]] = {}
    for row in results:
        by_month.setdefault(row.month, []).append(row)

    for rows in by_month.values():
        ordered = sorted(rows, key=lambda r: (-r.score, r.territory_id))
        for position, row in enumerate(ordered, start=1):
            ranks[row.key] = position
    return ranks


__all__ = [
    "BANDS",
    "BUDGET_8_3",
    "DEGENERATE_INDICATORS",
    "INDICATORS",
    "OVERRIDE_FLOOR",
    "THRESHOLDS",
    "BudgetRawIndicators",
    "BudgetRowInputs",
    "BudgetRowResult",
    "NormalizationBand",
    "data_completeness",
    "evaluate_row",
    "indicator_values",
    "override_triggered",
    "rank_within_month",
    "spec_for_row",
]
