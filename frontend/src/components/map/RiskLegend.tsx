"use client";

import type { LayerCoverageSummary } from "@/lib/api/territories";

/**
 * Легенда карты рисков.
 *
 * Цвета берутся из тех же токенов, что и заливка полигонов, а не задаются
 * второй раз числами: легенда, разошедшаяся с картой, хуже отсутствующей.
 *
 * Серый уровень стоит в одном ряду с остальными, а не выносится в сноску. Он
 * не «прочее»: территория без данных — это состояние, о котором пользователь
 * обязан знать так же ясно, как о критическом риске, потому что отсутствие
 * данных не означает отсутствия риска.
 */

const LEVELS = [
  { code: "low", label: "Низкий", token: "--risk-low-fill" },
  { code: "medium", label: "Средний", token: "--risk-medium-fill" },
  { code: "high", label: "Высокий", token: "--risk-high-fill" },
  { code: "critical", label: "Критический", token: "--risk-critical-fill" },
  { code: "unknown", label: "Нет данных", token: "--risk-none-fill" },
] as const;

export function RiskLegend({ coverage }: { coverage?: LayerCoverageSummary }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
        Уровень риска
      </h3>

      <ul className="mt-2 space-y-1">
        {LEVELS.map((level) => (
          <li key={level.code} className="flex items-center gap-2 text-sm text-text">
            <span
              aria-hidden="true"
              className="size-3.5 shrink-0 rounded-sm border border-border-base"
              style={{ backgroundColor: `var(${level.token})` }}
            />
            {level.label}
          </li>
        ))}
      </ul>

      <p className="mt-2 text-xs text-text-subtle">
        Цвет территории — худший из измеренных уровней её объектов. Сколько
        объектов на каждом уровне, видно в подсказке при наведении.
      </p>

      {coverage && <Coverage coverage={coverage} />}
    </div>
  );
}

/**
 * Сколько объектов слоя попало на карту.
 *
 * Показывается всегда, а не только когда «что-то потерялось»: карта, на
 * которой видна треть слоя, внешне неотличима от полной, и единственный способ
 * не ввести пользователя в заблуждение — назвать число.
 */
function Coverage({ coverage }: { coverage: LayerCoverageSummary }) {
  const { objects_shown: shown, objects_total: total } = coverage;
  const hidden = coverage.objects_not_shown;
  const share = total > 0 ? Math.round((shown / total) * 100) : 0;

  return (
    <div className="mt-3 border-t border-border-base pt-3">
      <p className="text-xs text-text-muted">
        На карте <span className="font-medium text-text">{shown.toLocaleString("ru")}</span> из{" "}
        {total.toLocaleString("ru")} объектов слоя ({share} %).
      </p>

      {hidden > 0 && (
        <p className="mt-1 text-xs text-text-subtle">
          Остальные {hidden.toLocaleString("ru")} не показаны: у{" "}
          {coverage.objects_without_territory.toLocaleString("ru")} территория не
          определена, прочие привязаны к другому уровню или региону. Они доступны
          в режиме «Списком».
        </p>
      )}
    </div>
  );
}
