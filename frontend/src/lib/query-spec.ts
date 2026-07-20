/**
 * Каноническое описание выборки — зеркало серверного `QuerySpec`.
 *
 * ТЗ требует, чтобы «Списком» и «На карте» показывали одну и ту же выборку.
 * Значит, состояние фильтров не может жить внутри компонента: при
 * переключении представления оно бы сбрасывалось или расходилось. Оно живёт в
 * адресной строке, и этот модуль — единственное место, где описано, как оно
 * туда кладётся и как оттуда читается.
 *
 * Побочная выгода: ссылку можно переслать коллеге, и он увидит ровно ту же
 * выборку, а кнопка «назад» в браузере восстанавливает предыдущую.
 */

import { RISK_LEVELS, type RiskLevel } from "@/lib/risk";

export const SORT_FIELDS = ["risk", "amount", "relevance", "name"] as const;
export type SortField = (typeof SORT_FIELDS)[number];

export const SORT_ORDERS = ["asc", "desc"] as const;
export type SortOrder = (typeof SORT_ORDERS)[number];

export const OBJECT_TYPES = [
  "territory",
  "contract",
  "subsidy_recipient",
  "ppp_project",
  "expertise_object",
  "organization",
] as const;
export type ObjectType = (typeof OBJECT_TYPES)[number];

export const SORT_FIELD_LABELS: Record<SortField, string> = {
  risk: "По риску",
  amount: "По сумме",
  relevance: "По актуальности",
  name: "По названию",
};

export const OBJECT_TYPE_LABELS: Record<ObjectType, string> = {
  territory: "Территории",
  contract: "Договоры",
  subsidy_recipient: "Получатели субсидий",
  ppp_project: "Проекты ГЧП",
  expertise_object: "Объекты экспертизы",
  organization: "Организации",
};

export interface QuerySpec {
  dateFrom: string | null;
  dateTo: string | null;
  year: number | null;

  territoryCodes: string[];
  includeChildTerritories: boolean;

  objectTypes: ObjectType[];
  layers: string[];
  industries: string[];
  statuses: string[];

  amountMin: number | null;
  amountMax: number | null;

  riskLevels: RiskLevel[];
  completenessMin: number | null;
  completenessMax: number | null;
  onlyCategoryA: boolean;

  search: string | null;

  sort: SortField;
  order: SortOrder;
  page: number;
  pageSize: number;
}

/**
 * Значения по умолчанию.
 *
 * Пустая выборка означает «всё, что есть», а не «ничего»: пользователь,
 * впервые открывший экран, должен увидеть данные, а не просьбу настроить
 * фильтры.
 *
 * Уровень «нет данных» включён намеренно. Убрать его из умолчаний — значит
 * молча спрятать неизмеренные объекты от того, кто фильтры не трогал.
 */
export const DEFAULT_QUERY_SPEC: QuerySpec = {
  dateFrom: null,
  dateTo: null,
  year: null,

  territoryCodes: [],
  includeChildTerritories: true,

  objectTypes: [],
  layers: [],
  industries: [],
  statuses: [],

  amountMin: null,
  amountMax: null,

  riskLevels: [...RISK_LEVELS],
  completenessMin: null,
  completenessMax: null,
  onlyCategoryA: false,

  search: null,

  sort: "risk",
  order: "desc",
  page: 1,
  pageSize: 25,
};

/** Имена в адресной строке — snake_case, как на сервере. */
const PARAM_NAMES: Record<keyof QuerySpec, string> = {
  dateFrom: "date_from",
  dateTo: "date_to",
  year: "year",
  territoryCodes: "territory_codes",
  includeChildTerritories: "include_child_territories",
  objectTypes: "object_types",
  layers: "layers",
  industries: "industries",
  statuses: "statuses",
  amountMin: "amount_min",
  amountMax: "amount_max",
  riskLevels: "risk_levels",
  completenessMin: "completeness_min",
  completenessMax: "completeness_max",
  onlyCategoryA: "only_category_a",
  search: "search",
  sort: "sort",
  order: "order",
  page: "page",
  pageSize: "page_size",
};

