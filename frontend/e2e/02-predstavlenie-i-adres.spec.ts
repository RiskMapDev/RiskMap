import { expect, test } from "@playwright/test";

import { signIn } from "./helpers/auth";

/**
 * Сценарий 2 приёмки: «Списком | На карте» сохраняет выборку и адрес,
 * «назад» возвращает прежнее состояние.
 *
 * Почему это важно именно здесь. Состояние выборки в этой системе живёт в
 * адресной строке (см. `src/lib/query-spec.ts`) ровно для того, чтобы
 * переключение представления не сбрасывало фильтры и чтобы ссылку можно было
 * переслать коллеге. Если при переключении параметры теряются, аналитик,
 * настроивший выборку из десятка условий, теряет её одним нажатием и — что
 * хуже — присылает коллеге ссылку на другую выборку, не заметив подмены.
 */

/** Выборка, которую переключение обязано пронести через себя без потерь. */
const SELECTION = "object_types=contract&risk_levels=high,critical&territory_codes=karasayskiy";

test.describe("Сценарий 2. Переключение представления и история браузера", () => {
  test("переключение «На карте» → «Списком» сохраняет все параметры выборки", async ({
    page,
  }) => {
    await signIn(page, "analyst");
    await page.goto(`/map?${SELECTION}&view=map`);

    const switcher = page.getByRole("radiogroup", { name: "Представление выборки" });
    await expect(switcher).toBeVisible();
    await expect(page.getByRole("radio", { name: "На карте" })).toBeChecked();

    await page.getByRole("radio", { name: "Списком" }).click();

    // Режим сменился и записан в адрес.
    await expect(page.getByRole("radio", { name: "Списком" })).toBeChecked();
    const afterSwitch = new URL(page.url());
    expect(afterSwitch.searchParams.get("view")).toBe("list");

    // Ни один параметр выборки не потерялся — проверяем каждый поимённо, а не
    // «адрес непустой»: потеря одного условия из трёх меняет ответ на вопрос
    // пользователя, оставляя адрес правдоподобным.
    expect(afterSwitch.searchParams.get("object_types")).toBe("contract");
    expect(afterSwitch.searchParams.get("risk_levels")).toBe("high,critical");
    expect(afterSwitch.searchParams.get("territory_codes")).toBe("karasayskiy");
  });

  test("кнопка «назад» возвращает прежнее представление и прежний адрес", async ({ page }) => {
    await signIn(page, "analyst");
    await page.goto(`/map?${SELECTION}&view=map`);
    await expect(page.getByRole("radio", { name: "На карте" })).toBeChecked();

    await page.getByRole("radio", { name: "Списком" }).click();
    await expect(page.getByRole("radio", { name: "Списком" })).toBeChecked();

    await page.goBack();

    /*
      Проверяется не только адрес, но и отмеченная кнопка. Экран читает режим
      из `window.location` и обновляется по событию `popstate`; если подписки
      нет, адрес откатится, а интерфейс останется в прежнем состоянии — и
      пользователь увидит одно, а перешлёт ссылку на другое.
    */
    const afterBack = new URL(page.url());
    expect(afterBack.searchParams.get("view")).toBe("map");
    expect(afterBack.searchParams.get("object_types")).toBe("contract");
    await expect(page.getByRole("radio", { name: "На карте" })).toBeChecked();

    await page.goForward();
    await expect(page.getByRole("radio", { name: "Списком" })).toBeChecked();
    expect(new URL(page.url()).searchParams.get("view")).toBe("list");
  });

  test("переключение стрелками с клавиатуры работает как в шаблоне radiogroup", async ({
    page,
  }) => {
    /*
      Переключатель объявлен группой радиокнопок с роверным tabindex: в группу
      входят одним Tab, дальше перемещаются стрелками. Проверка нужна потому,
      что при обычных кнопках скринридер зачитал бы три несвязанные кнопки
      вместо «2 из 3», а пользователь клавиатуры перебирал бы их по одной.
    */
    await signIn(page, "analyst");
    await page.goto("/map?view=map");

    await page.getByRole("radio", { name: "На карте" }).focus();
    await page.keyboard.press("ArrowRight");

    await expect(page.getByRole("radio", { name: "Карта + список" })).toBeChecked();
    expect(new URL(page.url()).searchParams.get("view")).toBe("split");

    await page.keyboard.press("ArrowLeft");
    await expect(page.getByRole("radio", { name: "На карте" })).toBeChecked();
  });

  test.fixme(
    "режим «Списком» показывает выборку списком",
    async () => {
      /*
        НЕ РЕАЛИЗОВАНО В ПРИЛОЖЕНИИ.

        Компоненты списка написаны и покрыты модульными тестами
        (`src/components/list/ResultList.tsx`, `ResultCard.tsx`, `SortControl.tsx`),
        но ни на один экран не подключены: `MapScreen` держит состояние `view`
        и рисует переключатель, а в разметку всегда выводит карту — ветки для
        `view === "list"` в компоненте нет. Проверить нечего: при `view=list`
        на экране остаётся та же карта.

        Тест намеренно не написан «мягко» — проверка вида «адрес содержит
        view=list» проходила бы, создавая впечатление работающего списка.
      */
    },
  );
});
