/**
 * Уровни риска: единый словарь для всего интерфейса.
 *
 * ТЗ задаёт цвета — зелёный, жёлтый, красный, тёмно-красный, серый. Но проверка
 * контраста (`scripts/check-contrast.mjs`) показала, что подписи «высокого» и
 * «критического» различаются между собой всего в 1.55:1 в светлой теме и
 * 1.46:1 в тёмной. Это фактически один цвет для глаза, а для человека с
 * нарушением цветовосприятия — тем более.
 *
 * Поэтому цвет здесь никогда не единственный носитель смысла: у каждого уровня
 * есть текстовая подпись, значок и — на карте — паттерн заливки. Требование ТЗ
 * по цветам выполняется, но смысл держится не на нём.
 */

export const RISK_LEVELS = ["low", "medium", "high", "critical", "unknown"] as const;

export type RiskLevel = (typeof RISK_LEVELS)[number];

export interface RiskLevelMeta {
  readonly level: RiskLevel;
  readonly label: string;
  /** Ранг для сортировки «по возрастанию тревожности». */
  readonly order: number;
  /**
   * Значок, дублирующий цвет. Формы намеренно разные, а не оттенки одного
   * знака: различаться должен силуэт.
   */
  readonly glyph: string;
  /** Паттерн заливки полигона на карте — второй канал после цвета. */
  readonly pattern: "solid" | "hatch" | "cross-hatch" | "dots" | "none";
  readonly description: string;
}

export const RISK_LEVEL_META: Readonly<Record<RiskLevel, RiskLevelMeta>> = {
  low: {
    level: "low",
    label: "Низкий",
    order: 0,
    glyph: "●",
    pattern: "solid",
    description: "Показатели в пределах нормы.",
  },
  medium: {
    level: "medium",
    label: "Средний",
    order: 1,
    glyph: "◆",
    pattern: "dots",
    description: "Есть отклонения, требующие внимания.",
  },
  high: {
    level: "high",
    label: "Высокий",
    order: 2,
    glyph: "▲",
    pattern: "hatch",
    description: "Существенные отклонения по нескольким индикаторам.",
  },
  critical: {
    level: "critical",
    label: "Критический",
    order: 3,
    glyph: "■",
    pattern: "cross-hatch",
    description: "Критические отклонения либо сработавшее жёсткое правило.",
  },
  unknown: {
    /*
      Ранг −1, а не «между низким и средним»: объект без данных не должен
      уезжать в благополучный конец списка при сортировке по риску. Отсутствие
      измерения — это не хорошая новость.
    */
    level: "unknown",
    label: "Нет данных",
    order: -1,
    glyph: "○",
    pattern: "none",
    description: "Данных недостаточно для оценки. Это не означает отсутствие риска.",
  },
};

/** CSS-классы Tailwind для плашки уровня. Токены объявлены в globals.css. */
export const RISK_LEVEL_CLASSES: Readonly<Record<RiskLevel, string>> = {
  low: "text-risk-low-text bg-risk-low-bg border-risk-low-border",
  medium: "text-risk-medium-text bg-risk-medium-bg border-risk-medium-border",
  high: "text-risk-high-text bg-risk-high-bg border-risk-high-border",
  critical: "text-risk-critical-text bg-risk-critical-bg border-risk-critical-border",
  unknown: "text-risk-none-text bg-risk-none-bg border-risk-none-border",
};

export function riskMeta(level: RiskLevel): RiskLevelMeta {
  return RISK_LEVEL_META[level];
}

/** Порядок уровней для легенды и фильтров: от тревожного к спокойному, «нет данных» последним. */
export const RISK_LEVELS_DISPLAY_ORDER: readonly RiskLevel[] = [
  "critical",
  "high",
  "medium",
  "low",
  "unknown",
];

/**
 * Сравнение уровней для сортировки списка по риску.
 * По убыванию тревожности; объекты без данных идут после измеренных,
 * но не смешиваются с низким уровнем.
 */
export function compareByRisk(a: RiskLevel, b: RiskLevel): number {
  return RISK_LEVEL_META[b].order - RISK_LEVEL_META[a].order;
}

export function isMeasured(level: RiskLevel): boolean {
  return level !== "unknown";
}