function sameList(a: readonly unknown[], b: readonly unknown[]): boolean {
  if (a.length !== b.length) return false;
  const left = [...a].map(String).sort();
  const right = [...b].map(String).sort();
  return left.every((value, index) => value === right[index]);
}

/**
 * Превратить выборку в параметры адресной строки.
 *
 * Значения, совпадающие с умолчанием, опускаются: ссылка должна оставаться
 * читаемой, а не тащить два десятка параметров, ничего не меняющих.
 */
export function toSearchParams(spec: QuerySpec): URLSearchParams {
  const params = new URLSearchParams();

  for (const key of Object.keys(PARAM_NAMES) as (keyof QuerySpec)[]) {
    const value = spec[key];
    const fallback = DEFAULT_QUERY_SPEC[key];
    const name = PARAM_NAMES[key];

    if (Array.isArray(value)) {
      if (sameList(value, fallback as readonly unknown[])) continue;
      params.set(name, value.join(","));
      continue;
    }

    if (value === fallback || value === null) continue;
    params.set(name, String(value));
  }

  return params;
}

function parseNumber(raw: string | null): number | null {
  if (raw === null || raw.trim() === "") return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseList<T extends string>(raw: string | null, allowed: readonly T[]): T[] | null {
  if (raw === null) return null;
  if (raw === "") return [];
  const allowedSet = new Set<string>(allowed);
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter((part): part is T => allowedSet.has(part));
}

/**
 * Прочитать выборку из адресной строки.
 *
 * Неизвестные и повреждённые значения игнорируются и заменяются умолчанием:
 * ссылка, которую кто-то поправил руками или обвешал метками рекламной
 * аналитики, не должна ронять страницу.
 */
export function fromSearchParams(params: URLSearchParams | null | undefined): QuerySpec {
  if (!params) return { ...DEFAULT_QUERY_SPEC };

  const get = (key: keyof QuerySpec) => params.get(PARAM_NAMES[key]);

  const risk = parseList(get("riskLevels"), RISK_LEVELS);
  const sortRaw = get("sort");
  const orderRaw = get("order");

  const page = parseNumber(get("page"));
  const pageSize = parseNumber(get("pageSize"));

  return {
    dateFrom: get("dateFrom"),
    dateTo: get("dateTo"),
    year: parseNumber(get("year")),

    territoryCodes: params.has(PARAM_NAMES.territoryCodes)
      ? (get("territoryCodes") ?? "").split(",").filter(Boolean)
      : [...DEFAULT_QUERY_SPEC.territoryCodes],
    includeChildTerritories: get("includeChildTerritories") !== "false",

    objectTypes: parseList(get("objectTypes"), OBJECT_TYPES) ?? [
      ...DEFAULT_QUERY_SPEC.objectTypes,
    ],
    layers: params.has(PARAM_NAMES.layers)
      ? (get("layers") ?? "").split(",").filter(Boolean)
      : [...DEFAULT_QUERY_SPEC.layers],
    industries: params.has(PARAM_NAMES.industries)
      ? (get("industries") ?? "").split(",").filter(Boolean)
      : [...DEFAULT_QUERY_SPEC.industries],
    statuses: params.has(PARAM_NAMES.statuses)
      ? (get("statuses") ?? "").split(",").filter(Boolean)
      : [...DEFAULT_QUERY_SPEC.statuses],

    amountMin: parseNumber(get("amountMin")),
    amountMax: parseNumber(get("amountMax")),

    /*
      Пустой список уровней означал бы заведомо пустую выборку, и пользователь
      не понял бы, почему ничего не видно. Такое состояние трактуется как
      «фильтр не задан».
    */
    riskLevels: risk && risk.length > 0 ? risk : [...DEFAULT_QUERY_SPEC.riskLevels],
    completenessMin: parseNumber(get("completenessMin")),
    completenessMax: parseNumber(get("completenessMax")),
    onlyCategoryA: get("onlyCategoryA") === "true",

    search: get("search")?.trim() || null,

    sort: SORT_FIELDS.includes(sortRaw as SortField)
      ? (sortRaw as SortField)
      : DEFAULT_QUERY_SPEC.sort,
    order: SORT_ORDERS.includes(orderRaw as SortOrder)
      ? (orderRaw as SortOrder)
      : DEFAULT_QUERY_SPEC.order,
    page: page && page >= 1 ? Math.floor(page) : 1,
    pageSize: pageSize && pageSize >= 1 ? Math.min(Math.floor(pageSize), 200) : 25,
  };
}

/** Отличается ли выборка от умолчания. Страница и сортировка фильтром не считаются. */
export function hasActiveFilters(spec: QuerySpec): boolean {
  const params = toSearchParams(spec);
  for (const ignored of ["page", "page_size", "sort", "order"]) {
    params.delete(ignored);
  }
  return [...params.keys()].length > 0;
}

export interface FilterChip {
  key: keyof QuerySpec;
  label: string;
  value: string;
}

/** Чипы активных фильтров над списком и картой. */
export function activeFilterChips(spec: QuerySpec): FilterChip[] {
  const chips: FilterChip[] = [];

  if (spec.year !== null) {
    chips.push({ key: "year", label: "Период", value: String(spec.year) });
  } else if (spec.dateFrom || spec.dateTo) {
    chips.push({
      key: "dateFrom",
      label: "Период",
      value: `${spec.dateFrom ?? "…"} — ${spec.dateTo ?? "…"}`,
    });
  }

  if (spec.territoryCodes.length > 0) {
    chips.push({
      key: "territoryCodes",
      label: "Территория",
      value: `выбрано: ${spec.territoryCodes.length}`,
    });
  }

  if (spec.objectTypes.length > 0) {
    chips.push({
      key: "objectTypes",
      label: "Тип объекта",
      value: spec.objectTypes.map((t) => OBJECT_TYPE_LABELS[t]).join(", "),
    });
  }

  if (spec.amountMin !== null || spec.amountMax !== null) {
    const low = spec.amountMin !== null ? spec.amountMin.toLocaleString("ru-RU") : "0";
    const high = spec.amountMax !== null ? spec.amountMax.toLocaleString("ru-RU") : "∞";
    chips.push({ key: "amountMin", label: "Сумма", value: `${low} — ${high} ₸` });
  }

  if (!sameList(spec.riskLevels, DEFAULT_QUERY_SPEC.riskLevels)) {
    chips.push({
      key: "riskLevels",
      label: "Уровень риска",
      value: `выбрано: ${spec.riskLevels.length}`,
    });
  }

  if (spec.completenessMin !== null || spec.completenessMax !== null) {
    const low = Math.round((spec.completenessMin ?? 0) * 100);
    const high = Math.round((spec.completenessMax ?? 1) * 100);
    chips.push({ key: "completenessMin", label: "Полнота данных", value: `${low}% — ${high}%` });
  }

  if (spec.onlyCategoryA) {
    chips.push({ key: "onlyCategoryA", label: "Категория", value: "только категория A" });
  }

  if (spec.search) {
    chips.push({ key: "search", label: "Поиск", value: spec.search });
  }

  return chips;
}

/** Снять один фильтр, вернув его к умолчанию. */
export function clearFilter(spec: QuerySpec, key: keyof QuerySpec): QuerySpec {
  const reset: Partial<QuerySpec> = { [key]: DEFAULT_QUERY_SPEC[key] } as Partial<QuerySpec>;

  // Период задаётся парой полей: снимать его по одному бессмысленно.
  if (key === "dateFrom" || key === "dateTo") {
    reset.dateFrom = null;
    reset.dateTo = null;
  }
  if (key === "amountMin" || key === "amountMax") {
    reset.amountMin = null;
    reset.amountMax = null;
  }
  if (key === "completenessMin" || key === "completenessMax") {
    reset.completenessMin = null;
    reset.completenessMax = null;
  }

  // Снятие любого фильтра возвращает на первую страницу: иначе пользователь
  // окажется на седьмой странице выборки, в которой теперь три результата.
  return { ...spec, ...reset, page: 1 };
}

/** Изменить фильтры, сбросив страницу. */
export function withFilters(spec: QuerySpec, patch: Partial<QuerySpec>): QuerySpec {
  const changesPagination = "page" in patch || "pageSize" in patch;
  return { ...spec, ...patch, page: changesPagination ? (patch.page ?? spec.page) : 1 };
}
