import { describe, expect, it } from "vitest";

import {
  CONFIDENCE_LINE_STYLE,
  NODE_SHAPE,
  RISK_BORDER_STYLE,
  RISK_BORDER_WIDTH,
  edgeLabel,
  nodeDescription,
  nodeLabel,
  truncateLabel,
} from "@/lib/graph-style";
import { RISK_LEVELS } from "@/lib/risk";

describe("форма узла несёт тип сущности", () => {
  it("у каждого типа своя форма", () => {
    const shapes = Object.values(NODE_SHAPE);
    expect(new Set(shapes).size).toBe(shapes.length);
  });

  it("организация — прямоугольник, физлицо — круг, как на референсе", () => {
    expect(NODE_SHAPE.organization).toBe("round-rectangle");
    expect(NODE_SHAPE.person).toBe("ellipse");
  });
});

describe("уровень риска передаётся не только цветом", () => {
  it("в подписи есть значок и слово уровня", () => {
    const подпись = nodeLabel({
      label: "ТОО Пример",
      risk_level: "critical",
      risk_score: 82.4,
      risk_is_preliminary: false,
    });

    expect(подпись).toContain("Критический");
    // Значок различается силуэтом, а не оттенком одного знака.
    expect(подпись).toContain("■");
  });

  it("высокий и критический различимы без цвета", () => {
    const высокий = nodeLabel({
      label: "А",
      risk_level: "high",
      risk_score: null,
      risk_is_preliminary: false,
    });
    const критический = nodeLabel({
      label: "А",
      risk_level: "critical",
      risk_score: null,
      risk_is_preliminary: false,
    });

    // Эта пара по цвету почти неразличима (1.5:1), поэтому проверяются
    // именно нецветовые каналы: подпись, значок и толщина рамки.
    expect(высокий).not.toBe(критический);
    expect(RISK_BORDER_WIDTH.critical).toBeGreaterThan(RISK_BORDER_WIDTH.high);
    expect(RISK_BORDER_STYLE.critical).not.toBe(RISK_BORDER_STYLE.high);
  });

  it("предварительный балл помечен тильдой", () => {
    const подпись = nodeLabel({
      label: "А",
      risk_level: "unknown",
      risk_score: 41,
      risk_is_preliminary: true,
    });
    expect(подпись).toContain("~41");
  });

  it("отсутствие балла не превращается в ноль", () => {
    const подпись = nodeLabel({
      label: "А",
      risk_level: "unknown",
      risk_score: null,
      risk_is_preliminary: false,
    });
    expect(подпись).not.toContain("0");
    expect(подпись).toContain("Нет данных");
  });

  it("у «нет данных» рамка пунктирная — неизмеренное не выглядит уверенно", () => {
    expect(RISK_BORDER_STYLE.unknown).toBe("dashed");
  });

  it("оформление задано для всех уровней, включая «нет данных»", () => {
    for (const level of RISK_LEVELS) {
      expect(RISK_BORDER_WIDTH[level]).toBeGreaterThan(0);
      expect(RISK_BORDER_STYLE[level]).toBeTruthy();
    }
  });
});

describe("достоверность связи передаётся начертанием", () => {
  it("достоверная — сплошная, предположительная — пунктир", () => {
    expect(CONFIDENCE_LINE_STYLE.confirmed).toBe("solid");
    expect(CONFIDENCE_LINE_STYLE.probable).toBe("dashed");
  });

  it("предположительная связь помечена ещё и словом", () => {
    expect(edgeLabel({ relation_type_label: "Руководитель", confidence: "probable" })).toContain(
      "предпол.",
    );
    expect(edgeLabel({ relation_type_label: "Поставщик", confidence: "confirmed" })).toBe(
      "Поставщик",
    );
  });
});

describe("подписи", () => {
  it("длинная подпись обрезается многоточием", () => {
    const длинная = "Заявка на получение субсидий на ведение селекционной работы";
    expect(truncateLabel(длинная, 20).endsWith("…")).toBe(true);
    expect(truncateLabel(длинная, 20).length).toBeLessThanOrEqual(21);
  });

  it("короткая подпись не трогается", () => {
    expect(truncateLabel("ТОО Альфа")).toBe("ТОО Альфа");
  });

  it("описание для скринридера называет тип, уровень и число связей", () => {
    const описание = nodeDescription({
      label: "ТОО Альфа",
      node_type_label: "Организация",
      risk_level: "high",
      risk_level_label: "Высокий",
      risk_is_preliminary: true,
      degree: 12,
    });

    expect(описание).toContain("Организация");
    expect(описание).toContain("Высокий");
    expect(описание).toContain("предварительная");
    expect(описание).toContain("12");
  });
});
