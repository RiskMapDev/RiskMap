/**
 * Запросы графа взаимосвязей.
 *
 * Весь граф не запрашивается никогда — такого запроса просто нет. Экран умеет
 * только два действия: найти узел по названию и получить его окружение с
 * ограничением глубины и числа узлов. Раскрытие соседа — тот же запрос
 * окружения с новым центром, а не отдельный «expand»: два запроса пришлось бы
 * держать в согласии по фильтрам и лимитам, и рассогласование было бы
 * вопросом времени.
 */

import { API_BASE } from "@/lib/api/territories";
import type { RiskLevel } from "@/lib/risk";

export type NodeTypeCode = "organization" | "person" | "contract" | "subsidy" | "project";

export type RelationTypeCode =
  | "director"
  | "founder"
  | "supplier"
  | "contractor"
  | "recipient"
  | "co_recipient"
  | "shared_address";

export type ConfidenceCode = "confirmed" | "probable";

/**
 * Идентификатор узла в том виде, в каком его разрешено показывать роли.
 *
 * `present` отдаётся и тогда, когда `value` пуст: интерфейс обязан отличать
 * «идентификатора нет в данных» от «вам не положено его видеть». Без этого
 * различия пользователь считает данные неполными.
 */
export interface MaskedIdentifier {
  value: string | null;
  present: boolean;
  access: "full" | "masked" | "hidden";
}

export interface GraphNodePayload {
  key: string;
  node_type: NodeTypeCode;
  node_type_label: string;
  label: string;
  sublabel: string | null;
  identifier: MaskedIdentifier | null;
  identifier_kind: "bin" | "iin" | null;
  risk_level: RiskLevel;
  risk_level_label: string;
  risk_score: number | null;
  risk_is_preliminary: boolean;
  /** Сколько связей у узла всего — до всех ограничений выборки. */
  degree: number;
  source_layer: string;
  ref_entity_type: string | null;
  ref_entity_id: string | null;
  attributes: Record<string, unknown>;
}

export interface GraphEdgePayload {
  id: string;
  relation_type: RelationTypeCode;
  relation_type_label: string;
  source: string;
  target: string;
  direction: "directed" | "undirected";
  confidence: ConfidenceCode;
  confidence_label: string;
  /** Чем именно доказана связь. Без этого «предположительная» нечем проверить. */
  confidence_basis: string;
  source_layer: string;
  derivation_rule: string;
  amount: number | null;
  data_as_of: string | null;
  evidence: Record<string, unknown>;
}

export interface SubgraphPayload {
  center: string;
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
  depth: number;
  max_nodes: number;
  /** Соседей больше, чем поместилось. Обязательно к показу. */
  truncated: boolean;
  omitted_nodes: number;
  total_neighbors: number;
  scope_note: string;
}

export interface GraphLegend {
  node_types: Array<{ code: NodeTypeCode; label: string }>;
  relation_types: Array<{ code: RelationTypeCode; label: string }>;
  confidence: Array<{
    code: ConfidenceCode;
    label: string;
    style: "solid" | "dashed";
    note: string;
  }>;
  directions: string[];
  limits: { max_depth: number; default_max_nodes: number; max_nodes: number };
}

export interface RelationBreakdownRow {
  relation_type: RelationTypeCode;
  label: string;
  confirmed: number;
  probable: number;
  total: number;
}

export interface GraphStats {
  nodes: Array<{ code: NodeTypeCode; label: string; count: number }>;
  nodes_total: number;
  relations: Array<{
    code: RelationTypeCode;
    label: string;
    confirmed: number;
    probable: number;
    total: number;
  }>;
  relations_total: number;
}

async function request<T>(path: string, token: string | null, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    signal,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!response.ok) {
    /*
      Код сохраняется в тексте ошибки: экран различает 401 (сессия истекла)
      и всё остальное, и подменять простую причину «ошибкой сервера» значит
      отправить пользователя разбираться не туда.
    */
    throw new Error(`Запрос графа не выполнен: код ${response.status}`);
  }

  return (await response.json()) as T;
}

export function fetchGraphLegend(token: string | null, signal?: AbortSignal): Promise<GraphLegend> {
  return request<GraphLegend>("/graph/legend", token, signal);
}

