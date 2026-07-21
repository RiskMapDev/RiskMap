import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, auth, loginApi, url } from "./helpers/api";
import { signIn } from "./helpers/auth";
import { USERS } from "./helpers/env";

/**
 * Сценарий 10 приёмки: роль «Просмотр» и разграничение прав (критерий ТЗ 23.11).
 *
 * Ключевая мысль проверки: интерфейс не источник истины о правах. Скрытая
 * кнопка — удобство, а не защита; отказ обязан приходить от сервера, потому
 * что запрос к API можно отправить и мимо интерфейса. Поэтому здесь
 * проверяются обе стороны: сервер отказывает, а экран объясняет отказ.
 *
 * «Просмотр» по ТЗ 5.4 — минимальная роль: карта и оценки риска. Ни выгрузки,
 * ни обоснования оценки, ни персональных данных, ни администрирования.
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

/** Что роли положено и что запрещено — по ТЗ 5.4. */
const VIEWER_ALLOWED = [
  { path: "/dashboard", why: "аналитическая панель — часть просмотра" },
  { path: "/objects?page_size=1", why: "выборка объектов доступна по map.view" },
  { path: "/objects/summary", why: "сводка по уровням доступна по risk.view" },
  { path: "/territories/layers?level=district", why: "слои карты" },
];

