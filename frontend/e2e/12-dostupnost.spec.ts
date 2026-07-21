import { expect, test, type Page } from "@playwright/test";

import { signIn } from "./helpers/auth";

/**
 * Доступность: ориентиры страницы, заголовки и работа с клавиатуры.
 *
 * Требование ТЗ 18. Проверяется то, без чего экран непригоден для работы без
 * мыши и для скринридера:
 *
 *  • ориентиры (`banner`, `navigation`, `main`) — по ним пользователь
 *    скринридера перемещается между областями, не прослушивая всё подряд;
 *  • ровно один заголовок первого уровня — он отвечает на вопрос «где я»;
 *  • ссылка «Перейти к содержимому» — иначе до первой кнопки экрана нужно
 *    протабать через всё меню, и так на каждой странице;
 *  • достижимость основных действий с клавиатуры.
 *
 * Проверка автоматическая и потому неполная: она ловит отсутствие разметки,
 * но не подтверждает, что экраном удобно пользоваться. Это не замена
 * проверке живым пользователем.
 */

/** Экраны, на которых проверяется общий каркас. */
const SCREENS = [
  { path: "/dashboard", heading: "Аналитическая панель" },
  { path: "/graph", heading: "Граф связей" },
  { path: "/reports", heading: "Отчёты и экспорт" },
  { path: "/import", heading: "Загрузка и импорт данных" },
] as const;

/** Кто сейчас в фокусе — в виде, пригодном для сообщения об ошибке. */
async function focused(page: Page): Promise<string> {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (!element) return "ничего";
    const label =
      element.getAttribute("aria-label") ??
      element.textContent?.trim().slice(0, 40) ??
      "";
    return `${element.tagName.toLowerCase()}${label ? ` «${label}»` : ""}`;
  });
}

