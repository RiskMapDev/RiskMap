import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GraphFilters } from "@/components/graph/GraphFilters";
import { DEFAULT_VIEW_STATE, type GraphLegend } from "@/lib/api/graph";

const legend: GraphLegend = {
  node_types: [
    { code: "organization", label: "Организация" },
    { code: "person", label: "Физическое лицо" },
  ],
  relation_types: [
    { code: "supplier", label: "Поставщик" },
    { code: "recipient", label: "Получатель" },
    { code: "shared_address", label: "Общий адрес" },
  ],
  confidence: [
    { code: "confirmed", label: "Достоверная", style: "solid", note: "по идентификатору" },
    { code: "probable", label: "Предположительная", style: "dashed", note: "по наименованию" },
  ],
  directions: ["directed", "undirected"],
  limits: { max_depth: 2, default_max_nodes: 60, max_nodes: 200 },
};

describe("панель фильтров графа", () => {
  it("типы связей приходят из легенды сервера, а не зашиты в экран", () => {
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /Поставщик/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Общий адрес/ })).toBeInTheDocument();
  });

  it("пустой набор типов объявлен как «все», а не как «ничего»", () => {
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.getByText(/Ни одной отметки — показываются все типы/)).toBeInTheDocument();
  });

  it("отметка типа добавляет его в выборку", async () => {
    const onChange = vi.fn();
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={onChange}
        onReset={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("checkbox", { name: /Получатель/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ relationTypes: ["recipient"] }),
    );
  });

  it("повторная отметка снимает тип", async () => {
    const onChange = vi.fn();
    render(
      <GraphFilters
        legend={legend}
        value={{ ...DEFAULT_VIEW_STATE, relationTypes: ["recipient"] }}
        onChange={onChange}
        onReset={() => {}}
      />,
    );

    await userEvent.click(screen.getByRole("checkbox", { name: /Получатель/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ relationTypes: [] }));
  });

  it("фильтр достоверности объясняет, что именно он отбрасывает", () => {
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.getByText(/требуют проверки/)).toBeInTheDocument();
    expect(screen.getByText(/пунктирные/)).toBeInTheDocument();
  });

  it("пределы выборки видны пользователю, а не спрятаны", () => {
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    // Человек, не знающий, что показаны 60 узлов из трёх тысяч, делает
    // неверный вывод о разреженности связей.
    expect(screen.getByText(/Граф не отдаётся целиком/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /Глубина связей/ })).toBeInTheDocument();
  });

  it("предел глубины берётся из ответа сервера", () => {
    render(
      <GraphFilters
        legend={legend}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.getAllByRole("option")).toHaveLength(legend.limits.max_depth);
  });

  it("до загрузки легенды панель не падает и не выдумывает типы", () => {
    render(
      <GraphFilters
        legend={null}
        value={DEFAULT_VIEW_STATE}
        onChange={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.queryByRole("checkbox", { name: /Поставщик/ })).not.toBeInTheDocument();
  });
});
