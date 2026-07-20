import { describe, expect, it } from "vitest";

import {
  DEFAULT_VIEW_STATE,
  buildViewSearch,
  parseViewState,
  type GraphViewState,
} from "@/lib/api/graph";

describe("состояние выборки читается из адреса", () => {
  it("пустой адрес даёт умолчания", () => {
    expect(parseViewState("")).toEqual(DEFAULT_VIEW_STATE);
  });

  it("узел, глубина и предел узлов разбираются", () => {
    const state = parseViewState("?node=person:abc&depth=2&max_nodes=120");

    expect(state.node).toBe("person:abc");
    expect(state.depth).toBe(2);
    expect(state.maxNodes).toBe(120);
  });

  it("глубина за пределом прижимается к разрешённой", () => {
    // Клиент не источник истины о том, сколько сервер готов отдать; но и
    // отправлять заведомо отклоняемый запрос незачем.
    expect(parseViewState("?depth=9").depth).toBe(2);
    expect(parseViewState("?depth=-4").depth).toBe(1);
  });

  it("число узлов за пределом прижимается", () => {
    expect(parseViewState("?max_nodes=100000").maxNodes).toBe(200);
    expect(parseViewState("?max_nodes=1").maxNodes).toBe(10);
  });

  it("мусор в числовых параметрах заменяется умолчанием", () => {
    expect(parseViewState("?depth=выдумка&max_nodes=").depth).toBe(1);
    expect(parseViewState("?max_nodes=выдумка").maxNodes).toBe(60);
  });

  it("неизвестные типы связей отбрасываются", () => {
    const state = parseViewState("?relations=supplier,выдумка,recipient");
    expect(state.relationTypes).toEqual(["supplier", "recipient"]);
  });

  it("фильтр достоверности читается только по точному значению", () => {
    expect(parseViewState("?confidence=confirmed").confirmedOnly).toBe(true);
    expect(parseViewState("?confidence=probable").confirmedOnly).toBe(false);
    expect(parseViewState("?confidence=да").confirmedOnly).toBe(false);
  });
});

describe("адрес собирается обратно", () => {
  it("умолчания в ссылку не попадают — она остаётся читаемой", () => {
    expect(buildViewSearch(DEFAULT_VIEW_STATE)).toBe("");
  });

  it("ссылка воспроизводит выборку целиком", () => {
    const state: GraphViewState = {
      node: "organization:ff00",
      depth: 2,
      maxNodes: 100,
      relationTypes: ["supplier", "recipient"],
      confirmedOnly: true,
    };

    expect(parseViewState(buildViewSearch(state))).toEqual(state);
  });

  it("только узел даёт короткий адрес", () => {
    expect(buildViewSearch({ ...DEFAULT_VIEW_STATE, node: "contract:1" })).toBe(
      "?node=contract%3A1",
    );
  });
});
