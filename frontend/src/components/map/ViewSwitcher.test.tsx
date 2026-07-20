import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ViewSwitcher, parseViewMode } from "@/components/map/ViewSwitcher";

describe("разбор режима из адреса", () => {
  it("известные режимы читаются", () => {
    expect(parseViewMode("map")).toBe("map");
    expect(parseViewMode("split")).toBe("split");
  });

  it("мусор и отсутствие дают список", () => {
    // На мобильном список — основной режим, и он же безопасен без геоданных.
    expect(parseViewMode("выдумка")).toBe("list");
    expect(parseViewMode(null)).toBe("list");
  });
});

describe("переключатель представления", () => {
  it("объявлен группой радиокнопок с отмеченным текущим", () => {
    render(<ViewSwitcher value="map" onChange={() => {}} />);

    expect(screen.getByRole("radiogroup", { name: "Представление выборки" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /На карте/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Списком/ })).not.toBeChecked();
  });

  it("щелчок сообщает выбранный режим", async () => {
    const onChange = vi.fn();
    render(<ViewSwitcher value="list" onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /На карте/ }));

    expect(onChange).toHaveBeenCalledWith("map");
  });

  it("стрелка вправо переходит к следующему режиму", async () => {
    const onChange = vi.fn();
    render(<ViewSwitcher value="list" onChange={onChange} />);

    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");

    expect(onChange).toHaveBeenCalledWith("map");
  });

  it("стрелка влево с первого режима уходит на последний", async () => {
    const onChange = vi.fn();
    render(<ViewSwitcher value="list" onChange={onChange} />);

    await userEvent.tab();
    await userEvent.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith("split");
  });

  it("в обход клавишей Tab попадает только текущий вариант", () => {
    // Роверный tabindex: группа — одна остановка, внутри ходят стрелками.
    render(<ViewSwitcher value="map" onChange={() => {}} />);

    expect(screen.getByRole("radio", { name: /На карте/ })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: /Списком/ })).toHaveAttribute("tabindex", "-1");
  });

  it("совмещённый режим можно отключить", () => {
    render(<ViewSwitcher value="list" onChange={() => {}} allowSplit={false} />);

    expect(screen.queryByRole("radio", { name: /Карта \+ список/ })).not.toBeInTheDocument();
  });
});
