import type { Locator, Page } from "@playwright/test";

import { normalizeDigits } from "./api";
import type { DashboardKpi } from "./api";

/** Секция карточек показателей — по её же `aria-label`, а не по классам. */
export function kpiSection(page: Page): Locator {
  return page.locator('section[aria-label="Ключевые показатели"]');
}

/** Карточка одного показателя. Заголовки показателей уникальны. */
export function kpiCard(page: Page, title: string): Locator {
  return kpiSection(page).locator("> div > *").filter({ hasText: title });
}

/**
 * Как интерфейс печатает значение показателя.
 *
 * Повторяет `formatValue` из `KpiCard`. Повтор осознанный: тест сравнивает
 * *напечатанное* с тем, что вернул сервер, и импортировать сюда ту же функцию
 * значило бы проверять её саму собой — при ошибке в округлении обе стороны
 * ошиблись бы одинаково и тест бы прошёл.
 */
export function formatKpiValue(kpi: Pick<DashboardKpi, "value" | "unit">): string {
  const value = kpi.value ?? 0;
  const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

  if (kpi.unit !== "₸") return normalizeDigits(nf.format(value));

  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2).replace(".", ",")} млрд`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1).replace(".", ",")} млн`;
  return normalizeDigits(nf.format(value));
}

/** Текст карточки показателя с приведёнными пробелами — для сравнения чисел. */
export async function kpiText(page: Page, title: string): Promise<string> {
  return normalizeDigits(await kpiCard(page, title).innerText());
}
