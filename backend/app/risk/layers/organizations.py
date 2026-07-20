"""Модель риска слоя 8.7 — хозяйствующие субъекты (организации).

Единица анализа — юридическое лицо, ключ — БИН.

    S_raw   = Σ (w_i × v_i)        по измеренным индикаторам
    W_avail = Σ (w_i)              по измеренным индикаторам
    балл    = 100 × S_raw / W_avail
    полнота = W_avail / W_total,   W_total = 110
    уровень: категория A → критический, иначе полнота < 50 % → серый,
             иначе 75 / 50 / 25 → критический / высокий / средний / низкий

**Главное про эту модель — она обеспечена данными на 41 %.** Из тринадцати
индикаторов ТЗ 9.4 считаются пять: юридический факт A1 (без веса) и четыре
весовых — B3, B5, B6, B8, дающих 45 баллов веса из 110. Остальные девять не
подключены, потому что у их источников нет публичного API: КГД «Сведения по
контрагентам», списки неблагонадёжных КГД, реестр РНУ квазигоссектора,
elicense.kz.

Неподключённые индикаторы описаны здесь наравне с работающими и помечены
`available=False`. Прятать их нельзя по двум причинам. Во-первых, полнота
считается от полного веса методики — уберите их из списка, и модель с четырьмя
работающими индикаторами отрапортует стопроцентную полноту. Во-вторых,
пользователь обязан видеть, **что именно** не измерено и почему: раздел «не
измерено» в карточке риска — это единственное честное объяснение серого уровня.

Следствие, которое нельзя сгладить: максимальная полнота во всей выборке —
40.9 %, ниже порога серого. Поэтому в строгом режиме серыми становятся все
3645 организаций, кроме 23 категории A. Предварительное распределение (1147
низких, 2211 средних, 278 высоких, 32 критических) показывается рядом с серым
уровнем, но официальным уровнем не становится.

Все веса — черновые, назначены экспертно; лист книги так и называется. До
калибровки на размеченной выборке подтверждённых нарушений они остаются
параметром администратора (ТЗ п.14, п.98), а не константой кода. Отдельно
отмечено: B5 срабатывает у 70.6 % выборки и почти не разделяет объекты —
это первый кандидат на пересмотр веса.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from app.risk.core import (
    IndicatorSpec,
    IndicatorValue,
    RiskLevel,
    RiskModelSpec,
    RiskResult,
    evaluate,
)
from app.risk.layers.infrastructure import GradedScale, graded

THRESHOLDS_8_7: tuple[tuple[float, RiskLevel], ...] = (
    (0.0, RiskLevel.LOW),
    (25.0, RiskLevel.MEDIUM),
    (50.0, RiskLevel.HIGH),
    (75.0, RiskLevel.CRITICAL),
)

MIN_COMPLETENESS_8_7 = 0.5

CATEGORY_A_CODES: tuple[str, ...] = ("A1", "A2", "A3", "A4")
"""Юридически подтверждённые факты. В баллах не участвуют — переопределяют уровень."""

B3_SCALE: GradedScale = ((10.0, 1.0), (5.0, 0.7), (3.0, 0.3))
"""Число организаций по одному адресу регистрации."""

B6_SCALE: GradedScale = ((4.0, 1.0), (3.0, 0.4))
"""Число секций ОКЭД: множественный ОКЭД законен для холдингов, отсюда мягкая шкала."""

B8_SCALE: GradedScale = ((5.0, 1.0), (3.0, 0.6), (2.0, 0.2))
"""Число организаций у одного ИИН руководителя. Две–три компании — норма для МСБ."""

B5_NO_ACTIVITY_VALUE = 1.0
"""Признаков физической деятельности нет вовсе."""

B5_INACTIVE_KKM_VALUE = 0.5
"""Есть только неактивный контрольно-кассовый аппарат."""

NOT_CONNECTED = "источник не подключён: нет публичного API"

ORGANIZATION_INDICATORS: tuple[IndicatorSpec, ...] = (
    # --- Категория A: юридические факты, вес 0 -------------------------------
    # Веса нулевые не по недосмотру: эти признаки не складываются с баллами, а
    # переопределяют уровень целиком. Держать их в общем списке всё равно нужно,
    # чтобы карточка риска показывала все тринадцать признаков ТЗ 9.4, а не
    # только весовые, и чтобы неподключённые A2–A4 были видны как «не измерено».
    IndicatorSpec(
        code="A1",
        name="В реестре недобросовестных участников госзакупок",
        weight=0.0,
        description="Юридический факт. Категория A — уровень критический независимо от балла.",
        source="goszakup.gov.kz /v3/rnu",
    ),
    IndicatorSpec(
        code="A2",
        name="В реестре недобросовестных участников квазигоссектора",
        weight=0.0,
        available=False,
        description="Юридический факт категории A.",
        source="goszakup.gov.kz /v3/rnu_quasi",
    ),
    IndicatorSpec(
        code="A3",
        name="Лжепредприятие по решению суда",
        weight=0.0,
        available=False,
        description="Юридический факт категории A.",
        source="portal.kgd.gov.kz, список лжепредприятий",
    ),
    IndicatorSpec(
        code="A4",
        name="Директор в списке лжепредпринимателей",
        weight=0.0,
        available=False,
        description="Юридический факт категории A.",
        source="portal.kgd.gov.kz по ИИН руководителя",
    ),
    # --- Категория B: весовые индикаторы, суммарно 110 -----------------------
    IndicatorSpec(
        code="B1",
        name="Минимальная налоговая нагрузка при значительных оборотах",
        weight=15.0,
        available=False,
        description="Нагрузка ниже 3 % при обороте свыше 100 млн ₸ (ТЗ 9.4.1).",
        source="КГД «Сведения по контрагентам»",
    ),
    IndicatorSpec(
        code="B2",
        name="Частая смена руководителей и учредителей",
        weight=10.0,
        available=False,
        description="Три и более смен за 24 месяца (ТЗ 9.4.2).",
        source="Реестр юридических лиц, stat.gov.kz",
    ),
    IndicatorSpec(
        code="B3",
        name="Массовая регистрация по одному адресу",
        weight=10.0,
        description="Число организаций по addr_norm: ≥10 — 1.0, 5–9 — 0.7, 3–4 — 0.3 (ТЗ 9.4.3).",
        source="вычисляется по addr_norm",
    ),
    IndicatorSpec(
        code="B4",
        name="Связь с ликвидированными и проблемными организациями",
        weight=15.0,
        available=False,
        description="Связь через директора или адрес (ТЗ 9.4.4).",
        source="КГД + реестр ЮЛ + граф связей",
    ),
    IndicatorSpec(
        code="B5",
        name="Отсутствие работников и активов",
        weight=15.0,
        description="Нет физической активности — 1.0, только неактивный ККМ — 0.5 (ТЗ 9.4.5).",
        source="portal.kgd.gov.kz",
    ),
    IndicatorSpec(
        code="B6",
        name="Несоответствие операций профилю деятельности",
        weight=10.0,
        description="Число секций ОКЭД: ≥4 — 1.0, 3 — 0.4, ≤2 — 0 (ТЗ 9.4.6).",
        source="ОКЭД из goszakup /subject.okedList",
    ),
    IndicatorSpec(
        code="B7",
        name="Транзитные финансовые операции",
        weight=15.0,
        available=False,
        description="Транзит свыше 80 % оборота при оседании менее 3 дней (ТЗ 9.4.7).",
        source="КГД и банковские данные",
    ),
    IndicatorSpec(
        code="B8",
        name="Признаки номинального руководства",
        weight=10.0,
        description="Число организаций у ИИН: ≥5 — 1.0, 3–4 — 0.6, 2 — 0.2 (ТЗ 9.4.8).",
        source="Реестр юридических лиц по ИИН руководителя",
    ),
    IndicatorSpec(
        code="B9",
        name="Отсутствие или недействительность лицензии",
        weight=10.0,
        available=False,
        description="Лицензия отсутствует или отозвана при лицензируемом виде деятельности.",
        source="elicense.kz",
    ),
)


def category_a_override(result: RiskResult) -> tuple[RiskLevel, str] | None:
    """Жёсткое переопределение уровня по категории A.

    Правило читает подтверждённые факты прямо из расшифровки: у признаков
    категории A вес нулевой, они не измеряются в смысле баллов, но их сырое
    значение доходит до `FactorBreakdown.raw_value`. Так переопределение
    остаётся частью модели, а не превращается в скрытое состояние снаружи.

    Переопределение сильнее нехватки данных: организация с юридически
    подтверждённым фактом критическая независимо от того, сколько индикаторов
    удалось измерить, и независимо от балла — трое из 23 имеют балл 0.
    """
    confirmed = [f for f in result.factors if f.code in CATEGORY_A_CODES and f.raw_value is True]
    if not confirmed:
        return None
    reasons = "; ".join(f"{f.code} {f.name.lower()}" for f in confirmed)
    return RiskLevel.CRITICAL, f"категория A: {reasons}"


ORGANIZATION_MODEL = RiskModelSpec(
    code="8.7-organizations",
    version="1.0",
    title="Слой 8.7 — хозяйствующие субъекты",
    indicators=ORGANIZATION_INDICATORS,
    thresholds=THRESHOLDS_8_7,
    min_completeness=MIN_COMPLETENESS_8_7,
    override=category_a_override,
    notes=(
        "3668 организаций. Территориальной привязки нет ни в каком виде — слой "
        "в текущем состоянии на карту не выводится. Обеспеченность источниками "
        "41 %: работают A1, B3, B5, B6, B8. Веса черновые (ТЗ п.14, п.98)."
    ),
)


def category_a_fact(code: str, *, confirmed: bool | None) -> IndicatorValue:
    """Собрать юридический факт категории A для передачи в расчёт.

    Значение всегда `None` — факт не участвует в баллах. Сам факт едет в
    `raw_value`, а `note` объясняет пользователю, что именно известно. Ноль
    здесь был бы неправильным вдвойне: он и добавил бы нулевой вес в
    знаменатель, и выдал бы «не состоит» за «не проверяли».
    """
    if confirmed is None:
        note = NOT_CONNECTED
    elif confirmed:
        note = "факт подтверждён — уровень переопределяется на критический"
    else:
        note = "по подключённому источнику факт не подтверждён"
    return IndicatorValue(code=code, value=None, raw_value=confirmed, note=note)


def unmeasured(code: str, note: str = NOT_CONNECTED) -> IndicatorValue:
    """Индикатор, который методика описывает, но источник не даёт."""
    return IndicatorValue(code=code, value=None, note=note)


def b3_value(address_company_count: int | None) -> IndicatorValue:
    """Массовая регистрация по адресу."""
    count = None if address_company_count is None else float(address_company_count)
    value = graded(count, B3_SCALE)
    return IndicatorValue(code="B3", value=value, raw_value=address_company_count)


def b5_value(
    *, no_physical_activity: bool | None, inactive_kkm_only: bool | None
) -> IndicatorValue:
    """Отсутствие работников и активов.

    Индикатор считается измеренным, когда известен хотя бы один из двух
    признаков: «нет физической активности» и «только неактивный ККМ» —
    отрицательный ответ здесь такой же результат наблюдения, как и
    положительный.
    """
    if no_physical_activity is None and inactive_kkm_only is None:
        return unmeasured("B5", "нет сведений о физической активности")
    if no_physical_activity:
        value = B5_NO_ACTIVITY_VALUE
    elif inactive_kkm_only:
        value = B5_INACTIVE_KKM_VALUE
    else:
        value = 0.0
    return IndicatorValue(
        code="B5",
        value=value,
        raw_value={
            "no_physical_activity": no_physical_activity,
            "inactive_kkm_only": inactive_kkm_only,
        },
    )


def b6_value(oked_sections_count: int | None) -> IndicatorValue:
    """Несоответствие операций профилю деятельности.

    Пустой ОКЭД — именно «не измерено», а не «одна секция»: 763 организации из
    3668 не имеют сведений об ОКЭД, и это ровно те строки, у которых полнота
    падает с 40.9 до 31.8 %.
    """
    if oked_sections_count is None:
        return unmeasured("B6", "сведения об ОКЭД отсутствуют")
    return IndicatorValue(
        code="B6", value=graded(float(oked_sections_count), B6_SCALE), raw_value=oked_sections_count
    )


def b8_value(director_company_count: int | None) -> IndicatorValue:
    """Признаки номинального руководства."""
    if director_company_count is None:
        return unmeasured("B8", "ИИН руководителя неизвестен")
    return IndicatorValue(
        code="B8",
        value=graded(float(director_company_count), B8_SCALE),
        raw_value=director_company_count,
    )


def evaluate_organization(values: Mapping[str, IndicatorValue]) -> RiskResult:
    """Посчитать риск одной организации.

    Есть один пограничный случай, который ядро не покрывает: если не измерен
    ни один весовой индикатор, расчёт завершается досрочно и жёсткие правила не
    применяются. Для слоя 8.7 это недопустимо — юридически подтверждённый факт
    делает организацию критической даже тогда, когда измерить не удалось
    ничего. Поэтому переопределение здесь применяется явно. В наличных данных
    случай не встречается (B3 и B5 заполнены у всех 3668 строк), но правило
    методики не должно зависеть от того, повезло ли с данными.
    """
    result = evaluate(ORGANIZATION_MODEL, values)
    if result.override_applied:
        return result

    decision = category_a_override(result)
    if decision is None:
        return result

    forced_level, reason = decision
    return replace(
        result,
        level=forced_level,
        override_applied=reason,
        is_preliminary=False,
        notes=(*result.notes, f"жёсткое переопределение уровня: {reason}"),
    )


def preliminary_level(result: RiskResult) -> RiskLevel:
    """Уровень по одному лишь баллу — «предварительный» уровень книги.

    Показывается рядом с серым уровнем, но официальным не является: в фильтрах
    и агрегатах по уровню риска такая организация относится к «нет данных».
    Категория A и здесь сильнее балла.
    """
    if result.override_applied:
        return result.level
    if result.score is None:
        return RiskLevel.UNKNOWN
    return ORGANIZATION_MODEL.level_for(result.score)


__all__ = [
    "B3_SCALE",
    "B5_INACTIVE_KKM_VALUE",
    "B5_NO_ACTIVITY_VALUE",
    "B6_SCALE",
    "B8_SCALE",
    "CATEGORY_A_CODES",
    "MIN_COMPLETENESS_8_7",
    "NOT_CONNECTED",
    "ORGANIZATION_INDICATORS",
    "ORGANIZATION_MODEL",
    "THRESHOLDS_8_7",
    "b3_value",
    "b5_value",
    "b6_value",
    "b8_value",
    "category_a_fact",
    "category_a_override",
    "evaluate_organization",
    "preliminary_level",
    "unmeasured",
]
