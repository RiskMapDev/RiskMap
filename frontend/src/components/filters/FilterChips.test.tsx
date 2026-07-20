import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterChips } from "@/components/filters/FilterChips";
import { activeFilterChips, withFilters, DEFAULT_QUERY_SPEC } from "@/lib/query-spec";

describe("чипы активных фильтров", () => {
  it("при нетронутых фильтрах ничего не рисуется", () => {
    const { container } = render(
      <FilterChips chips={activeFilterChips(DEFAULT_QUERY_SPEC)} onClear={() => {}} onReset={() => {}} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("активный фильтр виден подписью и значением", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { search: "ТЕСТ-ЗАПРОС" });

    render(<FilterChips chips={activeFilterChips(spec)} onClear={() => {}} onReset={() => {}} />);

    expect(screen.getByText("Поиск:")).toBeInTheDocument();
    expect(screen.getByText("ТЕСТ-ЗАПРОС")).toBeInTheDocument();
  });

  it("кнопка снятия названа вместе со значением фильтра", async () => {
    // Список одинаковых кнопок «Убрать» бесполезен при обходе с клавиатуры.
    const spec = withFilters(DEFAULT_QUERY_SPEC, { search: "ТЕСТ-ЗАПРОС" });
    const onClear = vi.fn();

    render(<FilterChips chips={activeFilterChips(spec)} onClear={onClear} onReset={() => {}} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Снять фильтр «Поиск: ТЕСТ-ЗАПРОС»" }),
    );

    expect(onClear).toHaveBeenCalledWith("search");
  });

  it("несколько фильтров дают несколько чипов", () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, {
      search: "ТЕСТ",
      objectTypes: ["contract"],
      onlyCategoryA: true,
    });

    render(<FilterChips chips={activeFilterChips(spec)} onClear={() => {}} onReset={() => {}} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("есть общий сброс", async () => {
    const spec = withFilters(DEFAULT_QUERY_SPEC, { search: "ТЕСТ" });
    const onReset = vi.fn();

    render(<FilterChips chips={activeFilterChips(spec)} onClear={() => {}} onReset={onReset} />);
    await userEvent.click(screen.getByRole("button", { name: "Сбросить всё" }));

    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
