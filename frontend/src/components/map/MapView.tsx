"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl, { type MapGeoJSONFeature } from "maplibre-gl";
/*
  Стиль MapLibre подключён глобально в `app/globals.css`, а не здесь.
  React 19 считает импортированную в компоненте таблицу стилей ресурсом и
  приостанавливает ближайшую границу Suspense до её загрузки. На странице
  карты это приводило к тому, что заглушка «Загрузка карты…» не сменялась
  никогда: дерево отрисовывалось в скрытом контейнере, эффекты не
  запускались, запросы к API не уходили.
*/

import {
  ALMATY_OBLAST_VIEW,
  KAZAKHSTAN_BOUNDS,
  MAP_STYLE_URL,
  createBaseStyle,
  riskFillColorExpression,
  riskFillOpacityExpression,
} from "@/lib/map/style";
import type { RiskLevel } from "@/lib/risk";

const SOURCE_ID = "territories";
const FILL_LAYER = "territories-fill";
const LINE_LAYER = "territories-line";
const HATCH_LAYER = "territories-critical-hatch";

export interface TerritoryFeatureProperties {
  code: string;
  name_ru: string;
  name_kk: string | null;
  level: string;
  admin_center: string | null;
  population: number | null;
  population_as_of: string | null;
  area_km2: number | null;
  area_km2_computed: number | null;
  risk_level?: RiskLevel;
  risk_score?: number | null;
  amount?: number | null;
  /** Код слоя, по которому посчитан уровень. */
  risk_layer?: string;
  /** Распределение объектов территории по уровням — рядом с цветом. */
  risk_counts?: Record<string, number>;
  objects_total?: number;
}

interface MapViewProps {
  /** GeoJSON границ с показателями. `null` — данные ещё не пришли. */
  geojson: GeoJSON.FeatureCollection | null;
  /** Обязательная атрибуция источника границ. Без неё карту показывать нельзя. */
  attribution: string;
  selectedCode?: string | null;
  onSelect?: (code: string | null) => void;
  onHover?: (properties: TerritoryFeatureProperties | null) => void;
  loading?: boolean;
}

/**
 * Свойства объекта карты в пригодном для React виде.
 *
 * MapLibre хранит свойства в плоском виде и отдаёт вложенные объекты строкой
 * JSON. Без разбора распределение по уровням попало бы в подсказку как
 * `"{\"low\":8}"`, поэтому оно восстанавливается здесь, а не у потребителя:
 * иначе каждый новый потребитель свойств повторял бы этот разбор заново.
 */
function normalizeProperties(raw: unknown): TerritoryFeatureProperties {
  const properties = { ...(raw as Record<string, unknown>) };
  const counts = properties.risk_counts;

  if (typeof counts === "string") {
    try {
      properties.risk_counts = JSON.parse(counts) as Record<string, number>;
    } catch {
      // Разбитый JSON — не повод ронять подсказку целиком: остальные поля
      // территории по-прежнему верны, а распределение просто не покажется.
      delete properties.risk_counts;
    }
  }

  return properties as unknown as TerritoryFeatureProperties;
}

