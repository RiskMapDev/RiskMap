"""Тесты единого списка объектов.

Отдельное внимание — выборке по одному типу объектов. Именно на ней вскрылся
дефект: у организаций нет территории, и в объединении из одной ветки база не
могла вывести тип для соединения с таблицей территорий. При двух и более
типах ошибка не проявлялась, потому что тип подхватывался от соседней ветки.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.api.queryspec import ObjectType, QuerySpec
from app.db.session import get_session_factory
from app.risk.core import RiskLevel
from app.services import catalog


@pytest.fixture(scope="module")
def session() -> Session:
    factory = get_session_factory()
    with factory() as active:
        yield active


@pytest.mark.integration
class TestВыборкаПоОдномуТипу:
    @pytest.mark.parametrize("object_type", list(ObjectType))
    def test_каждый_тип_запрашивается_отдельно(
        self, session: Session, object_type: ObjectType
    ) -> None:
        """Выборка по одному типу не должна падать ни для одного из слоёв."""
        spec = QuerySpec(object_types=[object_type], page_size=5)
        cards, total = catalog.list_objects(session, spec)

        assert total >= 0
        assert all(card.object_type is object_type for card in cards)

    def test_организации_без_территории_находятся(self, session: Session) -> None:
        """У слоя 8.7 территории нет вовсе — выборка обязана работать всё равно."""
        spec = QuerySpec(object_types=[ObjectType.ORGANIZATION], page_size=5)
        cards, total = catalog.list_objects(session, spec)

        assert total == 3668
        assert all(card.territory_code is None for card in cards)

    def test_сводка_по_одному_типу_не_падает(self, session: Session) -> None:
        spec = QuerySpec(object_types=[ObjectType.ORGANIZATION])
        counts = catalog.level_counts(session, spec)

        assert sum(counts.values()) == 3668
        assert counts[RiskLevel.CRITICAL] == 23


@pytest.mark.integration
class TestОбъёмы:
    def test_полная_выборка_содержит_все_слои(self, session: Session) -> None:
        """355 договоров + 3413 получателей + 6165 объектов 8.6 + 3668 организаций."""
        _, total = catalog.list_objects(session, QuerySpec(page_size=1))
        assert total == 355 + 3413 + 6165 + 3668

    def test_пустой_доступ_даёт_пустую_выборку(self, session: Session) -> None:
        """Пустое множество территорий и отсутствие ограничения — разные вещи.

        Спутать их означало бы открыть все данные пользователю, которому не
        назначена ни одна территория.
        """
        _, total = catalog.list_objects(session, QuerySpec(), allowed_territory_ids=[])
        assert total == 0


@pytest.mark.integration
class TestСортировка:
    def test_объекты_без_оценки_не_выдают_себя_за_низкий_риск(
        self, session: Session
    ) -> None:
        """При сортировке по риску серые не должны попадать между уровнями."""
        spec = QuerySpec(sort="risk", order="desc", page_size=50)
        cards, _ = catalog.list_objects(session, spec)

        levels = [card.risk_level for card in cards]
        # Первыми идут критические, «нет данных» — в самом конце убывания.
        assert levels[0] is RiskLevel.CRITICAL
        assert RiskLevel.UNKNOWN not in levels[: len(levels) // 2]

    def test_страницы_не_повторяют_объекты(self, session: Session) -> None:
        """Без устойчивого третьего ключа сортировки объект мог бы попасть
        на две страницы подряд, а другой не показаться вовсе."""
        first, _ = catalog.list_objects(session, QuerySpec(page=1, page_size=20))
        second, _ = catalog.list_objects(session, QuerySpec(page=2, page_size=20))

        ids_first = {(c.object_type, c.object_id) for c in first}
        ids_second = {(c.object_type, c.object_id) for c in second}

        assert not (ids_first & ids_second)
