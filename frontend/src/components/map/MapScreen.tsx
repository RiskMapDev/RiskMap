"use client";

import { useEffect, useMemo, useState } from "react";
import { Globe, Info, Layers, MapPin, SlidersHorizontal } from "lucide-react";

import { FilterPanel } from "@/components/filters/FilterPanel";

import { MapView, type TerritoryFeatureProperties } from "@/components/map/MapView";
import { TerritoryPopup } from "@/components/map/TerritoryPopup";
import {
  VIEW_MODE_PARAM,
  ViewSwitcher,
  parseViewMode,
  type ViewMode,
} from "@/components/map/ViewSwitcher";
import { ObjectsPanel } from "@/components/map/ObjectsPanel";
import type { ListItem } from "@/lib/api/types";
import {
  fetchLayers,
  fetchTerritoriesGeoJson,
  type ThematicLayerInfo,
  type TerritoriesGeoJson,
} from "@/lib/api/territories";
import {
  DEFAULT_QUERY_SPEC,
  fromSearchParams,
  toSearchParams,
  type QuerySpec,
} from "@/lib/query-spec";

export type MapLevel = "region" | "district";

const LEVEL_TITLES: Record<MapLevel, string> = {
  region: "области Казахстана",
  district: "районы Алматинской области",
};

const LEVELS = [
  {
    value: "region" as const,
    label: "Республика",
    icon: Globe,
    hint: "Области Казахстана. На этом уровне доступен бюджетный слой.",
  },
  {
    value: "district" as const,
    label: "Алматинская область",
    icon: MapPin,
    hint: "Районы и города областного значения. Закупки, субсидии, экспертиза.",
  },
];

/**
 * Переключатель уровня карты.
 *
 * Уровни различаются не только масштабом, но и составом доступных слоёв, и
 * подсказка называет это прямо: пользователь, у которого при приближении исчез
 * бюджетный слой, иначе решит, что интерфейс сломался.
 */
