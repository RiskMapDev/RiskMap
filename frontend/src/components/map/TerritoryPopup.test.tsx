import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TerritoryPopup } from "@/components/map/TerritoryPopup";
import type { TerritoryFeatureProperties } from "@/components/map/MapView";

function территория(
  overrides: Partial<TerritoryFeatureProperties> = {},
): TerritoryFeatureProperties {
  return {
    code: "test-district",
    name_ru: "Тестовый район",
    name_kk: "Тест ауданы",
    level: "district",
    admin_center: "с. Тестовое",
    population: 74000,
    population_as_of: "2026-04-01",
    area_km2: 13900,
    area_km2_computed: 13850,
    risk_level: "medium",
    risk_score: 42.5,
    ...overrides,
  };
}

describe("popup территории", () => {
  it("показывает название и казахское название", () => {
    render(<TerritoryPopup territory={территория()} />);

    expect(screen.getByText("Тестовый район")).toBeInTheDocument();
    expect(screen.getByText("Тест ауданы")).toBeInTheDocument();
  });

  it("отмечает казахское название атрибутом языка", () => {
    // Без lang скринридер прочитает казахский текст по правилам русского.
    render(<TerritoryPopup territory={территория()} />);

    expect(screen.getByText("Тест ауданы")).toHaveAttribute("lang", "kk");
  });

  it("разделяет разряды в населении", () => {
    render(<TerritoryPopup territory={территория()} />);

    expect(screen.getByText(/74\s*000 чел\./)).toBeInTheDocument();
  });

  it("показывает уровень риска подписью, а не только цветом", () => {
    render(<TerritoryPopup territory={территория({ risk_level: "critical" })} />);

    expect(screen.getByText("Критический")).toBeInTheDocument();
  });
});

describe("распределение объектов по уровням", () => {
  it("показывает, сколько объектов на каждом уровне", () => {
    /*
      Уровень территории — это худший её объект. Без разбивки пользователь не
      отличит район, где критичны все, от района, где критичен один из
      трёхсот, а это разные поводы для действий.
    */
    render(
      <TerritoryPopup
        territory={территория({
          risk_level: "critical",
          risk_counts: { low: 300, medium: 12, high: 0, critical: 1, unknown: 0 },
          objects_total: 313,
        })}
      />,
    );

    expect(screen.getByText("Объектов слоя: 313")).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("не показывает уровни, которых в территории нет", () => {
    render(
      <TerritoryPopup
        territory={территория({
          risk_counts: { low: 5, medium: 0, high: 0, critical: 0, unknown: 0 },
          objects_total: 5,
        })}
      />,
    );

    // Строка «Критический: 0» создаёт впечатление проверенного отсутствия
    // там, где просто нет таких объектов.
    expect(screen.queryByText("Критический")).not.toBeInTheDocument();
    expect(screen.getByText("Низкий")).toBeInTheDocument();
  });

  it("без слоя разбивка не показывается", () => {
    render(<TerritoryPopup territory={территория()} />);

    expect(screen.queryByText(/Объектов слоя/)).not.toBeInTheDocument();
  });

  it("территория без объектов не изображает пустую разбивку", () => {
    render(
      <TerritoryPopup
        territory={территория({
          risk_level: "unknown",
          risk_counts: { low: 0, medium: 0, high: 0, critical: 0, unknown: 0 },
          objects_total: 0,
        })}
      />,
    );

    expect(screen.queryByText(/Объектов слоя/)).not.toBeInTheDocument();
  });
});

describe("отсутствие данных", () => {
  it("пишет «нет данных» вместо нуля", () => {
    // «0 чел.» и «нет данных» — разные утверждения. Подменять второе первым
    // запрещено требованием ТЗ.
    render(<TerritoryPopup territory={территория({ population: null })} />);

    expect(screen.getByText("нет данных")).toBeInTheDocument();
    expect(screen.queryByText(/^0 чел\./)).not.toBeInTheDocument();
  });

  it("отсутствие адм. центра не превращается в пустую строку", () => {
    render(<TerritoryPopup territory={территория({ admin_center: null })} />);

    expect(screen.getAllByText("нет данных").length).toBeGreaterThan(0);
  });

  it("без оценки показывает серый уровень", () => {
    render(
      <TerritoryPopup
        territory={территория({ risk_level: undefined, risk_score: null })}
      />,
    );

    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });

  it("расчётная площадь помечается как расчётная", () => {
    // Заявленная в документе и вычисленная по геометрии — разные величины,
    // и выдавать вторую за первую нельзя.
    render(<TerritoryPopup territory={территория({ area_km2: null })} />);

    expect(screen.getByText(/расчётная/)).toBeInTheDocument();
  });
});
