"""Каталог тематических слоёв карты.

Карта иерархическая: республика → область → район → объект. Но данные,
которыми мы располагаем, живут на разных уровнях этой иерархии, и притворяться,
что все слои доступны везде, нельзя.

    слой 8.3 бюджет          — только уровень области, 20 регионов республики
    слой 8.4 закупки         — районы Алматинской области
    слой 8.5 субсидии        — районы Алматинской области
    слой 8.6 ГЧП             — только область: районной привязки в источнике нет
    слой 8.6 экспертиза      — районы
    слой 8.7 организации     — территориальной привязки нет вообще

Отсюда правило: слой объявляет уровни, на которых он существует. Если слой на
текущем уровне карты не имеет данных, интерфейс говорит об этом прямо —
«нет данных на этом уровне», — а не показывает пустую заливку, неотличимую от
нулевого риска.

Слой 8.7 не выводится на карту вовсе, и это не недоработка: в книге нет ни
района, ни адреса, ни координат, ни КАТО. Организации доступны в списке,
карточке и графе связей. Придумать им координаты означало бы поместить
3668 объектов в точки, которых источник не знает.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.db.models.territory import TerritoryLevel


class LayerRenderKind(StrEnum):
    """Как слой рисуется на карте."""

    CHOROPLETH = "choropleth"
    """Заливка полигонов территорий по значению показателя."""

    POINTS = "points"
    """Точечные объекты, при сгущении — серверная кластеризация."""

    NONE = "none"
    """Слой не выводится на карту: у данных нет географии."""


@dataclass(frozen=True, slots=True)
class ThematicLayer:
    """Описание одного тематического слоя."""

    code: str
    title: str
    description: str
    render: LayerRenderKind

    levels: frozenset[TerritoryLevel]
    """Уровни, на которых у слоя есть данные. Пустое множество — слоя нет на карте."""

    source_layer: str | None = None
    """Код слоя по ТЗ: 8.1, 8.3 … 8.7."""

    enabled_by_default: bool = False
    coverage_note: str = ""
    """Чем ограничено покрытие. Показывается пользователю, а не прячется в код."""

    def available_at(self, level: TerritoryLevel) -> bool:
        return level in self.levels

    def unavailability_reason(self, level: TerritoryLevel) -> str:
        """Почему слоя нет на этом уровне — текст для интерфейса."""
        if self.available_at(level):
            return ""
        if not self.levels:
            return self.coverage_note or "у данных слоя нет географической привязки"
        available = ", ".join(sorted(_LEVEL_LABELS[lvl] for lvl in self.levels))
        return f"данные слоя есть только на уровне: {available}"


_LEVEL_LABELS: dict[TerritoryLevel, str] = {
    TerritoryLevel.COUNTRY: "республика",
    TerritoryLevel.REGION: "область",
    TerritoryLevel.DISTRICT: "район",
    TerritoryLevel.CITY: "город",
    TerritoryLevel.RURAL_OKRUG: "сельский округ",
    TerritoryLevel.SETTLEMENT: "населённый пункт",
}

_REGION = frozenset({TerritoryLevel.REGION})
_DISTRICT = frozenset({TerritoryLevel.DISTRICT, TerritoryLevel.CITY})
_REGION_AND_DISTRICT = _REGION | _DISTRICT


LAYERS: tuple[ThematicLayer, ...] = (
    ThematicLayer(
        code="administrative",
        title="Административно-территориальный",
        description="Границы областей, районов и городов областного значения.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_REGION_AND_DISTRICT,
        source_layer="8.1",
        enabled_by_default=True,
        coverage_note=(
            "Границы из OpenStreetMap, ODbL. Районный уровень выгружен для "
            "Алматинской области; по остальным регионам доступен только "
            "областной контур."
        ),
    ),
    ThematicLayer(
        code="population",
        title="Социально-экономический",
        description="Численность населения: всего, по полу, город и село.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_REGION_AND_DISTRICT,
        source_layer="8.1",
        enabled_by_default=True,
        coverage_note=(
            "Данные на 1 апреля 2026 года по Алматинской области: 11 единиц "
            "второго уровня. По другим регионам разбивки нет."
        ),
    ),
    ThematicLayer(
        code="budget",
        title="Бюджетный",
        description="Риски исполнения бюджета: недобор доходов, недоисполнение расходов.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_REGION,
        source_layer="8.3",
        enabled_by_default=True,
        coverage_note=(
            "Слой общереспубликанский: 20 регионов, помесячно. Разбивки по "
            "районам в источнике нет, поэтому на районном уровне слой пуст."
        ),
    ),
    ThematicLayer(
        code="procurement",
        title="Государственные закупки",
        description="Риски по договорам: единственный источник, дробление, расторжения.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_DISTRICT,
        source_layer="8.4",
        coverage_note=(
            "355 договоров 26 поставщиков по Алматинской области. Это не "
            "сплошная выборка всех закупок региона, а целевой срез: выводы по "
            "нему нельзя распространять на регион целиком."
        ),
    ),
    ThematicLayer(
        code="subsidies",
        title="Субсидии и господдержка",
        description="Риски получателей субсидий: концентрация, повторность, аффилированность.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_DISTRICT,
        source_layer="8.5",
        coverage_note=(
            "21 521 выплата, 3 413 получателей. На карту попадают 1 944: "
            "у 66 район не указан, а ещё 1 403 отнесены к районам Жетысуской "
            "области, выделенной из Алматинской в 2022 году. В справочнике "
            "текущего деления таких районов нет, поэтому на карте Алматинской "
            "области им не место. Все они видны в режиме «Списком»."
        ),
    ),
    ThematicLayer(
        code="infrastructure_ppp",
        title="Инфраструктура — проекты ГЧП",
        description="Риски проектов государственно-частного партнёрства.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_REGION,
        source_layer="8.6",
        coverage_note=(
            "У проектов ГЧП в источнике указана только область, без района. "
            "На районный уровень слой не выводится, чтобы не приписывать "
            "проекты территориям, которых источник не называет."
        ),
    ),
    ThematicLayer(
        code="infrastructure_expertise",
        title="Инфраструктура — объекты строительной экспертизы",
        description="Риски по заключениям экспертизы: корректировки ПСД, повторные заключения.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_DISTRICT,
        source_layer="8.6",
        coverage_note=(
            "Единица учёта — заключение экспертизы, а не объект: у одного "
            "объекта бывает несколько заключений. Проекты ГЧП и объекты "
            "экспертизы — разные совокупности без общего ключа."
        ),
    ),
    ThematicLayer(
        code="organizations",
        title="Хозяйствующие субъекты",
        description="Профили организаций и предварительная оценка риска.",
        render=LayerRenderKind.NONE,
        levels=frozenset(),
        source_layer="8.7",
        coverage_note=(
            "В источнике нет ни района, ни адреса, ни координат, ни КАТО — "
            "поэтому организации не выводятся на карту. Они доступны в списке, "
            "карточке и графе связей. Обеспеченность источниками 41 %: "
            "работают 4 индикатора из 13, поэтому уровень почти у всех серый, "
            "а балл показывается как предварительный."
        ),
    ),
    ThematicLayer(
        code="risk_summary",
        title="Сводный риск",
        description="Максимальный уровень риска территории по всем доступным слоям.",
        render=LayerRenderKind.CHOROPLETH,
        levels=_REGION_AND_DISTRICT,
        coverage_note=(
            "Сводка считается только по слоям, доступным на данном уровне. "
            "Территория без измеренных слоёв получает серый уровень, а не низкий."
        ),
    ),
    ThematicLayer(
        code="relations",
        title="Связи",
        description="Организации и лица, связанные с объектами выбранной территории.",
        render=LayerRenderKind.POINTS,
        levels=_DISTRICT,
        coverage_note=(
            "Наложение поверх других слоёв. Полный граф открывается на "
            "отдельном экране."
        ),
    ),
)

LAYERS_BY_CODE: dict[str, ThematicLayer] = {layer.code: layer for layer in LAYERS}


def layers_for_level(level: TerritoryLevel) -> tuple[ThematicLayer, ...]:
    """Слои, у которых есть данные на указанном уровне."""
    return tuple(layer for layer in LAYERS if layer.available_at(level))


def mappable_layers() -> tuple[ThematicLayer, ...]:
    """Слои, которые вообще выводятся на карту."""
    return tuple(layer for layer in LAYERS if layer.render is not LayerRenderKind.NONE)


def get_layer(code: str) -> ThematicLayer:
    try:
        return LAYERS_BY_CODE[code]
    except KeyError:
        known = ", ".join(sorted(LAYERS_BY_CODE))
        raise KeyError(f"Слой {code!r} не описан. Есть: {known}") from None
