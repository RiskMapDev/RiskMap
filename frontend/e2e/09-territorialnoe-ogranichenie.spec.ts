import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  apiContext,
  fetchDashboard,
  fetchObjects,
  formatCount,
  loginApi,
  normalizeDigits,
} from "./helpers/api";
import { signIn } from "./helpers/auth";
import { kpiText } from "./helpers/dashboard";
import { USERS } from "./helpers/env";

/**
 * Сценарий 9 приёмки: территориальное ограничение роли.
 *
 * `analyst` и `analyst.karasay` — одна и та же роль «Аналитик» с одинаковым
 * набором прав. Различаются они только территорией: первый привязан к
 * Алматинской области, второй — к Карасайскому району. Если второй увидит
 * столько же объектов, сколько первый, значит ограничение не работает вовсе, и
 * никакие права уже ничего не ограничивают: роль не единственная ось доступа.
 *
 * Проверка идёт с двух сторон. Сначала — что сервер действительно отдаёт
 * разные выборки (иначе интерфейсу неоткуда взять разницу). Затем — что
 * интерфейс показывает именно свою, урезанную, и объясняет пользователю, что
 * выборка неполна: число, меньшее ожидаемого, без объяснения читается как
 * «в районе мало объектов», а не как «вам видно не всё».
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

test.describe("Сценарий 9. Территориальное ограничение видимости", () => {
  test("сервер отдаёт аналитику района строго меньшую выборку, чем аналитику области", async () => {
    const oblast = await loginApi(api, "analyst");
    const rayon = await loginApi(api, "analystKarasay");

    const oblastObjects = await fetchObjects(api, oblast, { page_size: 1 });
    const rayonObjects = await fetchObjects(api, rayon, { page_size: 1 });

    expect(oblastObjects.page.total, "выборка аналитика области пуста").toBeGreaterThan(0);
    expect(rayonObjects.page.total, "выборка аналитика района пуста").toBeGreaterThan(0);

    /*
      Именно «строго меньше», а не «не больше». Равенство означало бы, что
      ограничение не применилось; ноль означал бы, что оно применилось слишком
      жёстко и роль стала бесполезной. Оба исхода — отказ.
    */
    expect(
      rayonObjects.page.total,
      `${USERS.analystKarasay.login} (${USERS.analystKarasay.scope}) видит не меньше, чем ` +
        `${USERS.analyst.login} (${USERS.analyst.scope})`,
    ).toBeLessThan(oblastObjects.page.total);

    // Все объекты урезанной выборки — из своей территории. Проверяем состав,
    // а не только количество: правильное число при чужих объектах внутри было
    // бы худшим из возможных отказов.
    const sample = await fetchObjects(api, rayon, { page_size: 50 });
    const territories = new Set(
      sample.items.map((item) => item.territory_name).filter((name): name is string => !!name),
    );
    expect(
      [...territories],
      "в выборку аналитика района попали чужие территории",
    ).toEqual(["Карасайский район"]);
  });

  test("панель аналитика района показывает свои числа, а не областные", async ({ page }) => {
    const oblastToken = await loginApi(api, "analyst");
    const rayonToken = await loginApi(api, "analystKarasay");

    const oblast = await fetchDashboard(api, oblastToken);
    const rayon = await fetchDashboard(api, rayonToken);

    expect(
      rayon.risk_distribution.total,
      "распределение по риску у района не меньше областного",
    ).toBeLessThan(oblast.risk_distribution.total);

    await signIn(page, "analystKarasay");

    // Итог диаграммы — свой, районный.
    await expect(
      page.getByText(`${formatCount(rayon.risk_distribution.total)} объектов всего`),
    ).toBeVisible();

    // И заведомо не областной: одно и то же число у обоих означало бы, что
    // панель считает по всей области независимо от того, кто вошёл.
    await expect(
      page.getByText(`${formatCount(oblast.risk_distribution.total)} объектов всего`),
    ).toHaveCount(0);

    /*
      Пояснение о составе выборки обязательно. Аналитик района видит числа
      меньше, чем коллега за соседним столом, и без явной оговорки это выглядит
      потерей данных, а не ограничением доступа.
    */
    await expect(page.getByText(rayon.risk_distribution.scope_note)).toBeVisible();
  });

  test("денежные показатели района меньше областных", async ({ page }) => {
    /*
      Отдельная проверка сумм: ограничение может примениться к перечню
      объектов, но не к агрегатам — тогда карточка покажет районному аналитику
      областную сумму субсидий, и он оценит масштаб на два порядка неверно.
    */
    const oblastToken = await loginApi(api, "analyst");
    const rayonToken = await loginApi(api, "analystKarasay");

    const oblast = await fetchDashboard(api, oblastToken);
    const rayon = await fetchDashboard(api, rayonToken);

    const money = ["procurement", "subsidies", "risk_exposure"];
    for (const code of money) {
      const wide = oblast.kpis.find((kpi) => kpi.code === code);
      const narrow = rayon.kpis.find((kpi) => kpi.code === code);
      expect(wide?.value, `показателя ${code} нет в ответе`).toBeTruthy();
      expect(
        narrow!.value!,
        `показатель «${wide!.title}» у аналитика района не меньше областного`,
      ).toBeLessThan(wide!.value!);
    }

    await signIn(page, "analystKarasay");

    // Показатель без территориальной привязки — «Хозяйствующие субъекты» —
    // напротив, обязан совпасть: организаций слоя 8.7 территория не касается,
    // и урезать их было бы выдумкой.
    const organizations = rayon.kpis.find((kpi) => kpi.code === "organizations")!;
    const oblastOrganizations = oblast.kpis.find((kpi) => kpi.code === "organizations")!;
    expect(organizations.value).toBe(oblastOrganizations.value);

    const text = await kpiText(page, organizations.title);
    expect(normalizeDigits(text)).toContain(formatCount(organizations.value!));
  });

  test("территориальное ограничение нельзя обойти параметром адреса", async () => {
    /*
      Самая важная проверка блока. Ограничение обязано жить на сервере: если
      его накладывает только интерфейс, достаточно вписать чужой код
      территории в адрес, чтобы получить закрытые данные. Запрашиваем от имени
      районного аналитика соседний район.
    */
    const rayon = await loginApi(api, "analystKarasay");

    const foreign = await fetchObjects(api, rayon, {
      page_size: 25,
      territory_codes: "talgarskiy",
    });

    expect(
      foreign.page.total,
      "аналитик Карасайского района получил объекты Талгарского района через параметр адреса",
    ).toBe(0);
  });
});
