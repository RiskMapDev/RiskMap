import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FilterPanel } from "@/components/filters/FilterPanel";
import type { FilterOptions } from "@/lib/api/types";
import { DEFAULT_QUERY_SPEC, withFilters } from "@/lib/query-spec";
import { RISK_LEVELS } from "@/lib/risk";

/** Справочники заведомо тестовые: настоящие придут из API. */
const OPTIONS: FilterOptions = {
  territories: [
    { value: "ТЕСТ-РАЙОН-1", label: "Тестовый район 1" },
    { value: "ТЕСТ-РАЙОН-2", label: "Тестовый район 2" },
  ],
  industries: [{ value: "ТЕСТ-ОТРАСЛЬ", label: "Тестовая отрасль" }],
  statuses: [{ value: "ТЕСТ-СТАТУС", label: "Тестовый статус" }],
  years: [2001, 2002],
};

function setup(overrides: Partial<React.ComponentProps<typeof FilterPanel>> = {}) {
  const onApply = vi.fn();
  const onReset = vi.fn();

  render(
    <FilterPanel
      spec={DEFAULT_QUERY_SPEC}
      options={OPTIONS}
      onApply={onApply}
      onReset={onReset}
      {...overrides}
    />,
  );

  return { onApply, onReset };
}

describe("состав панели", () => {
  it("присутствуют все блоки референса", () => {
    setup();

    expect(screen.getByText("ПЕРИОД")).toBeInTheDocument();
    expect(screen.getByLabelText("ТЕРРИТОРИЯ")).toBeInTheDocument();
    expect(screen.getByLabelText("ОТРАСЛЬ")).toBeInTheDocument();
    expect(screen.getByText("УРОВЕНЬ РИСКА")).toBeInTheDocument();
    expect(screen.getByText("СУММА, ₸")).toBeInTheDocument();
    expect(screen.getByLabelText("СТАТУС ОБЪЕКТА")).toBeInTheDocument();
  });

  it("уровень «Нет данных» стоит в общем ряду и включён", () => {
    // По ТЗ это полноправный фильтруемый уровень, а не служебное состояние.
    setup();

    const checkbox = screen.getByRole("checkbox", { name: /Нет данных/ });
    expect(checkbox).toBeChecked();
    expect(screen.getAllByRole("checkbox").length).toBeGreaterThanOrEqual(RISK_LEVELS.length);
  });

  it("внизу закреплены «Сбросить» и «Применить»", () => {
    setup();

    expect(screen.getByRole("button", { name: "Сбросить" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Применить" })).toBeInTheDocument();
  });
});

describe("черновик и применение", () => {
  it("изменение чекбокса не применяется само по себе", () => {
    // Выборка серверная: применять каждый щелчок значит слать запрос на щелчок.
    const { onApply } = setup();

    screen.getByRole("checkbox", { name: /Низкий/ }).click();

    expect(onApply).not.toHaveBeenCalled();
  });

  it("«Применить» отдаёт накопленный черновик", async () => {
    const { onApply } = setup();

    await userEvent.click(screen.getByRole("checkbox", { name: /Низкий/ }));
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0]?.[0].riskLevels).not.toContain("low");
  });

  it("снять последний уровень нельзя — выборка стала бы заведомо пустой", async () => {
    const { onApply } = setup({
      spec: withFilters(DEFAULT_QUERY_SPEC, { riskLevels: ["high"] }),
    });

    await userEvent.click(screen.getByRole("checkbox", { name: /Высокий/ }));
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(onApply.mock.calls[0]?.[0].riskLevels).toEqual([...RISK_LEVELS]);
  });

  it("выбор года гасит диапазон дат", async () => {
    // Иначе даты остались бы активным, но невидимым в чипах фильтром.
    const { onApply } = setup({
      spec: withFilters(DEFAULT_QUERY_SPEC, { dateFrom: "2001-01-01", dateTo: "2001-12-31" }),
    });

    await userEvent.click(screen.getByRole("button", { name: "2002" }));
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    const applied = onApply.mock.calls[0]?.[0];
    expect(applied.year).toBe(2002);
    expect(applied.dateFrom).toBeNull();
    expect(applied.dateTo).toBeNull();
  });

  it("выбор территории попадает в выборку", async () => {
    const { onApply } = setup();

    await userEvent.selectOptions(screen.getByLabelText("ТЕРРИТОРИЯ"), "ТЕСТ-РАЙОН-2");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(onApply.mock.calls[0]?.[0].territoryCodes).toEqual(["ТЕСТ-РАЙОН-2"]);
  });

  it("границы суммы читаются числами, пустое поле — как «не задано»", async () => {
    const { onApply } = setup();

    await userEvent.type(screen.getByLabelText("от"), "500");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    const applied = onApply.mock.calls[0]?.[0];
    expect(applied.amountMin).toBe(500);
    expect(applied.amountMax).toBeNull();
  });

  it("«Сбросить» не смешивается с «Применить»", async () => {
    const { onApply, onReset } = setup();

    await userEvent.click(screen.getByRole("button", { name: "Сбросить" }));

    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("внешняя смена выборки пересобирает черновик", () => {
    // Кнопка «назад» или снятие чипа не должны оставлять панель в старом виде.
    const { rerender } = render(
      <FilterPanel
        spec={DEFAULT_QUERY_SPEC}
        options={OPTIONS}
        onApply={() => {}}
        onReset={() => {}}
      />,
    );

    rerender(
      <FilterPanel
        spec={withFilters(DEFAULT_QUERY_SPEC, { riskLevels: ["critical"] })}
        options={OPTIONS}
        onApply={() => {}}
        onReset={() => {}}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /Критический/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Низкий/ })).not.toBeChecked();
  });
});

describe("выдвижная панель и недоступные возможности", () => {
  it("кнопка закрытия появляется только с обработчиком", async () => {
    const onClose = vi.fn();
    setup({ onClose });

    await userEvent.click(screen.getByRole("button", { name: "Закрыть панель фильтров" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("«Сравнить периоды» показывается недоступной, а не прячется", () => {
    // Спрятанная возможность выглядит как отсутствующая; недоступная — как будущая.
    setup();

    expect(screen.getByRole("button", { name: "Сравнить периоды" })).toBeDisabled();
  });
});
