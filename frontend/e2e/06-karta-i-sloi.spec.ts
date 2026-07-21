import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, auth, loginApi, url } from "./helpers/api";
import { signIn } from "./helpers/auth";

/**
 * Сценарий 6 приёмки: карта отрисовывается, панель слоёв называет недоступные
 * слои и причину недоступности.
 *
 * Почему причина важнее самого списка. Слой, которого нет на текущем уровне,
 * можно было бы просто не показывать — интерфейс стал бы короче. Но тогда
 * пользователь, глядя на карту районов без бюджетного слоя, остался бы в
 * уверенности, что видит все данные, и сделал бы вывод «по бюджету вопросов
 * нет» из того, что бюджет вообще не измерялся на этом уровне. Названный слой
 * с причиной превращает молчание в утверждение, которое можно проверить.
 */

interface LayerInfo {
  code: string;
  title: string;
  available: boolean;
  unavailability_reason: string | null;
}

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

async function layers(token: string, level: "region" | "district"): Promise<LayerInfo[]> {
  const response = await api.get(url("/territories/layers"), {
    headers: auth(token),
    params: { level },
  });
  expect(response.status()).toBe(200);
  return (await response.json()) as LayerInfo[];
}

test.describe("Сценарий 6. Карта и панель тематических слоёв", () => {
  test("карта отрисовывает границы районов, а не пустой холст", async ({ page }) => {
    const token = await loginApi(api, "analyst");

    // Сколько районов сервер отдаёт на районном уровне — столько геометрий и
    // должно доехать до браузера.
    const geo = await api.get(url("/territories/geojson"), {
      headers: auth(token),
      params: { level: "district", parent: "almaty-oblast", zoom: 7 },
    });
    expect(geo.status()).toBe(200);
    const payload = (await geo.json()) as {
      features: Array<{ properties: { name_ru: string } }>;
      attribution: string;
    };
    expect(payload.features.length, "сервер не отдал ни одной границы").toBeGreaterThan(0);

    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    // Холст MapLibre появился. Сам по себе он ничего не доказывает — карта
    // 0×0 тоже создаёт холст, — поэтому ниже проверяются размеры и данные.
    const canvas = page.locator('[data-testid="map-container"] canvas');
    await expect(canvas).toBeVisible();

    const box = await canvas.boundingBox();
    expect(box, "холст карты не получил размеров").toBeTruthy();
    expect(box!.width, "карта нулевой ширины — MapLibre ничего не нарисует").toBeGreaterThan(200);
    expect(box!.height, "карта нулевой высоты").toBeGreaterThan(200);

    /*
      Обязательная атрибуция источника границ. Она не косметика: границы взяты
      из OpenStreetMap под ODbL, и лицензия требует указания источника.
    */
    await expect(page.getByText(payload.attribution, { exact: false }).first()).toBeVisible();

    // Ошибку загрузки границ карта показывает текстом. Её быть не должно.
    await expect(page.getByText("Границы не загрузились")).toHaveCount(0);
  });

  test("панель слоёв показывает доступные слои и их число", async ({ page }) => {
    const token = await loginApi(api, "analyst");
    const districtLayers = await layers(token, "district");
    const available = districtLayers.filter((layer) => layer.available);

    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const panel = page.locator("aside");
    await expect(panel).toBeVisible();

    // Заголовок панели несёт счётчик «доступно / всего» — числа берём из API.
    await expect(
      panel.getByText(`Тематические слои (${available.length} / ${districtLayers.length})`),
    ).toBeVisible();

    for (const layer of available) {
      await expect(
        panel.getByText(layer.title, { exact: true }),
        `слой «${layer.title}» доступен, но не показан`,
      ).toBeVisible();
    }
  });

  test("недоступные слои перечислены вместе с причиной", async ({ page }) => {
    const token = await loginApi(api, "analyst");
    const districtLayers = await layers(token, "district");
    const unavailable = districtLayers.filter(
      (layer) => !layer.available && layer.unavailability_reason,
    );

    expect(
      unavailable.length,
      "на районном уровне все слои доступны — проверять сокрытие нечем",
    ).toBeGreaterThan(0);

    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const panel = page.locator("aside");
    await expect(panel.getByText("Нет данных на этом уровне")).toBeVisible();

    for (const layer of unavailable) {
      await expect(
        panel.getByText(layer.title, { exact: true }),
        `недоступный слой «${layer.title}» просто спрятан вместо объяснения`,
      ).toBeVisible();

      /*
        Причина сверяется с ответом сервера дословно (первые слова — остальное
        может переноситься). Пересказ причины в интерфейсе своими словами
        неизбежно разошёлся бы с данными.
      */
      /*
        `.first()` здесь не небрежность: причина «данные слоя есть только на
        уровне: область» одна и та же у бюджета и у проектов ГЧП, и совпадений
        в панели закономерно два.
      */
      const reason = layer.unavailability_reason!.slice(0, 40);
      await expect(
        panel.getByText(reason, { exact: false }).first(),
        `слой «${layer.title}» перечислен без причины`,
      ).toBeVisible();
    }
  });

  test("смена уровня карты меняет состав слоёв — так же, как на сервере", async ({ page }) => {
    /*
      Уровни различаются не масштабом, а составом данных: бюджет существует
      только по областям, закупки и субсидии — только по районам. Если панель
      не пересчитывает состав при смене уровня, пользователь увидит бюджетный
      слой там, где его нет, включит его и получит пустую карту без объяснения.
    */
    const token = await loginApi(api, "analyst");
    const regionLayers = await layers(token, "region");
    const budget = regionLayers.find((layer) => layer.code === "budget");
    expect(budget?.available, "бюджетный слой обязан быть доступен на уровне области").toBe(true);

    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const panel = page.locator("aside");
    // На районном уровне бюджет лежит в разделе «нет данных».
    await expect(panel.getByText("Нет данных на этом уровне")).toBeVisible();

    await page.getByRole("button", { name: "Республика" }).click();

    const availableRegion = regionLayers.filter((layer) => layer.available);
    await expect(
      panel.getByText(`Тематические слои (${availableRegion.length} / ${regionLayers.length})`),
    ).toBeVisible();

    /*
      Бюджетный слой переехал в доступные — с переключателем, а не в списке
      причин. Именно переключатель, а не флажок: заливка показывает один слой,
      потому что у полигона один цвет, и совместить на нём закупки с
      субсидиями нельзя, не солгав о том, чей это уровень риска.
    */
    await expect(
      panel.getByRole("radio").locator("xpath=ancestor::label").filter({ hasText: budget!.title }),
    ).toHaveCount(1);
  });

  test("выбор слоя перекрашивает карту по уровню риска этого слоя", async ({ page }) => {
    /*
      Ради этого весь слой и существует. Проверяется не наличие переключателя,
      а то, что после переключения в браузер приезжают границы с уровнями
      риска выбранного слоя: карта, запросившая слой и не получившая оценок,
      выглядела бы ровно так же, как работающая, — сплошной серой заливкой.
    */
    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const ответ = page.waitForResponse(
      (response) =>
        response.url().includes("/territories/geojson") &&
        response.url().includes("layer=procurement"),
    );

    await page
      .getByRole("radio", { name: "Государственные закупки", exact: true })
      .check();

    const данные = (await (await ответ).json()) as {
      features: Array<{ properties: { name_ru: string; risk_level: string } }>;
    };

    const уровни = new Set(данные.features.map((f) => f.properties.risk_level));

    // По закупкам районы расходятся: есть и критические, и неизмеренные.
    // Один уровень на все районы означал бы, что заливка ни от чего не зависит.
    expect(уровни.size, `все районы одного уровня: ${[...уровни]}`).toBeGreaterThan(1);
    for (const уровень of уровни) {
      expect(["low", "medium", "high", "critical", "unknown"]).toContain(уровень);
    }

    /*
      Район, где договоров нет, обязан быть серым, а не зелёным. Зелёный
      сказал бы «проверено, риск низкий» там, где не проверено ничего, — и
      это ровно та подмена, которую ТЗ запрещает.
    */
    const пустые = данные.features.filter(
      (f) => (f.properties as { objects_total?: number }).objects_total === 0,
    );
    expect(пустые.length, "в выборке нет района без договоров").toBeGreaterThan(0);
    for (const район of пустые) {
      expect(
        район.properties.risk_level,
        `${район.properties.name_ru} без договоров окрашен как измеренный`,
      ).toBe("unknown");
    }
  });

  test("легенда называет все пять уровней и долю показанных объектов", async ({ page }) => {
    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const panel = page.locator("aside");
    for (const уровень of ["Низкий", "Средний", "Высокий", "Критический", "Нет данных"]) {
      await expect(panel.getByText(уровень, { exact: true }).first()).toBeVisible();
    }

    /*
      Доля показанных объектов — не украшение. Слой экспертизы попадает на
      районную карту на 7 %: без числа карта выглядит полной, и пользователь
      сделает вывод обо всей совокупности по её двадцатой части.
    */
    await expect(panel.getByText(/На карте .* из .* объектов слоя/)).toBeVisible();
  });
});
