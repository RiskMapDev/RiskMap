import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, fetchDashboard, fetchObjects, loginApi } from "./helpers/api";
import { signIn } from "./helpers/auth";
import { kpiCard } from "./helpers/dashboard";

/**
 * Сценарий 4 приёмки: клик по показателю ведёт в отфильтрованную выборку.
 *
 * Почему проверка важна. Показатель без перехода — тупик: пользователь видит
 * «113 объектов высокого и критического риска» и не может узнать, какие
 * именно. Но опаснее другое: переход, теряющий условие. Если по показателю
 * «Высокий и критический риск» открылась бы выборка без `risk_levels`,
 * пользователь получил бы все 2807 объектов, будучи уверен, что смотрит 113
 * рискованных, — и сделал бы вывод о масштабе проблемы на порядок неверный.
 * Поэтому тест сверяет параметры перехода с тем, что показатель обещает, а
 * обещание — с числом объектов в этой выборке по данным API.
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

test.describe("Сценарий 4. Переход из показателя в выборку", () => {
  test("«Высокий и критический риск» открывает выборку ровно этих уровней", async ({ page }) => {
    const token = await loginApi(api, "analyst");
    const dashboard = await fetchDashboard(api, token);

    const kpi = dashboard.kpis.find((item) => item.code === "high_risk");
    expect(kpi, "показателя high_risk нет в ответе панели").toBeTruthy();
    expect(kpi!.drill_down, "показатель обязан вести в выборку").toEqual({
      risk_levels: "high,critical",
    });

    await signIn(page, "analyst");
    await expect(kpiCard(page, kpi!.title)).toBeVisible();
    await kpiCard(page, kpi!.title).click();

    await page.waitForURL("**/map**");
    const url = new URL(page.url());

    // Условие показателя перенесено в адрес полностью.
    expect(url.searchParams.get("risk_levels")).toBe("high,critical");
    // И режим показа — список: пользователь шёл смотреть перечень объектов,
    // а не территорию на карте.
    expect(url.searchParams.get("view")).toBe("list");

    /*
      Обещание показателя проверяем числом: выборка, в которую ведёт переход,
      обязана содержать ровно столько объектов, сколько напечатано на
      карточке. Расхождение означает, что показатель и выборка считаются
      по-разному, и одно из двух чисел вводит в заблуждение.
    */
    const selection = await fetchObjects(api, token, {
      page_size: 1,
      risk_levels: "high,critical",
    });
    expect(
      selection.page.total,
      "число на карточке не совпадает с размером выборки, в которую она ведёт",
    ).toBe(kpi!.value);
  });

  test("каждый показатель с переходом ведёт в непустую и согласованную выборку", async ({
    page,
  }) => {
    const token = await loginApi(api, "analyst");
    const dashboard = await fetchDashboard(api, token);
    const clickable = dashboard.kpis
      .filter((kpi) => kpi.available && kpi.drill_down !== null)
      // «Хозяйствующие субъекты» исключены не потому, что переход не нужен, а
      // потому что выборка только организаций падает на сервере с 500 —
      // см. отдельный `test.fixme` в конце файла. Молча оставить показатель в
      // общем цикле значило бы вечно красный набор, скрывающий одну ошибку;
      // выбросить проверку совсем — скрыть её насовсем.
      .filter((kpi) => kpi.drill_down!.object_types !== "organization");

    expect(clickable.length, "ни один показатель не ведёт в выборку").toBeGreaterThan(0);

    await signIn(page, "analyst");

    for (const kpi of clickable) {
      await page.goto("/dashboard");
      await expect(kpiCard(page, kpi.title)).toBeVisible();
      await kpiCard(page, kpi.title).click();
      await page.waitForURL("**/map**");

      const url = new URL(page.url());
      for (const [key, value] of Object.entries(kpi.drill_down!)) {
        expect(
          url.searchParams.get(key),
          `переход из «${kpi.title}» потерял условие ${key}`,
        ).toBe(value);
      }

      // Выборка, в которую ведёт переход, не должна быть пустой: показатель
      // с ненулевым значением, открывающий «ничего не найдено», — ошибка
      // сопоставления фильтров, а не отсутствие данных.
      const selection = await fetchObjects(api, token, { page_size: 1, ...kpi.drill_down! });
      expect(
        selection.page.total,
        `переход из «${kpi.title}» ведёт в пустую выборку`,
      ).toBeGreaterThan(0);
    }
  });

  test("недоступный показатель не притворяется ссылкой", async ({ page }) => {
    /*
      «Аналитические материалы и меры» в источниках отсутствуют как сущность.
      Сделать карточку кликабельной значило бы пообещать выборку, которой нет,
      и привести пользователя в пустой экран без объяснения.
    */
    const token = await loginApi(api, "analyst");
    const dashboard = await fetchDashboard(api, token);
    const unavailable = dashboard.kpis.filter((kpi) => !kpi.available);
    test.skip(unavailable.length === 0, "на стенде все показатели доступны");

    await signIn(page, "analyst");

    for (const kpi of unavailable) {
      const card = kpiCard(page, kpi.title);
      await expect(card).toBeVisible();
      await expect(
        card.locator("xpath=self::button"),
        `недоступный показатель «${kpi.title}» отрисован кнопкой`,
      ).toHaveCount(0);
    }
  });

  test.fixme(
    "переход из «Хозяйствующие субъекты» открывает выборку организаций",
    async () => {
      /*
        ОШИБКА В ПРИЛОЖЕНИИ, не отсутствие функции.

        Показатель ведёт в `/map?object_types=organization&view=list`, но
        `GET /api/v1/objects?object_types=organization` отвечает 500 для любой
        роли, включая администратора. Тот же запрос вместе с любым другим
        типом (`object_types=organization,contract`) отрабатывает нормально —
        значит, ломается именно одиночная выборка организаций. То же самое у
        `GET /objects/summary?object_types=organization`.

        Похоже на нетипизированный NULL: в `_organizations_select`
        (`backend/app/services/catalog.py`) колонка `territory_id` задана
        константой `None`, и в одиночном запросе Postgres не может вывести её
        тип для `outerjoin` по `Territory.id`. В объединении с другой выборкой
        тип приходит от соседней ветки, поэтому ошибка и не видна.

        Тест включить после исправления бэкенда — правка `backend/` в этой
        задаче не предусмотрена.
      */
    },
  );
});
