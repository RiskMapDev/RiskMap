import { RISK_LEVELS_DISPLAY_ORDER, riskMeta, type RiskLevel } from "@/lib/risk";

interface RiskDonutProps {
  counts: Record<RiskLevel, number>;
  labels: Record<RiskLevel, string>;
  total: number;
}

/** Цвет заливки сегмента берётся из тех же токенов, что и карта. */
const FILL: Record<RiskLevel, string> = {
  low: "var(--risk-low-fill)",
  medium: "var(--risk-medium-fill)",
  high: "var(--risk-high-fill)",
  critical: "var(--risk-critical-fill)",
  unknown: "var(--risk-none-fill)",
};

const RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * Кольцевая диаграмма распределения по уровням риска.
 *
 * Уровень «нет данных» — полноправный сегмент. Убрать его значит показать
 * картину благополучнее, чем она есть: неизмеренные объекты исчезли бы из
 * знаменателя, и доли остальных уровней выросли бы сами собой.
 *
 * Диаграмма декоративна для скринридера: те же числа лежат рядом в таблице,
 * и дублировать их в SVG значило бы заставить прочитать всё дважды.
 */
export function RiskDonut({ counts, labels, total }: RiskDonutProps) {
  /*
    Смещение каждого сегмента — сумма длин предыдущих. Считается накопительно
    через reduce, а не мутацией переменной в map: изменяемое состояние во
    время отрисовки ломает предположения компилятора React о чистоте.
  */
  const segments = RISK_LEVELS_DISPLAY_ORDER.reduce<
    Array<{ level: RiskLevel; count: number; share: number; length: number; offset: number }>
  >((acc, level) => {
    const count = counts[level] ?? 0;
    const share = total > 0 ? count / total : 0;
    const length = share * CIRCUMFERENCE;
    const previous = acc[acc.length - 1];
    const offset = previous ? previous.offset + previous.length : 0;

    acc.push({ level, count, share, length, offset });
    return acc;
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg viewBox="0 0 130 130" className="size-36 shrink-0 -rotate-90" aria-hidden="true">
        <circle cx="65" cy="65" r={RADIUS} fill="none" stroke="var(--border)" strokeWidth="16" />
        {segments
          .filter((s) => s.length > 0)
          .map((s) => (
            <circle
              key={s.level}
              cx="65"
              cy="65"
              r={RADIUS}
              fill="none"
              stroke={FILL[s.level]}
              strokeWidth="16"
              strokeDasharray={`${s.length} ${CIRCUMFERENCE - s.length}`}
              strokeDashoffset={-s.offset}
            />
          ))}
      </svg>

      <table className="min-w-52 flex-1 text-sm">
        <caption className="sr-only">Распределение объектов по уровням риска</caption>
        <tbody>
          {segments.map((s) => {
            const meta = riskMeta(s.level);
            return (
              <tr key={s.level} className="border-b border-border-base last:border-0">
                <td className="py-1.5 pr-2">
                  <span className="flex items-center gap-2">
                    {/* Значок дублирует цвет: полагаться только на цвет нельзя. */}
                    <span aria-hidden="true" style={{ color: FILL[s.level] }}>
                      {meta.glyph}
                    </span>
                    <span className="text-text">{labels[s.level] ?? meta.label}</span>
                  </span>
                </td>
                <td className="py-1.5 text-right tabular-nums text-text">
                  {s.count.toLocaleString("ru-RU")}
                </td>
                <td className="py-1.5 pl-3 text-right tabular-nums text-text-muted">
                  {total > 0 ? `${(s.share * 100).toFixed(1)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
