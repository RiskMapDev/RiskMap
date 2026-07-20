import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  EXPECTED_SCALE,
  apiContext,
  fetchDashboard,
  formatCount,
  loginApi,
  normalizeDigits,
} from "./helpers/api";
import { signIn } from "./helpers/auth";
import { formatKpiValue, kpiCard, kpiSection, kpiText } from "./helpers/dashboard";
import { USERS, type RoleKey } from "./helpers/env";

/**
 * Сценарий 1 приёмки: вход по роли и аналитическая панель с настоящими числами.
 *
 * Смысл проверки не в том, что панель отрисовалась. Отрисованная панель с
 * нулями выглядит работающей, но означает противоположное: либо запрос не
 * дошёл, либо выборка пуста, либо интерфейс подставил заглушку вместо данных.
 * Именно нули — самый опасный отказ этой системы: пользователь принимает
 * решение по картине «рисков нет», которой на самом деле никто не измерял.
 * Поэтому тест сверяет напечатанное с ответом API того же стенда и отдельно
 * убеждается, что база вообще наполнена (`EXPECTED_SCALE`).
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

const ROLES_WITH_DASHBOARD: RoleKey[] = ["admin", "analyst", "manager", "viewer"];

test.describe("Сценарий 1. Вход по роли и показатели панели", () => {
  test("демо-стенд наполнен: панель не имеет права показать нули", async () => {
    const token = await loginApi(api, "analyst");
    const dashboard = await fetchDashboard(api, token);

    const byCode = new Map(dashboard.kpis.map((kpi) => [kpi.code, kpi]));

    // Опорные величины: если база пуста, ниже сойдутся ноль с нулём, и все
    // остальные проверки пройдут вхолостую. Ловим это здесь.
    expect(byCode.get("budget")?.value, "строк бюджетного слоя 8.3").toBe(
      EXPECTED_SCALE.budgetRows,
    );
    expect(
      byCode.get("organizations")?.value ?? 0,
      "организаций слоя 8.7",
    ).toBeGreaterThanOrEqual(EXPECTED_SCALE.organizationsMin);
    expect(
      dashboard.risk_distribution.total,
      "объектов в выборке аналитика области",
    ).toBeGreaterThanOrEqual(EXPECTED_SCALE.analystObjectsMin);

    // Сумма по уровням обязана сходиться с итогом: расхождение означало бы,
    // что часть объектов потерялась при группировке и картина неполна.
    const sum = Object.values(dashboard.risk_distribution.counts).reduce((a, b) => a + b, 0);
    expect(sum, "сумма по уровням риска равна итогу").toBe(dashboard.risk_distribution.total);
  });

  for (const role of ROLES_WITH_DASHBOARD) {
    test(`роль «${USERS[role].roleTitle}» (${USERS[role].login}) видит на панели значения из базы`, async ({
      page,
    }) => {
      const token = await loginApi(api, role);
      const expected = await fetchDashboard(api, token);

      await signIn(page, role);

      // Пока данные не пришли, на месте карточек стоят скелетоны — ждём
      // появления первого настоящего заголовка показателя.
      await expect(kpiSection(page).getByText("Бюджетные наблюдения")).toBeVisible();

      for (const kpi of expected.kpis) {
        const card = kpiCard(page, kpi.title);
        await expect(card, `карточка «${kpi.title}» отсутствует`).toBeVisible();

        if (kpi.available && kpi.value !== null) {
          const text = await kpiText(page, kpi.title);
          expect(
            text,
            `показатель «${kpi.title}»: интерфейс печатает не то, что вернул сервер (${kpi.value})`,
          ).toContain(formatKpiValue(kpi));
        } else {
          /*
            Недоступный показатель обязан говорить «нет данных» и называть
            причину. Ноль здесь означал бы измеренное отсутствие, а сущности
            в источниках нет вовсе — выводы из этих состояний противоположны.
          */
          const text = await kpiText(page, kpi.title);
          expect(text, `показатель «${kpi.title}» без данных`).toContain("нет данных");
          expect(text, `причина недоступности «${kpi.title}» не показана`).toContain(
            kpi.reason.slice(0, 40),
          );
          expect(text, `«${kpi.title}» подменяет отсутствие данных нулём`).not.toMatch(
            /(^|\s)0($|\s)/,
          );
        }
      }

      // Кольцевая диаграмма подписана итогом выборки — тем же, что в API.
      await expect(
        page.getByText(`${formatCount(expected.risk_distribution.total)} объектов всего`),
      ).toBeVisible();

      // И каждым уровнем в отдельности, включая «нет данных»: спрятать
      // неизмеренные объекты значит показать картину благополучнее реальной.
      const table = page.locator('section[aria-label="Объекты по уровню риска"] table');
      for (const [level, label] of Object.entries(expected.risk_distribution.labels)) {
        const count = expected.risk_distribution.counts[level] ?? 0;
        const row = table.locator("tr").filter({ hasText: label });
        await expect(row, `в диаграмме нет уровня «${label}»`).toHaveCount(1);
        expect(
          normalizeDigits(await row.innerText()),
          `уровень «${label}»: ожидалось ${count}`,
        ).toContain(formatCount(count));
      }
    });
  }

  test("неверный пароль не пускает и объясняет отказ", async ({ page }) => {
    /*
      Проверка обратной стороны сценария: если пускает кто угодно, то
      разграничение прав (критерий ТЗ 23.11) не значит ничего. Заодно
      убеждаемся, что причина отказа общая и не выдаёт, существует ли логин, —
      иначе перебором составляется список учётных записей.
    */
    await page.goto("/login");
    await page.getByLabel("Логин").fill(USERS.analyst.login);
    await page.getByLabel("Пароль").fill("заведомо неверный пароль");
    await page.getByRole("button", { name: "Войти" }).click();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).not.toContainText("не найден");
    expect(page.url()).toContain("/login");

    const token = await page.evaluate(() => localStorage.getItem("riskmap-token"));
    expect(token, "после неудачного входа токен не должен появляться").toBeNull();

    /*
      Успешный вход тем же логином сразу после неудачного — не украшение.
      Сервер считает неудачные попытки и после нескольких блокирует запись на
      время; удачный вход счётчик сбрасывает. Без этого каждый прогон тестов
      приближал бы демо-аккаунт к блокировке, и однажды упал бы весь набор.
    */
    await signIn(page, "analyst");
  });
});
