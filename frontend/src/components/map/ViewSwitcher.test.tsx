import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ViewSwitcher, parseViewMode } from "@/components/map/ViewSwitcher";

/**
 * Задать ширину окна для теста.
 *
 * Сдвоенный режим существует только на широком экране, поэтому раскладка —
 * такое же условие теста, как значение пропса, и задаётся явно.
 */
function withViewport(wide: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: wide,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

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

  it("на широком экране стрелка влево с первого режима уходит на сдвоенный", async () => {
    // Раскладка — часть условий: сдвоенный режим существует только когда
    // экран достаточно широк, поэтому она задаётся явно.
    withViewport(true);

    const onChange = vi.fn();
    render(<ViewSwitcher value="list" onChange={onChange} />);

    await userEvent.tab();
    await userEvent.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith("split");
  });

  it("на узком экране сдвоенного режима нет ни на экране, ни в обходе стрелками", async () => {
    /*
      Раньше он прятался классом `hidden lg:inline-flex`, но обе утилиты
      задают `display`, и в собранном CSS побеждала вторая: на телефоне
      кнопка оставалась видимой и фокусируемой. Теперь режим убирается из
      набора, поэтому выбрать раскладку, которая не поместится, нельзя.
    */
    withViewport(false);

    const onChange = vi.fn();
    render(<ViewSwitcher value="list" onChange={onChange} />);

    expect(screen.queryByRole("radio", { name: /Карта \+ список/ })).not.toBeInTheDocument();

    await userEvent.tab();
    await userEvent.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith("map");
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
