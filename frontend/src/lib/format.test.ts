import { describe, expect, it } from "vitest";

import {
  EM_DASH,
  formatAmount,
  formatCount,
  formatDate,
  formatObjectCount,
  formatShare,
  pluralRu,
} from "@/lib/format";

/** Intl разделяет разряды неразрывным пробелом — для сравнения приводим к обычному. */
const plain = (value: string) => value.replace(/[  ]/g, " ");

describe("числа и суммы", () => {
  it("ноль показывается как ноль, а не как прочерк", () => {
    // Нулевая сумма договора — измеренный факт, его нельзя прятать.
    expect(plain(formatAmount(0, "₸"))).toBe("0 ₸");
    expect(formatCount(0)).toBe("0");
  });

  it("отсутствие значения показывается прочерком, а не нулём", () => {
    expect(formatAmount(null, "₸")).toBe(EM_DASH);
    expect(formatCount(null)).toBe(EM_DASH);
  });

  it("разряды разделяются", () => {
    expect(plain(formatCount(1234567))).toBe("1 234 567");
  });

  it("единица измерения не подставляется сама", () => {
    expect(plain(formatAmount(100, null))).toBe("100");
  });
});

describe("даты", () => {
  it("ISO-дата переводится в привычный вид", () => {
    expect(formatDate("2024-12-31")).toBe("31.12.2024");
  });

  it("дата не уезжает на сутки из-за часового пояса", () => {
    // Разбор строкой, а не через Date: `new Date('2024-01-01')` — это UTC-полночь.
    expect(formatDate("2024-01-01T00:00:00Z")).toBe("01.01.2024");
  });

  it("мусор и отсутствие дают прочерк", () => {
    expect(formatDate(null)).toBe(EM_DASH);
    expect(formatDate("не дата")).toBe(EM_DASH);
  });
});

describe("доли", () => {
  it("доля переводится в проценты", () => {
    expect(formatShare(0.85)).toBe("85 %");
  });

  it("нулевая полнота не превращается в прочерк", () => {
    expect(formatShare(0)).toBe("0 %");
  });

  it("неизвестная полнота — прочерк", () => {
    expect(formatShare(null)).toBe(EM_DASH);
  });
});

describe("склонение", () => {
  const forms = ["объект", "объекта", "объектов"] as const;

  it.each([
    [1, "объект"],
    [2, "объекта"],
    [5, "объектов"],
    [11, "объектов"],
    [21, "объект"],
    [104, "объекта"],
    [0, "объектов"],
  ])("%i → %s", (count, expected) => {
    expect(pluralRu(count, forms)).toBe(expected);
  });

  it("счётчик собирает число и слово", () => {
    expect(plain(formatObjectCount(1234))).toBe("1 234 объекта");
  });
});
