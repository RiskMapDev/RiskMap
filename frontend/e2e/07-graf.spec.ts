import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiContext, auth, loginApi, url } from "./helpers/api";
import { signIn } from "./helpers/auth";

/**
 * Сценарий 7 приёмки: граф открывается, показывает узлы, раскрытие соседа работает.
 *
 * Почему проверяется именно раскрытие. Граф не отдаётся целиком (ТЗ 20):
 * сервер возвращает окружение одного субъекта с ограничением глубины и числа
 * узлов. Значит, единственный способ дойти до дальних связей — раскрывать
 * соседей по одному. Если раскрытие не перезапрашивает сервер, а разворачивает
 * то, что уже пришло, пользователь никогда не увидит связей соседа, которых
 * нет в усечённом подграфе, и заключит, что их не существует.
 *
 * Проверки идут по списку узлов, а не по канве. Канва — это `<canvas>`,
 * заглянуть внутрь неё нельзя ни тесту, ни скринридеру; рядом с ней живёт
 * `GraphNodeList` с тем же содержимым, и это осознанное решение приложения
 * (см. комментарий в `GraphCanvas.tsx`). Тест опирается на него — заодно
 * подтверждая, что текстовое зеркало действительно отражает граф.
 */

/** Запрос, дающий на демо-стенде организации с заметным числом связей. */
const SEARCH_TERM = "ТОО";

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

interface SearchItem {
  key: string;
  label: string;
  degree: number;
  node_type_label: string;
}

async function searchNodes(token: string, query: string): Promise<SearchItem[]> {
  const response = await api.get(url("/graph/search"), { headers: auth(token), params: { q: query } });
  expect(response.status(), "поиск по графу не отвечает").toBe(200);
  const body = (await response.json()) as { items: SearchItem[] };
  return body.items;
}

/** Найти в интерфейсе узел и открыть его окружение. */
async function openNodeByName(page: Page, label: string): Promise<void> {
  const search = page.getByRole("searchbox", {
    name: "Поиск узла по наименованию или ФИО",
  });
  await search.fill(SEARCH_TERM);

  const results = page.getByRole("list", { name: "Найденные узлы" });
  await expect(results, "поиск не вернул ни одного узла").toBeVisible();

  await results.getByRole("button").filter({ hasText: label }).first().click();
}

