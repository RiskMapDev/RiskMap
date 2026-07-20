import type { StyleSpecification } from "maplibre-gl";

/**
 * Стиль базовой карты.
 *
 * ТЗ требует развёртывания в закрытом контуре без внешних CDN. Поэтому по
 * умолчанию подложки нет вовсе: карта рисует только наши собственные границы
 * поверх однотонного фона. Это выглядит скромнее, чем спутниковая подложка на
 * референсе, но работает без интернета и без чужих лицензий на тайлы.
 *
 * Если подложка нужна, задайте `NEXT_PUBLIC_MAP_STYLE_URL` — адрес стиля
 * собственного тайл-сервера. Внешние публичные сервисы сюда подставлять не
 * следует: это и утечка запросов наружу, и зависимость, которой в закрытом
 * контуре не будет.
 */
export const MAP_STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? null;

/** Границы Казахстана, чтобы карта не улетала в океан. */
export const KAZAKHSTAN_BOUNDS: [[number, number], [number, number]] = [
  [46.0, 40.0],
  [88.0, 56.0],
];

/** Стартовый вид: Алматинская область целиком. */
export const ALMATY_OBLAST_VIEW = {
  center: [77.5, 44.2] as [number, number],
  zoom: 6.4,
};

/** Вид на республику для верхнего уровня иерархии. */
export const KAZAKHSTAN_VIEW = {
  center: [67.0, 48.0] as [number, number],
  zoom: 3.6,
};

/**
 * Пустой стиль: фон и ничего больше.
 *
 * Цвета берутся из токенов оформления через CSS-переменные — так карта
 * переключается вместе с темой интерфейса, а не остаётся вечно тёмной.
 */
export function createBaseStyle(background: string): StyleSpecification {
  return {
    version: 8,
    // Шрифты и спрайты не подключаются: их источник был бы внешним, а подписи
    // territories рисуются HTML-маркерами поверх карты.
    sources: {},
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": background },
      },
    ],
  };
}

/**
 * Выражение цвета заливки по уровню риска.
 *
 * Возвращается выражение MapLibre, а не готовый цвет: раскраска считается на
 * стороне карты по свойству объекта, иначе при каждом изменении фильтра
 * пришлось бы пересобирать весь GeoJSON.
 */
export function riskFillColorExpression(colors: Record<string, string>): unknown[] {
  return [
    "match",
    ["get", "risk_level"],
    "low",
    colors.low,
    "medium",
    colors.medium,
    "high",
    colors.high,
    "critical",
    colors.critical,
    // Территория без оценки — серая. Это не «низкий риск», а «не измерено»,
    // и цвет обязан отличаться от всех измеренных уровней.
    colors.unknown,
  ];
}

/**
 * Насыщенность заливки.
 *
 * У серых территорий она ниже: неизмеренное не должно перетягивать внимание
 * с измеренного, но и исчезать не должно — иначе пропадёт сам факт пробела.
 */
export function riskFillOpacityExpression(): unknown[] {
  return ["case", ["==", ["get", "risk_level"], "unknown"], 0.25, 0.55];
}
