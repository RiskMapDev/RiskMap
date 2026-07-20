/**
 * Клиент API.
 *
 * Базовый URL берётся из `NEXT_PUBLIC_API_URL`. Префикс `NEXT_PUBLIC_`
 * обязателен: адрес нужен и на клиенте тоже, а переменные без префикса Next
 * заменяет пустой строкой в клиентском бандле — сломалось бы молча.
 *
 * Секретов здесь нет и быть не должно. Bearer-токен FastAPI читается только на
 * сервере и в этот модуль не попадает: всё, что импортируется клиентским
 * компонентом, уезжает в браузер целиком.
 *
 * Компоненты списка и фильтров этот модуль не импортируют — они получают
 * данные пропсами. Так их можно проверить тестом без сети и без моков HTTP.
 */

import { toSearchParams, type QuerySpec } from "@/lib/query-spec";
import type { FilterOptions, ListResponse } from "@/lib/api/types";

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8100/api/v1";

/**
 * Хвостовой слеш срезается: иначе `${base}/objects` даст `//objects`, и часть
 * серверов ответит редиректом, потеряв заголовки.
 */
export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim();
  return (raw && raw.length > 0 ? raw : DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

/** Ошибка запроса с сохранённым кодом ответа: интерфейс различает 404 и 500. */
export class ApiError extends Error {
  readonly status: number;
  readonly url: string;

  constructor(message: string, status: number, url: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.url = url;
  }
}

/** Собрать адрес запроса списка из канонической выборки. */
export function buildListUrl(spec: QuerySpec, base: string = apiBaseUrl()): string {
  const params = toSearchParams(spec);
  /*
    `toSearchParams` опускает значения по умолчанию — ссылка остаётся читаемой.
    Но серверу страница и размер страницы нужны всегда, иначе он подставит свои
    умолчания, и клиент с сервером разойдутся в том, что такое «страница 1».
  */
  params.set("page", String(spec.page));
  params.set("page_size", String(spec.pageSize));

  const query = params.toString();
  return query ? `${base}/objects?${query}` : `${base}/objects`;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(url, {
      ...init,
      /*
        Кэш выключен явно. В Next 16 fetch по умолчанию не кэшируется, но
        документация сама себе противоречит в разделе `fetchCache`, а показать
        вчерашние риски как сегодняшние — хуже, чем лишний запрос.
      */
      cache: "no-store",
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (cause) {
    // Сеть не ответила: сообщение должно быть про связь, а не про JSON.
    throw new ApiError(
      cause instanceof Error ? cause.message : "Сервер недоступен",
      0,
      url,
    );
  }

  if (!response.ok) {
    throw new ApiError(`Сервер ответил ${response.status}`, response.status, url);
  }

  return (await response.json()) as T;
}

/** Страница списка объектов по текущей выборке. */
export function fetchObjectList(spec: QuerySpec, init?: RequestInit): Promise<ListResponse> {
  return requestJson<ListResponse>(buildListUrl(spec), init);
}

/** Справочники для панели фильтров: районы, отрасли, статусы, годы. */
export function fetchFilterOptions(init?: RequestInit): Promise<FilterOptions> {
  return requestJson<FilterOptions>(`${apiBaseUrl()}/objects/filter-options`, init);
}