test.describe("Сценарий 7. Граф связей", () => {
  test("до выбора узла граф не показывает ничего и объясняет почему", async ({ page }) => {
    /*
      Показать «что-нибудь» при входе значило бы либо отдать весь граф, что
      запрещено, либо выбрать узел наугад и выдать случайность за результат.
      Пустой экран здесь — правильное поведение, но только если он объяснён.
    */
    await signIn(page, "analyst");
    await page.goto("/graph");

    await expect(page.getByText("Выберите узел, чтобы построить окружение")).toBeVisible();
    await expect(page.getByRole("region", { name: "Узлы подграфа списком" })).toHaveCount(0);
  });

  test("поиск находит узел, граф строит его окружение с реальными связями", async ({ page }) => {
    const token = await loginApi(api, "analyst");
    const found = await searchNodes(token, SEARCH_TERM);
    expect(found.length, `поиск «${SEARCH_TERM}» ничего не нашёл — стенд без графа`).toBeGreaterThan(
      0,
    );

    // Берём узел с наибольшим числом связей: у него окружение заведомо
    // непустое, и есть кого раскрывать дальше.
    const hub = [...found].sort((a, b) => b.degree - a.degree)[0];
    expect(hub.degree, "у найденных узлов нет ни одной связи").toBeGreaterThan(0);

    const neighbors = await api.get(url("/graph/neighbors"), {
      headers: auth(token),
      params: { node: hub.key, depth: 1, max_nodes: 60 },
    });
    expect(neighbors.status()).toBe(200);
    const subgraph = (await neighbors.json()) as {
      nodes: Array<{ key: string; label: string }>;
      edges: unknown[];
    };

    await signIn(page, "analyst");
    await page.goto("/graph");
    await openNodeByName(page, hub.label);

    // Адрес несёт выбранный узел: ссылка на граф обязана воспроизводить его.
    await expect.poll(() => new URL(page.url()).searchParams.get("node")).toBe(hub.key);

    const list = page.getByRole("region", { name: "Узлы подграфа списком" });
    await expect(list).toBeVisible();

    /*
      Узлов в списке ровно столько, сколько вернул сервер. Проверка «список
      непустой» пропустила бы потерю половины окружения при отрисовке.
    */
    await expect(list.locator("> ul > li")).toHaveCount(subgraph.nodes.length);

    // И это те же узлы, а не какие-нибудь. Сверяем центр и одного соседа.
    await expect(list.getByText(hub.label, { exact: false }).first()).toBeVisible();
    const neighbour = subgraph.nodes.find((node) => node.key !== hub.key);
    expect(neighbour, "у узла-концентратора нет соседей").toBeTruthy();
    await expect(list.getByText(neighbour!.label, { exact: false }).first()).toBeVisible();

    // Канва графа тоже создана — списком она не подменяется, а дополняется.
    await expect(page.locator('[data-testid="graph-canvas"] canvas').first()).toBeVisible();
  });

  test("раскрытие соседа перестраивает граф вокруг него", async ({ page }) => {
    const token = await loginApi(api, "analyst");
    const found = await searchNodes(token, SEARCH_TERM);
    const hub = [...found].sort((a, b) => b.degree - a.degree)[0];

    await signIn(page, "analyst");
    await page.goto("/graph");
    await openNodeByName(page, hub.label);

    const list = page.getByRole("region", { name: "Узлы подграфа списком" });
    await expect(list).toBeVisible();

    // Кнопка «Раскрыть» есть у соседей и отсутствует у центра: раскрывать
    // то, что уже в центре, не имеет смысла.
    const expandButtons = list.getByRole("button", { name: "Раскрыть" });
    const expandable = await expandButtons.count();
    expect(expandable, "ни одного соседа, которого можно раскрыть").toBeGreaterThan(0);
    await expect(list.locator("> ul > li")).toHaveCount(expandable + 1);

    await expandButtons.first().click();

    /*
      Центр графа сменился — это и есть раскрытие. Проверяем по адресу: он
      единственный источник состояния выборки, и если он не изменился, то
      ссылка на «раскрытого» соседа вернёт исходный граф.
    */
    const centerBefore = hub.key;
    await expect
      .poll(
        () => new URL(page.url()).searchParams.get("node"),
        { message: "после раскрытия соседа центр графа не сменился" },
      )
      .not.toBe(centerBefore);

    const newCenter = new URL(page.url()).searchParams.get("node")!;

    // Новое окружение пришло с сервера отдельным запросом, а не развернулось
    // из прежнего ответа: сверяем состав с тем, что отдаёт API для нового
    // центра.
    const fresh = await api.get(url("/graph/neighbors"), {
      headers: auth(token),
      params: { node: newCenter, depth: 1, max_nodes: 60 },
    });
    expect(fresh.status()).toBe(200);
    const freshSubgraph = (await fresh.json()) as { nodes: unknown[] };

    await expect(list.locator("> ul > li")).toHaveCount(freshSubgraph.nodes.length);
  });

  test("карточка узла показывает достоверность связей и происхождение", async ({ page }) => {
    /*
      Связь «предположительная» и связь «достоверная» ведут к разным решениям:
      по первой нельзя ничего утверждать. Если интерфейс не различает их
      словами, а только начертанием линии, то в списке (и в скринридере)
      различие исчезает совсем.
    */
    const token = await loginApi(api, "analyst");
    const found = await searchNodes(token, SEARCH_TERM);
    const hub = [...found].sort((a, b) => b.degree - a.degree)[0];

    await signIn(page, "analyst");
    await page.goto("/graph");
    await openNodeByName(page, hub.label);

    const card = page.getByRole("region", { name: "Карточка узла" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("Источник: слой");
    await expect(card).toContainText(`Всего связей: ${hub.degree}`);

    await expect(page.getByRole("region", { name: "Условные обозначения" })).toBeVisible();
  });
});