test.describe("Доступность: ориентиры, заголовки, клавиатура", () => {
  for (const screen of SCREENS) {
    test(`${screen.path}: ориентиры страницы и единственный заголовок первого уровня`, async ({
      page,
    }) => {
      await signIn(page, "analyst");
      await page.goto(screen.path);

      // Ориентиры. Верхняя панель — `banner`, меню — `navigation`,
      // содержимое — `main`.
      await expect(page.getByRole("banner")).toBeVisible();
      await expect(page.getByRole("navigation", { name: "Основная навигация" })).toBeVisible();
      await expect(page.getByRole("main")).toBeVisible();

      /*
        Заголовок первого уровня обязан быть ровно один. Ноль означает, что
        скринридер не назовёт страницу; два и больше — что он назовёт её
        дважды по-разному, и пользователь не поймёт, где находится.
      */
      const h1 = page.getByRole("heading", { level: 1 });
      await expect(h1, `на ${screen.path} должен быть ровно один h1`).toHaveCount(1);
      await expect(h1).toHaveText(screen.heading);

      // Заголовки разделов внутри страницы — второго уровня, без пропусков
      // от h1 сразу к h3: пропуск уровня ломает навигацию по заголовкам.
      const levels = await page.evaluate(() =>
        [...document.querySelectorAll("main h1, main h2, main h3, main h4")].map((node) =>
          Number(node.tagName.slice(1)),
        ),
      );
      let previous = 1;
      for (const level of levels) {
        expect(
          level - previous,
          `на ${screen.path} уровень заголовков перескакивает через ступень (h${previous} → h${level})`,
        ).toBeLessThanOrEqual(1);
        previous = Math.max(previous, level);
      }
    });
  }

  test("первый Tab попадает на ссылку «Перейти к содержимому», и она работает", async ({
    page,
  }) => {
    await signIn(page, "analyst");

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Перейти к содержимому" });
    await expect(skip, `в фокусе оказался ${await focused(page)}`).toBeFocused();

    // Ссылка не декоративная: она обязана быть видимой в фокусе, иначе
    // зрячий пользователь клавиатуры не поймёт, куда попал.
    await expect(skip).toBeVisible();

    await page.keyboard.press("Enter");
    expect(page.url(), "ссылка пропуска не ведёт к содержимому").toContain("#main");
  });

  test("до входа в систему форма заполняется и отправляется одной клавиатурой", async ({
    page,
  }) => {
    /*
      Вход — единственный экран, миновать который нельзя. Если он недоступен с
      клавиатуры, недоступна вся система, сколько бы ни было сделано дальше.
    */
    await page.goto("/login");

    await page.getByLabel("Логин").focus();
    await page.keyboard.type("analyst");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Пароль")).toBeFocused();
    await page.keyboard.type("Ec+Jdkzt87X!");
    await page.keyboard.press("Tab");

    await expect(
      page.getByRole("button", { name: "Войти" }),
      `после поля пароля фокус ушёл на ${await focused(page)}, а не на кнопку входа`,
    ).toBeFocused();

    await page.keyboard.press("Enter");
    await page.waitForURL("**/dashboard");
  });

  test("основные действия панели достижимы с клавиатуры", async ({ page }) => {
    /*
      Переход из показателя в выборку — основное действие панели. Оно сделано
      кнопкой, а не карточкой с обработчиком клика, именно чтобы попадать в
      обход с клавиатуры; проверяем, что так и есть.
    */
    await signIn(page, "analyst");

    const kpi = page
      .locator('section[aria-label="Ключевые показатели"] > div > *')
      .filter({ hasText: "Высокий и критический риск" });
    await expect(kpi).toBeVisible();

    await kpi.focus();
    await expect(kpi, "карточка показателя не принимает фокус с клавиатуры").toBeFocused();

    await page.keyboard.press("Enter");
    await page.waitForURL("**/map**");
    expect(new URL(page.url()).searchParams.get("risk_levels")).toBe("high,critical");
  });

  test("переключатель темы и поиск подписаны для скринридера", async ({ page }) => {
    /*
      Кнопка без доступного имени зачитывается как «кнопка» — пользователь
      обязан нажать её, чтобы узнать назначение. Для необратимых действий это
      недопустимо, для остальных — просто плохо.
    */
    await signIn(page, "analyst");

    const header = page.getByRole("banner");
    const buttons = header.getByRole("button");
    const count = await buttons.count();
    expect(count, "в верхней панели нет ни одной кнопки").toBeGreaterThan(0);

    for (let index = 0; index < count; index += 1) {
      const button = buttons.nth(index);
      const name = (
        (await button.getAttribute("aria-label")) ??
        (await button.innerText())
      ).trim();
      expect(name, `кнопка №${index + 1} в верхней панели без доступного имени`).not.toBe("");
    }

    // У поля глобального поиска есть подпись, пусть и скрытая визуально.
    await expect(page.getByLabel("Поиск по реестрам системы")).toBeVisible();
  });

  test("карта сопровождается текстовыми пояснениями, а не только цветом", async ({ page }) => {
    /*
      Карта — холст, недоступный скринридеру в принципе. Требование ТЗ 18
      выполняется тем, что состав слоёв и причины недоступности изложены
      текстом рядом. Если этот текст исчезнет, карта останется картинкой без
      альтернативы.
    */
    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    const panel = page.locator("aside");
    await expect(panel.getByRole("heading", { level: 2 })).toContainText("Тематические слои");
    await expect(panel.getByText("Нет данных на этом уровне")).toBeVisible();

    // Уровень карты объяснён скринридеру через aria-describedby, а не через
    // title: title подменил бы доступное имя кнопки.
    const level = page.getByRole("button", { name: "Республика" });
    const describedBy = await level.getAttribute("aria-describedby");
    expect(describedBy, "у переключателя уровня нет пояснения для скринридера").toBeTruthy();
    await expect(page.locator(`#${describedBy}`)).toHaveText(/бюджетный слой/);
  });

  test("экран карты имеет заголовок первого уровня", async ({ page }) => {
    /*
      Пользователь скринридера, перейдя на карту, должен услышать название
      страницы, а навигация по заголовкам — начинаться с первого уровня, а не
      сразу со второго.

      Заголовок визуально скрыт (`sr-only`): на карте для него нет места, но
      скринридеру он нужен. Поэтому проверяется наличие в дереве
      доступности, а не видимость на экране.

      Вход обязателен: без сессии оболочка уводит на страницу входа, и
      проверка увидела бы её заголовок вместо заголовка карты.
    */
    await signIn(page, "analyst");
    await page.goto("/map");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toHaveCount(1);
    await expect(heading).toContainText("Карта рисков");
  });
});
