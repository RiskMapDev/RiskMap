"""Тесты агрегатов аналитической панели.

Проверяется главным образом одно: панель не выдаёт отсутствие данных за ноль.
Ноль означает измеренное отсутствие, а «нет данных» — что измерения не было,
и подмена одного другим приводит к ложному выводу о благополучии.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.session import get_session_factory
from app.risk.core import RiskLevel
from app.services import dashboard


@pytest.fixture(scope="module")
def session() -> Session:
    factory = get_session_factory()
    with factory() as active:
        yield active


@pytest.mark.integration
class TestПоказатели:
    def test_показателей_восемь(self, session: Session) -> None:
        """Столько же, сколько карточек на референсе."""
        assert len(dashboard.build_kpis(session)) == 8

    def test_у_каждого_показателя_есть_определение(self, session: Session) -> None:
        """Требование ТЗ: у значения должен быть тултип с определением."""
        for kpi in dashboard.build_kpis(session):
            assert kpi.definition.strip(), kpi.code

    def test_аналитические_материалы_честно_без_данных(self, session: Session) -> None:
        """Такой сущности в источниках нет вовсе.

        Ноль означал бы «материалов не заведено», тогда как на деле их учёт в
        приложенных данных не ведётся. Разница существенна для вывода.
        """
        materials = next(k for k in dashboard.build_kpis(session) if k.code == "analytic_materials")

        assert materials.value is None
        assert not materials.is_available
        assert "нет такой сущности" in materials.reason

    def test_недоступный_показатель_объясняет_причину(self, session: Session) -> None:
        for kpi in dashboard.build_kpis(session):
            if not kpi.is_available:
                assert kpi.reason.strip(), f"{kpi.code} без причины"

    def test_сумма_субсидий_совпадает_с_книгой(self, session: Session) -> None:
        subsidies = next(k for k in dashboard.build_kpis(session) if k.code == "subsidies")

        assert subsidies.value == pytest.approx(67_535_553_445, rel=1e-9)

    def test_организации_не_ограничиваются_территорией(self, session: Session) -> None:
        """У слоя 8.7 территориальной привязки нет ни в каком виде.

        Поэтому фильтр по территории к нему неприменим, и это отражено в
        определении показателя, а не спрятано.
        """
        orgs = next(k for k in dashboard.build_kpis(session) if k.code == "organizations")

        assert orgs.value == 3668
        assert "территориальной привязки" in orgs.definition.casefold()
        assert "не выводятся" in orgs.definition

    def test_экспозиция_названа_неполной(self, session: Session) -> None:
        """Экспозиция считается только по слою 8.5.

        Выдать её за сумму по всем слоям значило бы занизить оценку, не
        сказав об этом.
        """
        exposure = next(k for k in dashboard.build_kpis(session) if k.code == "risk_exposure")

        assert "только по слою 8.5" in exposure.definition
        assert "неполна" in exposure.definition

    def test_выборка_закупок_помечена_как_целевая(self, session: Session) -> None:
        procurement = next(k for k in dashboard.build_kpis(session) if k.code == "procurement")
        assert "не все закупки региона" in procurement.definition


@pytest.mark.integration
class TestРаспределениеПоУровням:
    def test_серый_уровень_присутствует_всегда(self, session: Session) -> None:
        """Убрать серые объекты из диаграммы значит приукрасить картину."""
        distribution = dashboard.level_distribution(session)

        assert RiskLevel.UNKNOWN.value in distribution

    def test_присутствуют_все_пять_уровней(self, session: Session) -> None:
        distribution = dashboard.level_distribution(session)
        assert set(distribution) == {level.value for level in RiskLevel}

    def test_сумма_совпадает_с_числом_объектов(self, session: Session) -> None:
        """13 601 объект: 355 + 3413 + 6165 + 3668."""
        distribution = dashboard.level_distribution(session)
        assert sum(distribution.values()) == 355 + 3413 + 6165 + 3668

    def test_критических_объектов_не_меньше_чем_категория_а(self, session: Session) -> None:
        """23 организации категории A обязаны попасть в критические."""
        distribution = dashboard.level_distribution(session)
        assert distribution[RiskLevel.CRITICAL.value] >= 23


@pytest.mark.integration
class TestДинамика:
    def test_динамика_помесячная_и_только_по_бюджету(self, session: Session) -> None:
        """Помесячную разбивку содержит только слой 8.3.

        Рисовать по остальным слоям линию было бы выдумыванием данных.
        """
        points = dashboard.budget_dynamics(session)

        assert len(points) == 12
        assert all(point["rows"] == 20 for point in points)

    def test_у_каждой_точки_есть_средний_балл(self, session: Session) -> None:
        for point in dashboard.budget_dynamics(session):
            assert point["avg_score"] is not None


@pytest.mark.integration
class TestРейтингТерриторий:
    def test_рейтинг_не_пуст(self, session: Session) -> None:
        assert dashboard.territory_ranking(session)

    def test_рейтинг_упорядочен_по_убыванию(self, session: Session) -> None:
        ranking = dashboard.territory_ranking(session)
        counts = [row["risky_count"] for row in ranking]
        assert counts == sorted(counts, reverse=True)
