import { Info } from "lucide-react";
import type { KpiPayload } from "@/lib/api/dashboard";

interface KpiCardProps {
  kpi: KpiPayload;
  onOpen?: (drillDown: Record<string, string>) => void;
}

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });

/**
 * Крупные суммы читаются человеком плохо. Приводим к миллиардам и миллионам,
 * но только денежные величины: «13 601 объектов» в миллиардах не бывает.
 */
function formatValue(value: number, unit: string): string {
  if (unit !== "₸") return nf.format(value);

  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2).replace(".", ",")} млрд`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(1).replace(".", ",")} млн`;
  return nf.format(value);
}

/**
 * Карточка показателя.
 *
 * Отсутствие значения показывается словами и с причиной, а не нулём и не
 * прочерком. Ноль означал бы измеренное отсутствие — например, что
 * аналитических материалов не заведено, — тогда как в действительности такой
 * сущности в источниках нет вовсе, и вывод из этих двух состояний
 * противоположный.
 */
export function KpiCard({ kpi, onOpen }: KpiCardProps) {
  const clickable = kpi.available && kpi.drill_down !== null;

  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium text-text-muted">{kpi.title}</span>
        <span
          className="shrink-0 text-text-subtle"
          title={
            `${kpi.definition}` +
            (kpi.sources.length ? `\n\nИсточники: ${kpi.sources.join(", ")}` : "") +
            (kpi.data_as_of ? `\nДанные за: ${kpi.data_as_of}` : "")
          }
        >
          <Info className="size-3.5" aria-hidden="true" />
        </span>
      </div>

      {kpi.available && kpi.value !== null ? (
        <>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-text">
            {formatValue(kpi.value, kpi.unit)}
            {kpi.unit === "₸" && <span className="ml-1 text-base font-normal">₸</span>}
            {kpi.unit && kpi.unit !== "₸" && (
              <span className="ml-1 text-sm font-normal text-text-muted">{kpi.unit}</span>
            )}
          </p>
          {kpi.caption && <p className="mt-0.5 text-xs text-text-subtle">{kpi.caption}</p>}
        </>
      ) : (
        <>
          <p className="mt-2 text-lg font-medium text-text-subtle">нет данных</p>
          <p className="mt-0.5 text-xs text-text-subtle">{kpi.reason}</p>
        </>
      )}
    </>
  );

  const shared =
    "flex flex-col rounded-panel border border-border-base bg-surface p-4 text-left shadow-card";

  if (!clickable) {
    return <div className={shared}>{body}</div>;
  }

  return (
    <button
      type="button"
      onClick={() => onOpen?.(kpi.drill_down!)}
      className={`${shared} transition-colors hover:border-accent hover:bg-surface-hover`}
    >
      {body}
      <span className="mt-2 text-xs text-accent">Открыть выборку →</span>
    </button>
  );
}
