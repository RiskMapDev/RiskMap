import { describe, expect, it } from "vitest";

import {
  DEFAULT_QUERY_SPEC,
  activeFilterChips,
  clearFilter,
  fromSearchParams,
  hasActiveFilters,
  toSearchParams,
  withFilters,
  type QuerySpec,
} from "@/lib/query-spec";
import { RISK_LEVELS } from "@/lib/risk";

function roundTrip(spec: QuerySpec): QuerySpec {
  return fromSearchParams(toSearchParams(spec));
}

describe("умолчания", () => {
  it("уровень «нет данных» включён", () => {
    // Иначе неизмеренные объекты молча исчезнут у того, кто фильтры не трогал.
    expect(DEFAULT_QUERY_SPEC.riskLevels).toContain("unknown");
    expect(DEFAULT_QUERY_SPEC.riskLevels).toHaveLength(RISK_LEVELS.length);
  });

  it("пустая выборка не даёт параметров в ссылке", () => {
    expect([...toSearchParams(DEFAULT_QUERY_SPEC).keys()]).toHaveLength(0);
  });

  it("дочерние территории включены", () => {
    // Выбор области без районов дал бы пустую выборку.
    expect(DEFAULT_QUERY_SPEC.includeChildTerritories).toBe(true);
  });
});

describe("обратимость через адресную строку", () => {
  it("полная выборка переживает круг", () => {
    const spec: QuerySpec = {
      ...DEFAULT_QUERY_SPEC,
      dateFrom: "2024-01-01",
      dateTo: "2024-06-30",
      territoryCodes: ["talgarskiy", "iliyskiy"],
      objectTypes: ["contract"],
      amountMin: 1000,
      amountMax: 5_000_000,
      riskLevels: ["high", "critical"],
      completenessMin: 0.5,
      onlyCategoryA: true,
      search: "ТОО Строй",
      sort: "amount",
      order: "asc",
      page: 3,
      pageSize: 50,
    };

    expect(roundTrip(spec)).toEqual(spec);
  });

  it("выбор территорий переживает круг", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, {
      territoryCodes: ["talgarskiy", "konaev"],
    });
    expect(roundTrip(spec).territoryCodes).toEqual(["talgarskiy", "konaev"]);
  });

  it("порядок уровней риска не влияет на равенство", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { riskLevels: ["critical", "high"] });
    expect(roundTrip(spec).riskLevels).toEqual(["critical", "high"]);
  });
});

describe("устойчивость к мусору в ссылке", () => {
  it("посторонние параметры игнорируются", () => {
    // Ссылку могли обвесить метками рекламной аналитики — страница не должна падать.
    const spec = fromSearchParams(new URLSearchParams("utm_source=mail&page=2"));
    expect(spec.page).toBe(2);
  });

  it("нечисловая страница заменяется первой", () => {
    expect(fromSearchParams(new URLSearchParams("page=абв")).page).toBe(1);
  });

  it("отрицательная страница заменяется первой", () => {
    expect(fromSearchParams(new URLSearchParams("page=-5")).page).toBe(1);
  });

  it("чрезмерный размер страницы ограничивается", () => {
    // Иначе один запрос вытянет всю базу и уронит норматив времени отклика.
    expect(fromSearchParams(new URLSearchParams("page_size=100000")).pageSize).toBe(200);
  });

  it("неизвестный уровень риска отбрасывается", () => {
    const spec = fromSearchParams(new URLSearchParams("risk_levels=high,выдумка"));
    expect(spec.riskLevels).toEqual(["high"]);
  });

  it("пустой список уровней трактуется как «фильтр не задан»", () => {
    // Пустой список дал бы заведомо пустую выборку без объяснения причины.
    const spec = fromSearchParams(new URLSearchParams("risk_levels="));
    expect(spec.riskLevels).toEqual(DEFAULT_QUERY_SPEC.riskLevels);
  });

  it("неизвестное поле сортировки заменяется умолчанием", () => {
    expect(fromSearchParams(new URLSearchParams("sort=выдумка")).sort).toBe("risk");
  });

  it("отсутствие параметров даёт умолчания", () => {
    expect(fromSearchParams(null)).toEqual(DEFAULT_QUERY_SPEC);
  });

  it("пустой поиск становится null", () => {
    expect(fromSearchParams(new URLSearchParams("search=%20%20")).search).toBeNull();
  });
});

describe("чипы активных фильтров", () => {
  it("нетронутые фильтры не дают чипов", () => {
    expect(activeFilterChips(DEFAULT_QUERY_SPEC)).toEqual([]);
    expect(hasActiveFilters(DEFAULT_QUERY_SPEC)).toBe(false);
  });

  it("страница не считается активным фильтром", () => {
    // Переход на вторую страницу не должен зажигать кнопку «Сбросить».
    expect(hasActiveFilters({ ...DEFAULT_QUERY_SPEC, page: 5 })).toBe(false);
  });

  it("полный набор уровней не даёт чипа", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { riskLevels: [...RISK_LEVELS] });
    expect(activeFilterChips(spec).some((c) => c.label === "Уровень риска")).toBe(false);
  });

  it("поиск попадает в чипы", () => {
    const chips = activeFilterChips(withFilters(DEFAULT_QUERY_SPEC, { search: "ТОО" }));
    expect(chips).toContainEqual({ key: "search", label: "Поиск", value: "ТОО" });
  });
});

describe("снятие фильтров", () => {
  it("снятие возвращает значение к умолчанию", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { search: "ТОО" });
    expect(clearFilter(spec, "search").search).toBeNull();
  });

  it("период снимается целиком обеими границами", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, {
      dateFrom: "2024-01-01",
      dateTo: "2024-06-30",
    });
    const cleared = clearFilter(spec, "dateFrom");

    expect(cleared.dateFrom).toBeNull();
    expect(cleared.dateTo).toBeNull();
  });

  it("снятие фильтра возвращает на первую страницу", () => {
    // Иначе пользователь останется на седьмой странице выборки из трёх строк.
    const spec = { ...DEFAULT_QUERY_SPEC, search: "ТОО", page: 7 };
    expect(clearFilter(spec, "search").page).toBe(1);
  });
});

describe("изменение фильтров", () => {
  it("смена фильтра сбрасывает страницу", () => {
    const spec = { ...DEFAULT_QUERY_SPEC, page: 5 };
    expect(withFilters(spec, { search: "ТОО" }).page).toBe(1);
  });

  it("явная смена страницы страницу не сбрасывает", () => {
    const spec = { ...DEFAULT_QUERY_SPEC, search: "ТОО" };
    const next = withFilters(spec, { page: 3 });

    expect(next.page).toBe(3);
    expect(next.search).toBe("ТОО");
  });
});
