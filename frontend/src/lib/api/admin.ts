/**
 * Запросы экранов администрирования.
 *
 * Четыре вкладки референса — четыре группы запросов. Права ни одна из них не
 * проверяет: клиент не источник истины о правах, и единственное, что он умеет
 * делать с отказом, — показать его пользователю. Скрывать вкладку целиком по
 * ответу 403 тоже нельзя: пользователь должен понимать, что раздел существует
 * и почему он ему недоступен.
 */

import { request } from "@/lib/api/request";

export interface AdminUser {
  id: string;
  login: string;
  full_name: string;
  email: string | null;
  role: string;
  role_title: string;
  territory_id: string | null;
  /** Готовая подпись: «Все районы» вместо пустого места. */
  territory: string;
  last_login_at: string | null;
  is_active: boolean;
  is_locked: boolean;
  failed_login_attempts: number;
}

export interface PermissionInfo {
  code: string;
  title: string;
  description: string;
}

export interface RoleInfo {
  code: string;
  title: string;
  description: string | null;
  sensitive_data_access: string;
  users_count: number;
  permissions: PermissionInfo[];
}

export interface TerritoryRow {
  id: string;
  code: string;
  name_ru: string;
  name_kk: string | null;
  level: string;
  parent_id: string | null;
  is_current: boolean;
}

export interface ReferencePayload {
  territories: TerritoryRow[];
  roles: RoleInfo[];
  sensitive_access_levels: Array<{ code: string; title: string }>;
  risk_levels: Array<{ code: string; title: string }>;
}

export interface IndicatorInfo {
  code: string;
  name: string;
  weight: number;
  direction: string;
  source: string;
}

export interface ThresholdInfo {
  from_score: number;
  level: string;
  title: string;
}

export interface RiskModelVersion {
  version: string | null;
  based_on: string | null;
  comment: string;
  weights: Array<{ code: string; weight: number }>;
  thresholds: Array<{ from_score: number; level: string }>;
  changed_by: string | null;
  changed_at: string;
}

export interface RiskModelInfo {
  code: string;
  title: string;
  /** Действующая версия: последняя редакция либо исходная из кода. */
  version: string;
  base_version: string;
  scale: number;
  min_completeness: number | null;
  notes: string;
  indicators: IndicatorInfo[];
  thresholds: ThresholdInfo[];
  history: RiskModelVersion[];
}

export interface AuditEntry {
  id: string;
  occurred_at: string;
  user_login: string | null;
  action: string;
  action_title: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  request_id: string | null;
  details: Record<string, unknown> | null;
}

export interface AuditPage {
  total: number;
  page: number;
  page_size: number;
  items: AuditEntry[];
  actions: Array<{ code: string; title: string }>;
}

export interface AuditFilters {
  userLogin?: string;
  action?: string;
  dateFrom?: string;
  dateTo?: string;
  page?: number;
  pageSize?: number;
}

export function fetchUsers(token: string | null, signal?: AbortSignal): Promise<AdminUser[]> {
  return request<AdminUser[]>("/admin/users", { token, signal });
}

export function createUser(
  token: string | null,
  body: {
    login: string;
    full_name: string;
    password: string;
    role_code: string;
    territory_id?: string | null;
    email?: string | null;
  },
): Promise<AdminUser> {
  return request<AdminUser>("/admin/users", { token, method: "POST", body });
}

export function updateUser(
  token: string | null,
  userId: string,
  body: {
    full_name?: string;
    role_code?: string;
    territory_id?: string | null;
    is_active?: boolean;
    reset_lockout?: boolean;
  },
): Promise<AdminUser> {
  return request<AdminUser>(`/admin/users/${userId}`, { token, method: "PATCH", body });
}

export function fetchReference(
  token: string | null,
  signal?: AbortSignal,
): Promise<ReferencePayload> {
  return request<ReferencePayload>("/admin/reference", { token, signal });
}

export function fetchRiskModels(
  token: string | null,
  signal?: AbortSignal,
): Promise<RiskModelInfo[]> {
  return request<RiskModelInfo[]>("/admin/risk-models", { token, signal });
}

export function updateRiskModel(
  token: string | null,
  modelCode: string,
  body: {
    version: string;
    weights: Array<{ code: string; weight: number }>;
    thresholds: Array<{ from_score: number; level: string }>;
    comment: string;
  },
): Promise<RiskModelInfo> {
  return request<RiskModelInfo>(`/admin/risk-models/${modelCode}`, {
    token,
    method: "PUT",
    body,
  });
}

export function fetchAuditLog(
  token: string | null,
  filters: AuditFilters = {},
  signal?: AbortSignal,
): Promise<AuditPage> {
  return request<AuditPage>("/admin/audit", {
    token,
    signal,
    query: {
      user_login: filters.userLogin,
      action: filters.action,
      date_from: filters.dateFrom,
      date_to: filters.dateTo,
      page: filters.page ?? 1,
      page_size: filters.pageSize ?? 50,
    },
  });
}

/** Вкладки экрана администрирования — порядок с референса. */
export const ADMIN_TABS = [
  { code: "users", title: "Пользователи" },
  { code: "reference", title: "Справочники" },
  { code: "risk", title: "Критерии риска" },
  { code: "audit", title: "Журнал действий" },
] as const;

export type AdminTab = (typeof ADMIN_TABS)[number]["code"];

export function isAdminTab(value: string): value is AdminTab {
  return ADMIN_TABS.some((tab) => tab.code === value);
}
