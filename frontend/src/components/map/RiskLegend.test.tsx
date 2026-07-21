import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskLegend } from "@/components/map/RiskLegend";
import type { LayerCoverageSummary } from "@/lib/api/territories";

function покрытие(overrides: Partial<LayerCoverageSummary> = {}): LayerCoverageSummary {
  return {
    code: "subsidies",
    objects_total: 3413,
    objects_shown: 1944,
    objects_not_shown: 1469,
    objects_without_territory: 66,
    ...overrides,
  };
}

describe("легенда карты рисков", () => {
  it("перечисляет все пять уровней", () => {
    render(<RiskLegend />);

    for (const label of ["Низкий", "Средний", "Высокий", "Критический", "Нет данных"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("называет «нет данных» наравне с измеренными уровнями", () => {
    /*
      Серый уровень не выносится в сноску и не прячется: отсутствие данных не
      означает отсутствия риска, и пользователь обязан видеть это состояние
      так же ясно, как критический уровень.
    */
    render(<RiskLegend />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[4]).toHaveTextContent("Нет данных");
  });

  it("объясняет, что цвет — это худший объект территории", () => {
    render(<RiskLegend />);

    expect(screen.getByText(/худший из измеренных уровней/)).toBeInTheDocument();
  });

  it("называет долю показанных объектов слоя", () => {
    render(<RiskLegend coverage={покрытие()} />);

    // 1944 из 3413 — это 57 %. Карта, показывающая чуть больше половины
    // слоя, внешне неотличима от полной, поэтому число обязательно.
    expect(screen.getByText(/1 944/)).toBeInTheDocument();
    expect(screen.getByText(/57 %/)).toBeInTheDocument();
  });

  it("объясняет, почему объекты не попали на карту", () => {
    render(<RiskLegend coverage={покрытие()} />);

    expect(screen.getByText(/территория не определена/)).toBeInTheDocument();
    expect(screen.getByText(/Списком/)).toBeInTheDocument();
  });

  it("не выдумывает пропуски, когда показан весь слой", () => {
    render(
      <RiskLegend
        coverage={покрытие({
          objects_total: 355,
          objects_shown: 355,
          objects_not_shown: 0,
          objects_without_territory: 0,
        })}
      />,
    );

    expect(screen.queryByText(/не показаны/)).not.toBeInTheDocument();
    expect(screen.getByText(/100 %/)).toBeInTheDocument();
  });

  it("без сведений о слое показывает только шкалу", () => {
    render(<RiskLegend />);

    expect(screen.queryByText(/На карте/)).not.toBeInTheDocument();
  });
});
