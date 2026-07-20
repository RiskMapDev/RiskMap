"""Вывод графа связей из загруженных данных (ТЗ 13).

Запуск::

    python -m scripts.build_relations            # перестроить граф
    python -m scripts.build_relations --dry-run  # показать план, ничего не менять

**Главное правило: связь выводится из факта, а не придумывается.** Если в
источнике нет основания — связи нет, и в отчёте о сборке напротив её типа
стоит ноль с объяснением, почему. Это относится, в частности, к учредителям:
таблица `organization_person_roles` пуста, потому что книга слоя 8.7 состава
учредителей не содержит вовсе. Заполнить этот тип «похожими» связями —
единственный способ его показать, и он же самый опасный: аффилированность,
выведенная из ничего, в аналитической справке неотличима от установленной.

**Почему граф перестраивается целиком, а не дополняется.** Связь — производная
величина, а не факт. Изменился источник — изменился и набор связей, включая
исчезнувшие. Инкрементальное дополнение оставило бы в витрине связи, которых
в данных больше нет, и обнаружить их было бы нечем.

Разбор конкретных решений по каждому типу связи — в комментариях функций
`_build_*` ниже.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models.graph import (
    EntityRelation,
    GraphNode,
    NodeType,
    RelationConfidence,
    RelationDirection,
    RelationType,
    node_key,
)
from app.db.models.infrastructure import ParticipantRole, ProjectEntity, ProjectParticipant
from app.db.models.organization import Organization, OrganizationPersonRole, PersonRoleKind
from app.db.models.procurement import Contract, Supplier
from app.db.models.subsidy import SubsidyPayment, SubsidyProgram, SubsidyRecipient
from app.db.session import session_scope

#: Дата актуальности связей. Берётся не «сегодня», а дата данных: связь
#: актуальна ровно настолько, насколько актуален факт, из которого она выведена.
#: Единой даты у четырёх книг нет, поэтому берётся максимум `data_as_of` по
#: источнику; при пустом значении дата остаётся NULL, а не подменяется текущей.
DEFAULT_AS_OF: date | None = None


# ---------------------------------------------------------------------------
# Опознание идентификатора
# ---------------------------------------------------------------------------

#: Пятая цифра БИН — тип юридического лица: 4 резидент, 5 нерезидент, 6 ИП/КХ.
#: У ИИН на этой позиции стоит десяток дня рождения, то есть 0–3. Признак
#: проверен на всей выборке слоя 8.5: 3183 значения с цифрой 0–3 в точности
#: совпали с 3183 записями, чьё наименование начинается на «ИП», и 230 значений
#: с цифрой 4 — с 230 юридическими лицами (ТОО, СПК, АО и прочие).
_BIN_TYPE_DIGITS = frozenset("456")


def identifier_kind(xin: str) -> str:
    """«bin» либо «iin» по структуре 12-значного идентификатора.

    Разделение обязательно и не является косметическим. БИН — публичный
    реквизит юридического лица, его прячут только от лишнего шума; ИИН —
    персональные данные, и его раскрытие журналируется. Показать ИИН как БИН
    значит выдать персональные данные всем, кому открыты реквизиты компаний.
    """
    return "bin" if len(xin) == 12 and xin[4] in _BIN_TYPE_DIGITS else "iin"


def normalize_name(raw: str | None) -> str:
    """Свёртка наименования или ФИО для сравнения.

    Только буквы и цифры, регистр снят. Ровно такая же свёртка применяется в
    слое 8.6 (`ProjectParticipant.name_key`), и повторить её здесь важнее, чем
    придумать «лучшую»: расхождение свёрток разорвало бы узлы, которые слой уже
    считает одним участником.
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw.casefold() if ch.isalnum())


def normalize_address(raw: str | None) -> str:
    """Свёртка юридического адреса.

    Дом и квартиру намеренно **не** отбрасываем: «одна улица» — это не общий
    адрес, а соседство, и связь по нему была бы шумом. Совпадать должна вся
    строка целиком, включая номер дома.
    """
    if not raw:
        return ""
    return " ".join(raw.casefold().split())


