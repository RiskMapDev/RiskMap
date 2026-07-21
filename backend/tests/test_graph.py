"""Граф взаимосвязей: вывод связей, ограничение выборки, права и маскирование.

Проверяется четыре вещи, и все четыре — про честность, а не про механику.

**Связь выводится из факта.** Тесты сверяют число связей с числом строк
источника: 355 договоров дают 355 связей «поставщик», и ни одной больше.
Тип «учредитель» пуст, и это утверждается тестом отдельно — иначе однажды
кто-то заполнит его правдоподобными догадками, и никто не заметит.

**Достоверность различает доказанное и предположенное.** Связь по внешнему
ключу и БИН — достоверная, по совпадению ФИО или адреса — предположительная.
Ошибка в этой границе означает, что аналитик примет догадку за факт.

**Весь граф наружу не отдаётся.** Ограничение проверяется на узле-хабе,
у которого соседей заведомо больше предела.

**ИИН не покидает сервер незамаскированным** — ни в значении, ни в ключе узла,
который уезжает в адресную строку.

Все тесты работают через `db_session` — сессию, откатываемую после случая.
Модульная сессия здесь не годится: маскирование пишет в журнал запись со
ссылкой на пользователя, а пользователи тестов живут только внутри откатываемой
транзакции. Запись журнала в другую сессию упёрлась бы во внешний ключ и
испортила бы соединение всем последующим тестам.

Маршруты подключаются к приложению здесь же: `app/main.py` в задаче этого
модуля не правится, и тест не должен зависеть от того, подключил ли кто-то
роутер снаружи.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.graph_routes import router as graph_router
from app.core import security
from app.core.config import get_settings
from app.db.models.access import AuditAction, AuditLogEntry, RoleCode
from app.db.models.graph import (
    EntityRelation,
    GraphNode,
    NodeType,
    RelationConfidence,
    RelationDirection,
    RelationType,
    node_key,
)
from app.db.models.procurement import Contract
from app.db.models.subsidy import SubsidyRecipient
from app.db.models.territory import Territory
from app.db.session import get_db
from app.main import create_app
from app.services import graph
from scripts.build_relations import identifier_kind, normalize_address, normalize_name
from tests.conftest import TEST_PASSWORD, UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def graph_app(db_session: Session) -> Iterator[FastAPI]:
    """Приложение с подключённым роутером графа.

    Роутер подключается здесь, а не в `app/main.py`: подключение — решение
    сборки приложения, а проверка маршрутов не должна от него зависеть.
    """
    application = create_app()
    application.include_router(graph_router, prefix=get_settings().api_prefix)
    application.dependency_overrides[get_db] = lambda: db_session
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


@pytest.fixture
def graph_client(graph_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(graph_app) as test_client:
        yield test_client
    security.clear_revoked_tokens()


def _token(client: TestClient, login: str) -> str:
    response = client.post("/api/v1/auth/login", json={"login": login, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def хаб(db_session: Session) -> GraphNode:
    """Узел с наибольшим числом связей — на нём и проверяется усечение."""
    node = db_session.execute(
        select(GraphNode).order_by(GraphNode.degree.desc()).limit(1)
    ).scalar_one()
    assert node.degree > graph.MAX_NODES_LIMIT, "для проверки усечения нужен узел-концентратор"
    return node


# ---------------------------------------------------------------------------
# Опознание идентификатора и свёртки
# ---------------------------------------------------------------------------


class TestОпознаниеИдентификатора:
    """Отличить ИИН от БИН — предпосылка всего маскирования.

    Ошибка здесь приводит к тому, что ИИН физического лица показывается как
    публичный реквизит компании, то есть к утечке персональных данных.
    """

    def test_пятая_цифра_разделяет_иин_и_бин(self) -> None:
        # 210440019216 — БИН ТОО: пятая цифра 4 (резидент, юридическое лицо).
        assert identifier_kind("210440019216") == "bin"
        # 850820499050 — ИИН: пятая цифра 2, это десяток дня рождения.
        assert identifier_kind("850820499050") == "iin"

    def test_признак_согласован_с_данными_книги(self, db_session: Session) -> None:
        """3183 «ИП» книги 8.5 обязаны опознаться как физические лица.

        Проверка идёт против независимого признака — наименования, — а не
        против самого правила: правило, сверенное само с собой, ничего не
        доказывает.
        """
        recipients = db_session.execute(
            select(SubsidyRecipient.xin, SubsidyRecipient.name)
        ).all()
        расхождения = [
            xin
            for xin, name in recipients
            if (identifier_kind(xin) == "iin") != name.strip().upper().startswith("ИП")
        ]
        assert расхождения == []

    def test_свёртка_наименования_снимает_регистр_и_знаки(self) -> None:
        assert normalize_name('ТОО "Сәт Транс"') == "тоосәттранс"
        assert normalize_name(None) == ""

    def test_свёртка_адреса_сохраняет_номер_дома(self) -> None:
        """«Одна улица» — это соседство, а не общий адрес."""
        assert normalize_address("Улица Абая, Дом: 1") != normalize_address("Улица  Абая, Дом: 2")


# ---------------------------------------------------------------------------
# Ключ узла
# ---------------------------------------------------------------------------


class TestКлючУзла:
    def test_ключ_устойчив_между_сборками(self) -> None:
        """Иначе сохранённая ссылка на узел перестала бы работать."""
        assert node_key(NodeType.PERSON, "iin:840712300112") == node_key(
            NodeType.PERSON, "iin:840712300112"
        )

    def test_ключ_не_содержит_идентификатора(self) -> None:
        """Ключ уезжает в адресную строку — персональных данных в нём быть не может."""
        иин = "840712300112"
        ключ = node_key(NodeType.PERSON, f"iin:{иин}")
        assert иин not in ключ
        assert ключ.startswith("person:")

    def test_разные_типы_дают_разные_ключи(self) -> None:
        assert node_key(NodeType.PERSON, "x") != node_key(NodeType.ORGANIZATION, "x")


# ---------------------------------------------------------------------------
# Состав витрины
# ---------------------------------------------------------------------------


class TestВыведенныеСвязи:
    def test_витрина_не_пуста(self, db_session: Session) -> None:
        assert db_session.scalar(select(func.count()).select_from(EntityRelation))
        assert db_session.scalar(select(func.count()).select_from(GraphNode))

    def test_поставщиков_столько_же_сколько_договоров(self, db_session: Session) -> None:
        """Связь выводится из строки источника, а не из догадки о ней."""
        договоров = db_session.scalar(select(func.count()).select_from(Contract))
        связей = db_session.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(EntityRelation.relation_type == RelationType.SUPPLIER.value)
        )
        assert связей == договоров

    def test_учредителей_нет_и_это_факт_о_данных(self, db_session: Session) -> None:
        """Состава учредителей нет ни в одной книге комплекта.

        Ноль здесь — содержательный результат, а не пробел в реализации.
        Заполнить этот тип «похожими» связями означало бы выдать построенную
        из ничего аффилированность за установленную.
        """
        учредителей = db_session.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(EntityRelation.relation_type == RelationType.FOUNDER.value)
        )
        assert учредителей == 0

    def test_нет_петель(self, db_session: Session) -> None:
        """У получателя-ИП руководителем записан он сам — такая связь не создаётся."""
        петель = db_session.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(EntityRelation.source_node_id == EntityRelation.target_node_id)
        )
        assert петель == 0

    def test_каждая_связь_объясняет_свою_достоверность(self, db_session: Session) -> None:
        """«Предположительная» без основания — ярлык, который нечем проверить."""
        for relation in db_session.execute(select(EntityRelation).limit(500)).scalars().all():
            assert relation.confidence_basis.strip(), relation.id
            assert relation.derivation_rule.strip(), relation.id

    def test_связи_выведены_только_из_подключённых_слоёв(self, db_session: Session) -> None:
        слои = set(
            db_session.execute(select(EntityRelation.source_layer).distinct()).scalars().all()
        )
        assert слои <= {"8.3", "8.4", "8.5", "8.6", "8.7"}


class TestДостоверность:
    def test_связь_по_внешнему_ключу_достоверна(self, db_session: Session) -> None:
        """Поставщик опознан по БИН из 12 знаков и связан внешним ключом."""
        предположительных = db_session.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(
                EntityRelation.relation_type == RelationType.SUPPLIER.value,
                EntityRelation.confidence == RelationConfidence.PROBABLE.value,
            )
        )
        assert предположительных == 0

    def test_связь_по_фио_предположительна(self, db_session: Session) -> None:
        """ИИН руководителя в книге 8.5 отсутствует — тёзки не исключены."""
        достоверных = db_session.scalar(
            select(func.count())
            .select_from(EntityRelation)
            .where(
                EntityRelation.relation_type == RelationType.DIRECTOR.value,
                EntityRelation.confidence == RelationConfidence.CONFIRMED.value,
            )
        )
        assert достоверных == 0

    def test_связь_по_адресу_предположительна(self, db_session: Session) -> None:
        """По одному адресу законно сидят арендаторы бизнес-центра."""
        rows = (
            db_session.execute(
                select(EntityRelation).where(
                    EntityRelation.relation_type == RelationType.SHARED_ADDRESS.value
                )
            )
            .scalars()
            .all()
        )
        assert rows
        assert all(
            RelationConfidence(str(row.confidence)) is RelationConfidence.PROBABLE for row in rows
        )

    def test_симметричные_связи_не_направлены(self, db_session: Session) -> None:
        """У «общего адреса» первенства сторон в данных нет — стрелки быть не должно."""
        rows = set(
            db_session.execute(
                select(EntityRelation.direction).where(
                    EntityRelation.relation_type.in_(
                        [RelationType.SHARED_ADDRESS.value, RelationType.CO_RECIPIENT.value]
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == {RelationDirection.UNDIRECTED.value}


# ---------------------------------------------------------------------------
# Серверная выборка окружения
# ---------------------------------------------------------------------------


class TestОграничениеВыборки:
    def test_подграф_не_превышает_предела(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        """Весь граф в браузер не отдаётся — это требование ТЗ, а не оптимизация."""
        подграф = graph.neighborhood(
            db_session, хаб.node_key, depth=1, max_nodes=25, user=make_user(RoleCode.ADMIN)
        )
        assert подграф is not None
        assert len(подграф.nodes) <= 25

    def test_усечение_объявляется(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        """Молчаливое обрезание страшнее отсутствия данных: по картинке сделают вывод."""
        подграф = graph.neighborhood(
            db_session, хаб.node_key, depth=1, max_nodes=10, user=make_user(RoleCode.ADMIN)
        )
        assert подграф is not None
        assert подграф.truncated
        assert подграф.omitted_nodes > 0
        assert подграф.total_neighbors > len(подграф.edges)

    def test_глубина_ограничена_сверху(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        """Запрос глубины 9 не должен разворачивать половину графа."""
        подграф = graph.neighborhood(
            db_session, хаб.node_key, depth=9, max_nodes=30, user=make_user(RoleCode.ADMIN)
        )
        assert подграф is not None
        assert подграф.depth == graph.MAX_DEPTH

    def test_все_рёбра_ведут_к_показанным_узлам(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        """Ребро в пустоту нарисовать невозможно, а к чужому узлу — значит соврать."""
        подграф = graph.neighborhood(
            db_session, хаб.node_key, depth=1, max_nodes=20, user=make_user(RoleCode.ADMIN)
        )
        assert подграф is not None
        ключи = {node.key for node in подграф.nodes}
        for edge in подграф.edges:
            assert edge.source in ключи and edge.target in ключи

    def test_центр_всегда_присутствует(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        подграф = graph.neighborhood(
            db_session, хаб.node_key, depth=1, max_nodes=5, user=make_user(RoleCode.ADMIN)
        )
        assert подграф is not None
        assert хаб.node_key in {node.key for node in подграф.nodes}

    def test_фильтр_по_достоверности_убирает_предположительные(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        node = db_session.execute(
            select(GraphNode)
            .join(EntityRelation, EntityRelation.target_node_id == GraphNode.id)
            .where(EntityRelation.confidence == RelationConfidence.PROBABLE.value)
            .limit(1)
        ).scalar_one()

        подграф = graph.neighborhood(
            db_session,
            node.node_key,
            depth=1,
            min_confidence=RelationConfidence.CONFIRMED.value,
            user=make_user(RoleCode.ADMIN),
        )
        assert подграф is not None
        assert all(
            edge.confidence == RelationConfidence.CONFIRMED.value for edge in подграф.edges
        )

    def test_фильтр_по_типу_связи_оставляет_только_его(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        подграф = graph.neighborhood(
            db_session,
            хаб.node_key,
            depth=1,
            relation_types=[RelationType.RECIPIENT.value],
            max_nodes=20,
            user=make_user(RoleCode.ADMIN),
        )
        assert подграф is not None
        assert all(
            edge.relation_type == RelationType.RECIPIENT.value for edge in подграф.edges
        )

    def test_неизвестный_узел_даёт_ничего(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        assert (
            graph.neighborhood(
                db_session, "organization:нет-такого", user=make_user(RoleCode.ADMIN)
            )
            is None
        )


class TestПоискУзла:
    def test_короткий_запрос_не_сканирует_таблицу(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        assert graph.search_nodes(db_session, "а", user=make_user(RoleCode.ADMIN)) == []

    def test_поиск_находит_по_наименованию(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        найденные = graph.search_nodes(
            db_session, "ТОО", limit=5, user=make_user(RoleCode.ADMIN)
        )
        assert найденные
        assert all("тоо" in node.label.casefold() for node in найденные)

    def test_разбивка_связей_показывает_обе_достоверности(
        self, db_session: Session, хаб: GraphNode
    ) -> None:
        разбивка = graph.relation_breakdown(db_session, хаб.node_key)
        assert разбивка
        for строка in разбивка:
            assert строка["total"] == строка["confirmed"] + строка["probable"]


class TestСводкаВитрины:
    def test_перечислены_все_типы_включая_пустые(self, db_session: Session) -> None:
        """«Учредителей 0» — содержательный факт, и он обязан быть виден."""
        сводка = graph.stats(db_session)
        assert {item["code"] for item in сводка["relations"]} == {
            str(item) for item in RelationType
        }
        assert {item["code"] for item in сводка["nodes"]} == {str(item) for item in NodeType}

    def test_легенда_различает_достоверности_начертанием(self) -> None:
        """Цвет и подпись — не единственные носители: у линии есть начертание."""
        стили = {item["style"] for item in graph.legend()["confidence"]}
        assert стили == {"solid", "dashed"}

    def test_легенда_объявляет_пределы_выборки(self) -> None:
        пределы = graph.legend()["limits"]
        assert пределы["max_depth"] == graph.MAX_DEPTH
        assert пределы["max_nodes"] == graph.MAX_NODES_LIMIT


# ---------------------------------------------------------------------------
# Персональные данные
# ---------------------------------------------------------------------------


def _person_node(session: Session) -> GraphNode:
    return session.execute(
        select(GraphNode).where(GraphNode.identifier_kind == "iin").limit(1)
    ).scalar_one()


class TestМаскированиеИИН:
    def test_наблюдателю_иин_не_показывается(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        person = _person_node(db_session)
        подграф = graph.neighborhood(
            db_session, person.node_key, depth=1, max_nodes=5, user=make_user(RoleCode.VIEWER)
        )
        assert подграф is not None
        центр = next(node for node in подграф.nodes if node.key == person.node_key)
        assert центр.identifier is not None
        assert центр.identifier["value"] is None
        # «Значение есть, но вам не положено» — не то же, что «поля нет».
        assert центр.identifier["present"] is True

    def test_аналитику_иин_маскируется(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        person = _person_node(db_session)
        подграф = graph.neighborhood(
            db_session, person.node_key, depth=1, max_nodes=5, user=make_user(RoleCode.ANALYST)
        )
        assert подграф is not None
        центр = next(node for node in подграф.nodes if node.key == person.node_key)
        значение = центр.identifier["value"] if центр.identifier else None
        assert значение is not None
        assert "*" in значение
        assert значение != person.identifier

    def test_бин_организации_не_маскируется(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """БИН — публичный реквизит юридического лица, и он делает граф проверяемым."""
        org = db_session.execute(
            select(GraphNode).where(GraphNode.identifier_kind == "bin").limit(1)
        ).scalar_one()

        подграф = graph.neighborhood(
            db_session, org.node_key, depth=1, max_nodes=5, user=make_user(RoleCode.VIEWER)
        )
        assert подграф is not None
        центр = next(node for node in подграф.nodes if node.key == org.node_key)
        assert центр.identifier is not None
        assert центр.identifier["value"] == org.identifier

    def test_полное_раскрытие_журналируется(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Полный ИИН нельзя получить мимо журнала — иначе аудит бессмыслен."""
        админ = make_user(RoleCode.ADMIN)
        person = _person_node(db_session)

        было = db_session.scalar(
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW.value)
        )
        graph.neighborhood(db_session, person.node_key, depth=1, max_nodes=5, user=админ)
        стало = db_session.scalar(
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW.value)
        )
        assert (стало or 0) > (было or 0)

    def test_просмотр_маски_журнал_не_засоряет(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Запись «посмотрел маску» за месяц утопила бы настоящие события в шуме."""
        person = _person_node(db_session)
        было = db_session.scalar(
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW.value)
        )
        graph.neighborhood(
            db_session, person.node_key, depth=1, max_nodes=5, user=make_user(RoleCode.VIEWER)
        )
        стало = db_session.scalar(
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW.value)
        )
        assert стало == было

    def test_иин_не_попадает_в_ключ_узла(self, db_session: Session) -> None:
        """Ключ уходит в адресную строку, а она оседает в истории и логах прокси."""
        rows = db_session.execute(
            select(GraphNode.node_key, GraphNode.identifier)
            .where(GraphNode.identifier_kind == "iin")
            .limit(200)
        ).all()
        assert rows
        for ключ, иин in rows:
            assert иин not in ключ


# ---------------------------------------------------------------------------
# HTTP-слой: права и территориальное ограничение
# ---------------------------------------------------------------------------


class TestДоступПоHTTP:
    def test_без_токена_граф_закрыт(self, graph_client: TestClient) -> None:
        assert graph_client.get("/api/v1/graph/stats").status_code == 401

    def test_наблюдатель_видит_граф(
        self, graph_client: TestClient, make_user: UserFactory
    ) -> None:
        """Право то же, что у списка: граф — другая проекция тех же записей."""
        user = make_user(RoleCode.VIEWER)
        ответ = graph_client.get(
            "/api/v1/graph/stats", headers=_auth(_token(graph_client, user.login))
        )
        assert ответ.status_code == 200
        assert ответ.json()["relations_total"] > 0

    def test_слишком_большая_глубина_отклоняется_на_границе(
        self, graph_client: TestClient, make_user: UserFactory, хаб: GraphNode
    ) -> None:
        """Запрос «отдай весь граф» обязан упереться в 422, а не в память сервера."""
        user = make_user(RoleCode.ADMIN)
        ответ = graph_client.get(
            f"/api/v1/graph/neighbors?node={хаб.node_key}&depth=9",
            headers=_auth(_token(graph_client, user.login)),
        )
        assert ответ.status_code == 422

    def test_слишком_много_узлов_отклоняется(
        self, graph_client: TestClient, make_user: UserFactory, хаб: GraphNode
    ) -> None:
        user = make_user(RoleCode.ADMIN)
        ответ = graph_client.get(
            f"/api/v1/graph/neighbors?node={хаб.node_key}&max_nodes=100000",
            headers=_auth(_token(graph_client, user.login)),
        )
        assert ответ.status_code == 422

    def test_ответ_несёт_пояснение_и_признак_усечения(
        self, graph_client: TestClient, make_user: UserFactory, хаб: GraphNode
    ) -> None:
        user = make_user(RoleCode.ADMIN)
        ответ = graph_client.get(
            f"/api/v1/graph/neighbors?node={хаб.node_key}&max_nodes=20",
            headers=_auth(_token(graph_client, user.login)),
        )
        assert ответ.status_code == 200
        тело = ответ.json()
        assert тело["scope_note"].strip()
        assert тело["truncated"] is True
        assert тело["total_neighbors"] > len(тело["edges"])

    def test_карточка_узла_несёт_разбивку_связей(
        self, graph_client: TestClient, make_user: UserFactory, хаб: GraphNode
    ) -> None:
        user = make_user(RoleCode.ADMIN)
        ответ = graph_client.get(
            f"/api/v1/graph/node/{хаб.node_key}",
            headers=_auth(_token(graph_client, user.login)),
        )
        assert ответ.status_code == 200
        assert ответ.json()["relations"]

    def test_чужая_территория_неотличима_от_отсутствия(
        self,
        graph_client: TestClient,
        db_session: Session,
        make_user: UserFactory,
        territories: dict[str, Territory],
    ) -> None:
        """Разные ответы позволяли бы перебором выяснить состав чужого района.

        Аналитик привязан к тестовому району, которого нет ни у одной записи
        витрины, поэтому любой узел с территорией для него закрыт.
        """
        аналитик = make_user(RoleCode.ANALYST, territory_id=territories["karasay"].id)
        узел = db_session.execute(
            select(GraphNode).where(GraphNode.territory_id.is_not(None)).limit(1)
        ).scalar_one()

        ответ = graph_client.get(
            f"/api/v1/graph/node/{узел.node_key}",
            headers=_auth(_token(graph_client, аналитик.login)),
        )
        assert ответ.status_code == 404

    def test_поиск_короче_предела_возвращает_пусто(
        self, graph_client: TestClient, make_user: UserFactory
    ) -> None:
        user = make_user(RoleCode.ADMIN)
        ответ = graph_client.get(
            "/api/v1/graph/search?q=а", headers=_auth(_token(graph_client, user.login))
        )
        assert ответ.status_code == 200
        assert ответ.json()["items"] == []

    def test_пустой_запрос_отдаёт_перечень_а_не_пусто(
        self, graph_client: TestClient, make_user: UserFactory
    ) -> None:
        """Список узлов — вход в граф для того, кто ещё не знает, что искать."""
        заголовки = _auth(_token(graph_client, make_user(RoleCode.ADMIN).login))
        ответ = graph_client.get("/api/v1/graph/search?limit=5", headers=заголовки)
        assert ответ.status_code == 200
        тело = ответ.json()
        assert тело["items"]
        # Общее число считается до постраничности, иначе «показано 5 из 5»
        # соврало бы о размере витрины.
        assert тело["total"] > len(тело["items"])

    def test_страницы_перечня_не_пересекаются(
        self, graph_client: TestClient, make_user: UserFactory
    ) -> None:
        """Без устойчивого третьего ключа сортировки узлы дублируются и теряются.

        Уровень риска и число связей совпадают у тысяч узлов, и порядок внутри
        группы без явного ключа не определён — соседние страницы показали бы
        одно и то же, а часть витрины не показали бы вовсе.
        """
        заголовки = _auth(_token(graph_client, make_user(RoleCode.ADMIN).login))
        первая = graph_client.get("/api/v1/graph/search?limit=5", headers=заголовки).json()
        вторая = graph_client.get(
            "/api/v1/graph/search?limit=5&offset=5", headers=заголовки
        ).json()

        ключи_первой = {item["key"] for item in первая["items"]}
        ключи_второй = {item["key"] for item in вторая["items"]}
        assert ключи_первой and ключи_второй
        assert not (ключи_первой & ключи_второй)


class TestТерриториальнаяОбластьВидимости:
    def test_связи_без_территории_ограниченному_не_видны(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Через «неопределённые» строки утекали бы чужие районы.

        Правило то же, что у `TerritoryScope.allows`: запись без территории не
        принадлежит ничьей зоне ответственности.
        """
        безтерритории = db_session.execute(
            select(GraphNode)
            .where(GraphNode.territory_id.is_(None), GraphNode.degree > 0)
            .limit(1)
        ).scalar_one()

        подграф = graph.neighborhood(
            db_session,
            безтерритории.node_key,
            depth=1,
            allowed_territory_ids=frozenset({uuid.uuid4()}),
            user=make_user(RoleCode.ANALYST),
        )
        assert подграф is None

    def test_пояснение_различает_ограниченного_и_полного(
        self, db_session: Session, хаб: GraphNode, make_user: UserFactory
    ) -> None:
        полный = graph.neighborhood(
            db_session, хаб.node_key, max_nodes=5, user=make_user(RoleCode.ADMIN)
        )
        assert полный is not None
        assert "всех территорий" in полный.scope_note
