"""Сведение риска объектов к цвету территории.

Проверяется главное правило карты: территория красится по худшему из
измеренных объектов, а territория без измерений остаётся серой. Ошибка здесь
не видна глазом — карта выглядит правдоподобно в обоих случаях, — поэтому
правило закреплено тестами, а не только комментарием.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models.budget import BudgetMonthlyMetric
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory, TerritoryGeometry
from app.risk.core import RiskLevel
from app.services.territories import territories_geojson
from app.services.territory_risk import _summarize, layer_coverage


@pytest.fixture
def mapped_territories(
    db_session: Session, territories: dict[str, Territory]
) -> dict[str, Territory]:
    """Те же территории, но с геометрией — иначе их нет в выдаче границ.

    Выдача соединяется с геометрией внутренним соединением: территория без
    контура на карте не рисуется, и показывать её было бы нечем.
    """
    for key in ("region", "karasay", "talgar"):
        db_session.add(
            TerritoryGeometry(
                territory_id=territories[key].id,
                geom=func.ST_GeomFromText(_SQUARE, 4326),
            )
        )
    db_session.flush()
    return territories


#: Квадрат в градусах — форма роли не играет, нужен лишь валидный контур.
_SQUARE = "POLYGON((76 43, 77 43, 77 44, 76 44, 76 43))"


def _recipient(
    session: Session,
    *,
    territory: Territory | None,
    level: str,
) -> SubsidyRecipient:
    """Получатель субсидии с заданным уровнем риска.

    Значения сумм не важны: тест про сведение уровней, а не про их расчёт.
    """
    recipient = SubsidyRecipient(
        xin=uuid.uuid4().hex[:12],
        name="Тестовый получатель",
        total_amount=Decimal("1000"),
        payments_count=1,
        programs_count=1,
        model_code="subsidy_recipient",
        model_version="1.0.0",
        risk_level=level,
        risk_completeness=Decimal("1"),
        territory_id=territory.id if territory else None,
    )
    session.add(recipient)
    session.flush()
    return recipient


class TestСведениеУровней:
    """Правило «максимум измеренных»."""

    def test_худший_объект_задаёт_уровень_территории(self) -> None:
        risk = _summarize({RiskLevel.LOW: 300, RiskLevel.CRITICAL: 1})

        # Один критический объект среди трёхсот благополучных делает
        # территорию критической. Это осознанный выбор: карта рисков обязана
        # показывать, где проблема есть, а не где её мало.
        assert risk.level is RiskLevel.CRITICAL
        assert risk.total == 301

    def test_неизмеренные_объекты_не_поднимают_уровень(self) -> None:
        risk = _summarize({RiskLevel.LOW: 2, RiskLevel.UNKNOWN: 50})

        # «Нет данных» — не «высокий риск». Пятьдесят неизвестных объектов не
        # делают территорию опаснее, чем показывают два известных.
        assert risk.level is RiskLevel.LOW
        assert risk.measured == 2
        assert risk.total == 52

    def test_территория_без_измерений_серая(self) -> None:
        assert _summarize({RiskLevel.UNKNOWN: 7}).level is RiskLevel.UNKNOWN
        assert _summarize({}).level is RiskLevel.UNKNOWN


class TestПокрытиеСлоя:
    """Что попадает на карту, а что остаётся за её пределами."""

    def test_территория_без_объектов_серая_а_не_низкая(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        _recipient(db_session, territory=territories["karasay"], level="low")

        coverage = layer_coverage(db_session, "subsidies")
        talgar = coverage.risk_for(territories["talgar"].id)

        # Ключевая проверка. Отсутствие записей — это незнание, а не
        # благополучие: зелёный Талгарский район сказал бы пользователю, что
        # там проверено и всё хорошо, тогда как там не проверено ничего.
        assert talgar.level is RiskLevel.UNKNOWN
        assert talgar.total == 0

    def test_объекты_без_территории_считаются_отдельно(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        # Тесты идут по рабочей базе с откатом, поэтому сравнивается прирост,
        # а не абсолютные числа: слой уже содержит настоящие данные.
        before = layer_coverage(db_session, "subsidies")

        _recipient(db_session, territory=territories["karasay"], level="high")
        _recipient(db_session, territory=None, level="critical")

        after = layer_coverage(db_session, "subsidies")

        assert after.total - before.total == 2
        assert after.unplaced - before.unplaced == 1
        # Критический объект без территории не покрасил чужой район.
        assert after.risk_for(territories["karasay"].id).level is RiskLevel.HIGH

    def test_неизвестный_слой_не_роняет_запрос(self, db_session: Session) -> None:
        coverage = layer_coverage(db_session, "administrative")

        # Слой без оценки риска отдаёт пустое покрытие, а не исключение:
        # карта покажет его без заливки по риску.
        assert coverage.by_territory == {}
        assert coverage.total == 0

    def test_бюджет_берёт_свежий_период_а_не_худший(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        """Строки бюджета — один регион в разные месяцы, а не разные объекты.

        Максимум по месяцам ответил бы «был ли когда-нибудь провал». Карта
        отвечает «как дела сейчас», поэтому берётся последний период.
        """
        for period, level in (("2026-01", "critical"), ("2026-02", "low")):
            db_session.add(_budget_metric(territories["region"], period, level))
        db_session.flush()

        coverage = layer_coverage(db_session, "budget")
        risk = coverage.risk_for(territories["region"].id)

        assert risk.level is RiskLevel.LOW, "взят критический январь вместо низкого февраля"


def _budget_metric(territory: Territory, period: str, level: str) -> BudgetMonthlyMetric:
    """Помесячная метрика с нулевыми индикаторами.

    Значения индикаторов не влияют на выбор периода, поэтому заполняются
    нулями: их подбор только затемнил бы предмет теста.
    """
    indicators: dict[str, Any] = {
        name: Decimal("0")
        for name in (
            "r01_revenue_execution",
            "r02_expense_execution",
            "r04_revision_intensity",
            "r05_profile_error",
            "r06_balance_deviation",
            "r07_cash_buffer_months",
            "r09_absorption_pressure",
            "r10_commitment_lag",
            "r11_unpaid_commitments",
            "r12_underexecution_width",
            "r13_expense_hhi",
            "r14_financial_ops_deviation",
        )
    }

    return BudgetMonthlyMetric(
        territory_id=territory.id,
        source_territory_code="REG-001",
        source_region_name=territory.name_ru,
        territory_name_normalized=territory.name_ru.lower(),
        period=period,
        period_year=int(period[:4]),
        period_month=int(period[5:]),
        closing_balance=Decimal("0"),
        model_version="1.0.0",
        data_completeness=Decimal("1"),
        indicator_completeness=Decimal("1"),
        risk_level=level,
        **indicators,
    )


class TestГраницыСоСлоем:
    """Слой в выдаче границ."""

    def test_свойства_содержат_уровень_и_распределение(
        self, db_session: Session, mapped_territories: dict[str, Territory]
    ) -> None:
        for level in ("low", "low", "high"):
            _recipient(db_session, territory=mapped_territories["karasay"], level=level)

        payload = territories_geojson(db_session, layer="subsidies")
        karasay = _feature(payload, mapped_territories["karasay"].code)

        assert karasay["risk_level"] == "high"
        assert karasay["risk_counts"]["low"] == 2
        assert karasay["risk_counts"]["high"] == 1
        # Распределение содержит все уровни, включая нулевые: иначе клиенту
        # пришлось бы отличать «ноль критических» от «поле не пришло».
        assert karasay["risk_counts"]["critical"] == 0

    def test_без_слоя_ответ_прежний(
        self, db_session: Session, mapped_territories: dict[str, Territory]
    ) -> None:
        payload = territories_geojson(db_session)

        assert "layer" not in payload
        assert "risk_level" not in _feature(payload, mapped_territories["karasay"].code)

    def test_сводка_называет_непоказанные_объекты(
        self, db_session: Session, mapped_territories: dict[str, Territory]
    ) -> None:
        before = territories_geojson(db_session, layer="subsidies")["layer"]

        _recipient(db_session, territory=mapped_territories["karasay"], level="low")
        _recipient(db_session, territory=None, level="low")

        after = territories_geojson(db_session, layer="subsidies")["layer"]

        # Карта, показывающая половину слоя, обязана назвать вторую половину.
        assert after["objects_total"] - before["objects_total"] == 2
        assert after["objects_shown"] - before["objects_shown"] == 1
        assert after["objects_not_shown"] - before["objects_not_shown"] == 1
        assert after["objects_without_territory"] - before["objects_without_territory"] == 1


def _feature(payload: dict[str, Any], code: str) -> dict[str, Any]:
    for feature in payload["features"]:
        if feature["id"] == code:
            properties: dict[str, Any] = feature["properties"]
            return properties
    raise AssertionError(f"территория {code} не найдена в выдаче")


class TestЭндпоинт:
    def test_неописанный_слой_отклоняется(self, client: TestClient) -> None:
        response = client.get("/api/v1/territories/geojson", params={"layer": "выдуманный"})

        # Молча вернуть некрашеную карту нельзя: пользователь решил бы, что
        # слой пуст, тогда как он просто не существует.
        assert response.status_code == 422
        assert "не описан" in response.json()["detail"]

    @pytest.mark.parametrize("layer", ["procurement", "subsidies", "infrastructure_expertise"])
    def test_слои_с_риском_принимаются(self, client: TestClient, layer: str) -> None:
        response = client.get("/api/v1/territories/geojson", params={"layer": layer})

        assert response.status_code == 200
        assert response.json()["layer"]["code"] == layer


class TestУровниВместе:
    """Районы и города запрашиваются одним набором."""

    def test_несколько_уровней_в_одной_выдаче(
        self, db_session: Session, territories: dict[str, Territory]
    ) -> None:
        payload = territories_geojson(db_session, levels=["region", "district"])
        levels = {feature["properties"]["level"] for feature in payload["features"]}

        # Города областного значения — отдельный уровень иерархии, но на карте
        # они покрывают территорию наравне с районами. Запрос одного уровня
        # оставлял на карте дыры на месте Конаева и Алатау.
        assert levels == {"region", "district"}
