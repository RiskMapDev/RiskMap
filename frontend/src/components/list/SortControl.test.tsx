import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SortControl } from "@/components/list/SortControl";
import { SORT_FIELDS } from "@/lib/query-spec";

describe("сортировка", () => {
  it("предлагает все поля сортировки из ТЗ", () => {
    render(<SortControl sort="risk" order="desc" onChange={() => {}} />);

    // риск / сумма / актуальность / название
    expect(screen.getAllByRole("option")).toHaveLength(SORT_FIELDS.length);
    expect(screen.getByRole("combobox", { name: "Сортировка" })).toHaveValue("risk");
  });

  it("смена поля задаёт осмысленное направление", async () => {
    // «По названию» логично начинать с начала алфавита, «по риску» — с опасных.
    const onChange = vi.fn();
    render(<SortControl sort="risk" order="desc" onChange={onChange} />);

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Сортировка" }), "name");

    expect(onChange).toHaveBeenCalledWith("name", "asc");
  });

  it("направление переключается, поле остаётся", async () => {
    const onChange = vi.fn();
    render(<SortControl sort="amount" order="desc" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /Направление/ }));

    expect(onChange).toHaveBeenCalledWith("amount", "asc");
  });

  it("направление подписано смыслом, а не механикой", () => {
    // «По убыванию» не объясняет, что окажется сверху.
    render(<SortControl sort="risk" order="desc" onChange={() => {}} />);

    expect(
      screen.getByRole("button", { name: "Направление: сначала опасные. Изменить" }),
    ).toBeInTheDocument();
  });
});
