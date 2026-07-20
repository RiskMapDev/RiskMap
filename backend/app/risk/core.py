"""Ядро расчёта риска.

Четыре книги-источника считают риск по-разному, и усреднять эти различия
нельзя. Но общий каркас у них один, и именно он здесь: измеренные индикаторы,
доступный вес, нормировка, полнота, пороги, жёсткие переопределения.

Главный принцип, который держит вся эта конструкция:

    **отсутствие данных — это «не измерено», а не ноль.**

Пустая ячейка в Excel неотличима от нуля, и книги этим грешат: неизмеренный
индикатор попадает в сумму как 0 и молча снижает балл. Здесь неизмеренный
индикатор не входит ни в числитель, ни в знаменатель. Если измерить не удалось
ничего, балла нет вовсе (`None`), а не ноль, и уровень — серый.

Обратная ошибка так же опасна: серый уровень не означает «риска нет». Он
означает «мы не знаем». Поэтому серый — полноправный уровень в фильтрах и
легенде, а не служебное состояние.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self


class RiskLevel(StrEnum):
    """Уровни риска по ТЗ.

    Порядок значим: `order` используется для сортировки и агрегатов.
    `UNKNOWN` намеренно не имеет числового ранга «между» уровнями — это не
    «средний из-за незнания», а отдельное состояние.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

    @property
    def label_ru(self) -> str:
        return {
            RiskLevel.LOW: "Низкий",
            RiskLevel.MEDIUM: "Средний",
            RiskLevel.HIGH: "Высокий",
            RiskLevel.CRITICAL: "Критический",
            RiskLevel.UNKNOWN: "Нет данных",
        }[self]

    @property
    def order(self) -> int:
        """Ранг для сортировки «по возрастанию тревожности».

        У `UNKNOWN` ранг −1: в списке, отсортированном по риску, объекты без
        данных не должны притворяться низкорисковыми и уезжать в конец вместе
        с благополучными.
        """
        return {
            RiskLevel.UNKNOWN: -1,
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }[self]

    @property
    def is_measured(self) -> bool:
        return self is not RiskLevel.UNKNOWN


class IndicatorDirection(StrEnum):
    """Куда растёт риск при росте значения индикатора."""

    HIGHER_IS_RISKIER = "higher_is_riskier"
    LOWER_IS_RISKIER = "lower_is_riskier"


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """Описание одного индикатора модели."""

    code: str
    name: str
    weight: float
    direction: IndicatorDirection = IndicatorDirection.HIGHER_IS_RISKIER
    description: str = ""
    source: str = ""
    """Откуда берётся значение: лист и колонка книги либо внешний реестр."""

    available: bool = True
    """False — индикатор описан в методике, но источник не подключён.

    Такой индикатор не участвует в расчёте и виден пользователю в разделе
    «не измерено». В слое 8.7 таких большинство, и прятать их нельзя: именно
    они объясняют, почему полнота низкая.
    """


