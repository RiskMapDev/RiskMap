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

const BREAKDOWN = [
  { code: "critical", label: "Критический", token: "--risk-critical-fill" },
  { code: "high", label: "Высокий", token: "--risk-high-fill" },
  { code: "medium", label: "Средний", token: "--risk-medium-fill" },
  { code: "low", label: "Низкий", token: "--risk-low-fill" },
  { code: "unknown", label: "Нет данных", token: "--risk-none-fill" },
] as const;

/**
 * Распределение объектов территории по уровням.
 *
 * Без него цвет полигона вводит в заблуждение: район красен и когда критичны
 * все объекты, и когда критичен один из трёхсот. Уровень отвечает на вопрос
 * «есть ли здесь проблема», разбивка — «насколько она распространена», и
 * второй вопрос без первого не имеет смысла, а первый без второго опасен.
 *
 * Порядок от критического к низкому: читают сверху, а важное — сверху.
 */
function RiskBreakdown({
  counts,
  total,
}: {
  counts?: Record<string, number>;
  total?: number;
}) {
  if (!counts || !total) return null;

  const present = BREAKDOWN.filter((item) => (counts[item.code] ?? 0) > 0);
  if (present.length === 0) return null;

  return (
    <div className="mt-3 border-t border-border-base pt-3">
      <p className="text-[11px] text-text-muted">
        Объектов слоя: {nf.format(total)}
      </p>
      <ul className="mt-1.5 space-y-1">
        {present.map((item) => {
          const count = counts[item.code] ?? 0;
          return (
            <li key={item.code} className="flex items-center gap-2 text-[11px]">
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-sm"
                style={{ backgroundColor: `var(${item.token})` }}
              />
              <span className="flex-1 text-text-muted">{item.label}</span>
              <span className="tabular-nums text-text">{nf.format(count)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
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

      <RiskBreakdown counts={territory.risk_counts} total={territory.objects_total} />

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
