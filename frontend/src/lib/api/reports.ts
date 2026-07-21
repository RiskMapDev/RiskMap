/**
 * Отчёты и экспорт: каталог шаблонов, форматы выгрузки, скачивание файла.
 *
 * Формирование отчёта отличается от остальных запросов тем, что ответ — не
 * JSON, а файл. Поэтому здесь не используется общий `request()`: он разбирает
 * тело как JSON и на потоке двоичных данных сломался бы. Разбор ошибок при
 * этом сохранён тот же — сервер отвечает на отказ обычным JSON с `detail`.
 */

import { API_BASE } from "@/lib/api/territories";
import { ApiRequestError } from "@/lib/api/request";
import type { QuerySpec } from "@/lib/query-spec";

/** Шаблон отчёта из каталога сервера. */
export interface ReportTemplateInfo {
  code: string;
  title: string;
  description: string;
}

/**
 * Формат выгрузки.
 *
 * `available` и `reason` приходят с сервера не для красоты: PDF собирается
 * только при установленном `reportlab` и наличии кириллического шрифта, и
 * интерфейс обязан знать об этом ДО нажатия кнопки. Иначе пользователь узнаёт
 * о невозможности выгрузки после ожидания и отказа сервера.
 */
export interface ReportFormatInfo {
  code: string;
  title: string;
  media_type: string;
  available: boolean;
  reason: string;
}

/** Готовый к сохранению файл отчёта. */
export interface ReportFile {
  blob: Blob;
  fileName: string;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJson<T>(path: string, token: string | null, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      signal,
      cache: "no-store",
      headers: { Accept: "application/json", ...authHeaders(token) },
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
    throw new ApiRequestError(`Сервер ответил ${response.status}`, response.status);
  }

  return (await response.json()) as T;
}

export function fetchReportTemplates(
  token: string | null,
  signal?: AbortSignal,
): Promise<ReportTemplateInfo[]> {
  return getJson<ReportTemplateInfo[]>("/reports/templates", token, signal);
}

export function fetchReportFormats(
  token: string | null,
  signal?: AbortSignal,
): Promise<ReportFormatInfo[]> {
  return getJson<ReportFormatInfo[]>("/reports/formats", token, signal);
}

/**
 * Выборка в том виде, в каком её принимает сервер.
 *
 * Модель выборки объявлена с `extra: "forbid"`, поэтому лишних ключей быть не
 * должно, а значения по умолчанию не передаются вовсе: пустое тело означает
 * «всё, что есть», и повторять умолчания значило бы дублировать их в двух
 * местах, которые однажды разойдутся.
 */
export function toServerSpec(spec: QuerySpec): Record<string, unknown> {
  const body: Record<string, unknown> = {};

  if (spec.dateFrom) body.date_from = spec.dateFrom;
  if (spec.dateTo) body.date_to = spec.dateTo;
  if (spec.year !== null) body.year = spec.year;

  if (spec.territoryCodes.length) body.territory_codes = spec.territoryCodes;
  if (!spec.includeChildTerritories) body.include_child_territories = false;

  if (spec.objectTypes.length) body.object_types = spec.objectTypes;
  if (spec.layers.length) body.layers = spec.layers;
  if (spec.industries.length) body.industries = spec.industries;
  if (spec.statuses.length) body.statuses = spec.statuses;

  if (spec.amountMin !== null) body.amount_min = spec.amountMin;
  if (spec.amountMax !== null) body.amount_max = spec.amountMax;

  // Полный набор уровней — это отсутствие фильтра. Передавать его значило бы
  // заставить сервер строить условие «IN (все пять значений)» на каждом отчёте.
  if (spec.riskLevels.length > 0 && spec.riskLevels.length < 5) {
    body.risk_levels = spec.riskLevels;
  }
  if (spec.completenessMin !== null) body.completeness_min = spec.completenessMin;
  if (spec.completenessMax !== null) body.completeness_max = spec.completenessMax;
  if (spec.onlyCategoryA) body.only_category_a = true;

  if (spec.search) body.search = spec.search;

  return body;
}

/**
 * Имя файла из заголовка `Content-Disposition`.
 *
 * Сервер отдаёт два имени сразу: ASCII-запасное в `filename` и настоящее
 * кириллическое в `filename*` по RFC 5987. По RFC 6266 клиент, понимающий
 * `filename*`, обязан предпочесть его — иначе отчёт сохранится с
 * транслитерированным именем, которое человеку читать неудобно.
 */
export function fileNameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;

  const extended = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (extended) {
    try {
      return decodeURIComponent(extended[1].trim());
    } catch {
      // Испорченная кодировка — не повод терять файл: ниже запасное имя.
    }
  }

  const plain = /filename="([^"]+)"/i.exec(header) ?? /filename=([^;]+)/i.exec(header);
  if (plain) return plain[1].trim();

  return fallback;
}

async function describeFailure(response: Response): Promise<ApiRequestError> {
  let message = `Сервер ответил ${response.status}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // Отказ без тела — остаётся код состояния.
  }
  return new ApiRequestError(message, response.status);
}

/**
 * Запасное имя файла из названия шаблона.
 *
 * Нужно чаще, чем хотелось бы. Интерфейс и API работают на разных источниках,
 * а `Content-Disposition` не входит в список заголовков, которые браузер отдаёт
 * межисточниковому запросу по умолчанию: без `Access-Control-Expose-Headers`
 * на сервере заголовок для скрипта попросту не существует, и настоящее имя
 * файла до нас не доходит. Правильное решение — перечислить заголовок на
 * сервере; до тех пор отчёт должен сохраняться под читаемым названием, а не
 * под кодом шаблона вроде «high-risk.docx».
 */
export function fallbackFileName(title: string, template: string, format: string): string {
  // Знаки, недопустимые в именах файлов Windows и нежелательные в остальных.
  const cleaned = title.replace(/[\\/:*?"<>|]/g, " ").replace(/\s+/g, " ").trim();
  return `${cleaned || template}.${format}`;
}

/** Сформировать отчёт и получить файл. Сохранение — забота вызывающего кода. */
export async function generateReport(
  template: string,
  format: string,
  spec: QuerySpec,
  token: string | null,
  signal?: AbortSignal,
  fallbackName?: string,
): Promise<ReportFile> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/reports/${encodeURIComponent(template)}?format=${encodeURIComponent(format)}`,
      {
        method: "POST",
        signal,
        cache: "no-store",
        headers: {
          Accept: "application/octet-stream",
          "Content-Type": "application/json",
          ...authHeaders(token),
        },
        body: JSON.stringify(toServerSpec(spec)),
      },
    );
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiRequestError(
      cause instanceof Error ? cause.message : "Сервер недоступен",
      0,
      "network",
    );
  }

  if (!response.ok) throw await describeFailure(response);

  const blob = await response.blob();
  const fileName = fileNameFromDisposition(
    response.headers.get("Content-Disposition"),
    fallbackName ?? `${template}.${format}`,
  );

  return { blob, fileName };
}

/**
 * Сохранить полученный файл на диск.
 *
 * Вынесено отдельно от `generateReport`, чтобы запрос можно было проверить
 * тестом: в jsdom нет ни настоящей загрузки, ни файловой системы, и смешивать
 * сетевой вызов с обращением к DOM значило бы сделать его непроверяемым.
 */
export function saveFile({ blob, fileName }: ReportFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Ссылка на объект живёт до перезагрузки страницы; браузер её сам не
  // отпустит, а отчёты — файлы на мегабайты.
  URL.revokeObjectURL(url);
}