@dataclass(frozen=True, slots=True)
class IndicatorValue:
    """Значение индикатора для конкретного объекта.

    `value` в диапазоне [0, 1]. `None` означает «не измерено» — принципиально
    иное состояние, чем 0.0.
    """

    code: str
    value: float | None
    raw_value: object = None
    """Исходное значение до нормировки — для расшифровки пользователю."""

    note: str = ""
    """Почему не измерено, если не измерено."""

    @property
    def is_measured(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class FactorBreakdown:
    """Вклад одного индикатора в итоговый балл — то, что видит пользователь."""

    code: str
    name: str
    weight: float
    value: float | None
    contribution: float | None
    """weight × value. `None`, если не измерено."""

    measured: bool
    direction: IndicatorDirection
    raw_value: object = None
    note: str = ""
    source: str = ""

    @property
    def effect(self) -> str:
        """Как фактор повлиял: повысил риск, не повлиял или не измерен."""
        if not self.measured:
            return "не измерено"
        if self.contribution is None or self.contribution == 0:
            return "не повлиял"
        return "повысил риск"


@dataclass(frozen=True, slots=True)
class RiskResult:
    """Результат расчёта по одному объекту."""

    model_code: str
    model_version: str

    raw_score: float | None
    """Σ(вес × значение) по измеренным индикаторам. `None`, если не измерено ничего."""

    available_weight: float
    """Σ весов измеренных индикаторов."""

    total_weight: float
    """Σ весов всех индикаторов модели, включая неподключённые."""

    normalized_score: float | None
    """Балл, приведённый к доступному весу и к шкале модели."""

    score: float | None
    """Итоговый балл после коэффициентов. Именно он сравнивается с порогами."""

    completeness: float
    """Доля измеренного веса, [0, 1]."""

    level: RiskLevel
    factors: tuple[FactorBreakdown, ...]

    is_preliminary: bool = False
    """True — балл посчитан, но полнота ниже порога, уровень серый.

    Балл при этом показывается пользователю с явной пометкой: он информативен,
    но не является основанием для вывода. Фильтры и агрегаты по уровню риска
    относят такой объект к «нет данных», а не к уровню, который подсказывает
    предварительный балл.
    """

    override_applied: str = ""
    """Название сработавшего жёсткого правила, если оно было."""

    notes: tuple[str, ...] = ()

    @property
    def measured_factors(self) -> tuple[FactorBreakdown, ...]:
        return tuple(f for f in self.factors if f.measured)

    @property
    def unmeasured_factors(self) -> tuple[FactorBreakdown, ...]:
        return tuple(f for f in self.factors if not f.measured)

    def top_factors(self, limit: int = 3) -> tuple[FactorBreakdown, ...]:
        """Главные факторы, повысившие риск, — для карточки в списке."""
        raising = [f for f in self.measured_factors if f.contribution]
        raising.sort(key=lambda f: f.contribution or 0.0, reverse=True)
        return tuple(raising[:limit])


Threshold = tuple[float, RiskLevel]


@dataclass(frozen=True, slots=True)
class RiskModelSpec:
    """Конфигурация модели риска одного слоя.

    Модель версионируется: старые оценки обязаны оставаться воспроизводимыми
    после изменения весов, поэтому в `RiskResult` записывается версия, а не
    ссылка на текущую конфигурацию.
    """

    code: str
    version: str
    title: str
    indicators: tuple[IndicatorSpec, ...]

    thresholds: tuple[Threshold, ...]
    """Пары «нижняя граница балла → уровень», по возрастанию границы.

    Пороги у слоёв разные (35/55/75 в 8.5 против 25/50/75 в 8.6 и 8.7), и
    приводить их к общему виду нельзя: это разные методики, а не разнобой.
    """

    scale: float = 100.0
    """К какой шкале приводится нормированный балл."""

    min_completeness: float | None = None
    """Порог полноты, ниже которого уровень становится серым.

    `None` — серого уровня в методике нет (случай слоя 8.5).
    """

    score_multiplier: Callable[[RiskResult], float] | None = None
    """Коэффициент значимости K, применяемый после нормировки (слои 8.4, 8.6)."""

    override: Callable[[RiskResult], tuple[RiskLevel, str] | None] = None  # type: ignore[assignment]
    """Жёсткое переопределение уровня, например категория A."""

    score_floor: Callable[[Mapping[str, IndicatorValue]], float | None] | None = None
    """Нижняя граница балла при срабатывании условия (слой 8.3 — пол в 75)."""

    notes: str = ""

    def __post_init__(self) -> None:
        if not self.indicators:
            raise ValueError(f"Модель {self.code}: нет ни одного индикатора")

        codes = [i.code for i in self.indicators]
        if len(codes) != len(set(codes)):
            duplicates = sorted({c for c in codes if codes.count(c) > 1})
            raise ValueError(f"Модель {self.code}: повторяющиеся коды индикаторов {duplicates}")

        bounds = [t[0] for t in self.thresholds]
        if bounds != sorted(bounds):
            raise ValueError(
                f"Модель {self.code}: пороги должны идти по возрастанию, дано {bounds}"
            )

    @property
    def total_weight(self) -> float:
        """Сумма весов всех индикаторов, включая неподключённые.

        Именно по этой величине считается полнота: знаменателем должен быть
        полный вес методики, иначе модель с одним работающим индикатором
        отрапортует стопроцентную полноту.
        """
        return sum(i.weight for i in self.indicators)

    @property
    def available_total_weight(self) -> float:
        """Сумма весов индикаторов, у которых подключён источник."""
        return sum(i.weight for i in self.indicators if i.available)

    def indicator(self, code: str) -> IndicatorSpec:
        for spec in self.indicators:
            if spec.code == code:
                return spec
        raise KeyError(f"Модель {self.code}: индикатор {code!r} не описан")

    def level_for(self, score: float) -> RiskLevel:
        """Уровень по баллу без учёта полноты и переопределений."""
        level = self.thresholds[0][1]
        for bound, candidate in self.thresholds:
            if score >= bound:
                level = candidate
        return level

    def with_version(self, version: str) -> Self:
        from dataclasses import replace

        return replace(self, version=version)


def evaluate(
    spec: RiskModelSpec,
    values: Mapping[str, IndicatorValue],
    *,
    strict_codes: bool = True,
) -> RiskResult:
    """Посчитать риск одного объекта по модели.

    Порядок ровно такой:

    1. развести измеренные и неизмеренные индикаторы;
    2. посчитать сырой балл и доступный вес только по измеренным;
    3. нормировать на доступный вес;
    4. применить коэффициент значимости, если он есть;
    5. применить пол балла, если методика его задаёт;
    6. определить уровень по порогам;
    7. заменить уровень на серый, если полноты не хватает;
    8. применить жёсткое переопределение — оно сильнее всего остального.

    Переопределение последнее не случайно: признак вроде лжепредприятия делает
    объект критическим независимо от того, сколько индикаторов удалось
    измерить. Полнота не должна «спасать» такой объект от уровня.
    """
    if strict_codes:
        unknown = set(values) - {i.code for i in spec.indicators}
        if unknown:
            raise KeyError(
                f"Модель {spec.code}: значения для неизвестных индикаторов {sorted(unknown)}"
            )

    factors: list[FactorBreakdown] = []
    raw_score = 0.0
    available_weight = 0.0
    measured_any = False

    for indicator in spec.indicators:
        supplied = values.get(indicator.code)

        if not indicator.available:
            note = supplied.note if supplied and supplied.note else "источник не подключён"
            factors.append(
                FactorBreakdown(
                    code=indicator.code,
                    name=indicator.name,
                    weight=indicator.weight,
                    value=None,
                    contribution=None,
                    measured=False,
                    direction=indicator.direction,
                    note=note,
                    source=indicator.source,
                )
            )
            continue

        if supplied is None or not supplied.is_measured:
            factors.append(
                FactorBreakdown(
                    code=indicator.code,
                    name=indicator.name,
                    weight=indicator.weight,
                    value=None,
                    contribution=None,
                    measured=False,
                    direction=indicator.direction,
                    raw_value=supplied.raw_value if supplied else None,
                    note=supplied.note if supplied else "значение отсутствует в источнике",
                    source=indicator.source,
                )
            )
            continue

        value = supplied.value
        assert value is not None  # гарантировано is_measured
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Модель {spec.code}, индикатор {indicator.code}: "
                f"значение {value} вне диапазона [0, 1]"
            )

        contribution = indicator.weight * value
        raw_score += contribution
        available_weight += indicator.weight
        measured_any = True

        factors.append(
            FactorBreakdown(
                code=indicator.code,
                name=indicator.name,
                weight=indicator.weight,
                value=value,
                contribution=contribution,
                measured=True,
                direction=indicator.direction,
                raw_value=supplied.raw_value,
                note=supplied.note,
                source=indicator.source,
            )
        )

    total_weight = spec.total_weight
    completeness = available_weight / total_weight if total_weight else 0.0

    if not measured_any:
        return RiskResult(
            model_code=spec.code,
            model_version=spec.version,
            raw_score=None,
            available_weight=0.0,
            total_weight=total_weight,
            normalized_score=None,
            score=None,
            completeness=0.0,
            level=RiskLevel.UNKNOWN,
            factors=tuple(factors),
            notes=("не измерен ни один индикатор",),
        )

    normalized = spec.scale * raw_score / available_weight
    score = normalized

    result_for_hooks = RiskResult(
        model_code=spec.code,
        model_version=spec.version,
        raw_score=raw_score,
        available_weight=available_weight,
        total_weight=total_weight,
        normalized_score=normalized,
        score=score,
        completeness=completeness,
        level=RiskLevel.UNKNOWN,
        factors=tuple(factors),
    )

    notes: list[str] = []

    if spec.score_multiplier is not None:
        multiplier = spec.score_multiplier(result_for_hooks)
        score = min(spec.scale, score * multiplier)
        if multiplier != 1.0:
            notes.append(f"коэффициент значимости K = {multiplier:.2f}")

    if spec.score_floor is not None:
        floor = spec.score_floor(values)
        if floor is not None and floor > score:
            notes.append(f"балл поднят до {floor:g} по правилу методики")
            score = floor

    level = spec.level_for(score)
    is_preliminary = False

    # Примечание о нехватке полноты хранится отдельно от остальных, потому что
    # жёсткое переопределение ниже может его отменить. Если сложить его в общий
    # список, в карточке окажутся одновременно «критический» и «уровень серый» —
    # пользователь увидит два взаимоисключающих утверждения о своём объекте.
    completeness_note = ""

    if spec.min_completeness is not None and completeness < spec.min_completeness:
        level = RiskLevel.UNKNOWN
        is_preliminary = True
        completeness_note = (
            f"полнота {completeness:.0%} ниже порога {spec.min_completeness:.0%} — "
            f"уровень серый, балл предварительный"
        )

    result = RiskResult(
        model_code=spec.code,
        model_version=spec.version,
        raw_score=raw_score,
        available_weight=available_weight,
        total_weight=total_weight,
        normalized_score=normalized,
        score=score,
        completeness=completeness,
        level=level,
        factors=tuple(factors),
        is_preliminary=is_preliminary,
        notes=(*notes, completeness_note) if completeness_note else tuple(notes),
    )

    if spec.override is not None:
        decision = spec.override(result)
        if decision is not None:
            forced_level, reason = decision
            from dataclasses import replace

            # Примечание о серой полноте отбрасывается: уровень больше не серый,
            # и балл больше не предварительный. Сам факт низкой полноты никуда
            # не девается — он виден в `completeness` и в разделе «не измерено».
            result = replace(
                result,
                level=forced_level,
                override_applied=reason,
                is_preliminary=False,
                notes=(*notes, f"жёсткое переопределение уровня: {reason}"),
            )

    return result


