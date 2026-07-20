import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ResultCard } from "@/components/list/ResultCard";
import type { ListItem } from "@/lib/api/types";

/**
 * Значения заведомо тестовые.
 *
 * Правдоподобные суммы и названия районов в тестах — плохая идея: их копируют
 * в демонстрацию, и выдуманные цифры начинают выглядеть как данные системы.
 */
const ITEM: ListItem = {
  id: "ТЕСТ-1",
  objectType: "contract",
  name: "ТЕСТОВЫЙ ОБЪЕКТ",
  identifier: "ТЕСТ-НОМЕР-1",
  territoryCode: "ТЕСТ-РАЙОН",
  territoryName: "Тестовый район",
  amount: 111,
  amountUnit: "₸",
  riskScore: 77.5,
  riskLevel: "high",
  riskScorePreliminary: false,
  completeness: 0.9,
  topFactors: [
    { code: "F1", label: "ТЕСТОВЫЙ ФАКТОР 1", weight: 0.5 },
    { code: "F2", label: "ТЕСТОВЫЙ ФАКТОР 2", weight: 0.3 },
    { code: "F3", label: "ТЕСТОВЫЙ ФАКТОР 3", weight: 0.1 },
    { code: "F4", label: "ЛИШНИЙ ФАКТОР", weight: 0.05 },
  ],
  status: "ТЕСТ-СТАТУС",
  statusLabel: "Тестовый статус",
  source: { code: "ТЕСТ-ИСТОЧНИК", title: "Тестовый источник" },
  actualAt: "2001-02-03",
};

describe("состав карточки", () => {
  it("показаны все поля, которых требует ТЗ", () => {
    render(<ResultCard item={ITEM} />);

    expect(screen.getByText("Договоры")).toBeInTheDocument(); // тип объекта
    expect(screen.getByText("ТЕСТОВЫЙ ОБЪЕКТ")).toBeInTheDocument(); // название
    expect(screen.getByText("ТЕСТ-НОМЕР-1")).toBeInTheDocument(); // идентификатор
    expect(screen.getByText("Тестовый район")).toBeInTheDocument(); // территория
    expect(screen.getByText(/111 ₸/)).toBeInTheDocument(); // сумма с единицей
    expect(screen.getByText("Высокий")).toBeInTheDocument(); // уровень
    expect(screen.getByText("77.5")).toBeInTheDocument(); // Risk Score
    expect(screen.getByText("90 %")).toBeInTheDocument(); // полнота данных
    expect(screen.getByText("Тестовый статус")).toBeInTheDocument(); // статус
    expect(screen.getByText("Тестовый источник")).toBeInTheDocument(); // источник
    expect(screen.getByText("03.02.2001")).toBeInTheDocument(); // актуальность
  });

  it("факторов риска показывается не больше трёх", () => {
    render(<ResultCard item={ITEM} />);

    expect(screen.getByText("ТЕСТОВЫЙ ФАКТОР 3")).toBeInTheDocument();
    expect(screen.queryByText("ЛИШНИЙ ФАКТОР")).not.toBeInTheDocument();
  });

  it("при отсутствии названия подписью служит идентификатор", () => {
    // У договора может не быть названия — «Без названия» скрыло бы номер.
    render(<ResultCard item={{ ...ITEM, name: null }} />);

    expect(screen.getByRole("heading")).toHaveTextContent("ТЕСТ-НОМЕР-1");
  });

  it("отсутствующие значения показываются прочерком, а не нулём", () => {
    render(
      <ResultCard
        item={{ ...ITEM, amount: null, completeness: null, actualAt: null, source: null }}
      />,
    );

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryByText("0 %")).not.toBeInTheDocument();
  });
});

describe("честность оценки", () => {
  it("предварительный балл помечен видимым текстом, а не только тильдой", () => {
    render(<ResultCard item={{ ...ITEM, riskScorePreliminary: true }} />);

    expect(screen.getByText(/Балл предварительный/)).toBeInTheDocument();
  });

  it("обычный балл такой пометки не получает", () => {
    render(<ResultCard item={ITEM} />);

    expect(screen.queryByText(/Балл предварительный/)).not.toBeInTheDocument();
  });

  it("низкая полнота данных названа словами", () => {
    // «41 %» ничего не говорит тому, кто не знает, сколько у объекта полей.
    render(<ResultCard item={{ ...ITEM, completeness: 0.41 }} />);

    expect(screen.getByText("данных мало")).toBeInTheDocument();
  });

  it("уровень риска передан не только цветом", () => {
    // У плашки есть подпись и значок — см. RiskBadge.
    render(<ResultCard item={{ ...ITEM, riskLevel: "unknown", riskScore: null }} />);

    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });
});

describe("действия карточки", () => {
  it("все три действия ТЗ на месте и вызывают обработчики", async () => {
    const onOpen = vi.fn();
    const onShowOnMap = vi.fn();
    const onShowLinks = vi.fn();

    render(
      <ResultCard
        item={ITEM}
        onOpen={onOpen}
        onShowOnMap={onShowOnMap}
        onShowLinks={onShowLinks}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Открыть карточку" }));
    await userEvent.click(screen.getByRole("button", { name: "Показать на карте" }));
    await userEvent.click(screen.getByRole("button", { name: "Показать связи" }));

    expect(onOpen).toHaveBeenCalledWith(ITEM);
    expect(onShowOnMap).toHaveBeenCalledWith(ITEM);
    expect(onShowLinks).toHaveBeenCalledWith(ITEM);
  });

  it("объект без территории нельзя показать на карте", () => {
    render(<ResultCard item={{ ...ITEM, territoryCode: null }} onShowOnMap={() => {}} />);

    expect(screen.getByRole("button", { name: "Показать на карте" })).toBeDisabled();
  });

  it("выбранный объект помечен для вспомогательных технологий", () => {
    // Выбор общий для карты и списка — он должен читаться в обоих.
    render(<ResultCard item={ITEM} selected />);

    expect(screen.getByRole("article")).toHaveAttribute("aria-current", "true");
  });
});
