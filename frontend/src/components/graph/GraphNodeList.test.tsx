import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GraphNodeList } from "@/components/graph/GraphNodeList";
import type { GraphEdgePayload, GraphNodePayload, SubgraphPayload } from "@/lib/api/graph";

function node(overrides: Partial<GraphNodePayload> = {}): GraphNodePayload {
  return {
    key: "organization:aaa",
    node_type: "organization",
    node_type_label: "Организация",
    label: "ТОО Альфа",
    sublabel: null,
    identifier: { value: "123456789012", present: true, access: "full" },
    identifier_kind: "bin",
    risk_level: "high",
    risk_level_label: "Высокий",
    risk_score: 71.2,
    risk_is_preliminary: false,
    degree: 40,
    source_layer: "8.4",
    ref_entity_type: "supplier",
    ref_entity_id: "00000000-0000-0000-0000-000000000001",
    attributes: {},
    ...overrides,
  };
}

function edge(overrides: Partial<GraphEdgePayload> = {}): GraphEdgePayload {
  return {
    id: "e1",
    relation_type: "supplier",
    relation_type_label: "Поставщик",
    source: "organization:aaa",
    target: "contract:bbb",
    direction: "directed",
    confidence: "confirmed",
    confidence_label: "Достоверная",
    confidence_basis: "внешний ключ источника",
    source_layer: "8.4",
    derivation_rule: "contracts.supplier_id",
    amount: 1000,
    data_as_of: null,
    evidence: {},
    ...overrides,
  };
}

function subgraph(overrides: Partial<SubgraphPayload> = {}): SubgraphPayload {
  return {
    center: "organization:aaa",
    nodes: [
      node(),
      node({
        key: "contract:bbb",
        node_type: "contract",
        node_type_label: "Договор",
        label: "Договор 22333284",
        identifier: null,
        identifier_kind: null,
        risk_level: "critical",
        risk_level_label: "Критический",
        risk_score: null,
        degree: 1,
      }),
    ],
    edges: [edge()],
    depth: 1,
    max_nodes: 60,
    truncated: false,
    omitted_nodes: 0,
    total_neighbors: 1,
    scope_note: "Показаны связи всех территорий.",
    ...overrides,
  };
}

describe("список узлов — текстовое зеркало канвы", () => {
  it("канва недоступна скринридеру, поэтому узлы есть списком", () => {
    render(<GraphNodeList subgraph={subgraph()} onExpand={() => {}} />);

    expect(screen.getByRole("region", { name: "Узлы подграфа списком" })).toBeInTheDocument();
    expect(screen.getByText("ТОО Альфа")).toBeInTheDocument();
    expect(screen.getByText("Договор 22333284")).toBeInTheDocument();
  });

  it("уровень риска назван словом, а не только цветом", () => {
    render(<GraphNodeList subgraph={subgraph()} onExpand={() => {}} />);

    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText("Критический")).toBeInTheDocument();
  });

  it("достоверность связи названа словом", () => {
    render(<GraphNodeList subgraph={subgraph()} onExpand={() => {}} />);
    expect(screen.getAllByText("достоверная").length).toBeGreaterThan(0);
  });

  it("у предположительной связи показано основание", () => {
    render(
      <GraphNodeList
        subgraph={subgraph({
          edges: [
            edge({
              confidence: "probable",
              confidence_label: "Предположительная",
              confidence_basis: "совпадение ФИО руководителя",
            }),
          ],
        })}
        onExpand={() => {}}
      />,
    );

    expect(screen.getAllByText(/совпадение ФИО руководителя/).length).toBeGreaterThan(0);
  });

  it("центр раскрывать не предлагается — он уже раскрыт", () => {
    render(<GraphNodeList subgraph={subgraph()} onExpand={() => {}} />);
    expect(screen.getAllByRole("button", { name: "Раскрыть" })).toHaveLength(1);
  });

  it("раскрытие соседа доступно с клавиатуры", async () => {
    const onExpand = vi.fn();
    render(<GraphNodeList subgraph={subgraph()} onExpand={onExpand} />);

    await userEvent.click(screen.getByRole("button", { name: "Раскрыть" }));

    expect(onExpand).toHaveBeenCalledWith(expect.objectContaining({ key: "contract:bbb" }));
  });

  it("показано «связей в подграфе N из M» — фрагмент не выдаётся за целое", () => {
    render(<GraphNodeList subgraph={subgraph()} onExpand={() => {}} />);
    expect(screen.getByText("связей в подграфе: 1 из 40")).toBeInTheDocument();
  });

  it("усечение объявляется прямо, а не подразумевается", () => {
    render(
      <GraphNodeList
        subgraph={subgraph({ truncated: true, omitted_nodes: 940, total_neighbors: 1000 })}
        onExpand={() => {}}
      />,
    );

    // Молчаливое обрезание привело бы к выводу «связей мало» по картинке,
    // которая на деле показывает «связей слишком много».
    expect(screen.getByText(/узлов не поместилось: 940/)).toBeInTheDocument();
    expect(screen.getByText(/нельзя судить о том, что связей мало/)).toBeInTheDocument();
  });
});
