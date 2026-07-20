/**
 * Оформление графа связей: форма узла, подпись, начертание ребра.
 *
 * Модуль вынесен из компонента и не знает ни про cytoscape, ни про DOM — так
 * его правила проверяются тестом без канвы и без браузера. Компонент только
 * подставляет полученные значения в таблицу стилей cytoscape.
 *
 * **Два независимых носителя смысла на узле.** Тип сущности передаётся
 * формой, уровень риска — значком и словом в подписи. Цвет не несёт смысла
 * в одиночку нигде: проверка контраста на этом проекте показала, что «высокий»
 * и «критический» различаются между собой на 1.5:1, то есть для глаза это
 * один цвет, а для человека с нарушением цветовосприятия — тем более.
 * Форму под риск отдать нельзя: её уже занял тип узла, и один канал не может
 * нести два разных смысла.
 *
 * **Начертание ребра передаёт достоверность.** Сплошная — связь доказана
 * идентификатором, пунктир — выведена из совпадения наименования или адреса.
 * Так это нарисовано и на референсе, и совпадение не случайно: различие
 * доказанного и предположенного — единственное, что нельзя потерять при
 * переносе графа в отчёт, где цвета может не быть вовсе.
 */

import { riskMeta, type RiskLevel } from "@/lib/risk";
import type { ConfidenceCode, NodeTypeCode, RelationTypeCode } from "@/lib/api/graph";

/** Форма узла cytoscape по типу сущности. */
export type NodeShape =
  | "round-rectangle"
  | "ellipse"
  | "diamond"
  | "hexagon"
  | "cut-rectangle";

export const NODE_SHAPE: Readonly<Record<NodeTypeCode, NodeShape>> = {
  // Организация — прямоугольная карточка, как на референсе.
  organization: "round-rectangle",
  // Физлицо — круг: на референсе это круглый аватар.
  person: "ellipse",
  contract: "diamond",
  subsidy: "hexagon",
  project: "cut-rectangle",
};

/** Цвет заливки узла по типу — вспомогательный канал, дублирующий форму. */
export const NODE_FILL: Readonly<Record<NodeTypeCode, string>> = {
  organization: "#dbeafe",
  person: "#e2e8f0",
  contract: "#fef3c7",
  subsidy: "#dcfce7",
  project: "#ede9fe",
};

/** Токен цвета обводки по уровню риска. Значения — из `globals.css`. */
export const RISK_BORDER_VAR: Readonly<Record<RiskLevel, string>> = {
  low: "--risk-low",
  medium: "--risk-medium",
  high: "--risk-high",
  critical: "--risk-critical",
  unknown: "--risk-none",
};

/**
 * Толщина обводки по уровню.
 *
 * Второй канал после значка: «критический» отличается от «высокого» не
 * только оттенком, который на этой паре почти неразличим, но и заметно
 * более толстой рамкой.
 */
export const RISK_BORDER_WIDTH: Readonly<Record<RiskLevel, number>> = {
  low: 2,
  medium: 2,
  high: 3,
  critical: 5,
  unknown: 1,
};

/**
 * Начертание обводки по уровню.
 *
 * У «нет данных» рамка пунктирная: неизмеренный объект не должен выглядеть
 * так же уверенно, как измеренный. Это ровно та же мысль, что и у
 * предположительной связи.
 */
export const RISK_BORDER_STYLE: Readonly<Record<RiskLevel, "solid" | "dashed" | "double">> = {
  low: "solid",
  medium: "solid",
  high: "solid",
  // Двойная рамка у критического — форма, а не цвет.
  critical: "double",
  unknown: "dashed",
};

/** Начертание ребра по достоверности связи. */
export const CONFIDENCE_LINE_STYLE: Readonly<Record<ConfidenceCode, "solid" | "dashed">> = {
  confirmed: "solid",
  probable: "dashed",
};

/** Цвет ребра по типу связи. Совпадает с цветными точками левой панели. */
export const RELATION_COLOR: Readonly<Record<RelationTypeCode, string>> = {
  director: "#7c3aed",
  founder: "#9333ea",
  supplier: "#2563eb",
  contractor: "#0891b2",
  recipient: "#16a34a",
  co_recipient: "#ca8a04",
  shared_address: "#db2777",
};

const MAX_LABEL_LENGTH = 42;

/** Обрезать длинную подпись, не обрывая слово посреди, если это возможно. */
export function truncateLabel(raw: string, limit: number = MAX_LABEL_LENGTH): string {
  const value = raw.trim();
  if (value.length <= limit) return value;
  const cut = value.slice(0, limit);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > limit * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}

/**
 * Подпись узла: значок уровня, наименование и уровень словом.
 *
 * Слово обязательно. Значок различим глазом, но не читается вслух, а цвет
 * не читается вовсе — по требованию WCAG 2.1 AA уровень риска обязан быть
 * доступен текстом. Тильда перед баллом означает, что балл предварительный:
 * посчитан, но полноты данных не хватило, и выводов по нему делать нельзя.
 */
export function nodeLabel(node: {
  label: string;
  risk_level: RiskLevel;
  risk_score: number | null;
  risk_is_preliminary: boolean;
}): string {
  const meta = riskMeta(node.risk_level);
  const score =
    typeof node.risk_score === "number"
      ? ` ${node.risk_is_preliminary ? "~" : ""}${node.risk_score.toFixed(0)}`
      : "";
  return `${meta.glyph} ${truncateLabel(node.label)}\n${meta.label}${score}`;
}

/**
 * Текст для скринридера и подсказки.
 *
 * Собирается отдельно от подписи на канве: канва для вспомогательных
 * технологий недоступна в принципе, и рядом с ней всегда стоит список узлов,
 * который читает именно это описание.
 */
export function nodeDescription(node: {
  label: string;
  node_type_label: string;
  risk_level: RiskLevel;
  risk_level_label: string;
  risk_is_preliminary: boolean;
  degree: number;
}): string {
  const preliminary = node.risk_is_preliminary
    ? ", оценка предварительная — данных недостаточно"
    : "";
  return (
    `${node.node_type_label}: ${node.label}. ` +
    `Уровень риска: ${node.risk_level_label}${preliminary}. ` +
    `Связей: ${node.degree}.`
  );
}

/** Подпись ребра: тип связи и, для предположительной, пометка словом. */
export function edgeLabel(edge: {
  relation_type_label: string;
  confidence: ConfidenceCode;
}): string {
  return edge.confidence === "probable"
    ? `${edge.relation_type_label} (предпол.)`
    : edge.relation_type_label;
}

/**
 * Прочитать значение CSS-переменной темы.
 *
 * Цвета живут в `globals.css` и меняются вместе с темой; дублировать их
 * константами здесь значило бы получить граф, который не темнеет вместе с
 * остальным интерфейсом.
 */
export function readThemeColor(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
