import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { ResultList } from "@/components/list/ResultList";
import type { ListItem } from "@/lib/api/types";

/*
  jsdom не считает раскладку: `offsetHeight` у всего равен нулю. Виртуализатор
  при нулевой высоте области честно решает, что видимых строк нет, и не рисует
  ничего. Поэтому высота подставляется вручную — это подпорка окружения, а не
  подмена поведения компонента.
*/
const originalOffsetHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "offsetHeight",
);

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get: () => 600,
  });
});

afterAll(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", originalOffsetHeight);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, "offsetHeight");
  }
});

/** Значения заведомо тестовые — их нельзя перепутать с настоящими данными. */
function testItem(index: number): ListItem {
  return {
    id: `ТЕСТ-${index}`,
    objectType: "contract",
    name: `ТЕСТОВЫЙ ОБЪЕКТ ${index}`,
    identifier: null,
    territoryCode: "ТЕСТ-РАЙОН",
    territoryName: "Тестовый район",
    amount: index,
    amountUnit: "₸",
    riskScore: index,
    riskLevel: "medium",
    riskScorePreliminary: false,
    completeness: 1,
    topFactors: [],
    status: null,
    statusLabel: null,
    source: null,
    actualAt: null,
  };
}

const ITEMS = [testItem(1), testItem(2), testItem(3)];

function setup(overrides: Partial<React.ComponentProps<typeof ResultList>> = {}) {
  const onPageChange = vi.fn();

  render(
    <ResultList
      items={ITEMS}
      status="ready"
      total={ITEMS.length}
      page={1}
      totalPages={1}
      onPageChange={onPageChange}
      {...overrides}
    />,
  );

  return { onPageChange };
}

describe("состояния списка", () => {
  it("во время загрузки не показывается число найденного", () => {
    // Прямой запрет ТЗ: ложный «0» заставляет менять фильтры без причины.
    setup({ status: "loading", items: [], total: null });

    expect(screen.getByText("Идёт поиск…")).toBeInTheDocument();
    expect(screen.queryByText(/Найдено/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 объектов/)).not.toBeInTheDocument();
  });

  it("во время загрузки не показывается и пустое состояние", () => {
    setup({ status: "loading", items: [], total: null });

    expect(screen.queryByText(/ничего не подошло/)).not.toBeInTheDocument();
  });

  it("ошибка отличается от пустоты и предлагает повтор", async () => {
    const onRetry = vi.fn();
    setup({ status: "error", items: [], total: null, onRetry });

    expect(screen.getByText("Не удалось загрузить список")).toBeInTheDocument();
    expect(screen.getByText("Число объектов неизвестно")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Повторить/ }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("пусто из-за фильтров и пусто из-за отсутствия данных — разные сообщения", () => {
    const { unmount } = render(
      <ResultList
        items={[]}
        status="ready"
        total={0}
        page={1}
        totalPages={0}
        filtered
        onPageChange={() => {}}
      />,
    );
    expect(screen.getByText("Под фильтры ничего не подошло")).toBeInTheDocument();
    unmount();

    render(
      <ResultList
        items={[]}
        status="ready"
        total={0}
        page={1}
        totalPages={0}
        onPageChange={() => {}}
      />,
    );
    expect(screen.getByText("Объектов пока нет")).toBeInTheDocument();
  });

  it("нулевой результат после загрузки показывается честно", () => {
    setup({ items: [], total: 0, totalPages: 0 });

    expect(screen.getByText(/0 объектов/)).toBeInTheDocument();
  });

  it("непосчитанное сервером число не выдаётся за ноль", () => {
    setup({ total: null });

    expect(screen.getByText("Показаны первые результаты")).toBeInTheDocument();
  });
});

describe("содержимое и счётчик", () => {
  it("счётчик склоняется по-русски", () => {
    setup();
    expect(screen.getByText(/3 объекта/)).toBeInTheDocument();
  });

  it("объекты выборки отрисованы карточками", () => {
    setup();

    expect(screen.getByText("ТЕСТОВЫЙ ОБЪЕКТ 1")).toBeInTheDocument();
    expect(screen.getByText("ТЕСТОВЫЙ ОБЪЕКТ 3")).toBeInTheDocument();
  });

  it("счётчик объявляется вспомогательным технологиям", () => {
    // Смена фильтров не двигает фокус — без live-области изменение незаметно.
    setup();

    const live = screen.getByText(/3 объекта/).closest("[aria-live]");
    expect(live).toHaveAttribute("aria-live", "polite");
  });

  it("шапка принимает сортировку слотом", () => {
    setup({ toolbar: <span>ТЕСТОВЫЙ СЛОТ</span> });

    expect(screen.getByText("ТЕСТОВЫЙ СЛОТ")).toBeInTheDocument();
  });
});

describe("серверная пагинация", () => {
  it("на первой странице «Назад» недоступна", () => {
    setup({ page: 1, totalPages: 3 });

    expect(screen.getByRole("button", { name: /Назад/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Вперёд/ })).toBeEnabled();
  });

  it("на последней странице «Вперёд» недоступна", () => {
    setup({ page: 3, totalPages: 3 });

    expect(screen.getByRole("button", { name: /Вперёд/ })).toBeDisabled();
  });

  it("переход запрашивает страницу у родителя, а не листает локально", async () => {
    const { onPageChange } = setup({ page: 2, totalPages: 3 });

    await userEvent.click(screen.getByRole("button", { name: /Вперёд/ }));

    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("номер страницы виден", () => {
    setup({ page: 2, totalPages: 5 });

    expect(screen.getByText(/Страница 2/)).toBeInTheDocument();
    expect(screen.getByText(/из 5/)).toBeInTheDocument();
  });

  it("пагинация не мешается в пустом и ошибочном состояниях", () => {
    setup({ status: "error", items: [], total: null });

    expect(screen.queryByRole("navigation", { name: "Страницы результатов" })).not.toBeInTheDocument();
  });
});