test.describe("Сценарий 10. Роль «Просмотр» и разграничение прав", () => {
  test("роль «Просмотр» получает ровно минимальный набор прав по ТЗ 5.4", async () => {
    const token = await loginApi(api, "viewer");
    const response = await api.get(url("/auth/me"), { headers: auth(token) });
    expect(response.status()).toBe(200);

    const profile = (await response.json()) as {
      role: string;
      role_title: string;
      permissions: string[];
      sensitive_data_access: string;
    };

    expect(profile.role).toBe("viewer");
    expect(profile.role_title).toBe(USERS.viewer.roleTitle);

    const granted = new Set(profile.permissions);

    // Права, которых у роли быть не должно. Каждое названо отдельно: проверка
    // «прав меньше, чем у аналитика» пропустила бы выданную по ошибке выгрузку.
    for (const forbidden of [
      "export.data",
      "report.generate",
      "risk.explain",
      "sensitive.view",
      "data.import",
      "data.edit",
      "users.manage",
      "roles.manage",
      "audit.view",
    ]) {
      expect(granted.has(forbidden), `роли «Просмотр» выдано право ${forbidden}`).toBe(false);
    }

    // Персональные данные скрыты полностью, а не замаскированы.
    expect(profile.sensitive_data_access).toBe("hidden");
  });

  test("закрытые эндпоинты отвечают отказом, а не данными", async () => {
    const token = await loginApi(api, "viewer");

    const denied: Array<{ method: "get" | "post"; path: string; what: string }> = [
      { method: "get", path: "/admin/users", what: "список пользователей" },
      { method: "get", path: "/admin/audit", what: "журнал действий" },
      { method: "get", path: "/imports/kinds", what: "импорт данных" },
    ];

    /*
      `/admin/reference` в этот список намеренно не входит. Он открыт по праву
      `data.view`, которое у роли «Просмотр» есть, — так задумано в
      `admin_routes.py`: справочники территорий и слоёв нужны любому, кто
      вообще смотрит данные. Стоит держать в уме, что вместе с ними в ответ
      попадает раскладка прав по ролям; это не утечка данных наблюдения, но и
      не то, что обязательно показывать минимальной роли.
    */

    for (const item of denied) {
      const response = await api.get(url(item.path), { headers: auth(token) });
      expect(
        response.status(),
        `${item.what} (${item.path}) отдан роли «Просмотр»`,
      ).toBe(403);
    }

    /*
      Расшифровка оценки закрыта отдельным правом `risk.explain`: видеть
      уровень риска и видеть, из каких показателей он сложился, — разные
      полномочия, и второе раскрывает больше, чем первое.
    */
    const objects = await api.get(url("/objects"), {
      headers: auth(token),
      params: { page_size: 1 },
    });
    expect(objects.status(), "роли «Просмотр» закрыт даже список объектов").toBe(200);
    const page = (await objects.json()) as {
      items: Array<{ object_type: string; object_id: string }>;
    };
    const target = page.items[0];

    const card = await api.get(url(`/objects/${target.object_type}/${target.object_id}`), {
      headers: auth(token),
    });
    expect(card.status(), "расшифровка оценки отдана роли без права risk.explain").toBe(403);

    // Выгрузка отчёта — тоже отказ: файл выносит данные за периметр системы.
    const report = await api.post(url("/reports/region-summary"), {
      headers: auth(token),
      params: { format: "docx" },
      data: {},
    });
    expect(report.status(), "отчёт выгружен роли без права export.data").toBe(403);
  });

  test("разрешённое роли «Просмотр» остаётся доступным", async () => {
    /*
      Обратная проверка. Разграничение, закрывающее всё подряд, так же
      неверно, как открывающее всё: роль обязана оставаться работоспособной,
      иначе её выдача бессмысленна.
    */
    const token = await loginApi(api, "viewer");
    for (const item of VIEWER_ALLOWED) {
      const response = await api.get(url(item.path), { headers: auth(token) });
      expect(response.status(), `${item.path} закрыт, хотя ${item.why}`).toBe(200);
    }
  });

  test("экран администрирования отказывает роли «Просмотр» словами", async ({ page }) => {
    await signIn(page, "viewer");
    await page.goto("/admin");

    /*
      Отказ обязан быть виден на экране. Пустая таблица без сообщения читается
      как «пользователей нет», и администратор пойдёт искать пропавшие учётные
      записи вместо того, чтобы выдать себе роль.

      Ищем внутри `main`: Next.js держит в разметке собственный невидимый
      объявитель маршрута с той же ролью `alert`, и без ограничения области
      поиска в выборку попадал бы он.
    */
    await expect(page.getByRole("main").getByRole("alert")).toContainText("Недостаточно прав");

    // И ни одной строки чужих данных не просочилось.
    await expect(page.locator("tbody tr")).toHaveCount(0);
  });

  test("мастер импорта отказывает роли «Просмотр» словами", async ({ page }) => {
    await signIn(page, "viewer");
    await page.goto("/import");

    await expect(page.getByRole("main").getByRole("alert")).toContainText("Недостаточно прав");
  });

  test("администратор видит то, что закрыто роли «Просмотр»", async () => {
    /*
      Без этой проверки предыдущие доказывали бы лишь то, что эндпоинты не
      работают ни у кого. Разграничение — это разница, и её надо показать.
    */
    const token = await loginApi(api, "admin");

    const users = await api.get(url("/admin/users"), { headers: auth(token) });
    expect(users.status(), "администратору закрыт список пользователей").toBe(200);

    const list = (await users.json()) as unknown[] | { items: unknown[] };
    const rows = Array.isArray(list) ? list : list.items;
    expect(rows.length, "список пользователей пуст даже у администратора").toBeGreaterThan(0);

    const audit = await api.get(url("/admin/audit"), { headers: auth(token) });
    expect(audit.status(), "администратору закрыт журнал действий").toBe(200);
  });

  test("журнал действий фиксирует вход — критерий ТЗ 23.12", async () => {
    /*
      Журналирование входит в критерии приёмки отдельным пунктом. Проверяем
      наблюдаемо: вход конкретного пользователя обязан появиться в журнале.
    */
    const viewerToken = await loginApi(api, "viewer");
    expect(viewerToken).toBeTruthy();

    const adminToken = await loginApi(api, "admin");
    // Фильтр по логину, а не просмотр последних записей: журнал общий, и на
    // живом стенде нужное событие могло бы уехать за пределы первой страницы.
    const audit = await api.get(url("/admin/audit"), {
      headers: auth(adminToken),
      params: { user_login: USERS.viewer.login, page_size: 50 },
    });
    expect(audit.status()).toBe(200);

    const body = (await audit.json()) as {
      total: number;
      items: Array<{ user_login: string; action: string }>;
    };

    expect(body.items.length, "в журнале нет ни одной записи о пользователе").toBeGreaterThan(0);
    expect(
      body.items.some((entry) => entry.action === "login_success"),
      "успешный вход не зафиксирован в журнале",
    ).toBe(true);
    for (const entry of body.items) {
      expect(entry.user_login, "фильтр журнала по логину не работает").toContain(
        USERS.viewer.login,
      );
    }
  });

  test("роль «Просмотр» не видит в меню разделов, требующих прав", async ({ page }) => {
    /*
      Данные и без этого защищены: сервер отказывает, и экраны показывают
      «Недостаточно прав». Но вести пользователя в раздел, где его встретит
      отказ, — плохой интерфейс, и меню фильтруется по фактическим правам,
      полученным от сервера, а не по захардкоженной таблице ролей: роли
      настраиваются администратором, и таблица разошлась бы с реальностью.
    */
    await signIn(page, "viewer");
    await page.goto("/dashboard");

    const nav = page.getByRole("navigation", { name: "Основная навигация" });

    await expect(nav.getByRole("link", { name: "Дашборд" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Карта" })).toBeVisible();

    // Разделы, где «Просмотр» получит отказ сервера, в меню не предлагаются.
    await expect(nav.getByRole("link", { name: "Администрирование" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Данные (импорт)" })).toHaveCount(0);
  });

  test("верхняя панель показывает вошедшего, а не «Гостя»", async ({ page }) => {
    /*
      Подпись «Гость» у вошедшего пользователя — не косметика: человек не
      видит, под какой ролью работает, и не понимает, почему часть данных
      скрыта или замаскирована.
    */
    await signIn(page, "analyst");
    await page.goto("/dashboard");

    const header = page.getByRole("banner");
    await expect(header).not.toContainText("Гость");
    await expect(header).toContainText("Аналитик");
  });
});