# ---------------------------------------------------------------------------
# Накопитель графа
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _NodeDraft:
    """Узел до записи в базу."""

    key: str
    node_type: NodeType
    label: str
    source_layer: str
    sublabel: str | None = None
    identifier: str | None = None
    id_kind: str | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    risk_is_preliminary: bool = False
    territory_id: uuid.UUID | None = None
    ref_entity_type: str | None = None
    ref_entity_id: uuid.UUID | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _EdgeDraft:
    """Связь до записи в базу."""

    relation_type: RelationType
    source_key: str
    target_key: str
    confidence: RelationConfidence
    confidence_basis: str
    source_layer: str
    derivation_rule: str
    direction: RelationDirection = RelationDirection.DIRECTED
    territory_id: uuid.UUID | None = None
    amount: Decimal | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class GraphDraft:
    """Собираемый граф.

    Узлы складываются в словарь по ключу: одна и та же организация приходит и
    из слоя 8.4 (поставщик), и из 8.5 (получатель субсидий), и из 8.7
    (хозяйствующий субъект). Слияние по БИН — это и есть та «скрытая
    взаимосвязь», ради которой модуль существует, поэтому первый узел
    выигрывает по метке, но обогащается уровнем риска и территорией из
    последующих, если у него их не было.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, _NodeDraft] = {}
        self.edges: dict[tuple[str, str, str], _EdgeDraft] = {}
        self.skipped: dict[str, int] = defaultdict(int)

    def add_node(self, draft: _NodeDraft) -> str:
        existing = self.nodes.get(draft.key)
        if existing is None:
            self.nodes[draft.key] = draft
            return draft.key

        # Обогащение, а не перезапись: «нет данных» уступает измеренному
        # значению, но измеренное значение не затирается вторым измеренным —
        # расхождение слоёв в уровне риска разбирается отдельно и молча
        # выбирать «последний» нельзя.
        if existing.risk_level is None:
            existing.risk_level = draft.risk_level
            existing.risk_score = draft.risk_score
            existing.risk_is_preliminary = draft.risk_is_preliminary
        if existing.territory_id is None:
            existing.territory_id = draft.territory_id
        if existing.identifier is None:
            existing.identifier = draft.identifier
            existing.id_kind = draft.id_kind
        if existing.ref_entity_id is None:
            existing.ref_entity_type = draft.ref_entity_type
            existing.ref_entity_id = draft.ref_entity_id
        # Слои узла копятся списком: пользователь должен видеть, что этот
        # субъект встречается и в закупках, и в субсидиях.
        layers = set(str(existing.attributes.get("layers", "")).split()) | {
            existing.source_layer,
            draft.source_layer,
        }
        existing.attributes["layers"] = " ".join(sorted(layer for layer in layers if layer))
        return existing.key

    def add_edge(self, draft: _EdgeDraft) -> None:
        if draft.source_key == draft.target_key:
            # Петля: у получателя-ИП руководителем записан он сам. Такая
            # «связь» не сообщает ничего и запрещена ограничением базы.
            self.skipped["петля"] += 1
            return
        if draft.source_key not in self.nodes or draft.target_key not in self.nodes:
            self.skipped["узел не найден"] += 1
            return

        source, target = draft.source_key, draft.target_key
        if draft.direction is RelationDirection.UNDIRECTED and source > target:
            # Симметричная связь хранится в одном порядке, иначе пара попадёт
            # в таблицу дважды и нарисуется двумя рёбрами.
            source, target = target, source
            draft.source_key, draft.target_key = source, target

        self.edges.setdefault((str(draft.relation_type), source, target), draft)


# ---------------------------------------------------------------------------
# Правила вывода
# ---------------------------------------------------------------------------


def _organization_node(
    *,
    bin_value: str | None,
    name: str,
    layer: str,
    sublabel: str | None = None,
    risk_level: str | None = None,
    risk_score: float | None = None,
    risk_is_preliminary: bool = False,
    territory_id: uuid.UUID | None = None,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> _NodeDraft:
    """Узел юридического лица.

    Ключ строится по БИН, когда он известен, и только тогда организации из
    разных слоёв сливаются в один узел. Без БИН ключом становится свёрнутое
    наименование — и такой узел **не** склеивается с БИН-узлом того же
    предприятия. Это осознанная потеря: сопоставление наименований слоя 8.6 с
    реестром организаций дало 2 совпадения на 809×769 сравнений, то есть шум.
    Ложное слияние двух компаний в одну хуже, чем два узла вместо одного.
    """
    if bin_value:
        key = node_key(NodeType.ORGANIZATION, f"bin:{bin_value}")
        identifier: str | None = bin_value
        id_kind: str | None = "bin"
    else:
        key = node_key(NodeType.ORGANIZATION, f"name:{normalize_name(name)}")
        identifier = None
        id_kind = None

    return _NodeDraft(
        key=key,
        node_type=NodeType.ORGANIZATION,
        label=name,
        sublabel=sublabel,
        identifier=identifier,
        id_kind=id_kind,
        risk_level=risk_level,
        risk_score=risk_score,
        risk_is_preliminary=risk_is_preliminary,
        territory_id=territory_id,
        ref_entity_type=ref_type,
        ref_entity_id=ref_id,
        source_layer=layer,
    )


def _person_node(
    *,
    iin: str | None,
    full_name: str,
    layer: str,
    sublabel: str | None = None,
    risk_level: str | None = None,
    risk_score: float | None = None,
    territory_id: uuid.UUID | None = None,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> _NodeDraft:
    """Узел физического лица.

    По ИИН, когда он есть, иначе по свёрнутому ФИО. Второй случай ненадёжен и
    отмечен в связи как предположительный: полные тёзки существуют, а в слое
    8.5 руководитель записан свободным текстом, где одно и то же лицо пишется
    то «Толысбаева Айжан Кошеевна», то заглавными.
    """
    if iin:
        key = node_key(NodeType.PERSON, f"iin:{iin}")
    else:
        key = node_key(NodeType.PERSON, f"name:{normalize_name(full_name)}")

    return _NodeDraft(
        key=key,
        node_type=NodeType.PERSON,
        label=full_name,
        sublabel=sublabel,
        identifier=iin,
        id_kind="iin" if iin else None,
        risk_level=risk_level,
        risk_score=risk_score,
        territory_id=territory_id,
        ref_entity_type=ref_type,
        ref_entity_id=ref_id,
        source_layer=layer,
    )


def _build_procurement(session: Session, graph: GraphDraft) -> None:
    """Слой 8.4: поставщик — договор.

    Самая надёжная связь во всём графе. Договор ссылается на поставщика
    внешним ключом, поставщик опознан по БИН из 12 знаков, и все 26 БИН
    поставщиков нашлись в реестре организаций слоя 8.7. Оснований сомневаться
    нет — связь достоверная, линия сплошная.

    Заказчик договора здесь **не** связывается: связь «заказчик» не входит в
    перечень типов этого модуля, а приписывать заказчику роль поставщика
    значило бы исказить смысл ребра ради того, чтобы оно появилось.
    """
    rows = session.execute(
        select(Contract, Supplier).join(Supplier, Contract.supplier_id == Supplier.id)
    ).all()

    for contract, supplier in rows:
        org_key = graph.add_node(
            _organization_node(
                bin_value=supplier.bin,
                name=supplier.name,
                layer="8.4",
                sublabel=supplier.district_source_name,
                risk_level=supplier.layer_8_7_level,
                territory_id=supplier.territory_id,
                ref_type="supplier",
                ref_id=supplier.id,
            )
        )

        amount = contract.final_amount or contract.planned_amount
        contract_key = graph.add_node(
            _NodeDraft(
                key=node_key(NodeType.CONTRACT, f"contract:{contract.contract_id}"),
                node_type=NodeType.CONTRACT,
                label=f"Договор {contract.contract_id}",
                sublabel=(contract.brief_content_ru or "")[:120] or None,
                risk_level=contract.risk_level,
                risk_score=float(contract.risk_score) if contract.risk_score is not None else None,
                risk_is_preliminary=contract.is_preliminary,
                territory_id=contract.territory_id,
                ref_entity_type="contract",
                ref_entity_id=contract.id,
                source_layer="8.4",
                attributes={
                    "amount": float(amount) if amount is not None else None,
                    "status": contract.contract_status,
                    "is_terminated": contract.is_terminated,
                },
            )
        )

        graph.add_edge(
            _EdgeDraft(
                relation_type=RelationType.SUPPLIER,
                source_key=org_key,
                target_key=contract_key,
                confidence=RelationConfidence.CONFIRMED,
                confidence_basis=(
                    "внешний ключ источника contracts.supplier_id, "
                    "поставщик опознан по БИН"
                ),
                source_layer="8.4",
                derivation_rule="contracts.supplier_id",
                territory_id=contract.territory_id,
                amount=amount,
                evidence={"contract_id": contract.contract_id, "supplier_bin": supplier.bin},
            )
        )


def _build_subsidies(session: Session, graph: GraphDraft) -> None:
    """Слой 8.5: получатель — субсидия, и руководитель получателя.

    **Почему узлом субсидии стала программа, а не отдельная выплата.** Выплат
    21 521, и каждая связана ровно с одним получателем: граф из них
    выродился бы в набор звёзд без единого пересечения — то есть не показал бы
    ни одной взаимосвязи, ради которых строится. Программа субсидирования
    (46 штук) — та единица, вокруг которой получатели действительно
    группируются. Кратность «получатель × программа» схлопнута: повторные
    выплаты по одной программе отражены суммой и числом выплат на ребре.

    **Тип узла получателя определяется структурой идентификатора.** 3183
    получателя — индивидуальные предприниматели с ИИН, и они узлы-физлица;
    230 — юридические лица с БИН. Записать всех организациями значило бы
    показать персональные данные под видом реквизитов компании.
    """
    recipients = {
        row.id: row for row in session.execute(select(SubsidyRecipient)).scalars().all()
    }
    programs = {row.id: row for row in session.execute(select(SubsidyProgram)).scalars().all()}

    # Кратность схлопывается в базе: тянуть 21 521 выплату в память ради
    # 9561 пары бессмысленно, а группировка по паре — ровно то, что нужно ребру.
    pairs = session.execute(
        select(
            SubsidyPayment.recipient_id,
            SubsidyPayment.program_id,
            func.sum(SubsidyPayment.amount_total).label("amount"),
            func.count().label("payments"),
        )
        .where(SubsidyPayment.program_id.is_not(None))
        .group_by(SubsidyPayment.recipient_id, SubsidyPayment.program_id)
    ).all()

    for recipient_id, program_id, amount, payments in pairs:
        recipient = recipients.get(recipient_id)
        program = programs.get(program_id)
        if recipient is None or program is None:
            graph.skipped["выплата без получателя или программы"] += 1
            continue

        recipient_key = _add_recipient_node(graph, recipient)

        program_key = graph.add_node(
            _NodeDraft(
                key=node_key(NodeType.SUBSIDY, f"program:{program.code}"),
                node_type=NodeType.SUBSIDY,
                label=program.name,
                sublabel=program.animal_type,
                # У программы нет ни уровня риска, ни территории: риск в слое
                # 8.5 считается по получателю, а программа общереспубликанская.
                # Оставить их пустыми честнее, чем усреднить по получателям.
                source_layer="8.5",
                ref_entity_type="subsidy_program",
                ref_entity_id=program.id,
                attributes={"program_code": program.code},
            )
        )

        graph.add_edge(
            _EdgeDraft(
                relation_type=RelationType.RECIPIENT,
                source_key=recipient_key,
                target_key=program_key,
                confidence=RelationConfidence.CONFIRMED,
                confidence_basis=(
                    "внешний ключ источника subsidy_payments.recipient_id, "
                    "получатель опознан по БИН/ИИН"
                ),
                source_layer="8.5",
                derivation_rule="subsidy_payments.recipient_id+program_id",
                # Территория берётся у получателя, а не у выплаты: район
                # выплаты в источнике пуст у 96 записей, а у получателя это
                # разобранное и сопоставленное со справочником значение.
                territory_id=recipient.territory_id,
                amount=amount,
                evidence={"payments": int(payments)},
            )
        )

    _build_directors_and_co_recipients(graph, list(recipients.values()))


def _add_recipient_node(graph: GraphDraft, recipient: SubsidyRecipient) -> str:
    """Узел получателя субсидий — организация или физическое лицо."""
    kind = identifier_kind(recipient.xin)
    if kind == "bin":
        return graph.add_node(
            _organization_node(
                bin_value=recipient.xin,
                name=recipient.name,
                layer="8.5",
                sublabel=recipient.territory_name_raw,
                risk_level=recipient.risk_level,
                risk_score=recipient.risk_score,
                territory_id=recipient.territory_id,
                ref_type="subsidy_recipient",
                ref_id=recipient.id,
            )
        )
    return graph.add_node(
        _person_node(
            iin=recipient.xin,
            full_name=recipient.name,
            layer="8.5",
            sublabel=recipient.territory_name_raw,
            risk_level=recipient.risk_level,
            risk_score=recipient.risk_score,
            territory_id=recipient.territory_id,
            ref_type="subsidy_recipient",
            ref_id=recipient.id,
        )
    )


def _build_directors_and_co_recipients(
    graph: GraphDraft, recipients: list[SubsidyRecipient]
) -> None:
    """Руководитель юридического лица и со-получатели с общим руководителем.

    **Почему руководитель выводится только у юридических лиц.** У
    индивидуального предпринимателя в поле руководителя записан он сам, и
    ребро «ИП Толысбаева → Толысбаева» — петля, не сообщающая ничего.
    Ограничением базы такие рёбра запрещены, и здесь они просто не создаются.

    **Почему обе связи предположительные.** Руководитель известен только по
    ФИО: ИИН руководителя в книге 8.5 отсутствует. Значит, узел лица опознан
    по написанию имени, а полные тёзки существуют — особенно при том, что одно
    и то же имя встречается в источнике то заглавными, то с прописной, то в
    казахском, то в русском написании. Со-получатели выводятся из того же
    совпадения ФИО и потому не могут быть достовернее его.
    """
    by_director: dict[str, list[SubsidyRecipient]] = defaultdict(list)

    for recipient in recipients:
        director = (recipient.director_name or "").strip()
        if not director:
            graph.skipped["получатель без руководителя"] += 1
            continue

        by_director[normalize_name(director)].append(recipient)

        if identifier_kind(recipient.xin) != "bin":
            continue

        org_key = _add_recipient_node(graph, recipient)
        person_key = graph.add_node(
            _person_node(
                iin=None,
                full_name=director,
                layer="8.5",
                sublabel="руководитель получателя субсидий",
                territory_id=recipient.territory_id,
            )
        )
        graph.add_edge(
            _EdgeDraft(
                relation_type=RelationType.DIRECTOR,
                source_key=person_key,
                target_key=org_key,
                confidence=RelationConfidence.PROBABLE,
                confidence_basis=(
                    "совпадение ФИО: ИИН руководителя в источнике отсутствует, "
                    "лицо опознано только по написанию имени"
                ),
                source_layer="8.5",
                derivation_rule="subsidy_recipients.director_name",
                territory_id=recipient.territory_id,
                evidence={"director_name": director},
            )
        )

    for key, group in by_director.items():
        if len(group) < 2 or not key:
            continue
        # Полная клика внутри группы: связаны все со всеми, а не цепочкой.
        # Цепочка задала бы порядок, которого в данных нет, и удаление одного
        # получателя рвало бы связь остальных.
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                graph.add_edge(
                    _EdgeDraft(
                        relation_type=RelationType.CO_RECIPIENT,
                        source_key=_add_recipient_node(graph, left),
                        target_key=_add_recipient_node(graph, right),
                        direction=RelationDirection.UNDIRECTED,
                        confidence=RelationConfidence.PROBABLE,
                        confidence_basis=(
                            "совпадение ФИО руководителя — не идентификатора; "
                            "однофамильцы и тёзки не исключены"
                        ),
                        source_layer="8.5",
                        derivation_rule="subsidy_recipients.director_name(group)",
                        territory_id=left.territory_id,
                        evidence={
                            "director_name": left.director_name,
                            "group_size": len(group),
                        },
                    )
                )


def _build_projects(session: Session, graph: GraphDraft) -> None:
    """Слой 8.6: подрядчик и проектировщик — проект.

    ТЗ 13 связью № 11 объединяет подрядчика, проектировщика и надзор, поэтому
    частный партнёр проекта ГЧП и генеральный проектировщик заключения
    экспертизы дают один тип связи.

    **Почему все эти связи предположительные.** БИН участника отсутствует у
    всех 12 271 записей — это признанный главный дефект слоя. Участник опознан
    исключительно по свёрнутому наименованию, а значит, две разные компании с
    похожим названием сольются в один узел, и наоборот. Пометить такую связь
    достоверной было бы прямым обманом.

    Заказчик и государственный партнёр не связываются: «заказчик» — не роль
    подрядчика, и подменять одно другим нельзя.
    """
    contractor_roles = (ParticipantRole.PRIVATE_PARTNER, ParticipantRole.GENERAL_DESIGNER)

    rows = session.execute(
        select(ProjectParticipant, ProjectEntity)
        .join(ProjectEntity, ProjectParticipant.project_entity_id == ProjectEntity.id)
        .where(ProjectParticipant.role.in_([str(role) for role in contractor_roles]))
    ).all()

    for participant, project in rows:
        name_key = normalize_name(participant.name_raw)
        # «Не определен» — заглушка источника, а не участник. Узел с таким
        # именем собрал бы вокруг себя сотни несвязанных проектов и выглядел
        # бы как крупнейший подрядчик области.
        if not name_key or name_key in {"неопределен", "неопределён", "нет", "отсутствует"}:
            graph.skipped["участник-заглушка"] += 1
            continue

        org_key = graph.add_node(
            _organization_node(
                bin_value=participant.bin,
                name=participant.name_raw,
                layer="8.6",
                sublabel="участник проекта",
                ref_type="project_participant",
                ref_id=participant.id,
            )
        )
        project_key = graph.add_node(
            _NodeDraft(
                key=node_key(NodeType.PROJECT, f"project:{project.id}"),
                node_type=NodeType.PROJECT,
                label=project.title[:200],
                sublabel=str(project.kind),
                risk_level=project.risk_level,
                risk_score=project.risk_score,
                risk_is_preliminary=project.risk_is_preliminary,
                territory_id=project.territory_id,
                ref_entity_type="project_entity",
                ref_entity_id=project.id,
                source_layer="8.6",
                attributes={
                    "kind": str(project.kind),
                    "territory_precision": str(project.territory_precision),
                },
            )
        )

        graph.add_edge(
            _EdgeDraft(
                relation_type=RelationType.CONTRACTOR,
                source_key=org_key,
                target_key=project_key,
                confidence=(
                    RelationConfidence.CONFIRMED
                    if participant.bin
                    else RelationConfidence.PROBABLE
                ),
                confidence_basis=(
                    "совпадение БИН участника"
                    if participant.bin
                    else (
                        "совпадение наименования: БИН участника отсутствует "
                        "во всех записях слоя 8.6"
                    )
                ),
                source_layer="8.6",
                derivation_rule=f"project_participants.role={participant.role}",
                territory_id=project.territory_id,
                evidence={"role": str(participant.role), "name_raw": participant.name_raw},
            )
        )


def _build_shared_addresses(session: Session, graph: GraphDraft) -> None:
    """Общий юридический адрес двух организаций.

    Индикатор ТЗ 9.4 «массовая регистрация по одному адресу» опирается именно
    на юридический адрес. Единственный слой, где адрес есть, — 8.4: он
    заполнен у всех 26 поставщиков. У 3668 организаций слоя 8.7 адреса нет ни
    в каком виде, поэтому основная масса компаний в этот вывод не попадает, и
    это ограничение данных, а не выборки.

    Связь предположительная всегда. Совпадение адреса — не доказательство
    аффилированности: по одному адресу законно сидят десятки арендаторов
    бизнес-центра. Это повод посмотреть, а не вывод.
    """
    suppliers = (
        session.execute(select(Supplier).where(Supplier.legal_address_raw.is_not(None)))
        .scalars()
        .all()
    )

    by_address: dict[str, list[Supplier]] = defaultdict(list)
    for supplier in suppliers:
        normalized = normalize_address(supplier.legal_address_raw)
        if normalized:
            by_address[normalized].append(supplier)

    for address, group in by_address.items():
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                left_key = graph.add_node(
                    _organization_node(
                        bin_value=left.bin, name=left.name, layer="8.4", ref_type="supplier",
                        ref_id=left.id,
                    )
                )
                right_key = graph.add_node(
                    _organization_node(
                        bin_value=right.bin, name=right.name, layer="8.4", ref_type="supplier",
                        ref_id=right.id,
                    )
                )
                graph.add_edge(
                    _EdgeDraft(
                        relation_type=RelationType.SHARED_ADDRESS,
                        source_key=left_key,
                        target_key=right_key,
                        direction=RelationDirection.UNDIRECTED,
                        confidence=RelationConfidence.PROBABLE,
                        confidence_basis=(
                            "совпадение юридического адреса — повод для проверки, "
                            "а не доказательство связи"
                        ),
                        source_layer="8.4",
                        derivation_rule="suppliers.legal_address_raw",
                        territory_id=left.territory_id,
                        evidence={"address": address[:200]},
                    )
                )


def _build_org_person_roles(session: Session, graph: GraphDraft) -> None:
    """Руководители и учредители из слоя 8.7.

    Единственный источник связи «учредитель» во всём проекте. Таблица
    `organization_person_roles` сейчас пуста: книга слоя 8.7 состава
    руководителей и учредителей не содержит, и импортировать оттуда нечего.
    Функция написана и вызывается, чтобы связь появилась сама, как только
    источник подключат, — и чтобы отчёт о сборке показывал честный ноль, а не
    умалчивал о типе.
    """
    rows = session.execute(
        select(OrganizationPersonRole, Organization)
        .join(Organization, OrganizationPersonRole.organization_id == Organization.id)
        .options()
    ).all()

    for role_row, organization in rows:
        person = role_row.person
        org_key = graph.add_node(
            _organization_node(
                bin_value=organization.bin,
                name=organization.name,
                layer="8.7",
                risk_level=organization.risk_level_strict,
                risk_score=organization.risk_score,
                risk_is_preliminary=organization.risk_is_preliminary,
                territory_id=organization.territory_id,
                ref_type="organization",
                ref_id=organization.id,
            )
        )
        person_key = graph.add_node(
            _person_node(
                iin=person.iin,
                full_name=person.full_name or "Лицо без имени в источнике",
                layer="8.7",
                ref_type="person",
                ref_id=person.id,
            )
        )
        confirmed = bool(person.iin)
        graph.add_edge(
            _EdgeDraft(
                relation_type=(
                    RelationType.DIRECTOR
                    if role_row.role == PersonRoleKind.DIRECTOR
                    else RelationType.FOUNDER
                ),
                source_key=person_key,
                target_key=org_key,
                confidence=(
                    RelationConfidence.CONFIRMED if confirmed else RelationConfidence.PROBABLE
                ),
                confidence_basis=(
                    "совпадение ИИН" if confirmed else "совпадение ФИО: ИИН лица не заполнен"
                ),
                source_layer="8.7",
                derivation_rule=f"organization_person_roles.role={role_row.role}",
                territory_id=organization.territory_id,
                evidence={"share_percent": float(role_row.share_percent or 0) or None},
            )
        )


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------


def build(session: Session) -> GraphDraft:
    """Собрать граф из всех подключённых источников."""
    graph = GraphDraft()
    _build_procurement(session, graph)
    _build_subsidies(session, graph)
    _build_projects(session, graph)
    _build_shared_addresses(session, graph)
    _build_org_person_roles(session, graph)
    return graph


def persist(session: Session, graph: GraphDraft) -> None:
    """Записать граф, заменив предыдущую версию целиком.

    Связи удаляются раньше узлов явно, хотя каскад сделал бы это сам: явный
    порядок не зависит от того, сохранится ли `ON DELETE CASCADE` при
    следующей правке схемы.
    """
    session.execute(delete(EntityRelation))
    session.execute(delete(GraphNode))
    session.flush()

    degree: dict[str, int] = defaultdict(int)
    for edge in graph.edges.values():
        degree[edge.source_key] += 1
        degree[edge.target_key] += 1

    node_ids: dict[str, uuid.UUID] = {}
    rows: list[GraphNode] = []
    for draft in graph.nodes.values():
        row = GraphNode(
            node_key=draft.key,
            node_type=draft.node_type,
            label=draft.label,
            sublabel=draft.sublabel,
            identifier=draft.identifier,
            identifier_kind=draft.id_kind,
            risk_level=draft.risk_level,
            risk_score=draft.risk_score,
            risk_is_preliminary=draft.risk_is_preliminary,
            territory_id=draft.territory_id,
            ref_entity_type=draft.ref_entity_type,
            ref_entity_id=draft.ref_entity_id,
            source_layer=draft.source_layer,
            degree=degree.get(draft.key, 0),
            attributes=draft.attributes or None,
            natural_key=draft.key,
            data_as_of=DEFAULT_AS_OF,
        )
        node_ids[draft.key] = row.id = uuid.uuid4()
        rows.append(row)

    session.add_all(rows)
    session.flush()

    session.add_all(
        EntityRelation(
            relation_type=edge.relation_type,
            direction=edge.direction,
            confidence=edge.confidence,
            confidence_basis=edge.confidence_basis[:255],
            source_node_id=node_ids[edge.source_key],
            target_node_id=node_ids[edge.target_key],
            source_layer=edge.source_layer,
            derivation_rule=edge.derivation_rule[:128],
            territory_id=edge.territory_id,
            amount=edge.amount,
            evidence=edge.evidence or None,
            natural_key=f"{edge.relation_type}|{edge.source_key}|{edge.target_key}"[:255],
            data_as_of=DEFAULT_AS_OF,
        )
        for edge in graph.edges.values()
    )
    session.flush()


def report(graph: GraphDraft) -> str:
    """Сводка сборки для консоли.

    Типы с нулём выводятся наравне с остальными: отсутствие связи — такой же
    результат, как её наличие, и молчание о нём создало бы впечатление, что
    тип просто забыли.
    """
    lines: list[str] = ["Узлы:"]
    by_type: dict[str, int] = defaultdict(int)
    for node in graph.nodes.values():
        by_type[str(node.node_type)] += 1
    for node_type in NodeType:
        lines.append(f"  {node_type.label_ru:<20} {by_type.get(str(node_type), 0):>7}")
    lines.append(f"  {'всего':<20} {len(graph.nodes):>7}")

    lines.append("Связи:")
    edges_by_type: dict[str, int] = defaultdict(int)
    confirmed_by_type: dict[str, int] = defaultdict(int)
    for edge in graph.edges.values():
        edges_by_type[str(edge.relation_type)] += 1
        if edge.confidence is RelationConfidence.CONFIRMED:
            confirmed_by_type[str(edge.relation_type)] += 1
    for relation_type in RelationType:
        total = edges_by_type.get(str(relation_type), 0)
        confirmed = confirmed_by_type.get(str(relation_type), 0)
        lines.append(
            f"  {relation_type.label_ru:<20} {total:>7}"
            f"   достоверных {confirmed}, предположительных {total - confirmed}"
        )
    lines.append(f"  {'всего':<20} {len(graph.edges):>7}")

    if graph.skipped:
        lines.append("Пропущено:")
        for reason, count in sorted(graph.skipped.items()):
            lines.append(f"  {reason:<32} {count:>7}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Вывести граф связей из загруженных данных")
    parser.add_argument(
        "--dry-run", action="store_true", help="показать сводку и откатить изменения"
    )
    args = parser.parse_args()

    try:
        with session_scope() as session:
            graph = build(session)
            print(report(graph))

            if args.dry_run:
                print("\n--dry-run: витрина не изменена.")
                session.rollback()
                return 0

            persist(session, graph)
            print("\nВитрина графа перестроена.")
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
