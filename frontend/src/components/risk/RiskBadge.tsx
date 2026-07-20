import { RISK_LEVEL_CLASSES, riskMeta, type RiskLevel } from "@/lib/risk";

interface RiskBadgeProps {
  level: RiskLevel;
  /**
   * Балл риска. Показывается рядом с уровнем, если он есть.
   * `null` означает «не посчитан», и это не то же самое, что 0.
   */
  score?: number | null;
  /**
   * Балл посчитан, но полноты данных не хватило — уровень серый.
   * Балл в этом случае помечается как предварительный: он информативен,
   * но не является основанием для вывода.
   */
  preliminary?: boolean;
  size?: "sm" | "md";
}

/**
 * Плашка уровня риска.
 *
 * Уровень передаётся тремя независимыми каналами — цветом, значком и текстом.
 * Цвет здесь вспомогательный: подписи «высокого» и «критического» по ТЗ
 * различаются слишком слабо, чтобы на него полагаться.
 */
export function RiskBadge({ level, score, preliminary = false, size = "md" }: RiskBadgeProps) {
  const meta = riskMeta(level);
  const padding = size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border font-medium ${padding} ${RISK_LEVEL_CLASSES[level]}`}
      title={meta.description}
    >
      {/* Значок декоративен для скринридера: смысл несёт соседний текст. */}
      <span aria-hidden="true">{meta.glyph}</span>
      <span>{meta.label}</span>
      {typeof score === "number" && (
        <span className="font-mono tabular-nums opacity-80">
          {preliminary && (
            /* Тильда — визуальный сигнал приблизительности; расшифровка в title. */
            <span aria-hidden="true">~</span>
          )}
          {score.toFixed(1)}
        </span>
      )}
      {preliminary && (
        <span className="sr-only">
          — балл предварительный, данных недостаточно для окончательной оценки
        </span>
      )}
    </span>
  );
}
