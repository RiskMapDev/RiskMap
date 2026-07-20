import { request, type APIRequestContext } from "@playwright/test";

import { API_URL, USERS, type RoleKey } from "./env";

/**
 * Прямой доступ к API — источник ожидаемых значений.
 *
 * Тест обязан сравнивать интерфейс с тем, что действительно лежит в базе.
 * Числа, вписанные в тест руками, проверяют лишь то, что кто-то однажды их
 * туда вписал: после первой же загрузки данных они начинают лгать, и тест
 * приходится «чинить» правкой ожиданий — то есть отключать.
 *
 * Поэтому ожидание берётся из API того же стенда, а сам API проверяется
 * отдельно: несколько опорных величин наполнения (см. `EXPECTED_SCALE`)
 * зафиксированы явно, и если база окажется пустой, тесты упадут на них, а не
 * сойдутся на нулях с обеих сторон.
 */

/** Опорные величины наполнения демо-стенда. Страховка от «ноль равен нулю». */
export const EXPECTED_SCALE = {
  /** Территорий в справочнике: 17 областей + 9 районов + города. */
  territoriesMin: 30,
  /** Договоров слоя 8.4. */
  contractsMin: 300,
  /** Организаций слоя 8.7. */
  organizationsMin: 3000,
  /** Строк бюджетного слоя 8.3: 20 регионов × 12 месяцев. */
  budgetRows: 240,
  /** Объектов в выборке аналитика области. */
  analystObjectsMin: 2000,
};

/**
 * Абсолютный адрес эндпоинта.
 *
 * `baseURL` контекста здесь не годится: Playwright разрешает относительный
 * адрес через `new URL(path, baseURL)`, а путь, начинающийся с косой черты,
 * по правилам URL затирает путь базы целиком — `/api/v1` терялся, и все
 * запросы уходили в корень, где отвечает 404. Собираем адрес сами.
 */
export function url(path: string): string {
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function apiContext(): Promise<APIRequestContext> {
  return request.newContext();
}

export async function loginApi(api: APIRequestContext, role: RoleKey): Promise<string> {
  const user = USERS[role];
  const response = await api.post(url("/auth/login"), {
    data: { login: user.login, password: user.password },
  });

  if (!response.ok()) {
    throw new Error(
      `Вход ${user.login} через API не удался: ${response.status()} ${await response.text()}`,
    );
  }

  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

export function auth(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export interface DashboardKpi {
  code: string;
  title: string;
  value: number | null;
  unit: string;
  available: boolean;
  reason: string;
  drill_down: Record<string, string> | null;
}

export interface DashboardPayload {
  kpis: DashboardKpi[];
  risk_distribution: {
    counts: Record<string, number>;
    labels: Record<string, string>;
    total: number;
    scope_note: string;
  };
  territory_ranking: Array<{ code: string; name: string; risky_count: number }>;
  freshness: { note: string; territories_as_of: string };
}

export async function fetchDashboard(
  api: APIRequestContext,
  token: string,
): Promise<DashboardPayload> {
  const response = await api.get(url("/dashboard"), { headers: auth(token) });
  if (!response.ok()) {
    throw new Error(`GET /dashboard → ${response.status()}`);
  }
  return (await response.json()) as DashboardPayload;
}

export interface ObjectsPage {
  items: Array<{
    object_type: string;
    object_id: string;
    title: string;
    risk_level: string;
    risk_completeness: number | null;
    territory_name: string | null;
  }>;
  page: { page: number; page_size: number; total: number; total_pages: number };
  applied_filters: Array<[string, string]>;
}

export async function fetchObjects(
  api: APIRequestContext,
  token: string,
  query: Record<string, string | number> = {},
): Promise<ObjectsPage> {
  const response = await api.get(url("/objects"), {
    headers: auth(token),
    params: query,
  });
  if (!response.ok()) {
    throw new Error(`GET /objects → ${response.status()}`);
  }
  return (await response.json()) as ObjectsPage;
}

/**
 * Число, как его печатает интерфейс.
 *
 * `Intl` в русской локали разделяет разряды неразрывным пробелом (U+00A0), а в
 * некоторых сборках — узким неразрывным (U+202F). Сравнивать строки посимвольно
 * поэтому нельзя: тест падал бы из-за версии ICU, а не из-за неверного числа.
 * Приводим любой пробельный символ к обычному.
 */
export function normalizeDigits(text: string): string {
  return text.replace(/[\s  ]+/g, " ").trim();
}

/** Ожидаемое представление целого числа в интерфейсе: «3 668». */
export function formatCount(value: number): string {
  return normalizeDigits(new Intl.NumberFormat("ru-RU").format(value));
}
