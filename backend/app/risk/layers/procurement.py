"""Слой 8.4 «Госзакупки»: модель, коэффициент значимости, категория A.

Единица анализа — **договор**. В книге их 355, по 26 поставщикам, все
зарегистрированы в Алматинской области; разрез идёт по 9 районам. Привязка к
району выполняется по юридическому адресу **поставщика**, а не заказчика и не
места поставки: КАТО места поставки заполнен лишь у половины лотов, а привязка
по заказчику покрывала бы 129 договоров из 355 вместо 355 из 355.

Расчёт (лист `Формула`, восемь шагов):

    S_raw   = Σ (wᵢ × vᵢ)             по доступным метрикам
    W_avail = Σ (wᵢ)                  по доступным метрикам
    S_norm  = 100 × S_raw / W_avail
    K       = 1,00 + 0,15×I_сумма + 0,15×I_расторгнут      ∈ [1,00; 1,30]
    Score   = min(100 ; S_norm × K)
    полнота = W_avail / 100 ;  ниже 50 % → серый уровень

Три вещи в этой методике устроены не так, как подсказывает интуиция.

**Категория A сильнее всего остального.** Присутствие поставщика в реестре
недобросовестных участников госзакупок либо в списке лжепредприятий делает
договор критическим независимо от балла и независимо от полноты. Это
установленный юридический факт, а не расчётный признак, поэтому реализовано
через `override` ядра, а не через пол балла, как в слое 8.3. Приоритет над
серым уровнем существенен: 48 критических договоров книги получены
исключительно так, и их баллы лежат в диапазоне 11,8–50,0.

**Порог «≥ 75 → критический» в этих данных недостижим.** Максимум по всей
выборке — 67,1. Ветка порога кодом поддержана и покрыта тестом на
синтетических значениях, но на реальных данных не срабатывает ни разу. Это
свойство выборки, а не ошибка: считать, что критических договоров нет, нельзя.

**Выборка смещена.** 26 поставщиков отобраны заранее как рискованные по слою
8.7 (22 «высокий» + 4 «критический»). Книга предупреждает об этом прямо:
достоверно только относительное ранжирование внутри выборки, абсолютные уровни
завышены. Модель это не исправляет и не должна.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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

_HIGH = IndicatorDirection.HIGHER_IS_RISKIER

INDICATORS: Final[tuple[IndicatorSpec, ...]] = (
    IndicatorSpec("B1", "Закупка из одного источника", 15.0, _HIGH,
                  "1,0 — из одного источника; 0,5 — электронный магазин; иначе 0",
                  "contract_details.planned_method"),
    IndicatorSpec("B2", "Низкая или формальная конкуренция", 15.0, _HIGH,
                  "1,0 при ≤1 заявке; 0,6 при 2; 0,3 при 3; иначе 0",
                  "lots.submitted_bids"),
    IndicatorSpec("B3", "Регулярная победа одного поставщика", 15.0, _HIGH,
                  "доля договоров пары «заказчик–поставщик»: 1,0 при ≥0,7; 0,6 при ≥0,5",
                  "lots.customer + contract_details.supplier_bin"),
    IndicatorSpec("B4", "Дробление закупок", 10.0, _HIGH,
                  "число договоров из одного источника у пары: 1,0 при ≥5; 0,6 при ≥3",
                  "lots.customer + planned_method"),
    IndicatorSpec("B5", "Неоднократное продление сроков", 10.0, _HIGH,
                  "доп. соглашений со сменой срока: 1,0 при ≥3; 0,6 при 2; 0,3 при 1",
                  "contract_additions.justification"),
    IndicatorSpec("B6", "Значительное увеличение цены", 10.0, _HIGH,
                  "рост суммы договора: 1,0 при ≥1,5; 0,6 при ≥1,2; 0,3 при ≥1,05",
                  "contract_additions.final_total_amount"),
    IndicatorSpec("B7", "Отсутствие у поставщика ресурсов", 10.0, _HIGH,
                  "1,0 при отсутствии физической активности; 0,5 при ≤1 договоре",
                  "organization_profile.no_physical_activity"),
    IndicatorSpec("B8", "Несоответствие профиля предмету закупки", 5.0, _HIGH,
                  "1,0, если предмет «Работа», а у поставщика нет секции «Строительство»",
                  "oked.csv + contract_details.subject_type"),
    IndicatorSpec("B9", "Признаки фиктивности вне категории A", 10.0, _HIGH,
                  "1,0 при номинальном директоре или массовом адресе; 0,5 при пёстром ОКЭД",
                  "organization_profile.nominal_director / mass_address"),
)

THRESHOLDS: Final[tuple[tuple[float, RiskLevel], ...]] = (
    (0.0, RiskLevel.LOW),
    (25.0, RiskLevel.MEDIUM),
    (50.0, RiskLevel.HIGH),
    (75.0, RiskLevel.CRITICAL),
)

MIN_COMPLETENESS: Final[float] = 0.5
"""Ниже 50 % доступного веса уровень становится серым (требование ТЗ 7.3)."""

AMOUNT_QUARTILE: Final[float] = 8_906_750.0
"""Верхний квартиль суммы договора по выборке — порог признака `I_сумма`."""

K_BASE: Final[float] = 1.00
K_STEP: Final[float] = 0.15
"""Каждый из двух признаков значимости добавляет к K по 0,15."""

DEGENERATE_INDICATORS: Final[frozenset[str]] = frozenset({"B4"})
"""B4 «дробление закупок» измерен у 224 договоров и везде равен нулю.

