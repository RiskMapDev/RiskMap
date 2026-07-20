import { expect, type Page } from "@playwright/test";

import { USERS, type RoleKey } from "./env";

/**
 * Вход через настоящую форму, а не подкладыванием токена в `localStorage`.
 *
 * Подложить токен было бы быстрее, но тогда сам вход — критерий приёмки ТЗ 23.11
 * о разграничении прав — не проверялся бы ни одним тестом. К тому же токен,
 * записанный мимо формы, обходит и журналирование входа (ТЗ 23.12).
 */
export async function signIn(page: Page, role: RoleKey): Promise<void> {
  const user = USERS[role];

  await page.goto("/login");
  await page.getByLabel("Логин").fill(user.login);
  await page.getByLabel("Пароль").fill(user.password);
  await page.getByRole("button", { name: "Войти" }).click();

  // Форма делает полную навигацию, чтобы экраны прочитали новый токен при
  // монтировании: ждём именно смены адреса, а не появления разметки.
  await page.waitForURL("**/dashboard", { timeout: 30_000 });

  // Токен должен оказаться в хранилище — иначе следующий экран откроется
  // «гостем» и упадёт с 401 в неожиданном месте.
  const token = await page.evaluate(() => localStorage.getItem("riskmap-token"));
  expect(token, `после входа ${user.login} токен не сохранён`).toBeTruthy();
}

/** Токен текущей сессии страницы — для прямых запросов к API от её имени. */
export async function tokenFromPage(page: Page): Promise<string> {
  const token = await page.evaluate(() => localStorage.getItem("riskmap-token"));
  if (!token) throw new Error("в localStorage нет токена: вход не выполнен");
  return token;
}
