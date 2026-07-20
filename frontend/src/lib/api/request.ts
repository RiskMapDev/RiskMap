/**
 * Запрос к API с токеном доступа.
 *
 * Вынесено в отдельный модуль, потому что мастер импорта и администрирование
 * обращаются к серверу одинаково, а два одинаковых обработчика ошибок
 * разъезжаются при первой же правке — и разъезжаются молча.
 *
 * Ошибку сервера разворачиваем целиком: FastAPI отдаёт `detail` то строкой, то
 * объектом `{code, message}`. Мастеру импорта нужен именно код — по нему
 * различаются «файл великоват» и «в файле не то», а подсказки у них
 * противоположные. Показывать вместо этого «Сервер ответил 400» значит
 * оставить пользователя без единственной полезной части ответа.
 */

import { API_BASE } from "@/lib/api/territories";

export class ApiRequestError extends Error {
  readonly status: number;
  /** Машинный код отказа, если сервер его прислал. */
  readonly code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions {
  method?: string;
  token: string | null;
  signal?: AbortSignal;
  /** Тело запроса. `FormData` уходит как есть — иначе потеряется boundary. */
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
}

function buildUrl(path: string, query: RequestOptions["query"]): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${url}?${search}` : url;
}

async function describeFailure(response: Response): Promise<ApiRequestError> {
  let message = `Сервер ответил ${response.status}`;
  let code: string | null = null;

  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      const record = detail as { code?: unknown; message?: unknown };
      if (typeof record.message === "string") message = record.message;
      if (typeof record.code === "string") code = record.code;
    }
  } catch {
    // Ответ без тела — остаётся общее сообщение с кодом состояния.
  }

  return new ApiRequestError(message, response.status, code);
}

export async function request<T>(path: string, options: RequestOptions): Promise<T> {
  const { method = "GET", token, signal, body, query } = options;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      signal,
      // Кэш выключен явно: показать вчерашнюю историю загрузок как сегодняшнюю
      // хуже, чем сделать лишний запрос.
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        // Content-Type для FormData не ставим — иначе boundary не подставится.
        ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiRequestError(
      cause instanceof Error ? cause.message : "Сервер недоступен",
      0,
      "network",
    );
  }

  if (!response.ok) {
    throw await describeFailure(response);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Человекочитаемая причина отказа — то, что показывается в интерфейсе. */
export function explain(cause: unknown): string {
  if (cause instanceof ApiRequestError) {
    if (cause.status === 401) {
      return "Сессия не начата или истекла — войдите в систему заново.";
    }
    if (cause.status === 403) {
      return "Недостаточно прав для этой операции.";
    }
    return cause.message;
  }
  return cause instanceof Error ? cause.message : "Неизвестная ошибка";
}
