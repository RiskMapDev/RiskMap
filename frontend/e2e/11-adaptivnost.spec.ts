import { expect, test, type Page } from "@playwright/test";

import { signIn } from "./helpers/auth";

/**
 * Адаптивность на трёх разрешениях.
 *
 * Проверяется не «страница открылась», а два конкретных отказа, которые
 * встречаются в такой вёрстке чаще всего и которые пользователь принимает за
 * поломку данных:
 *
 *  1. Горизонтальная прокрутка страницы. На узком экране она означает, что
 *     часть интерфейса уехала за правый край; пользователь её не найдёт и
 *     решит, что кнопки нет.
 *  2. Схлопнувшийся контейнер карты. MapLibre в контейнере нулевой высоты
 *     молча создаёт карту 0×0 и не рисует ничего — экран выглядит как «в
 *     регионе нет объектов». Ровно этот отказ уже случался в проекте (см.
 *     комментарий в `MapScreen.tsx`), поэтому размер холста проверяется
 *     числом на каждом разрешении.
 */

const VIEWPORTS = [
  { name: "1440×900 — рабочее место аналитика", width: 1440, height: 900 },
  { name: "1024×768 — ноутбук и планшет альбомом", width: 1024, height: 768 },
  { name: "390×844 — телефон", width: 390, height: 844 },
] as const;

/** Есть ли у страницы горизонтальная прокрутка. */
async function hasHorizontalOverflow(page: Page): Promise<{ overflow: boolean; by: number }> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    // Допуск в 1 пиксель: дробные размеры при масштабировании дают
    // расхождение, не видимое пользователем и не создающее прокрутки.
    const by = doc.scrollWidth - doc.clientWidth;
    return { overflow: by > 1, by };
  });
}

for (const viewport of VIEWPORTS) {
  test.describe(`Адаптивность: ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("панель показателей помещается по ширине и остаётся читаемой", async ({ page }) => {
      await signIn(page, "analyst");

      await expect(page.getByRole("heading", { name: "Аналитическая панель" })).toBeVisible();
      await expect(page.getByText("Бюджетные наблюдения")).toBeVisible();

      const { overflow, by } = await hasHorizontalOverflow(page);
      expect(overflow, `панель шире экрана на ${by} px — часть содержимого недоступна`).toBe(
        false,
      );

      /*
        Карточка показателя не должна схлопываться в полоску: значение
        обязано оставаться видимым, иначе панель превращается в список
        заголовков без чисел.
      */
      const card = page
        .locator('section[aria-label="Ключевые показатели"] > div > *')
        .filter({ hasText: "Хозяйствующие субъекты" });
      const box = await card.boundingBox();
      expect(box, "карточка показателя не отрисована").toBeTruthy();
      expect(box!.width, "карточка показателя схлопнулась по ширине").toBeGreaterThan(140);
      expect(box!.height, "карточка показателя схлопнулась по высоте").toBeGreaterThan(60);
    });

    test("карта получает ненулевой размер и не создаёт горизонтальной прокрутки", async ({
      page,
    }) => {
      await signIn(page, "analyst");
      await page.goto("/map?view=map");

      const canvas = page.locator('[data-testid="map-container"] canvas');
      await expect(canvas).toBeVisible();

      const box = await canvas.boundingBox();
      expect(box, "холст карты не отрисован").toBeTruthy();
      expect(
        box!.width,
        "карта нулевой ширины: MapLibre не нарисует ничего, а экран будет выглядеть как «объектов нет»",
      ).toBeGreaterThan(100);
      expect(box!.height, "карта нулевой высоты").toBeGreaterThan(100);

      // Карта не должна выпирать за правый край экрана.
      expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);

      const { overflow, by } = await hasHorizontalOverflow(page);
      expect(overflow, `экран карты шире окна на ${by} px`).toBe(false);
    });

    test("переключатель представления доступен на всех разрешениях", async ({ page }) => {
      /*
        По ТЗ 18 на мобильном основной режим — список, и переключатель обязан
        оставаться доступен: без него на телефоне не уйти с карты, которая там
        малополезна.
      */
      await signIn(page, "analyst");
      await page.goto("/map?view=map");

      await expect(page.getByRole("radio", { name: "Списком" })).toBeVisible();
      await expect(page.getByRole("radio", { name: "На карте" })).toBeVisible();

      // Переключение работает и на телефоне, а не только видно.
      await page.getByRole("radio", { name: "Списком" }).click();
      await expect(page.getByRole("radio", { name: "Списком" })).toBeChecked();
      expect(new URL(page.url()).searchParams.get("view")).toBe("list");
    });

    if (viewport.width >= 1024) {
      test("вариант «Карта + список» доступен на широком экране", async ({ page }) => {
        await signIn(page, "analyst");
        await page.goto("/map?view=map");
        await expect(page.getByRole("radio", { name: "Карта + список" })).toBeVisible();
      });
    } else {
      test.fixme(
        "вариант «Карта + список» скрыт на узком экране",
        async () => {
          /*
            ОШИБКА ВЁРСТКИ В ПРИЛОЖЕНИИ.

            `ViewSwitcher` задаёт варианту «split» классы `hidden lg:inline-flex`
            и в комментарии объясняет замысел: две колонки на узком экране не
            помещаются, а `display: none` заодно убирает кнопку из порядка
            обхода с клавиатуры. Замысел не срабатывает — при ширине 390 px у
            кнопки вычисленное `display: flex`, ширина 128 px, и она видима и
            фокусируема. Классы `inline-flex` и `hidden` стоят на одном
            элементе, и в собранном CSS побеждает не тот, который нужен.

            Последствие для пользователя телефона: доступен режим, который на
            его экране не помещается. Правка в `frontend/src/` в этой задаче не
            предусмотрена.
          */
        },
      );
    }

    test("боковое меню либо видно, либо уступает место содержимому", async ({ page }) => {
      /*
        На узком экране сайдбар скрыт по замыслу. Проверка нужна не ради самого
        факта, а ради последствия: если бы он остался, содержимому досталось бы
        меньше половины ширины телефона.
      */
      await signIn(page, "analyst");

      const sidebar = page.getByRole("navigation", { name: "Основная навигация" });
      const main = page.locator("main");
      const mainBox = await main.boundingBox();
      expect(mainBox).toBeTruthy();

      if (viewport.width >= 768) {
        await expect(sidebar).toBeVisible();
      } else {
        await expect(sidebar).toBeHidden();
        expect(
          mainBox!.width,
          "на телефоне содержимому досталось меньше 90 % ширины экрана",
        ).toBeGreaterThan(viewport.width * 0.9);
      }
    });
  });
}
