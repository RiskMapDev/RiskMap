/** Запросы аналитической панели. */

import { API_BASE } from "@/lib/api/territories";
import type { RiskLevel } from "@/lib/risk";

export interface KpiPayload {
  code: string;
  title: string;
  /** `null` означает «показателя нет в данных», а не ноль. */
  value: number | null;
  unit: string;
  caption: string;
  definition: string;
  sources: string[];
  data_as_of: string | null;
  available: boolean;
  /** Почему значения нет. Показывается пользователю вместо числа. */
  reason: string;
  drill_down: Record<string, string> | null;
}

export interface DashboardPayload {
  kpis: KpiPayload[];
  risk_distribution: {
    counts: Record<RiskLevel, number>;
    labels: Record<RiskLevel, string>;
    total: number;
    /** Что именно вошло в распределение с учётом прав пользователя. */
    scope_note: string;
  };
  territory_ranking: Array<{ code: string; name: string; risky_count: number }>;
  budget_dynamics: Array<{ period: string; avg_score: number | null; rows: number }>;
  freshness: { territories_as_of: string | null; note: string };
}

export async function fetchDashboard(
  token: string | null,
  signal?: AbortSignal,
): Promise<DashboardPayload> {
  const response = await fetch(`${API_BASE}/dashboard`, {
    signal,
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!response.ok) {
    throw new Error(`Панель не загрузилась: код ${response.status}`);
  }

  return (await response.json()) as DashboardPayload;
}
