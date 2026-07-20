import { RiskBadge } from "@/components/risk/RiskBadge";
import type { RiskLevel } from "@/lib/risk";
import type { TerritoryFeatureProperties } from "@/components/map/MapView";

interface TerritoryPopupProps {
  territory: TerritoryFeatureProperties;
  onOpenCard?: (code: string) => void;
  onZoom?: (code: string) => void;
}

/**
 * Формат числа с разделением разрядов.
 *
 * Локаль задана явно, а не берётся из браузера: иначе на сервере и на клиенте
 * получатся разные строки и React сообщит о расхождении при гидратации.
 */
const nf = new Intl.NumberFormat("ru-RU");

function formatValue(value: number | null | undefined, unit: string): string {
  /*
    Отсутствие значения показывается словами, а не прочерком и тем более не
    нулём. «0 чел.» и «нет данных» — принципиально разные утверждения, и
    подменять второе первым запрещено по ТЗ.
  */
  if (value === null || value === undefined) return "нет данных";
  return `${nf.format(value)} ${unit}`;
}

/**
 * Всплывающая карточка территории.
 *
 * Состав и порядок полей повторяют UI-референс: название, казахское название,
 * административный центр, население, площадь, уровень риска.
 */
export function TerritoryPopup({ territory, onOpenCard, onZoom }: TerritoryPopupProps) {
  const level = (territory.risk_level ?? "unknown") as RiskLevel;

  const rows: Array<{ label: string; value: string; muted?: boolean }> = [
    {
      label: "Адм. центр",
      value: territory.admin_center ?? "нет данных",
      muted: !territory.admin_center,
    },
    {
      label: "Население",
      value: formatValue(territory.population, "чел."),
      muted: territory.population === null,
    },
    {
      label: "Площадь",
      value:
        territory.area_km2 !== null && territory.area_km2 !== undefined
          ? `${nf.format(Math.round(territory.area_km2))} км²`
          : territory.area_km2_computed !== null && territory.area_km2_computed !== undefined
            ? `${nf.format(Math.round(territory.area_km2_computed))} км² (расчётная)`
            : "нет данных",
      muted: territory.area_km2 === null && territory.area_km2_computed === null,
    },
  ];

  return (
    <div className="w-72 rounded-panel border border-border-base bg-surface p-4 shadow-panel">
      <h3 className="text-sm font-semibold text-text">{territory.name_ru}</h3>
      {territory.name_kk && (
        <p lang="kk" className="mt-0.5 text-xs text-text-muted">
          {territory.name_kk}
        </p>
      )}

      <dl className="mt-3 space-y-1.5 border-t border-border-base pt-3">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-3 text-xs">
            <dt className="text-text-muted">{row.label}</dt>
            <dd className={row.muted ? "text-text-subtle italic" : "text-text"}>{row.value}</dd>
          </div>
        ))}

        <div className="flex items-baseline justify-between gap-3 pt-1 text-xs">
          <dt className="text-text-muted">Уровень риска</dt>
          <dd>
            <RiskBadge level={level} score={territory.risk_score ?? null} size="sm" />
          </dd>
        </div>
      </dl>

      {territory.population_as_of && (
        <p className="mt-2 text-[11px] text-text-subtle">
          Население на {territory.population_as_of}
        </p>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => onOpenCard?.(territory.code)}
          className="flex-1 rounded border border-border-base px-2 py-1.5 text-xs text-text transition-colors hover:bg-surface-hover"
        >
          Открыть карточку
        </button>
        <button
          type="button"
          onClick={() => onZoom?.(territory.code)}
          className="rounded border border-border-base px-2 py-1.5 text-xs text-text transition-colors hover:bg-surface-hover"
        >
          Приблизить
        </button>
      </div>
    </div>
  );
}
