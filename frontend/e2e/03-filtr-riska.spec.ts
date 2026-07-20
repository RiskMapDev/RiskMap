import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, fetchObjects, loginApi } from "./helpers/api";
import { signIn } from "./helpers/auth";

/**
 * Сценарий 3 приёмки: фильтр по уровню риска применяется и виден в адресе и чипах.
 *
 * Состояние здесь особое, и его нужно назвать прямо. Панель фильтров и чипы
 * активных фильтров в проекте **написаны** — `src/components/filters/FilterPanel.tsx`
 * и `FilterChips.tsx`, оба с модульными тестами, — но **не подключены ни к
 * одному экрану**: поиск по `src/` не находит ни одного места, где они
 * отрисовываются. Ни на карте, ни на панели, ни где-либо ещё пользователь не
 * может задать уровень риска через интерфейс.
 *
 * Поэтому сквозной проверки «нажал в фильтре — увидел чип» здесь нет: она
 * помечена `test.fixme` ниже. Вместо неё проверяется то, что действительно
 * работает и на чём фильтр будет держаться, когда панель подключат: сервер
 * фильтрует по уровню и возвращает готовую подпись чипа. Иначе после
 * подключения панели выяснилось бы, что фильтровать нечем.
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

test.describe("Сценарий 3. Фильтр по уровню риска", () => {
  test("сервер сужает выборку по уровню и подписывает чип", async () => {
    const token = await loginApi(api, "analyst");

    const all = await fetchObjects(api, token, { page_size: 1 });
    const critical = await fetchObjects(api, token, { page_size: 1, risk_levels: "critical" });
    const high = await fetchObjects(api, token, { page_size: 1, risk_levels: "high" });
    const both = await fetchObjects(api, token, {
      page_size: 1,
      risk_levels: "high,critical",
    });

    // Фильтр обязан сужать, а не просто возвращать что-нибудь: выборка без
    // фильтра строго больше отфильтрованной.
    expect(all.page.total, "выборка без фильтра пуста — проверять нечего").toBeGreaterThan(0);
    expect(critical.page.total).toBeGreaterThan(0);
    expect(critical.page.total).toBeLessThan(all.page.total);

    /*
      Два уровня дают ровно сумму двух выборок по одному. Проверка ловит самую
      частую ошибку такого фильтра — трактовку списка как «И» вместо «ИЛИ»:
      при ней ответ был бы пуст, а интерфейс сообщил бы «объектов не найдено»,
      что пользователь прочитает как «таких рисков нет».
    */
    expect(both.page.total, "high,critical должно быть объединением, а не пересечением").toBe(
      critical.page.total + high.page.total,
    );

    // Все элементы страницы действительно того уровня, который запрошен.
    const sample = await fetchObjects(api, token, { page_size: 25, risk_levels: "critical" });
    const levels = new Set(sample.items.map((item) => item.risk_level));
    expect([...levels], "в выборку по «критический» попали другие уровни").toEqual(["critical"]);

    // Подпись чипа приходит с сервера — интерфейсу не нужно её выдумывать.
    expect(critical.applied_filters).toContainEqual(["Уровень риска", "Критический"]);
  });

  test("выборка по уровню воспроизводится ссылкой", async ({ page }) => {
    /*
      Ключевое требование к состоянию выборки: адрес — единственный источник
      истины. Даже пока панель фильтров не подключена, параметр обязан
      переживать перезагрузку страницы; если бы адрес чистился при монтировании
      экрана, пересланная ссылка открывала бы у коллеги другую выборку.
    */
    await signIn(page, "analyst");

    await page.goto("/map?risk_levels=high,critical&view=map");
    await expect(page.getByRole("radio", { name: "На карте" })).toBeChecked();

    await page.reload();
    const url = new URL(page.url());
    expect(url.searchParams.get("risk_levels")).toBe("high,critical");
  });

  test.fixme(
    "панель фильтров задаёт уровень риска и показывает чип над выборкой",
    async () => {
      /*
        НЕ РЕАЛИЗОВАНО В ПРИЛОЖЕНИИ.

        `FilterPanel` и `FilterChips` существуют в `src/components/filters/`,
        но не смонтированы ни на одном экране — задать уровень риска через
        интерфейс невозможно, снять чип тоже. Проверять нечего.

        Что должен делать этот тест, когда панель подключат: открыть панель,
        снять уровни кроме «критический», убедиться, что в адресе появилось
        `risk_levels=critical`, над выборкой — чип «Уровень риска: выбрано 1»,
        число объектов совпало с `GET /objects?risk_levels=critical`, а
        закрытие чипа вернуло полную выборку.
      */
    },
  );
});