function LevelSwitcher({
  level,
  onChange,
}: {
  level: MapLevel;
  onChange: (level: MapLevel) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Уровень карты"
      className="inline-flex overflow-hidden rounded-lg border border-border-base bg-surface shadow-card"
    >
      {LEVELS.map((item) => {
        const active = item.value === level;
        const Icon = item.icon;

        // Подсказка передаётся через aria-describedby, а не title: атрибут
        // title подменяет доступное имя кнопки, и скринридер зачитывал бы
        // длинное пояснение вместо короткого «Республика».
        return (
          <button
            key={`level-${item.value}`}
            type="button"
            onClick={() => onChange(item.value)}
            aria-pressed={active}
            aria-describedby={`level-hint-${item.value}`}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs transition-colors ${
              active
                ? "bg-accent font-medium text-accent-fg"
                : "text-text-muted hover:bg-surface-hover hover:text-text"
            }`}
          >
            <Icon className="size-3.5" aria-hidden="true" />
            {item.label}
          </button>
        );
      })}

      {/* Пояснения доступны скринридеру, но не занимают места в интерфейсе. */}
      {LEVELS.map((item) => (
        <span key={`hint-${item.value}`} id={`level-hint-${item.value}`} className="sr-only">
          {item.hint}
        </span>
      ))}
    </div>
  );
}

/** Кнопка открытия панели фильтров. Отдельным компонентом ради читаемости разметки. */
function FiltersButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={`inline-flex items-center gap-1.5 rounded-lg border border-border-base px-3 py-1.5 text-xs transition-colors ${
        open
          ? "bg-accent font-medium text-accent-fg"
          : "bg-surface text-text-muted hover:bg-surface-hover hover:text-text"
      }`}
    >
      <SlidersHorizontal className="size-3.5" aria-hidden="true" />
      Фильтры
    </button>
  );
}

/**
 * Экран карты.
 *
 * Карта иерархическая: на уровне республики показываются области, при переходе
 * вглубь — районы Алматинской области. Это не украшение, а следствие данных:
 * бюджетный слой существует только по областям, закупки и субсидии — только по
 * районам. Показывать все слои на всех уровнях было бы враньём.
 */
export function MapScreen() {
  /*
    Режим представления читается из адреса напрямую, без `useSearchParams`.

    Причина не в удобстве. `useSearchParams` заставляет ближайшую границу
    Suspense ждать, и на этой странице ожидание не заканчивалось никогда:
    дерево отрисовывалось в скрытом контейнере, эффекты не запускались,
    запросы к API не уходили, а пользователь бесконечно видел «Загрузка
    карты…». Воспроизводилось и в режиме разработки, и в продакшн-сборке.

    Чтение из `window.location` даёт то же состояние без границы ожидания.
    Требование ТЗ о едином состоянии карты и списка при этом сохраняется:
    режим по-прежнему живёт в адресной строке, ссылка воспроизводит экран, а
    переходы пишутся в историю браузера.
  */
  const [view, setView] = useState<ViewMode>("map");

  /*
    Выборка живёт в том же адресе, что и режим показа. Это и есть требование
    ТЗ: «Списком» и «На карте» — два представления ОДНОЙ выборки, а не две
    страницы с расходящимся состоянием. Переключение режима не трогает
    фильтры, а смена фильтров видна обоим представлениям сразу.
  */
  const [spec, setSpec] = useState<QuerySpec>(DEFAULT_QUERY_SPEC);

  useEffect(() => {
    const apply = () => {
      const params = new URLSearchParams(window.location.search);
      setView(parseViewMode(params.get(VIEW_MODE_PARAM)));
      setSpec(fromSearchParams(params));
    };
    apply();
    // Кнопки «назад» и «вперёд» обязаны возвращать и режим, и фильтры.
    window.addEventListener("popstate", apply);
    return () => window.removeEventListener("popstate", apply);
  }, []);

  /** Записать состояние в адрес, сохранив то, чем управляет другая часть экрана. */
  function pushState(nextView: ViewMode, nextSpec: QuerySpec) {
    const params = toSearchParams(nextSpec);
    params.set(VIEW_MODE_PARAM, nextView);
    window.history.pushState({}, "", `?${params.toString()}`);
  }

  function changeView(next: ViewMode) {
    pushState(next, spec);
    setView(next);
  }

  function changeSpec(next: QuerySpec) {
    pushState(view, next);
    setSpec(next);
  }

  /*
    Переход к карточке объекта.

    Идентификатор в списке имеет вид `тип:идентификатор` (см. `toListItem` в
    `lib/api/objects.ts`), а адрес карточки — `/objects/тип/идентификатор`.
    Разбор по первому двоеточию, а не `split(":")`: идентификаторы источников
    сами содержат двоеточия, и разбиение по всем вхождениям потеряло бы хвост.

    Навигация обычная, с переходом на страницу: карточка — отдельный экран, а
    не панель внутри карты, и она должна открываться по ссылке, сохраняться в
    закладках и возвращаться кнопкой «назад».
  */
  function openCard(item: ListItem) {
    const separator = item.id.indexOf(":");
    if (separator < 1) return;
    const objectType = item.id.slice(0, separator);
    const objectId = item.id.slice(separator + 1);
    window.location.assign(
      `/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`,
    );
  }

  const [level, setLevel] = useState<MapLevel>("district");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<TerritoryFeatureProperties | null>(null);

  /*
    Панель фильтров выдвижная в обоих режимах. На референсе она перекрывает
    карту слева; в режиме списка ведёт себя так же, потому что фильтрует одну
    и ту же выборку — держать для неё второе место в разметке значило бы
    разводить два состояния одного фильтра.
  */
  const [filtersOpen, setFiltersOpen] = useState(false);

  /*
    Загруженные данные хранятся вместе с уровнем, для которого они получены.
    Это позволяет вывести признак загрузки, а не хранить его отдельным
    состоянием: запись состояния прямо в теле эффекта вызывала бы лишний
    каскад перерисовок при каждой смене уровня.
  */
  const [result, setResult] = useState<{
    level: MapLevel;
    geojson: TerritoriesGeoJson | null;
    layers: ThematicLayerInfo[];
    error: string | null;
  } | null>(null);

  const loading = result?.level !== level;
  const geojson = loading ? null : (result?.geojson ?? null);
  const layers = loading ? [] : (result?.layers ?? []);
  const error = loading ? null : (result?.error ?? null);

  useEffect(() => {
    const controller = new AbortController();

    const apiLevel = level === "region" ? "region" : "district";
    const parent = level === "district" ? "almaty-oblast" : undefined;

    Promise.all([
      fetchTerritoriesGeoJson(
        { level: apiLevel, parent, zoom: level === "region" ? 4 : 7 },
        controller.signal,
      ),
      fetchLayers(apiLevel, controller.signal),
    ])
      .then(([geo, layerInfo]) => {
        if (controller.signal.aborted) return;
        setResult({ level, geojson: geo, layers: layerInfo, error: null });
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        /*
          Ошибку показываем текстом, а не пустой картой. Пустая карта
          неотличима от «в регионе нет объектов», и пользователь сделает
          неверный вывод о данных, а не о связи с сервером.
        */
        setResult({
          level,
          geojson: null,
          layers: [],
          error: cause instanceof Error ? cause.message : "не удалось загрузить границы",
        });
      });

    return () => controller.abort();
  }, [level]);

  // Города областного значения приходят отдельным уровнем, но на карте они
  // равноправны районам, поэтому склеиваются в один набор.
  const features = useMemo(() => geojson?.features ?? [], [geojson]);

  const availableLayers = layers.filter((layer) => layer.available);
  const unavailableLayers = layers.filter(
    (layer) => !layer.available && layer.unavailability_reason,
  );

  return (
    /*
      `absolute inset-0`, а не `h-full`. Процентная высота не разрешается
      внутри flex-элемента, у которого нет явной высоты: контейнер карты
      получал нулевой размер, MapLibre молча создавал карту 0×0 и не рисовал
      ничего. Абсолютное позиционирование относительно области содержимого
      даёт определённый размер независимо от способа раскладки родителя.
    */
    <div className="absolute inset-0 flex">
      {/* Заголовок нужен скринридеру: без него страницу нечем назвать. */}
      <h1 className="sr-only">Карта рисков — {LEVEL_TITLES[level]}</h1>

      {filtersOpen && (
        <>
          {/*
            Подложка закрывает панель щелчком мимо неё. Без неё выдвижную
            панель на телефоне можно закрыть только точным попаданием в
            крестик.
          */}
          <button
            type="button"
            aria-label="Закрыть панель фильтров"
            onClick={() => setFiltersOpen(false)}
            className="absolute inset-0 z-20 bg-black/30 lg:hidden"
          />
          <div className="absolute inset-y-0 left-0 z-30 w-80 max-w-[85vw] overflow-y-auto border-r border-border-base bg-surface shadow-panel">
            <FilterPanel
              spec={spec}
              onApply={(next) => {
                changeSpec(next);
                setFiltersOpen(false);
              }}
              onReset={() => {
                changeSpec(DEFAULT_QUERY_SPEC);
                setFiltersOpen(false);
              }}
              onClose={() => setFiltersOpen(false)}
            />
          </div>
        </>
      )}

      {/*
        Режим «Списком» отдаёт всю ширину списку, «Карта + список» делит её.
        Список и карта берут одну и ту же выборку, поэтому переключение
        режима не перезапрашивает фильтры и не сбрасывает состояние.
      */}
      {/* Карта: занимает всю ширину в режиме «На карте», половину — в сдвоенном. */}
      {view !== "list" && (
        <div className="relative min-w-0 flex-1">
          {error ? (
            <div
              role="alert"
              className="flex h-full flex-col items-center justify-center gap-2 bg-surface-muted p-6 text-center"
            >
              <p className="text-sm font-medium text-text">Границы не загрузились</p>
              <p className="max-w-md text-sm text-text-muted">{error}</p>
              <p className="max-w-md text-xs text-text-subtle">
                Это сбой связи с сервером, а не отсутствие объектов в регионе.
              </p>
            </div>
          ) : (
            <MapView
              geojson={geojson ? { type: "FeatureCollection", features } : null}
              attribution={geojson?.attribution ?? ""}
              selectedCode={selected}
              onSelect={setSelected}
              onHover={setHovered}
              loading={loading}
            />
          )}

          <div className="absolute left-14 top-3 z-10 flex flex-wrap items-center gap-2">
            <ViewSwitcher value={view} onChange={changeView} />
            <LevelSwitcher level={level} onChange={setLevel} />
            <FiltersButton open={filtersOpen} onToggle={() => setFiltersOpen((v) => !v)} />
          </div>

          {hovered && (
            <div className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
              <TerritoryPopup territory={hovered} />
            </div>
          )}
        </div>
      )}

      {/* Список: в режиме «Списком» на всю ширину, в сдвоенном — правая колонка. */}
      {view !== "map" && (
        <div
          className={
            view === "list"
              ? "flex min-w-0 flex-1 flex-col"
              : "hidden w-[26rem] shrink-0 flex-col border-l border-border-base xl:flex"
          }
        >
          {view === "list" && (
            <div className="shrink-0 border-b border-border-base bg-surface px-4 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <ViewSwitcher value={view} onChange={changeView} />
                <LevelSwitcher level={level} onChange={setLevel} />
                <FiltersButton
                  open={filtersOpen}
                  onToggle={() => setFiltersOpen((value) => !value)}
                />
              </div>
            </div>
          )}
          <div className="min-h-0 flex-1">
            <ObjectsPanel
              spec={spec}
              onSpecChange={changeSpec}
              selectedId={selected}
              onOpen={openCard}
            />
          </div>
        </div>
      )}

      {/* Панель слоёв нужна только карте: в режиме списка она ни на что не влияет. */}
      {view !== "list" && (
      <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-border-base bg-surface p-4 lg:block">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
          <Layers className="size-3.5" aria-hidden="true" />
          Тематические слои ({availableLayers.length} / {layers.length})
        </h2>

        <ul className="mt-3 space-y-2">
          {availableLayers.map((layer) => (
            <li key={layer.code} className="text-sm">
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  defaultChecked={layer.enabled_by_default}
                  className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
                />
                <span>
                  <span className="text-text">{layer.title}</span>
                  {layer.coverage_note && (
                    <span className="mt-0.5 block text-xs text-text-subtle">
                      {layer.coverage_note}
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>

        {/*
          Недоступные слои не прячутся, а перечисляются с причиной. Молча
          убрать слой из списка — значит оставить пользователя в убеждении,
          что он видит все данные.
        */}
        {unavailableLayers.length > 0 && (
          <div className="mt-5 border-t border-border-base pt-4">
            <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
              <Info className="size-3.5" aria-hidden="true" />
              Нет данных на этом уровне
            </h3>
            <ul className="mt-2 space-y-2">
              {unavailableLayers.map((layer) => (
                <li key={layer.code} className="text-sm">
                  <span className="text-text-subtle">{layer.title}</span>
                  <span className="mt-0.5 block text-xs text-text-subtle">
                    {layer.unavailability_reason}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
      )}
    </div>
  );
}
