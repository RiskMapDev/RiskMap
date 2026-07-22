/**
 * Знак системы: восьмиконечная звезда из двух квадратов, круги и лучи.
 *
 * Нарисован кодом, а не положен картинкой: логотип живёт в местах размером
 * 32–36 пикселей, и растровая копия там мылится, а SVG со `currentColor`
 * наследует цвет контейнера и не требует отдельных версий под тёмную тему.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 100 100"
      fill="none"
      stroke="currentColor"
      strokeWidth={4}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {/* Два квадрата — прямой и повёрнутый — дают восьмиконечную звезду. */}
      <rect x="22" y="22" width="56" height="56" />
      <rect x="22" y="22" width="56" height="56" transform="rotate(45 50 50)" />
      <circle cx="50" cy="50" r="26" />
      <circle cx="50" cy="50" r="17" />
      <circle cx="50" cy="50" r="8" />
      {/* Восемь лучей: к вершинам повёрнутого квадрата и к углам прямого. */}
      <path d="M50 10v80M10 50h80M22 22l56 56M78 22l-56 56" />
    </svg>
  );
}
