"""Граф связей — ТЗ раздел 13 «Модуль взаимосвязей».

Две таблицы: узел (:class:`GraphNode`) и связь (:class:`EntityRelation`).

**Почему граф хранится, а не считается на лету.** Связи выводятся из четырёх
слоёв сразу — джойн договоров, субсидий, проектов и организаций на каждый
запрос раскрытия узла не укладывается ни в норматив ТЗ 20 («фильтры ≤ 5 с»),
ни в `statement_timeout` проекта. Поэтому граф — производная витрина: скрипт
`scripts/build_relations.py` перестраивает её целиком, а API только читает.
Отсюда же следует, что денормализация здесь безопасна: расхождение между
витриной и источником невозможно, потому что витрина не правится по месту.

**Почему узел — отдельная таблица, а не пара колонок в связи.** Экрану нужна
точка входа: пользователь ищет организацию по названию и уже от неё раскрывает
окружение. Поиск по узлам — индексируемая операция по одной таблице; поиск по
денормализованным концам рёбер потребовал бы `DISTINCT` по двум колонкам на
каждый запрос. Кроме того, метка узла у программы субсидирования — до 321
знака, и дублировать её в каждой из тысяч связей значит платить мегабайтами.

**Почему ключ узла — хеш, а не сам идентификатор.** Ключ уезжает в браузер и в
адресную строку. У 3183 получателей субсидий идентификатор — это ИИН, то есть
персональные данные, и класть его в URL нельзя (см. `services/masking.py`).
Поэтому `node_key` — необратимая свёртка, а сам идентификатор лежит в
`identifier` и отдаётся наружу только через маскирование по роли.

**Почему `confidence` — обязательное поле, а не примечание.** Часть связей
доказана совпадением БИН или внешним ключом, часть — только совпадением ФИО
или адреса. У последних ложноположительные срабатывания неизбежны: полные
тёзки существуют, а один адрес бывает у бизнес-центра. Отдать оба вида связи
одинаково — значит выдать догадку за факт, и на референсе они поэтому же
нарисованы сплошной и пунктирной линией.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, uuid_pk


class NodeType(StrEnum):
    """Типы узлов графа.

    Ровно пять — те, что обеспечены данными. ТЗ 13 перечисляет шестнадцать
    видов узлов (адрес, телефон, судебное дело, правонарушение и прочие), но
    ни один из недостающих не имеет ни таблицы, ни источника: заводить для них
    пустой тип значило бы обещать в легенде то, чего в графе не бывает.
    """

    ORGANIZATION = "organization"
    """Юридическое лицо. Ключ — БИН, а при его отсутствии — свёрнутое имя."""

    PERSON = "person"
    """Физическое лицо: ИП-получатель субсидий либо руководитель организации."""

    CONTRACT = "contract"
    """Договор государственной закупки, слой 8.4."""

    SUBSIDY = "subsidy"
    """Программа субсидирования, слой 8.5."""

    PROJECT = "project"
    """Объект слоя 8.6: проект ГЧП либо заключение экспертизы ПСД."""

    @property
    def label_ru(self) -> str:
        return {
            NodeType.ORGANIZATION: "Организация",
            NodeType.PERSON: "Физическое лицо",
            NodeType.CONTRACT: "Договор",
            NodeType.SUBSIDY: "Субсидия",
            NodeType.PROJECT: "Проект",
        }[self]


class RelationType(StrEnum):
    """Типы связей.

    Соответствие типам ТЗ 13 указано у каждого значения. Тип «подрядчик»
    покрывает подрядчика, проектировщика и надзор одной связью — так они и
    сгруппированы в ТЗ (связь № 11).
    """

    DIRECTOR = "director"
    """ТЗ 13 № 1: юридическое лицо — руководитель."""

    FOUNDER = "founder"
    """ТЗ 13 № 1: юридическое лицо — учредитель."""

    SUPPLIER = "supplier"
    """ТЗ 13 № 3 и № 4: компания — договор в роли поставщика."""

    CONTRACTOR = "contractor"
    """ТЗ 13 № 11: объект — подрядчик, проектировщик или надзор."""

    RECIPIENT = "recipient"
    """ТЗ 13 № 5: компания или лицо — субсидия."""

    CO_RECIPIENT = "co_recipient"
    """ТЗ 13 № 9: два получателя поддержки с общим руководителем."""

    SHARED_ADDRESS = "shared_address"
    """ТЗ 13 № 9: две организации по одному юридическому адресу."""

    @property
    def label_ru(self) -> str:
        return {
            RelationType.DIRECTOR: "Руководитель",
            RelationType.FOUNDER: "Учредитель",
            RelationType.SUPPLIER: "Поставщик",
            RelationType.CONTRACTOR: "Подрядчик",
            RelationType.RECIPIENT: "Получатель",
            RelationType.CO_RECIPIENT: "Со-получатель",
            RelationType.SHARED_ADDRESS: "Общий адрес",
        }[self]


class RelationDirection(StrEnum):
    """Направление связи.

    Различие содержательное, а не оформительское. «Поставщик» направлен: у
    договора есть поставщик, у поставщика — договор, и эти утверждения не
    равнозначны. «Общий адрес» симметричен: обе организации в нём равноправны,
    и рисовать стрелку значило бы приписать одной из них первенство, которого
    в данных нет.
    """

    DIRECTED = "directed"
    UNDIRECTED = "undirected"


class RelationConfidence(StrEnum):
    """Достоверность связи.

    Значений намеренно два, а не числовая шкала: у выводимых из данных связей
    нет вероятностной модели, и число вроде «0.72» создавало бы видимость
    точности, которой нет. Разделение же на «доказано идентификатором» и
    «совпало написание» опирается на проверяемый признак.
    """

    CONFIRMED = "confirmed"
    """Совпадение идентификатора (БИН/ИИН) либо внешний ключ источника."""

    PROBABLE = "probable"
    """Совпадение адреса или наименования. Требует проверки аналитиком."""

    @property
    def label_ru(self) -> str:
        return {
            RelationConfidence.CONFIRMED: "Достоверная",
            RelationConfidence.PROBABLE: "Предположительная",
        }[self]


#: Длина шестнадцатеричной свёртки в ключе узла. 24 знака — это 96 бит, при
#: 25 тысячах узлов вероятность коллизии порядка 10⁻²⁰; короче брать нельзя,
#: длиннее — незачем, ключ ещё и в адресной строке.
NODE_HASH_LENGTH = 24


def node_key(node_type: NodeType | str, identity: str) -> str:
    """Устойчивый непрозрачный ключ узла.

    Чистая функция: перестройка витрины не меняет ключи, и сохранённая ссылка
    на узел продолжает работать.

    Свёртка, а не сам идентификатор, — потому что у трёх с лишним тысяч
    получателей субсидий идентификатор является ИИН. Ключ попадает в JSON
    ответа и в адресную строку, а персональные данные в URL недопустимы даже
    для администратора: адреса оседают в истории браузера и в логах прокси,
    куда правила разграничения доступа не дотягиваются.
    """
    digest = hashlib.blake2s(
        identity.strip().casefold().encode("utf-8"), digest_size=NODE_HASH_LENGTH // 2
    ).hexdigest()
    return f"{node_type}:{digest}"


class GraphNode(Base, TimestampMixin, ProvenanceMixin):
    """Узел графа — сущность, вокруг которой строится окружение.

    `ref_entity_type` и `ref_entity_id` указывают на запись слоя, из которой
    узел получен, и нужны для перехода к карточке объекта (требование ТЗ 13:
    «переход к карточкам связанных объектов»). Они пустые у узлов, за которыми
    нет отдельной записи, — например, у руководителя, известного только по
    имени в поле `director_name`.
    """

    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("node_key", name="uq_graph_node_key"),
        Index("ix_graph_nodes_type", "node_type"),
        Index("ix_graph_nodes_label", "label"),
        Index("ix_graph_nodes_territory", "territory_id"),
        Index("ix_graph_nodes_risk_level", "risk_level"),
        CheckConstraint("degree >= 0", name="ck_graph_node_degree_non_negative"),
        CheckConstraint(
            "identifier IS NULL OR identifier_kind IS NOT NULL",
            name="ck_graph_node_identifier_kind",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    node_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Непрозрачный ключ вида «person:9f3c…». Единственное, что уходит наружу.",
    )
    node_type: Mapped[NodeType] = mapped_column(String(24), nullable=False)

    label: Mapped[str] = mapped_column(
        Text, nullable=False, doc="Подпись узла на канве — наименование либо ФИО."
    )
    sublabel: Mapped[str | None] = mapped_column(
        Text, doc="Вторая строка карточки узла: район, сумма, статус."
    )

    identifier: Mapped[str | None] = mapped_column(
        String(32),
        doc=(
            "БИН или ИИН. Персональные данные: наружу отдаётся только через "
            "`services/masking.py` и никогда не входит в `node_key`."
        ),
    )
    identifier_kind: Mapped[str | None] = mapped_column(
        String(8),
        doc=(
            "bin | iin. Разделение обязательно: БИН — публичный реквизит "
            "юридического лица, ИИН — персональные данные физического, и "
            "маскировать их одинаково нельзя."
        ),
    )

    risk_level: Mapped[str | None] = mapped_column(
        String(16),
        doc="Официальный (строгий) уровень риска записи-источника. NULL — уровня нет вовсе.",
    )
    risk_score: Mapped[float | None] = mapped_column()
    risk_is_preliminary: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        doc="Балл посчитан, но полноты не хватает: уровень серый, вывод делать нельзя.",
    )

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="SET NULL"),
        doc=(
            "Территория узла. NULL — привязки нет в источнике (организации "
            "слоя 8.7, программы субсидирования, физические лица). Такой узел "
            "не показывается пользователю с территориальным ограничением."
        ),
    )

    ref_entity_type: Mapped[str | None] = mapped_column(
        String(32), doc="Тип записи слоя для перехода в карточку: contract, subsidy_recipient, …"
    )
    ref_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    source_layer: Mapped[str] = mapped_column(
        String(16), nullable=False, doc="Слой-источник: «8.4», «8.5», «8.6», «8.7»."
    )

    degree: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        doc=(
            "Число инцидентных связей, посчитанное при сборке. Нужно, чтобы "
            "предупредить пользователя об усечении до раскрытия узла, а не "
            "после: у программы субсидирования соседей тысячи."
        ),
    )

    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, doc="Дополнительные поля карточки узла — сумма, статус, вид деятельности."
    )

    def __repr__(self) -> str:
        return f"<GraphNode {self.node_type} {self.label[:40]!r}>"


class EntityRelation(Base, TimestampMixin, ProvenanceMixin):
    """Связь между двумя узлами графа.

    Дата актуальности связи берётся из `ProvenanceMixin.data_as_of` — того же
    поля, что и у всех фактов проекта. Отдельное поле «дата связи» завели бы
    только для того, чтобы оно рано или поздно разошлось с датой факта, из
    которого связь выведена.

    Хранится ровно одна строка на пару узлов и тип связи. Для симметричных
    связей («общий адрес», «со-получатель») концы упорядочены по ключу узла —
    иначе одна и та же пара попала бы в таблицу дважды и на канве нарисовалась
    двумя параллельными рёбрами.
    """

    __tablename__ = "entity_relations"
    __table_args__ = (
        UniqueConstraint(
            "relation_type",
            "source_node_id",
            "target_node_id",
            name="uq_entity_relation_pair",
        ),
        Index("ix_entity_relations_source", "source_node_id"),
        Index("ix_entity_relations_target", "target_node_id"),
        Index("ix_entity_relations_type", "relation_type"),
        Index("ix_entity_relations_confidence", "confidence"),
        Index("ix_entity_relations_territory", "territory_id"),
        # Петля означала бы, что запись связана сама с собой: у получателя-ИП
        # руководителем записан он же. Такая «связь» ничего не сообщает и
        # только засоряет окружение, поэтому запрещена на уровне базы.
        CheckConstraint("source_node_id <> target_node_id", name="ck_entity_relation_no_self_loop"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    relation_type: Mapped[RelationType] = mapped_column(String(24), nullable=False)
    direction: Mapped[RelationDirection] = mapped_column(
        String(16),
        nullable=False,
        default=RelationDirection.DIRECTED,
        doc="У симметричных связей стрелка не рисуется: первенства сторон в данных нет.",
    )
    confidence: Mapped[RelationConfidence] = mapped_column(
        String(16),
        nullable=False,
        doc="Доказана идентификатором или только совпадением написания.",
    )
    confidence_basis: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc=(
            "Чем именно доказана связь, человеческими словами: «внешний ключ "
            "источника: contracts.supplier_id», «совпадение ФИО руководителя». "
            "Показывается в подсказке к ребру — без этого «предположительная» "
            "остаётся ярлыком, который нечем проверить."
        ),
    )

    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    source_node: Mapped[GraphNode] = relationship(foreign_keys=[source_node_id])

    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node: Mapped[GraphNode] = relationship(foreign_keys=[target_node_id])

    source_layer: Mapped[str] = mapped_column(
        String(16), nullable=False, doc="Слой, из которого выведена связь."
    )
    derivation_rule: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc=(
            "Машинное имя правила вывода: `contracts.supplier_id`, "
            "`subsidy_recipients.director_name`. По нему связь трассируется до "
            "строки источника при разборе спорного случая."
        ),
    )

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="SET NULL"),
        doc=(
            "Территория факта, из которого выведена связь. По ней работает "
            "территориальное ограничение доступа. NULL — территории у факта "
            "нет, и ограниченному пользователю связь не показывается."
        ),
    )

    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), doc="Денежный вес связи: сумма договора либо выплаченных субсидий."
    )

    evidence: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, doc="Опорные значения: номер договора, число выплат, совпавшая строка адреса."
    )

    def __repr__(self) -> str:
        return f"<EntityRelation {self.relation_type} {self.confidence}>"


__all__ = [
    "NODE_HASH_LENGTH",
    "EntityRelation",
    "GraphNode",
    "NodeType",
    "RelationConfidence",
    "RelationDirection",
    "RelationType",
    "node_key",
]
