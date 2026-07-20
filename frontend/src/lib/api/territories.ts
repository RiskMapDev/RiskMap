/** Запросы к API территорий. */

import type { TerritoryFeatureProperties } from "@/components/map/MapView";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100/api/v1";

export interface TerritoriesGeoJson {
  type: "FeatureCollection";
  features: GeoJSON.Feature[];
  /** Обязательная атрибуция источника границ — приходит вместе с данными. */
  attribution: string;
  geometry_detail: string;
}

export interface ThematicLayerInfo {
  code: string;
  title: string;
  description: string;
  render: "choropleth" | "points" | "none";
  levels: string[];
  source_layer: string | null;
  enabled_by_default: boolean;
  coverage_note: string;
  available: boolean;
  /** Почему слой недоступен на текущем уровне. Показывается пользователю. */
  unavailability_reason: string;
}

export type TerritoryLevel = "country" | "region" | "district" | "city";

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    // Данные должны быть свежими: кэш ответа скрыл бы результат импорта,
    // а пользователь решил бы, что импорт не сработал.
    cache: "no-store",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(
      `Запрос ${path} завершился с кодом ${response.status}` +
        (body ? `: ${body.slice(0, 200)}` : ""),
    );
  }

  return (await response.json()) as T;
}

export function fetchTerritoriesGeoJson(
  params: { level?: TerritoryLevel; parent?: string; zoom?: number },
  signal?: AbortSignal,
): Promise<TerritoriesGeoJson> {
  const query = new URLSearchParams();
  if (params.level) query.set("level", params.level);
  if (params.parent) query.set("parent", params.parent);
  if (params.zoom !== undefined) query.set("zoom", String(params.zoom));

  return request<TerritoriesGeoJson>(`/territories/geojson?${query.toString()}`, signal);
}

export function fetchLayers(
  level: TerritoryLevel | undefined,
  signal?: AbortSignal,
): Promise<ThematicLayerInfo[]> {
  const query = level ? `?level=${level}` : "";
  return request<ThematicLayerInfo[]>(`/territories/layers${query}`, signal);
}

export function fetchTerritory(
  code: string,
  signal?: AbortSignal,
): Promise<TerritoryFeatureProperties & { aliases: unknown[]; available_layers: string[] }> {
  return request(`/territories/${encodeURIComponent(code)}`, signal);
}