function readCssVariable(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/**
 * Карта территорий.
 *
 * Подложка по умолчанию отсутствует — см. `lib/map/style.ts`. Полигоны
 * раскрашиваются по уровню риска выражением MapLibre, а не пересборкой
 * GeoJSON: при смене фильтра меняется только выражение.
 *
 * Критический уровень дополнительно помечается штриховкой. Это не украшение:
 * проверка контраста показала, что «высокий» и «критический» по ТЗ
 * различаются в 1.5:1, то есть цветом их не различить. Второй канал
 * обязателен.
 */
export function MapView({
  geojson,
  attribution,
  selectedCode = null,
  onSelect,
  onHover,
  loading = false,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  /*
    Поддержку WebGL проверяем ДО попытки создать карту, а не ловим исключение
    из конструктора. Так отказ становится обычным состоянием отрисовки, а не
    записью состояния прямо в теле эффекта, которая вызывает каскад
    перерисовок. Проверка ленивая — выполняется один раз и только в браузере.
  */
  const [webglAvailable] = useState<boolean>(() => {
    if (typeof document === "undefined") return true;
    try {
      const probe = document.createElement("canvas");
      return Boolean(probe.getContext("webgl2") ?? probe.getContext("webgl"));
    } catch {
      return false;
    }
  });

  // Колбэки держим в ref: иначе смена обработчика пересоздавала бы карту,
  // а вместе с ней терялись бы масштаб и положение, выбранные пользователем.
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  useEffect(() => {
    onSelectRef.current = onSelect;
    onHoverRef.current = onHover;
  }, [onSelect, onHover]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !webglAvailable) return;

    const background = readCssVariable("--bg", "#0b1220");

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL ?? createBaseStyle(background),
      center: ALMATY_OBLAST_VIEW.center,
      zoom: ALMATY_OBLAST_VIEW.zoom,
      maxBounds: KAZAKHSTAN_BOUNDS,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      // Контейнер во flex-вёрстке может получить итоговую высоту уже после
      // конструктора карты. MapLibre фиксирует размер canvas в момент
      // инициализации и сам за контейнером не следит: без принудительного
      // resize карта остаётся пустой (виден только фон и элементы управления,
      // а полигоны не рисуются). Явный resize по событию load и наблюдатель
      // ниже закрывают этот случай.
      map.resize();
      setReady(true);
    });
    map.on("error", (event) => {
      setFailed(event.error?.message ?? "ошибка карты");
    });

    mapRef.current = map;

    // Следим за размером контейнера и переразмериваем карту при каждом
    // изменении — покрывает и первичную раскладку, и сворачивание сайдбаров,
    // и смену режима «На карте» / «Карта + список».
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [webglAvailable]);

  // Данные и слои
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !geojson) return;

    const colors: Record<string, string> = {
      low: readCssVariable("--risk-low-fill", "#22c55e"),
      medium: readCssVariable("--risk-medium-fill", "#eab308"),
      high: readCssVariable("--risk-high-fill", "#ef4444"),
      critical: readCssVariable("--risk-critical-fill", "#991b1b"),
      unknown: readCssVariable("--risk-none-fill", "#94a3b8"),
    };

    const existing = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(geojson);
      return;
    }

    map.addSource(SOURCE_ID, { type: "geojson", data: geojson, promoteId: "code" });

    map.addLayer({
      id: FILL_LAYER,
      type: "fill",
      source: SOURCE_ID,
      paint: {
        "fill-color": riskFillColorExpression(colors) as never,
        "fill-opacity": riskFillOpacityExpression() as never,
      },
    });

    // Штриховка критического уровня — второй канал различения после цвета.
    map.addLayer({
      id: HATCH_LAYER,
      type: "line",
      source: SOURCE_ID,
      filter: ["==", ["get", "risk_level"], "critical"],
      paint: {
        "line-color": colors.critical,
        "line-width": 2,
        "line-dasharray": [2, 2],
        "line-offset": 3,
      },
    });

    map.addLayer({
      id: LINE_LAYER,
      type: "line",
      source: SOURCE_ID,
      paint: {
        "line-color": riskFillColorExpression(colors) as never,
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          3.5,
          ["boolean", ["feature-state", "hover"], false],
          2.5,
          1.2,
        ] as never,
      },
    });

    map.on("click", FILL_LAYER, (event) => {
      const feature = event.features?.[0] as MapGeoJSONFeature | undefined;
      const code = feature?.properties?.code as string | undefined;
      onSelectRef.current?.(code ?? null);
    });

    // Клик мимо полигона снимает выделение: иначе от выбранного объекта
    // невозможно избавиться, не перезагрузив страницу.
    map.on("click", (event) => {
      const hits = map.queryRenderedFeatures(event.point, { layers: [FILL_LAYER] });
      if (hits.length === 0) onSelectRef.current?.(null);
    });

    let hovered: string | number | undefined;

    map.on("mousemove", FILL_LAYER, (event) => {
      const feature = event.features?.[0];
      if (!feature) return;

      map.getCanvas().style.cursor = "pointer";

      if (hovered !== undefined) {
        map.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: false });
      }
      hovered = feature.id;
      if (hovered !== undefined) {
        map.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: true });
      }

      onHoverRef.current?.(normalizeProperties(feature.properties));
    });

    map.on("mouseleave", FILL_LAYER, () => {
      map.getCanvas().style.cursor = "";
      if (hovered !== undefined) {
        map.setFeatureState({ source: SOURCE_ID, id: hovered }, { hover: false });
      }
      hovered = undefined;
      onHoverRef.current?.(null);
    });
  }, [ready, geojson]);

  // Выделение выбранного объекта
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource(SOURCE_ID)) return;

    map.removeFeatureState({ source: SOURCE_ID });
    if (selectedCode) {
      map.setFeatureState({ source: SOURCE_ID, id: selectedCode }, { selected: true });
    }
  }, [ready, selectedCode]);

  const zoomToSelection = useCallback(() => {
    const map = mapRef.current;
    if (!map || !geojson || !selectedCode) return;

    const feature = geojson.features.find(
      (item) => (item.properties as { code?: string } | null)?.code === selectedCode,
    );
    if (!feature?.geometry) return;

    const bounds = new maplibregl.LngLatBounds();
    const walk = (coords: unknown): void => {
      if (Array.isArray(coords) && typeof coords[0] === "number") {
        bounds.extend(coords as [number, number]);
        return;
      }
      if (Array.isArray(coords)) coords.forEach(walk);
    };
    walk((feature.geometry as { coordinates?: unknown }).coordinates);

    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 64, duration: 600 });
  }, [geojson, selectedCode]);

  useEffect(() => {
    if (selectedCode) zoomToSelection();
  }, [selectedCode, zoomToSelection]);

  if (!webglAvailable || failed) {
    const reason = webglAvailable
      ? failed
      : "браузер не поддерживает WebGL, без которого карта не рисуется";

    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-2 bg-surface-muted p-6 text-center"
      >
        <p className="text-sm font-medium text-text">Карта не загрузилась</p>
        <p className="max-w-md text-sm text-text-muted">{reason}</p>
        <p className="max-w-md text-xs text-text-subtle">
          Данные доступны в режиме «Списком» — переключитесь, чтобы продолжить работу.
        </p>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" data-testid="map-container" />

      {loading && (
        <div className="pointer-events-none absolute left-1/2 top-4 -translate-x-1/2 rounded-lg bg-surface px-3 py-1.5 text-xs text-text-muted shadow-panel">
          Загрузка данных…
        </div>
      )}

      {/*
        Атрибуция обязательна по лицензии ODbL и потому не прячется в подсказку:
        она видна всегда, пока карта на экране.
      */}
      {attribution && (
        <div className="pointer-events-none absolute bottom-1 right-1 rounded bg-surface/80 px-2 py-0.5 text-[10px] text-text-muted">
          {attribution}
        </div>
      )}
    </div>
  );
}
