/**
 * Запросы мастера импорта.
 *
 * Типы повторяют ответы сервера один в один и ничего не «улучшают» по дороге.
 * Причина простая: мастер показывает пользователю числа, за которые он берёт
 * на себя ответственность, нажимая «Подтвердить», и любое переименование поля
 * на клиенте — это лишнее место, где эти числа могут разойтись с серверными.
 *
 * Сопоставление везде хранится в одном направлении: **поле Системы → колонка
 * файла**. У поля источник ровно один, поэтому ключ однозначен; обратное
 * направление потребовало бы разбирать случай «одна колонка в двух полях».
 */

import { request } from "@/lib/api/request";

/** Уровень замечания к качеству данных. */
export type IssueSeverity = "info" | "warning" | "error";

/** Статусный бейдж карточки истории: как на референсе. */
export type JobBadge = "ok" | "warning" | "error" | "rolled_back";

export interface CanonicalFieldInfo {
  code: string;
  title: string;
  type: string;
  required: boolean;
  hint: string;
  aliases: string[];
}

export interface DataKindInfo {
  code: string;
  title: string;
  description: string;
  layer_code: string;
  /** Честное предупреждение о границах загрузки. Показывается на шаге 1. */
  note: string;
  fields: CanonicalFieldInfo[];
  targets: string[];
}

export interface KindsPayload {
  kinds: DataKindInfo[];
  accepted_extensions: string[];
  max_upload_mb: number;
  background_row_threshold: number;
}

export interface MappingTemplate {
  id: string;
  name: string;
  data_kind: string;
  mapping: Record<string, string>;
  created_at: string | null;
}

export interface UploadPayload {
  upload_id: string;
  source_file_id: string;
  file_name: string;
  size_bytes: number;
  sheet_name: string;
  row_count: number;
  columns: string[];
  preview: Array<Record<string, unknown>>;
  suggested_mapping: Record<string, string>;
  background_recommended: boolean;
  templates: MappingTemplate[];
}

export interface IssueRow {
  severity: IssueSeverity;
  code: string;
  message: string;
  /** Адрес строки в источнике. Без него замечание невозможно исправить. */
  row: string | null;
  column: string | null;
  raw_value: string | null;
  context: Record<string, unknown> | null;
}

export interface JobSummary {
  rows_read: number;
  rows_valid: number;
  rows_failed: number;
  duplicates_in_file: number;
  duplicates_in_db: number;
  issues: Record<IssueSeverity, number>;
}

export interface ImportJobPayload {
  id: string;
  layer_code: string | null;
  data_kind: string | null;
  importer: string;
  status: string;
  is_dry_run: boolean;
  data_version: number;
  file_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  rows_read: number;
  rows_created: number;
  rows_updated: number;
  rows_skipped: number;
  rows_failed: number;
  issues: Partial<Record<IssueSeverity, number>>;
  badge: JobBadge;
  summary: JobSummary | null;
  progress: { processed: number; total: number; percent: number } | null;
  territory: Record<string, unknown> | null;
  error_message: string | null;
  can_rollback: boolean;
  issue_list?: IssueRow[];
  background?: boolean;
}

export interface MappingRequest {
  upload_id: string;
  data_kind: string;
  mapping: Record<string, string>;
}

export function fetchKinds(token: string | null, signal?: AbortSignal): Promise<KindsPayload> {
  return request<KindsPayload>("/imports/kinds", { token, signal });
}

export function uploadFile(
  token: string | null,
  dataKind: string,
  file: File,
): Promise<UploadPayload> {
  const form = new FormData();
  form.append("data_kind", dataKind);
  form.append("file", file, file.name);
  return request<UploadPayload>("/imports/upload", { token, method: "POST", body: form });
}

export function dryRun(token: string | null, body: MappingRequest): Promise<ImportJobPayload> {
  return request<ImportJobPayload>("/imports/dry-run", { token, method: "POST", body });
}

export function confirmImport(
  token: string | null,
  body: MappingRequest,
  background = false,
): Promise<ImportJobPayload> {
  return request<ImportJobPayload>("/imports/confirm", {
    token,
    method: "POST",
    body,
    query: { background },
  });
}

export function fetchJobs(
  token: string | null,
  options: { limit?: number; layerCode?: string; signal?: AbortSignal } = {},
): Promise<ImportJobPayload[]> {
  return request<ImportJobPayload[]>("/imports/jobs", {
    token,
    signal: options.signal,
    query: { limit: options.limit ?? 20, layer_code: options.layerCode },
  });
}

export function fetchJob(token: string | null, jobId: string): Promise<ImportJobPayload> {
  return request<ImportJobPayload>(`/imports/jobs/${jobId}`, { token });
}

export function rollbackJob(
  token: string | null,
  jobId: string,
  reason: string,
): Promise<ImportJobPayload> {
  return request<ImportJobPayload>(`/imports/jobs/${jobId}/rollback`, {
    token,
    method: "POST",
    body: { reason },
  });
}

export function saveTemplate(
  token: string | null,
  body: MappingRequest & { name: string },
): Promise<MappingTemplate> {
  return request<MappingTemplate>("/imports/templates", { token, method: "POST", body });
}

export function fetchTemplates(
  token: string | null,
  dataKind: string,
): Promise<MappingTemplate[]> {
  return request<MappingTemplate[]>("/imports/templates", {
    token,
    query: { data_kind: dataKind },
  });
}

/** Подпись статусного бейджа. Цвет не может быть единственным носителем смысла. */
export const BADGE_LABELS: Record<JobBadge, string> = {
  ok: "ОК",
  warning: "Предупрежд.",
  error: "Ошибка",
  rolled_back: "Откачено",
};

export const SEVERITY_LABELS: Record<IssueSeverity, string> = {
  error: "Ошибка",
  warning: "Предупреждение",
  info: "Сведение",
};