10 % веса модели не работает. Как и вырожденные индикаторы слоя 8.3,
метрика оставлена в модели: её нулевой результат — вывод о данных, а не повод
переписать методику.
"""

PROCUREMENT_8_4: Final[RiskModelSpec] = RiskModelSpec(
    code="8.4",
    version="1.0",
    title="Госзакупки (единица анализа — договор)",
    indicators=INDICATORS,
    thresholds=THRESHOLDS,
    scale=100.0,
    min_completeness=MIN_COMPLETENESS,
    # Коэффициент K и категория A зависят от конкретного договора и поставщика,
    # поэтому привязываются построчно в `spec_for_contract()`. Здесь они не
    # заданы вовсе: модель без привязки к договору умножителя не имеет.
    score_multiplier=None,
    notes=(
        "Категория A даёт критический уровень независимо от балла и полноты. "
        "Порог «≥ 75 → критический» на данных книги недостижим (максимум 67,1). "
        "Индикатор B4 вырожден."
    ),
)


@dataclass(frozen=True, slots=True)
class SupplierRiskProfile:
    """Признаки поставщика, влияющие на оценку договора.

    `bin` хранится строкой из 12 знаков: в источниках БИН записан числом, и у
    763 организаций из 3 668 потеряны ведущие нули. Восстановление через
    `zfill(12)` выполняется на этапе импорта, сюда значение приходит уже
    нормализованным.
    """

    bin: str
    name: str = ""

    in_rnu_gz: bool = False
    """Реестр недобросовестных участников госзакупок — признак A1."""

    in_lzhepred_list: bool = False
    """Список лжепредприятий — признак A2."""

    @property
    def is_category_a(self) -> bool:
        return self.in_rnu_gz or self.in_lzhepred_list

    @property
    def category_a_reason(self) -> str:
        """Формулировка для показа пользователю: за что именно переопределено."""
        reasons = []
        if self.in_rnu_gz:
            reasons.append("реестр недобросовестных участников госзакупок")
        if self.in_lzhepred_list:
            reasons.append("список лжепредприятий")
        return "категория A: " + " и ".join(reasons) if reasons else ""


@dataclass(frozen=True, slots=True)
class ContractRiskInputs:
    """Всё, что нужно для оценки одного договора."""

    contract_id: str
    """Строка, а не число. В расчётном листе книги это `str`, в сырых листах —
    `int`; join без приведения к общему типу даёт ноль совпадений."""

    supplier: SupplierRiskProfile
    district: str
    """Район по юридическому адресу поставщика."""

    region: str = "Алматинская область"

    indicators: dict[str, float | None] = field(default_factory=dict)
    """Значения B1…B9 в [0, 1]. `None` — метрика недоступна и не участвует ни
    в числителе, ни в знаменателе. Подстановка нуля запрещена методикой явно:
    «нет данных» ≠ «нет риска»."""

    final_amount: float | None = None
    is_terminated: bool = False
    customer: str | None = None

    @property
    def amount_above_quartile(self) -> bool:
        """Признак `I_сумма`: сумма договора не ниже верхнего квартиля выборки."""
        return self.final_amount is not None and self.final_amount >= AMOUNT_QUARTILE

    @property
    def significance_multiplier(self) -> float:
        """Коэффициент значимости K ∈ {1,00; 1,15; 1,30}.

        Округление до двух знаков не косметическое: `1.0 + 0.15 + 0.15` в
        double даёт 1.2999999999999998, и сравнение с эталонным 1.30 в тесте
        падает без него.
        """
        k = K_BASE + K_STEP * self.amount_above_quartile + K_STEP * self.is_terminated
        return round(k, 2)


def indicator_values(inputs: ContractRiskInputs) -> dict[str, IndicatorValue]:
    """Разложить значения метрик в термины ядра.

    Метрика, отсутствующая в словаре или равная `None`, становится
    неизмеренной: ядро исключит её и из суммы, и из доступного веса.
    """
    values: dict[str, IndicatorValue] = {}
    for spec in INDICATORS:
        value = inputs.indicators.get(spec.code)
        values[spec.code] = IndicatorValue(
            code=spec.code,
            value=value,
            raw_value=value,
            note="" if value is not None else "метрика недоступна для этого договора",
        )
    return values


def spec_for_contract(inputs: ContractRiskInputs) -> RiskModelSpec:
    """Модель с привязанными к договору коэффициентом K и категорией A."""
    multiplier = inputs.significance_multiplier
    reason = inputs.supplier.category_a_reason

    def override(_result: RiskResult) -> tuple[RiskLevel, str] | None:
        return (RiskLevel.CRITICAL, reason) if reason else None

    return replace(
        PROCUREMENT_8_4,
        score_multiplier=lambda _result: multiplier,
        override=override,
    )


@dataclass(frozen=True, slots=True)
class ContractRiskResult:
    """Оценка одного договора."""

    contract_id: str
    supplier_bin: str
    district: str
    region: str

    risk: RiskResult
    significance_multiplier: float
    is_category_a: bool

    @property
    def raw_score(self) -> float | None:
        """`S_raw` книги — взвешенная сумма по доступным метрикам."""
        return self.risk.raw_score

    @property
    def available_weight(self) -> float:
        """`W_avail` книги."""
        return self.risk.available_weight

    @property
    def normalized_score(self) -> float | None:
        """`S_norm` книги — балл до умножения на K."""
        return self.risk.normalized_score

    @property
    def score(self) -> float | None:
        """`Risk Score` книги. `None`, если не измерена ни одна метрика."""
        return self.risk.score

    @property
    def level(self) -> RiskLevel:
        return self.risk.level

    @property
    def level_label_ru(self) -> str:
        """Название уровня в терминах книги 8.4.

        Книга пишет уровни строчными буквами и называет серый «серый
        (недостаточно данных)», книга 8.3 — с заглавной и без серого вовсе.
        Единый справочник уровней живёт в ядре; здесь только представление.
        """
        if self.level is RiskLevel.UNKNOWN:
            return "серый (недостаточно данных)"
        return self.level.label_ru.lower()


def evaluate_contract(inputs: ContractRiskInputs) -> ContractRiskResult:
    """Посчитать риск одного договора."""
    result = evaluate(spec_for_contract(inputs), indicator_values(inputs))
    return ContractRiskResult(
        contract_id=inputs.contract_id,
        supplier_bin=inputs.supplier.bin,
        district=inputs.district,
        region=inputs.region,
        risk=result,
        significance_multiplier=inputs.significance_multiplier,
        is_category_a=inputs.supplier.is_category_a,
    )


# --- Вывод метрик из сырых данных -------------------------------------------
#
# Ниже — независимая реализация формул листа `Реестр метрик`. Она нужна не
# чтобы заменить значения книги, а чтобы их проверить: расчётный лист 8.4 —
# статический экспорт без единой формулы, и без пересчёта из сырья утверждать,
# что методика воспроизводится, нельзя.


def derive_b1(method: str | None) -> float | None:
    """B1 «закупка из одного источника» по способу закупки.

    Способ неизвестен — метрика недоступна, а не равна нулю. Различие
    принципиально: у трёх договоров книги способ записан заглушкой `'nan'`
    (строка, а не пустая ячейка), и именно из-за них расчётный лист внутренне
    противоречив — см. `docs/assumptions-and-gaps.md`.
    """
    if method is None:
        return None
    low = method.casefold()
    if "одного источника" in low:
        return 1.0
    if "магазин" in low:
        return 0.5
    return 0.0


def derive_b2(submitted_bids: float | None) -> float | None:
    """B2 «низкая конкуренция» по числу поданных заявок."""
    if submitted_bids is None:
        return None
    if submitted_bids <= 1:
        return 1.0
    if submitted_bids == 2:
        return 0.6
    if submitted_bids == 3:
        return 0.3
    return 0.0


def derive_b3(pair_contracts: int, customer_contracts: int) -> float | None:
    """B3 «регулярная победа одного поставщика».

    Считается только у заказчиков с тремя и более договорами: на двух
    договорах доля 100 % ничего не означает.
    """
    if customer_contracts < 3:
        return None
    share = pair_contracts / customer_contracts
    if share >= 0.7:
        return 1.0
    if share >= 0.5:
        return 0.6
    return 0.0


def derive_b4(one_source_contracts: int) -> float:
    """B4 «дробление закупок» — число закупок из одного источника у пары."""
    if one_source_contracts >= 5:
        return 1.0
    if one_source_contracts >= 3:
        return 0.6
    return 0.0


def derive_b5(term_change_additions: int) -> float:
    """B5 «неоднократное продление сроков» по обоснованиям доп. соглашений."""
    if term_change_additions >= 3:
        return 1.0
    if term_change_additions == 2:
        return 0.6
    if term_change_additions == 1:
        return 0.3
    return 0.0


def derive_b6(amounts_in_order: list[float]) -> float | None:
    """B6 «значительное увеличение цены» по версиям суммы договора.

    `amounts_in_order` — суммы доп. соглашений в хронологическом порядке.
    Без доп. соглашений метрика недоступна: сравнивать не с чем.
    """
    values = [a for a in amounts_in_order if a is not None]
    if not values or not values[0]:
        return None
    growth = values[-1] / values[0]
    if growth >= 1.5:
        return 1.0
    if growth >= 1.2:
        return 0.6
    if growth >= 1.05:
        return 0.3
    return 0.0


def derive_b7(no_physical_activity: bool, n_contracts: float | None) -> float:
    """B7 «отсутствие у поставщика ресурсов»."""
    if no_physical_activity:
        return 1.0
    if n_contracts is not None and n_contracts <= 1:
        return 0.5
    return 0.0


def derive_b9(
    nominal_director: bool, mass_address: bool, high_oked_diversity: bool
) -> float:
    """B9 «признаки фиктивности», не дотягивающие до категории A."""
    if nominal_director or mass_address:
        return 1.0
    if high_oked_diversity:
        return 0.5
    return 0.0


__all__ = [
    "AMOUNT_QUARTILE",
    "DEGENERATE_INDICATORS",
    "INDICATORS",
    "K_BASE",
    "K_STEP",
    "MIN_COMPLETENESS",
    "PROCUREMENT_8_4",
    "THRESHOLDS",
    "ContractRiskInputs",
    "ContractRiskResult",
    "SupplierRiskProfile",
    "derive_b1",
    "derive_b2",
    "derive_b3",
    "derive_b4",
    "derive_b5",
    "derive_b6",
    "derive_b7",
    "derive_b9",
    "evaluate_contract",
    "indicator_values",
    "spec_for_contract",
]
