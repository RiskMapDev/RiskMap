"""Тесты карточки объекта.

Главное требование ТЗ, которое здесь проверяется: оценка риска обязана быть
объяснимой. Пользователь должен видеть не только балл, но и что на него
повлияло, а что не было измерено, — иначе число остаётся непроверяемым.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.api.queryspec import ObjectType
from app.db.session import get_session_factory
from app.risk.core import RiskLevel
from app.services import object_detail


@pytest.fixture(scope="module")
def session() -> Session:
    factory = get_session_factory()
    with factory() as active:
        yield active


@pytest.mark.integration
class TestДоговор:
    def test_эталонный_договор_совпадает_с_книгой(self, session: Session) -> None:
        """Договор 22333284: S_raw=35, W_avail=60, K=1.15 → 67.1 высокий."""
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "22333284")

        assert card is not None
        assert card.risk_level is RiskLevel.HIGH
        assert card.risk_score == pytest.approx(67.1, abs=0.05)

    def test_категория_а_переопределяет_уровень(self, session: Session) -> None:
        """Договор 14863203 — критический по жёсткому правилу, а не по баллу."""
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "14863203")

        assert card is not None
        assert card.risk_level is RiskLevel.CRITICAL
        assert card.risk_score == pytest.approx(50.0, abs=0.05)

    def test_несуществующий_договор_даёт_none(self, session: Session) -> None:
        assert object_detail.load_detail(session, ObjectType.CONTRACT, "нет-такого") is None


@pytest.mark.integration
class TestПолучательСубсидий:
    def test_эталонный_получатель_совпадает_с_книгой(self, session: Session) -> None:
        card = object_detail.load_detail(
            session, ObjectType.SUBSIDY_RECIPIENT, "780702300265"
        )

        assert card is not None
        assert card.risk_score == pytest.approx(72.095, abs=0.001)

    def test_отсутствие_района_объясняется_словами(self, session: Session) -> None:
        """66 получателей не имеют района. Пустое поле выглядело бы ошибкой."""
        cards = [
            object_detail.load_detail(session, ObjectType.SUBSIDY_RECIPIENT, key)
            for key in ("780702300265",)
        ]
        for card in cards:
            assert card is not None
            if card.territory_code is None:
                assert card.territory_note


@pytest.mark.integration
class TestОрганизация:
    def test_официальный_уровень_строгий(self, session: Session) -> None:
        """У слоя 8.7 полнота ниже порога, поэтому официальный уровень серый.

        Предварительный балл при этом сохраняется и показывается рядом —
        решение заказчика, — но уровнем не подменяется.
        """
        card = object_detail.load_detail(session, ObjectType.ORGANIZATION, "070340007515")

        assert card is not None
        assert card.risk_level is RiskLevel.UNKNOWN
        assert card.risk_is_preliminary is True
        assert card.risk_score is not None

    def test_категория_а_остаётся_критической(self, session: Session) -> None:
        """23 организации категории A критические независимо от полноты."""
        card = object_detail.load_detail(session, ObjectType.ORGANIZATION, "200840029395")

        assert card is not None
        assert card.risk_level is RiskLevel.CRITICAL
        assert card.risk_is_preliminary is False

    def test_наибольший_балл_не_означает_наивысший_уровень(self, session: Session) -> None:
        """Организация с максимальным баллом 93.3 официально «нет данных».

        А критическими становятся организации с баллом 42 и ниже, у которых
        сработало жёсткое правило категории A. Выглядит противоречиво, но это
        и есть требование методики: балл при полноте 41 % не является
        основанием для вывода, а признак лжепредприятия — является.

        Тест закрепляет именно это поведение: если однажды кто-то решит
        «исправить» его сортировкой по баллу, оценка перестанет соответствовать
        методике.
        """
        highest = object_detail.load_detail(session, ObjectType.ORGANIZATION, "170640011921")
        category_a = object_detail.load_detail(session, ObjectType.ORGANIZATION, "200840029395")

        assert highest is not None and category_a is not None
        assert highest.risk_score is not None and category_a.risk_score is not None

        assert highest.risk_score > category_a.risk_score
        assert highest.risk_level is RiskLevel.UNKNOWN
        assert category_a.risk_level is RiskLevel.CRITICAL

    def test_отсутствие_территории_объяснено(self, session: Session) -> None:
        """В слое 8.7 нет ни района, ни адреса, ни координат, ни КАТО."""
        card = object_detail.load_detail(session, ObjectType.ORGANIZATION, "170640011921")

        assert card is not None
        assert card.territory_code is None
        assert "КАТО" in card.territory_note

    def test_неизмеренные_факторы_показаны_с_причиной(self, session: Session) -> None:
        """Именно они объясняют, почему полнота 41 % и уровень серый."""
        card = object_detail.load_detail(session, ObjectType.ORGANIZATION, "070340007515")

        assert card is not None
        assert card.unmeasured_factors
        for factor in card.unmeasured_factors:
            assert factor.effect == "не измерено"


@pytest.mark.integration
class TestРасшифровка:
    def test_у_измеренных_факторов_есть_вклад(self, session: Session) -> None:
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "22333284")

        assert card is not None
        assert card.measured_factors

    def test_нулевой_вклад_отличается_от_неизмеренного(self, session: Session) -> None:
        """«Не повлиял» и «не измерено» — разные утверждения об объекте."""
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "22333284")

        assert card is not None
        effects = {factor.effect for factor in card.factors}
        assert effects <= {"повысил риск", "не повлиял", "не измерено"}

    def test_служебные_ключи_не_попадают_в_факторы(self, session: Session) -> None:
        """Расшифровка лежит внутри обёртки со сведениями об оценке целиком.

        Ключи обёртки — уровень, модель, примечания, балл — описывают оценку,
        а не отдельный индикатор. Раньше они попадали в список факторов, и
        карточка договора 10303009 писала «не измерено индикаторов: 4»,
        показывая при этом шесть строк. Пользователь, считающий строки,
        получал неверное представление о полноте.
        """
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "10303009")

        assert card is not None
        codes = {factor.code for factor in card.factors}

        assert not codes & {"level", "model", "notes", "score", "factors"}
        # У методики слоя 8.4 девять индикаторов — ровно столько и ожидается.
        assert len(card.factors) == 9

    def test_число_неизмеренных_совпадает_со_списком(self, session: Session) -> None:
        """Счётчик и список обязаны сходиться — иначе один из них врёт."""
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "10303009")

        assert card is not None
        unmeasured = [f for f in card.factors if not f.measured]
        assert len(card.unmeasured_factors) == len(unmeasured)

    def test_происхождение_записи_сохранено(self, session: Session) -> None:
        """Без происхождения оценку нельзя ни проверить, ни воспроизвести."""
        card = object_detail.load_detail(session, ObjectType.CONTRACT, "22333284")

        assert card is not None
        assert card.provenance["source_layer"] == "8.4"
        assert card.provenance["imported_at"] is not None