def aggregate_levels(results: Sequence[RiskResult]) -> dict[RiskLevel, int]:
    """Распределение по уровням — для дашборда и легенды.

    Считаются все уровни, включая `UNKNOWN`: спрятать серые объекты значило бы
    показать более благополучную картину, чем есть.
    """
    counts = dict.fromkeys(RiskLevel, 0)
    for result in results:
        counts[result.level] += 1
    return counts


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Реестр версий моделей.

    Оценка ссылается на версию, а не на «текущую» конфигурацию, — иначе
    правка веса администратором задним числом переписала бы историю.
    """

    _models: dict[tuple[str, str], RiskModelSpec] = field(default_factory=dict)

    def register(self, spec: RiskModelSpec) -> RiskModelSpec:
        key = (spec.code, spec.version)
        if key in self._models:
            raise ValueError(f"Модель {spec.code} версии {spec.version} уже зарегистрирована")
        self._models[key] = spec
        return spec

    def get(self, code: str, version: str) -> RiskModelSpec:
        try:
            return self._models[(code, version)]
        except KeyError:
            known = sorted(f"{c}@{v}" for c, v in self._models)
            raise KeyError(f"Модель {code}@{version} не найдена. Есть: {known}") from None

    def latest(self, code: str) -> RiskModelSpec:
        versions = [(v, spec) for (c, v), spec in self._models.items() if c == code]
        if not versions:
            raise KeyError(f"Модель {code} не зарегистрирована")
        return max(versions, key=lambda pair: pair[0])[1]

    def all_models(self) -> tuple[RiskModelSpec, ...]:
        return tuple(self._models.values())