export function fetchGraphStats(token: string | null, signal?: AbortSignal): Promise<GraphStats> {
  return request<GraphStats>("/graph/stats", token, signal);
}

/** Пустой `query` — весь перечень узлов страницами, в том же порядке. */
export function searchGraphNodes(
  query: string,
  token: string | null,
  signal?: AbortSignal,
  limit = 12,
  offset = 0,
): Promise<{
  items: GraphNodePayload[];
  query: string;
  total: number;
  offset: number;
  min_query_length: number;
}> {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
    offset: String(offset),
  });
  return request(`/graph/search?${params.toString()}`, token, signal);
}

export function fetchGraphNode(
  key: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<{ node: GraphNodePayload; relations: RelationBreakdownRow[] }> {
  return request(`/graph/node/${encodeURIComponent(key)}`, token, signal);
}

export interface NeighborsQuery {
  node: string;
  depth: number;
  maxNodes: number;
  relationTypes: RelationTypeCode[];
  /** `true` — только достоверные связи, предположительные отбрасываются сервером. */
  confirmedOnly: boolean;
}

export function fetchNeighbors(
  query: NeighborsQuery,
  token: string | null,
  signal?: AbortSignal,
): Promise<SubgraphPayload> {
  const params = new URLSearchParams({
    node: query.node,
    depth: String(query.depth),
    max_nodes: String(query.maxNodes),
  });
  /*
    Пустой список типов означает «все типы» и в запрос не попадает. Передать
    пустую строку значило бы попросить у сервера связи ни одного типа — то
    есть получить пустой граф там, где пользователь не ставил ни одной галки
    именно потому, что хотел видеть всё.
  */
  if (query.relationTypes.length > 0) {
    params.set("relation_types", query.relationTypes.join(","));
  }
  if (query.confirmedOnly) {
    params.set("min_confidence", "confirmed");
  }
  return request<SubgraphPayload>(`/graph/neighbors?${params.toString()}`, token, signal);
}

/**
 * Адрес экрана как единственный носитель состояния выборки.
 *
 * `useSearchParams` намеренно не используется: на этом проекте связка с
 * Suspense приводила к тому, что заглушка не сменялась никогда. Адрес читается
 * из `window.location`, а изменения — по событию `popstate`.
 */
export interface GraphViewState {
  node: string | null;
  depth: number;
  maxNodes: number;
  relationTypes: RelationTypeCode[];
  confirmedOnly: boolean;
}

const RELATION_CODES: readonly RelationTypeCode[] = [
  "director",
  "founder",
  "supplier",
  "contractor",
  "recipient",
  "co_recipient",
  "shared_address",
];

export const DEFAULT_VIEW_STATE: GraphViewState = {
  node: null,
  depth: 1,
  maxNodes: 60,
  relationTypes: [],
  confirmedOnly: false,
};

function clampInt(raw: string | null, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

/** Разобрать состояние из строки запроса. Мусор молча заменяется умолчанием. */
export function parseViewState(search: string): GraphViewState {
  const params = new URLSearchParams(search);
  const types = (params.get("relations") ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter((item): item is RelationTypeCode =>
      RELATION_CODES.includes(item as RelationTypeCode),
    );

  return {
    node: params.get("node"),
    depth: clampInt(params.get("depth"), 1, 1, 2),
    maxNodes: clampInt(params.get("max_nodes"), 60, 10, 200),
    relationTypes: types,
    confirmedOnly: params.get("confidence") === "confirmed",
  };
}

/** Собрать строку запроса. Значения по умолчанию опускаются — ссылка читаема. */
export function buildViewSearch(state: GraphViewState): string {
  const params = new URLSearchParams();
  if (state.node) params.set("node", state.node);
  if (state.depth !== DEFAULT_VIEW_STATE.depth) params.set("depth", String(state.depth));
  if (state.maxNodes !== DEFAULT_VIEW_STATE.maxNodes) {
    params.set("max_nodes", String(state.maxNodes));
  }
  if (state.relationTypes.length > 0) params.set("relations", state.relationTypes.join(","));
  if (state.confirmedOnly) params.set("confidence", "confirmed");
  const query = params.toString();
  return query ? `?${query}` : "";
}
