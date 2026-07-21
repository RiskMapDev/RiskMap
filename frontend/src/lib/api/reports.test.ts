import { describe, expect, it } from "vitest";

import { fallbackFileName, fileNameFromDisposition, toServerSpec } from "@/lib/api/reports";
import { DEFAULT_QUERY_SPEC, withFilters } from "@/lib/query-spec";

describe("имя файла отчёта", () => {
  it("предпочитает кириллическое имя из filename* запасному ASCII", () => {
    const header =
      "attachment; filename=\"Svodnyy_otchet.docx\"; filename*=UTF-8''%D0%A1%D0%B2%D0%BE%D0%B4%D0%BD%D1%8B%D0%B9.docx";
    expect(fileNameFromDisposition(header, "запас.docx")).toBe("Сводный.docx");
  });

  it("берёт обычное filename, когда расширенного нет", () => {
    expect(fileNameFromDisposition('attachment; filename="report.xlsx"', "запас.xlsx")).toBe(
      "report.xlsx",
    );
  });

  it("без заголовка отдаёт запасное имя, а не пустую строку", () => {
    expect(fileNameFromDisposition(null, "запас.pdf")).toBe("запас.pdf");
  });

  it("испорченную кодировку не роняет, а откатывает к ASCII-имени", () => {
    const header = "attachment; filename=\"ok.docx\"; filename*=UTF-8''%E0%A4%A";
    expect(fileNameFromDisposition(header, "запас.docx")).toBe("ok.docx");
  });
});

describe("запасное имя файла", () => {
  /*
    Заголовок с настоящим именем не доходит до скрипта, пока сервер не
    перечислит его в `Access-Control-Expose-Headers`: интерфейс и API живут на
    разных источниках. Пока этого нет, отчёт обязан сохраняться под названием
    шаблона, а не под кодом «high-risk.docx».
  */
  it("берёт название шаблона, а не код", () => {
    expect(fallbackFileName("Перечень высокорисковых объектов", "high-risk", "docx")).toBe(
      "Перечень высокорисковых объектов.docx",
    );
  });

  it("убирает знаки, недопустимые в имени файла", () => {
    expect(fallbackFileName("Отчёт по объекту/проекту", "project", "xlsx")).toBe(
      "Отчёт по объекту проекту.xlsx",
    );
  });

  it("без названия откатывается к коду шаблона, а не к пустому имени", () => {
    expect(fallbackFileName("   ", "ratings", "pdf")).toBe("ratings.pdf");
  });
});

describe("выборка для отчёта", () => {
  it("умолчания не передаются: пустое тело означает «всё, что есть»", () => {
    expect(toServerSpec(DEFAULT_QUERY_SPEC)).toEqual({});
  });

  it("переводит имена полей в те, что понимает сервер", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, {
      search: "ТЕСТ",
      territoryCodes: ["ТЕСТ-КОД"],
      amountMin: 1000,
      onlyCategoryA: true,
    });

    expect(toServerSpec(spec)).toEqual({
      search: "ТЕСТ",
      territory_codes: ["ТЕСТ-КОД"],
      amount_min: 1000,
      only_category_a: true,
    });
  });

  it("полный набор уровней риска не передаёт: это отсутствие фильтра", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, {
      riskLevels: ["low", "medium", "high", "critical", "unknown"],
    });
    expect(toServerSpec(spec)).toEqual({});
  });

  it("сокращённый набор уровней передаёт", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { riskLevels: ["critical", "high"] });
    expect(toServerSpec(spec)).toEqual({ risk_levels: ["critical", "high"] });
  });

  it("нулевую границу суммы передаёт, а не принимает за отсутствие фильтра", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { amountMin: 0 });
    expect(toServerSpec(spec)).toEqual({ amount_min: 0 });
  });
});
