/**
 * Список объектов: запрос к API и приведение к виду, который ждёт список.
 *
 * Сервер отдаёт поля в snake_case и своей структурой страницы; компоненты
 * списка объявлены на camelCase со своей. Перевод сделан здесь, в одном месте,
 * а не в компонентах: иначе каждое место, где список отрисовывается, знало бы
 * формат сервера, и любое изменение API пришлось бы искать по всему коду.
 */

import { API_BASE } from "@/lib/api/territories";
import { readToken } from "@/lib/api/auth";
import type { ListItem, ListResponse } from "@/lib/api/types";
import type { ObjectType, QuerySpec } from "@/lib/query-spec";
import type { RiskLevel } from "@/lib/risk";

interface ServerItem {
  object_type: string;
  object_id: string;
  title: string | null;
  subtitle: string | null;
  territory_code: string | null;
  territory_name: string | null;
  amount: number | null;
  amount_unit: string | null;
  risk_score: number | null;
  risk_level: string;
  risk_is_preliminary: boolean;
  risk_completeness: number | null;
  status: string | null;
  source_layer: string;
}

interface ServerResponse {
  items: ServerItem[];
  page: { page: number; page_size: number; total: number; total_pages: number };
  applied_filters: Array<[string, string]>;
  query: Record<string, string>;
}

function toListItem(raw: ServerItem): ListItem {
  return {
    id: `${raw.object_type}:${raw.object_id}`,
    objectType: raw.object_type as ObjectType,
    name: raw.title,
    identifier: raw.object_id,
    territoryCode: raw.territory_code,
    territoryName: raw.territory_name,
    amount: raw.amount,
    amountUnit: raw.amount_unit,
    riskScore: raw.risk_score,
    riskLevel: raw.risk_level as RiskLevel,
    riskScorePreliminary: raw.risk_is_preliminary,
    completeness: raw.risk_completeness,
    /*
      Главные факторы в списке пока не показываются: сервер отдаёт их только
      в карточке объекта. Пустой массив честнее выдуманных значений — список
      просто не покажет блок факторов.
    */
    topFactors: [],
    // `status` — машинный код состояния, `statusLabel` — то, что видит
    // человек. Сервер отдаёт одно значение, и оно годится для обоих: своего
    // словаря состояний у слоёв нет.
    status: raw.status,
    statusLabel: raw.status,
    source: { code: raw.source_layer, title: `Слой ${raw.source_layer}` },
    /*
      Дата актуальности приходит только в карточке объекта: в списке она
      потребовала бы отдельного запроса на каждую строку. `null` честно
      означает «в списке не показывается», и компонент это учитывает.
    */
    actualAt: null,
  };
}

/** Параметры выборки в том виде, в каком их понимает сервер. */
function toServerParams(spec: QuerySpec): URLSearchParams {
  const params = new URLSearchParams();

  params.set("page", String(spec.page));
  params.set("page_size", String(spec.pageSize));
  params.set("sort", spec.sort);
  params.set("order", spec.order);

  if (spec.search) params.set("search", spec.search);
  if (spec.objectTypes.length) params.set("object_types", spec.objectTypes.join(","));
  if (spec.territoryCodes.length) params.set("territory_codes", spec.territoryCodes.join(","));
  if (spec.amountMin !== null) params.set("amount_min", String(spec.amountMin));
  if (spec.amountMax !== null) params.set("amount_max", String(spec.amountMax));

  /*
    Уровни передаются, только когда выбраны не все. Полный набор — это
    отсутствие фильтра, и отправлять его значило бы заставить сервер строить
    условие «IN (все пять значений)» на каждом запросе.
  */
  if (spec.riskLevels.length > 0 && spec.riskLevels.length < 5) {
    params.set("risk_levels", spec.riskLevels.join(","));
  }

  return params;
}

export async function fetchObjects(
  spec: QuerySpec,
  signal?: AbortSignal,
): Promise<ListResponse> {
  const token = readToken();
  const response = await fetch(`${API_BASE}/objects?${toServerParams(spec).toString()}`, {
    signal,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("Сессия не начата или истекла — войдите в систему заново.");
    }
    throw new Error(`Не удалось загрузить список: код ${response.status}`);
  }

  const payload = (await response.json()) as ServerResponse;

  return {
    items: payload.items.map(toListItem),
    page: {
      page: payload.page.page,
      pageSize: payload.page.page_size,
      total: payload.page.total,
      totalPages: payload.page.total_pages,
    },
    aggregates: null,
  };
}
