import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { GraphScreen } from "@/components/graph/GraphScreen";
import type { GraphNodePayload } from "@/lib/api/graph";

vi.mock("@/lib/api/graph", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/graph")>("@/lib/api/graph");
  return {
    ...actual,
    fetchGraphLegend: vi.fn(() => new Promise(() => {})),
    searchGraphNodes: vi.fn(),
  };
});

vi.mock("@/lib/api/auth", () => ({ readToken: () => "тестовый-токен" }));

const узел = (key: string, label: string): GraphNodePayload =>
  ({
    key,
    label,
    node_type: "organization",
    node_type_label: "Организация",
    degree: 7,
    risk_level: "high",
    risk_score: 50,
    risk_is_preliminary: false,
  }) as GraphNodePayload;

const { searchGraphNodes } = await import("@/lib/api/graph");

describe("перечень узлов графа", () => {
  beforeEach(() => vi.mocked(searchGraphNodes).mockReset());

  /*
    Экран графа не имеет «первой страницы» по данным, но обязан иметь её по
    интерфейсу: без перечня человек, не знающий ни одного наименования, не
    может войти в граф вообще.
  */
  it("список виден без запроса — пустая строка означает «все узлы»", async () => {
    vi.mocked(searchGraphNodes).mockResolvedValue({
      items: [узел("organization:1", "ТОО БАЙСЕРКЕ-АГРО")],
      query: "",
      total: 11782,
      offset: 0,
      min_query_length: 2,
    });

    render(<GraphScreen />);

    expect(await screen.findByRole("list", { name: "Все узлы витрины" })).toBeInTheDocument();
    expect(screen.getByText("ТОО БАЙСЕРКЕ-АГРО")).toBeInTheDocument();
    // Размер витрины называется целиком: «показано 1» без «из 11 782»
    // выдало бы начало длинного списка за весь список.
    expect(screen.getByText(/11782|11 782/)).toBeInTheDocument();
    expect(vi.mocked(searchGraphNodes).mock.calls[0]?.[0]).toBe("");
  });

  it("«показать ещё» появляется, пока показано не всё", async () => {
    vi.mocked(searchGraphNodes).mockResolvedValue({
      items: [узел("organization:1", "ТОО БАЙСЕРКЕ-АГРО")],
      query: "",
      total: 11782,
      offset: 0,
      min_query_length: 2,
    });

    render(<GraphScreen />);

    expect(await screen.findByRole("button", { name: "Показать ещё" })).toBeInTheDocument();
  });
});
