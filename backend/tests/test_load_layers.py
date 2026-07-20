"""Проверки загрузчика слоёв 8.3–8.7.

Разделение здесь такое же, как в остальном проекте: механика, которую можно
проверить без базы, проверяется без базы, а всё, что держится на ограничениях
PostgreSQL — идемпотентность через `ON CONFLICT`, откат сухого прогона,
обязательность провенанса, — помечено `integration` и требует живой базы.
Подменять PostgreSQL на SQLite здесь бессмысленно вдвойне: и типы другие
(JSONB, UUID), и вся идемпотентность построена на диалектном `ON CONFLICT`.

Тесты, читающие книги целиком, помечены ещё и `slow`: книга 8.5 разбирается
семнадцать секунд, и держать это в быстром прогоне незачем.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.infrastructure import ProjectEntity
from app.db.models.organization import Organization
from app.db.models.procurement import Contract
from app.db.models.source import DataQualityIssue, ImportJob, ImportStatus, IssueSeverity
from app.db.models.subsidy import SubsidyPayment
from app.importers.persistence import (
    ControlCheck,
    IssueRecord,
    TerritoryIndex,
    _dedupe,
    check_controls,
    explanation_ru,
    factors_payload,
    jsonable,
    load_territory_index,
    risk_payload,
    stable_id,
    table_of,
)
from app.risk.core import (
    IndicatorSpec,
    IndicatorValue,
    RiskLevel,
    RiskModelSpec,
    evaluate,
)
from app.services.territory_resolver import TerritoryResolver
from scripts.load_layers import (
    CONTROLS_8_4,
    LOADERS,
    Truncator,
    _budget_explanation,
    _end_of_month,
    _location_candidates,
    dec,
    level_counts,
    load_budget,
    load_infrastructure,
    load_organizations,
    load_procurement,
    load_subsidies,
    max_score,
    parse_dmy,
    summarize_issues,
)

# Таблицы слоя 8.4 в порядке, обратном зависимостям, — для очистки внутри
# транзакции теста. Слой выбран как самый дешёвый по чтению: книга 877 КБ
# против 10,8 МБ у 8.3 и 4,3 МБ у 8.5, а таблиц в нём шесть.
PROCUREMENT_TABLES = (
    "contract_additions",
    "contracts",
    "procurement_lots",
    "procurements",
    "procurement_customers",
    "suppliers",
)


@pytest.fixture
def source_dir() -> Path:
    """Каталог immutable-исходников. Без него интеграционные тесты бессмысленны."""
    directory = get_settings().source_data_dir
    if not directory.is_dir():
        pytest.skip(f"Каталог исходников недоступен: {directory}")
    return directory


def _counts(session: Session, tables: tuple[str, ...]) -> dict[str, int]:
    return {
        name: int(session.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
        for name in tables
    }


def _clear(session: Session, tables: tuple[str, ...]) -> None:
    """Очистить таблицы слоя внутри транзакции теста.

    Нужно затем, чтобы «создано» и «обновлено» различались: в рабочей базе
    слой уже загружен, и без очистки первый прогон теста ничего бы не создал,
    а проверка идемпотентности выродилась бы в сравнение нулей.
    """
    for name in tables:
        session.execute(text(f"DELETE FROM {name}"))
    session.flush()


def _model() -> RiskModelSpec:
    """Крошечная модель на два индикатора — для проверок расшифровки."""
    return RiskModelSpec(
        code="test",
        version="1.0",
        title="Тестовая модель",
        indicators=(
            IndicatorSpec("X1", "Первый", 60.0, description="", source="Лист!A"),
            IndicatorSpec("X2", "Второй", 40.0, description="", source="Лист!B"),
        ),
        thresholds=((0.0, RiskLevel.LOW), (50.0, RiskLevel.HIGH)),
    )


# --- Ключи и сериализация ----------------------------------------------------


def test_stable_id_is_deterministic() -> None:
    """Один и тот же естественный ключ обязан давать один и тот же UUID.

    На этом держится вся идемпотентность: разойдись ключ между запусками —
    и повторная загрузка создаст вторую строку вместо обновления первой.
    """
    assert stable_id("contracts", "22333284") == stable_id("contracts", "22333284")
    assert isinstance(stable_id("contracts", "22333284"), uuid.UUID)


def test_stable_id_differs_by_scope() -> None:
    """БИН в организациях и БИН в поставщиках — разные строки разных таблиц."""
    assert stable_id("organizations", "000440010133") != stable_id("suppliers", "000440010133")


def test_stable_id_differs_by_natural_key() -> None:
    assert stable_id("contracts", "1") != stable_id("contracts", "2")


def test_jsonable_converts_dates_and_nested_values() -> None:
    payload = jsonable(
        {"date": dt.date(2026, 7, 17), "nested": [1, {"flag": True}], "set": {"a"}}
    )
    assert payload["date"] == "2026-07-17"
    assert payload["nested"] == [1, {"flag": True}]
    assert payload["set"] == ["a"]


def test_jsonable_turns_nan_into_text() -> None:
    """JSONB не принимает NaN: значение обязано сохраниться, а вставка — пройти."""
    assert jsonable(float("nan")) == "nan"
    assert jsonable(float("inf")) == "inf"
    assert jsonable(1.5) == 1.5


def test_table_of_returns_real_table() -> None:
    assert table_of(Contract).name == "contracts"


def test_table_of_rejects_non_table() -> None:
    class NotAModel:
        __table__ = "contracts"

    with pytest.raises(TypeError):
        table_of(NotAModel)


def test_dedupe_keeps_last_occurrence_and_counts() -> None:
    """Повтор ключа внутри загрузки сворачивается, а не роняет запрос.

    PostgreSQL отказывается выполнять `ON CONFLICT DO UPDATE`, если ключ
    встречается в запросе дважды, поэтому свёртка обязательна. Побеждает
    последняя строка — как при последовательной записи.
    """
    rows, duplicates = _dedupe(
        [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 1, "v": "c"}], ("id",)
    )
    assert duplicates == 1
    assert rows == [{"id": 1, "v": "c"}, {"id": 2, "v": "b"}]


# --- Сверка контрольных значений ---------------------------------------------


def test_check_controls_reports_delta() -> None:
    controls = check_controls({"rows": 240}, {"rows": 239})
    assert not controls[0].matches
    assert controls[0].delta == -1


def test_check_controls_respects_tolerance() -> None:
    """Максимальный балл в аудите округлён до десятой — допуск это учитывает."""
    controls = check_controls(
        {"max_score": 67.1}, {"max_score": 67.0833}, tolerances={"max_score": 0.05}
    )
    assert controls[0].matches


def test_check_controls_missing_metric_never_matches() -> None:
    """Опечатка в имени показателя не должна выглядеть как успешная сверка."""
    controls = check_controls({"rows": 240}, {})
    assert not controls[0].matches
    assert math.isnan(controls[0].actual)


def test_control_as_dict_carries_numbers() -> None:
    payload = ControlCheck(metric="rows", expected=240, actual=238).as_dict()
    assert payload == {
        "metric": "rows",
        "expected": 240.0,
        "actual": 238.0,
        "delta": -2.0,
        "tolerance": 0.0,
        "matches": False,
    }


# --- Мелкие преобразования ---------------------------------------------------


def test_dec_avoids_binary_float_noise() -> None:
    """`Decimal(0.1)` даёт хвост в семнадцатом знаке; через str — не даёт.

    Суммы слоя 8.4 сверяются с книгой до копейки, и такой хвост эту сверку
    ломает.
    """
    assert dec(0.1) == Decimal("0.1")
    assert dec(7_198_964_138.99) == Decimal("7198964138.99")
    assert dec(None) is None


def test_dec_drops_nan() -> None:
    assert dec(float("nan")) is None


def test_dec_rounds_to_places() -> None:
    assert dec(1.23456, places=2) == Decimal("1.23")


def test_parse_dmy() -> None:
    assert parse_dmy("12.06.2026") == dt.date(2026, 6, 12)
    assert parse_dmy("не дата") is None
    assert parse_dmy("31.02.2026") is None


def test_end_of_month_handles_december() -> None:
    assert _end_of_month(2025, 12) == dt.date(2025, 12, 31)
    assert _end_of_month(2025, 2) == dt.date(2025, 2, 28)


def test_truncator_records_every_truncation() -> None:
    """Обрезка не бывает молчаливой: обрезанное значение уже не найти в книге."""
    truncator = Truncator()
    assert truncator.fit("короткое", 32, "поле") == "короткое"
    assert truncator.fit("x" * 40, 32, "поле") == "x" * 32
    issues = truncator.issues()
    assert len(issues) == 1
    assert issues[0].code == "value_truncated"
    assert issues[0].context == {"rows_affected": 1}


def test_truncator_passes_none_through() -> None:
    assert Truncator().fit(None, 10, "поле") is None


def test_summarize_issues_groups_by_code_and_column() -> None:
    """21 521 одинаковое замечание превращается в одно с числом строк."""
    records = [
        IssueRecord(IssueSeverity.WARNING, "code_a", "Сообщение.", f"Лист!A{i}", "Колонка")
        for i in range(7)
    ] + [IssueRecord(IssueSeverity.INFO, "code_b", "Другое.", "Лист!A1", None)]
    summary = summarize_issues(records)
    by_code = {item.code: item for item in summary}
    assert set(by_code) == {"code_a", "code_b"}
    assert by_code["code_a"].context is not None
    assert by_code["code_a"].context["rows_affected"] == 7
    assert len(by_code["code_a"].context["sample_rows"]) == 5


# --- Расшифровка риска -------------------------------------------------------


def test_factors_payload_keeps_unmeasured_with_reason() -> None:
    """Неизмеренный индикатор обязан доехать до карточки вместе с причиной.

    Без него серый уровень оказывается без объяснения, а именно объяснение и
    отличает «риска нет» от «мы не знаем».
    """
    result = evaluate(
        _model(),
        {
            "X1": IndicatorValue(code="X1", value=1.0),
            "X2": IndicatorValue(code="X2", value=None, note="источник не подключён"),
        },
    )
    payload = factors_payload(result)
    unmeasured = [item for item in payload if not item["measured"]]
    assert [item["code"] for item in unmeasured] == ["X2"]
    assert unmeasured[0]["note"] == "источник не подключён"
    assert unmeasured[0]["contribution"] is None


def test_risk_payload_carries_weights_and_completeness() -> None:
    result = evaluate(
        _model(),
        {
            "X1": IndicatorValue(code="X1", value=1.0),
            "X2": IndicatorValue(code="X2", value=None),
        },
    )
    payload = risk_payload(result)
    assert payload["available_weight"] == 60.0
    assert payload["total_weight"] == 100.0
    assert payload["completeness"] == pytest.approx(0.6)
    assert payload["score"] == pytest.approx(100.0)
    assert payload["level"] == "high"


def test_explanation_ru_lists_raising_factors() -> None:
    result = evaluate(
        _model(),
        {
            "X1": IndicatorValue(code="X1", value=1.0),
            "X2": IndicatorValue(code="X2", value=0.0),
        },
    )
    text_value = explanation_ru(result)
    assert "X1" in text_value
    assert "X2" not in text_value


def test_explanation_ru_says_so_when_nothing_raised() -> None:
    """Пустая строка читалась бы как сбой, а не как «факторов не выявлено»."""
    result = evaluate(
        _model(),
        {
            "X1": IndicatorValue(code="X1", value=0.0),
            "X2": IndicatorValue(code="X2", value=0.0),
        },
    )
    assert explanation_ru(result) == "Ни один индикатор не повысил риск."


def test_budget_explanation_lists_only_strong_indicators() -> None:
    """Колонка слоя 8.3 описана как «индикаторы с баллом не ниже 50»."""
    result = evaluate(
        _model(),
        {
            "X1": IndicatorValue(code="X1", value=0.8),
            "X2": IndicatorValue(code="X2", value=0.2),
        },
    )
    assert "X1" in _budget_explanation(result)
    assert "X2" not in _budget_explanation(result)


def test_level_counts_and_max_score() -> None:
    high = evaluate(_model(), {"X1": IndicatorValue(code="X1", value=1.0)})
    low = evaluate(_model(), {"X1": IndicatorValue(code="X1", value=0.0)})
    counts = level_counts([high, low])
    assert counts["level_high"] == 1
    assert counts["level_low"] == 1
    assert max_score([high, low]) == pytest.approx(100.0)


# --- Сопоставление территорий ------------------------------------------------


def _index(pairs: dict[str, str], levels: dict[str, str] | None = None) -> TerritoryIndex:
    resolver = TerritoryResolver()
    resolver.add_many(pairs.items())
    ids = {code: stable_id("territories", code) for code in set(pairs.values())}
    return TerritoryIndex(resolver=resolver, ids=ids, levels=levels or {})


def test_territory_index_resolves_known_name() -> None:
    index = _index({"Талгарский район": "talgarskiy"})
    territory_id, resolution = index.lookup("Талгарский р-н", row_ref="Лист!A2")
    assert territory_id == index.ids["talgarskiy"]
    assert resolution.ok
    assert index.resolved == 1


def test_territory_index_never_guesses_unknown_name() -> None:
    """Неопознанное название оставляет территорию пустой — это правило слоя."""
    index = _index({"Талгарский район": "talgarskiy"})
    territory_id, _ = index.lookup("Панфиловский район", row_ref="Лист!A5")
    assert territory_id is None
    assert index.not_found == 1


def test_territory_index_groups_unresolved_names() -> None:
    """Замечание одно на написание, а не на строку: иначе их были бы тысячи."""
    index = _index({"Талгарский район": "talgarskiy"})
    for row in range(4):
        index.lookup("Панфиловский район", row_ref=f"Лист!A{row}")
    issues = index.issues()
    assert len(issues) == 1
    assert issues[0].code == "territory_not_resolved"
    assert issues[0].context is not None
    assert issues[0].context["rows_affected"] == 4
    assert issues[0].source_row_ref == "Лист!A0"


def test_territory_index_separates_empty_from_unknown() -> None:
    """Пусто в источнике и «название непонятно» — разные вещи для пользователя."""
    index = _index({"Талгарский район": "talgarskiy"})
    index.lookup(None, row_ref="Лист!A1")
    index.lookup("Небывалый район", row_ref="Лист!A2")
    assert index.empty == 1
    assert index.not_found == 1
    assert index.report()["distinct_unresolved_names"] == 1


def test_territory_index_marks_ambiguous_as_unresolved() -> None:
    index = _index({"Спорный район": "a"})
    index.resolver.add("Спорный район", "b")
    territory_id, _ = index.lookup("Спорный район", row_ref="Лист!A1")
    assert territory_id is None
    assert index.ambiguous == 1


def test_location_candidates_go_from_district_to_country() -> None:
    """Местоположение экспертизы разбирается от частного к общему."""
    assert _location_candidates(
        "Республика Казахстан, Акмолинская область, Аккольский р-н;"
    ) == ["Аккольский р-н", "Акмолинская область", "Республика Казахстан"]


def test_location_candidates_handles_short_form() -> None:
    """Строки Алматинской области записаны одним коротким названием района."""
    assert _location_candidates("Талгарский район") == ["Талгарский район"]


def test_location_candidates_takes_first_of_several() -> None:
    assert _location_candidates("A, Б; В, Г")[0] == "Б"


# --- Реестр загрузчиков ------------------------------------------------------


def test_all_five_layers_are_registered() -> None:
    assert set(LOADERS) == {"8.3", "8.4", "8.5", "8.6", "8.7"}


# --- Интеграционные проверки -------------------------------------------------


@pytest.mark.integration
def test_procurement_load_is_idempotent(db_session: Session, source_dir: Path) -> None:
    """Два прогона подряд дают одинаковое число строк, второй не создаёт ничего.

    Главная проверка всего модуля: именно здесь ломается импорт, устроенный
    через `INSERT` без ключа конфликта.
    """
    _clear(db_session, PROCUREMENT_TABLES)

    first = load_procurement(db_session, source_dir=source_dir)
    counts_first = _counts(db_session, PROCUREMENT_TABLES)

    second = load_procurement(db_session, source_dir=source_dir)
    counts_second = _counts(db_session, PROCUREMENT_TABLES)

    assert counts_first == counts_second
    assert all(counts.created > 0 for counts in first.tables.values())
    assert all(counts.created == 0 for counts in second.tables.values())
    assert all(counts.updated > 0 for counts in second.tables.values())


@pytest.mark.integration
def test_dry_run_writes_nothing(db_session: Session, source_dir: Path) -> None:
    """Сухой прогон выполняет все вставки и откатывает их вместе с заданием."""
    before = _counts(db_session, PROCUREMENT_TABLES)
    jobs_before = db_session.execute(select(func.count()).select_from(ImportJob)).scalar_one()

    report = load_procurement(db_session, source_dir=source_dir, dry_run=True)

    assert report.dry_run
    assert report.rows_written > 0
    assert _counts(db_session, PROCUREMENT_TABLES) == before
    assert (
        db_session.execute(select(func.count()).select_from(ImportJob)).scalar_one()
        == jobs_before
    )


@pytest.mark.integration
def test_procurement_controls_all_match(db_session: Session, source_dir: Path) -> None:
    """Контрольные значения книги 8.4 воспроизводятся собственным расчётом."""
    report = load_procurement(db_session, source_dir=source_dir, dry_run=True)
    assert {control.metric for control in report.controls} == set(CONTROLS_8_4)
    assert report.failed_controls == []


@pytest.mark.integration
def test_every_contract_carries_provenance(db_session: Session, source_dir: Path) -> None:
    """У каждой записи известно, откуда она и когда появилась."""
    _clear(db_session, PROCUREMENT_TABLES)
    load_procurement(db_session, source_dir=source_dir)

    missing = db_session.execute(
        select(func.count())
        .select_from(Contract)
        .where(
            (Contract.source_dataset_id.is_(None))
            | (Contract.import_job_id.is_(None))
            | (Contract.natural_key.is_(None))
            | (Contract.source_row_ref.is_(None))
            | (Contract.data_as_of.is_(None))
        )
    ).scalar_one()
    assert missing == 0

    sample = db_session.execute(select(Contract).limit(1)).scalar_one()
    # Адрес строки — «лист!ячейка», иначе трассировать до книги нечем.
    assert sample.source_row_ref is not None
    assert "!" in sample.source_row_ref


@pytest.mark.integration
def test_risk_is_recomputed_not_copied(db_session: Session, source_dir: Path) -> None:
    """Балл и расшифровка приходят из расчёта, а не из книги.

    Проверяется по существу: у договора сохранены и промежуточные величины
    методики, и расшифровка со всеми индикаторами модели, включая
    неизмеренные, — скопировать это из статического листа книги нельзя.
    """
    _clear(db_session, PROCUREMENT_TABLES)
    load_procurement(db_session, source_dir=source_dir)

    contract = db_session.execute(
        select(Contract).where(Contract.risk_score.is_not(None)).limit(1)
    ).scalar_one()
    assert contract.s_raw is not None
    assert contract.w_avail is not None
    assert contract.s_norm is not None
    assert contract.significance_multiplier is not None
    assert contract.completeness is not None

    factors: Any = contract.factors
    assert factors["model"] == "8.4"
    assert {item["code"] for item in factors["factors"]} == {f"B{i}" for i in range(1, 10)}
    assert any(not item["measured"] for item in factors["factors"])


@pytest.mark.integration
def test_import_job_records_reconciliation(db_session: Session, source_dir: Path) -> None:
    """Сверка сохраняется в задании импорта, а не только печатается в консоль."""
    _clear(db_session, PROCUREMENT_TABLES)
    report = load_procurement(db_session, source_dir=source_dir)

    job = db_session.get(ImportJob, report.job_id)
    assert job is not None
    assert job.status == ImportStatus.SUCCEEDED
    assert job.layer_code == "8.4"
    assert job.reconciliation is not None
    assert job.reconciliation["controls_total"] == len(CONTROLS_8_4)
    assert job.reconciliation["controls_passed"] == len(CONTROLS_8_4)
    assert job.territory_match_report is not None
    assert job.finished_at is not None


@pytest.mark.integration
@pytest.mark.slow
def test_budget_reports_unrepresentable_raw_facts(
    db_session: Session, source_dir: Path
) -> None:
    """Расхождение схемы с источником фиксируется, а не подгоняется.

    Естественная единица бюджетной статьи — путь в иерархии, а ограничение
    `uq_budget_program_code_name_level` этого не вмещает. Загрузчик обязан
    сказать об этом числами и не грузить две трети строк под видом всех.
    """
    report = load_budget(db_session, source_dir=source_dir, dry_run=True)
    assert report.failed_controls == []

    blockers = [item for item in report.issues if item.code == "schema_cannot_represent_source"]
    assert len(blockers) == 1
    context = blockers[0].context
    assert context is not None
    assert context["source_rows"] == 74_831
    assert context["distinct_paths"] > context["programs_allowed_by_schema"]
    assert context["rows_lost_by_schema_key"] > 0


@pytest.mark.integration
@pytest.mark.slow
def test_unresolved_subsidy_territory_stays_null(
    db_session: Session, source_dir: Path
) -> None:
    """Непонятое название района не превращается в «похожую» территорию."""
    report = load_subsidies(db_session, source_dir=source_dir)
    assert report.failed_controls == []

    unresolved = report.territory["unresolved_names"]
    assert unresolved, "ожидались районы вне справочника второго уровня"

    name = unresolved[0]["name"]
    rows = db_session.execute(
        select(func.count())
        .select_from(SubsidyPayment)
        .where(
            SubsidyPayment.territory_name_raw == name,
            SubsidyPayment.territory_id.is_not(None),
        )
    ).scalar_one()
    assert rows == 0

    recorded = db_session.execute(
        select(func.count())
        .select_from(DataQualityIssue)
        .where(
            DataQualityIssue.import_job_id == report.job_id,
            DataQualityIssue.code == "territory_not_resolved",
        )
    ).scalar_one()
    assert recorded == len(unresolved)


@pytest.mark.integration
@pytest.mark.slow
def test_ppp_projects_are_stored_with_region_precision(
    db_session: Session, source_dir: Path
) -> None:
    """У проектов ГЧП точность привязки — только область.

    Районной привязки нет ни в одном из пяти исходных реестров, и
    ограничение базы не даст записать иначе. Проверка нужна затем, чтобы
    правило не обошли массовой вставкой мимо конструктора Python.
    """
    report = load_infrastructure(db_session, source_dir=source_dir)
    assert report.failed_controls == []

    wrong = db_session.execute(
        select(func.count())
        .select_from(ProjectEntity)
        .where(
            ProjectEntity.kind == "ppp_project",
            ProjectEntity.territory_precision != "region",
        )
    ).scalar_one()
    assert wrong == 0


@pytest.mark.integration
@pytest.mark.slow
def test_organizations_have_no_territory_by_design(
    db_session: Session, source_dir: Path
) -> None:
    """Отсутствие территории в слое 8.7 — состояние источника, а не сбой.

    Поэтому оно выражено явным значением `territory_status`, а не выводится
    из пустого внешнего ключа.
    """
    report = load_organizations(db_session, source_dir=source_dir)
    assert report.failed_controls == []

    linked = db_session.execute(
        select(func.count())
        .select_from(Organization)
        .where(Organization.territory_id.is_not(None))
    ).scalar_one()
    assert linked == 0

    undetermined = db_session.execute(
        select(func.count())
        .select_from(Organization)
        .where(Organization.territory_status == "not_determined")
    ).scalar_one()
    assert undetermined == 3668


@pytest.mark.integration
@pytest.mark.slow
def test_organizations_keep_both_risk_levels(
    db_session: Session, source_dir: Path
) -> None:
    """Строгий и предварительный уровни хранятся раздельно.

    Свести их в одно поле — значит потерять либо честность (серый уровень при
    полноте 41 %), либо информативность (посчитанный балл).
    """
    load_organizations(db_session, source_dir=source_dir)

    strict_unknown = db_session.execute(
        select(func.count())
        .select_from(Organization)
        .where(Organization.risk_level_strict == "unknown")
    ).scalar_one()
    critical = db_session.execute(
        select(func.count())
        .select_from(Organization)
        .where(Organization.risk_level_strict == "critical")
    ).scalar_one()
    assert (strict_unknown, critical) == (3645, 23)

    preliminary_measured = db_session.execute(
        select(func.count())
        .select_from(Organization)
        .where(Organization.risk_level_preliminary != "unknown")
    ).scalar_one()
    assert preliminary_measured == 3668


@pytest.mark.integration
def test_territory_index_is_built_from_the_reference(db_session: Session) -> None:
    """Сопоставитель строится по таблице алиасов, а не по перечню в коде."""
    index = load_territory_index(db_session)
    assert index.ids, "справочник территорий пуст — сначала нужен load_territories"
    assert set(index.levels) == set(index.ids)
    resolution = index.resolver.resolve("Алматинская область")
    assert resolution.ok
