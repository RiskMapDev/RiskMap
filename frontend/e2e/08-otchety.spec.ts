import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, auth, loginApi, url } from "./helpers/api";
import { signIn } from "./helpers/auth";

/**
 * Сценарий 8 приёмки: отчёт формируется и выгружается файлом.
 *
 * Экрана отчётов в интерфейсе нет: `src/app/reports/page.tsx` показывает
 * заглушку «Шаблоны отчётов ещё не подключены» и ни одной кнопки. Сквозной
 * проверки «нажал — скачалось» поэтому не существует, она помечена `test.fixme`
 * ниже. Проверяется сама выгрузка через API — то, ради чего экран и делается.
 *
 * Почему проверяются тип содержимого и размер, а не только код 200. Отчёт —
 * это файл, который пользователь откроет в Word или Excel. Ответ 200 с нулевым
 * телом, с телом в 200 байт (пустой контейнер) или с типом `text/html`
 * (страница ошибки, отданная как файл) выглядит успехом в журнале и провалом
 * на столе у пользователя: он получит документ, который не открывается.
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

/** Минимальный правдоподобный размер: пустой контейнер OOXML и тот крупнее. */
const MIN_REPORT_BYTES = 4_000;

const FORMATS = [
  {
    code: "docx",
    mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    /* OOXML — это ZIP: файл обязан начинаться с сигнатуры PK. */
    signature: [0x50, 0x4b],
  },
  {
    code: "xlsx",
    mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    signature: [0x50, 0x4b],
  },
  {
    code: "pdf",
    mediaType: "application/pdf",
    /* %PDF */
    signature: [0x25, 0x50, 0x44, 0x46],
  },
] as const;

test.describe("Сценарий 8. Формирование и выгрузка отчёта", () => {
  test("каталог шаблонов не пуст — иначе формировать нечего", async () => {
    const response = await api.get(url("/reports/templates"));
    expect(response.status()).toBe(200);
    const templates = (await response.json()) as Array<{ code: string; title: string }>;

    // ТЗ 17 требует восемь шаблонов. Меньше — незакрытое требование, и молчать
    // об этом тест не должен.
    expect(templates.length, "шаблонов отчётов меньше восьми по ТЗ 17").toBeGreaterThanOrEqual(8);
    for (const template of templates) {
      expect(template.title, `шаблон ${template.code} без названия`).toBeTruthy();
    }
  });

  for (const format of FORMATS) {
    test(`отчёт выгружается в ${format.code.toUpperCase()}: тип, имя файла и непустое содержимое`, async () => {
      const token = await loginApi(api, "analyst");

      const formats = await api.get(url("/reports/formats"));
      const catalogue = (await formats.json()) as Array<{ code: string; available: boolean }>;
      const entry = catalogue.find((item) => item.code === format.code);
      test.skip(
        !entry?.available,
        `формат ${format.code} объявлен недоступным в этом развёртывании`,
      );

      const response = await api.post(url("/reports/region-summary"), {
        headers: auth(token),
        params: { format: format.code },
        data: {},
      });

      expect(response.status(), await response.text().catch(() => "")).toBe(200);

      // Тип содержимого — тот, что объявлен в каталоге форматов. Клиент
      // выбирает приложение для открытия именно по нему.
      expect(response.headers()["content-type"]).toContain(format.mediaType);

      /*
        Имя файла обязано приехать в двух видах: ASCII-запасное и настоящее в
        UTF-8 по RFC 5987. Без `filename*` кириллическое имя часть браузеров
        отбросит, и пользователь получит файл с именем «download».
      */
      const disposition = response.headers()["content-disposition"] ?? "";
      expect(disposition, "отчёт отдан без заголовка выгрузки").toContain("attachment");
      expect(disposition, "нет ASCII-имени файла").toMatch(/filename="[^"]+"/);
      expect(disposition, "нет имени файла в UTF-8 (RFC 5987)").toContain("filename*=UTF-8''");
      expect(disposition).toContain(`.${format.code}`);

      const body = await response.body();
      expect(
        body.length,
        `файл ${format.code} подозрительно мал (${body.length} байт) — вероятно, пустой контейнер`,
      ).toBeGreaterThan(MIN_REPORT_BYTES);

      // Содержимое действительно того формата, а не страница ошибки с
      // подменённым заголовком.
      expect(
        [...body.subarray(0, format.signature.length)],
        `сигнатура файла не соответствует ${format.code}`,
      ).toEqual([...format.signature]);

      // Кэшировать отчёт нельзя: он зависит от прав и территории автора.
      expect(response.headers()["cache-control"]).toContain("no-store");
    });
  }

  test("отчёт учитывает выборку: разные фильтры дают разные файлы", async () => {
    /*
      Отчёт, игнорирующий переданную выборку, опаснее отсутствующего: он
      выглядит как ответ на заданный вопрос, а отвечает на другой. Сравниваем
      размеры двух выгрузок — по всей области и по одному району.
    */
    const token = await loginApi(api, "analyst");

    const wide = await api.post(url("/reports/region-summary"), {
      headers: auth(token),
      params: { format: "xlsx" },
      data: {},
    });
    const narrow = await api.post(url("/reports/region-summary"), {
      headers: auth(token),
      params: { format: "xlsx" },
      data: { territory_codes: ["karasayskiy"], risk_levels: ["critical"] },
    });

    expect(wide.status()).toBe(200);
    expect(narrow.status()).toBe(200);

    const wideBody = await wide.body();
    const narrowBody = await narrow.body();

    expect(
      Buffer.compare(wideBody, narrowBody),
      "отчёт по всей области и отчёт по одному району байт в байт совпали — выборка не применяется",
    ).not.toBe(0);
  });

  test.fixme(
    "отчёт формируется и скачивается через экран «Отчёты и экспорт»",
    async () => {
      /*
        НЕ РЕАЛИЗОВАНО В ПРИЛОЖЕНИИ.

        `src/app/reports/page.tsx` — заглушка: `EmptyState` с текстом
        «Шаблоны отчётов ещё не подключены». Ни карточек шаблонов, ни выбора
        формата, ни кнопки выгрузки на экране нет, обработчика скачивания в
        `src/` тоже нет.

        Когда экран появится, тест должен: открыть /reports, выбрать шаблон и
        формат, поймать событие download, сверить `suggestedFilename` с
        заголовком `Content-Disposition` и убедиться, что сохранённый файл не
        пуст. Серверная часть, которую этот экран будет вызывать, проверена
        выше и работает.
      */
    },
  );

  test("экран отчётов честно сообщает, что шаблоны не подключены", async ({ page }) => {
    /*
      Пока раздела нет, он обязан говорить об этом словами. Пустой экран без
      объяснения пользователь читает как поломку и заводит обращение.
    */
    await signIn(page, "analyst");
    await page.goto("/reports");

    await expect(page.getByRole("heading", { name: "Отчёты и экспорт" })).toBeVisible();
    await expect(page.getByText("Шаблоны отчётов ещё не подключены")).toBeVisible();
  });
});
