/**
 * Форматирование значений для показа.
 *
 * Общее правило: `null` — это «нет данных», и он показывается прочерком, а не
 * нулём. Ноль в этой системе означает измеренный ноль (нулевая сумма договора),
 * и подменять им отсутствие измерения нельзя — ТЗ запрещает ложный ноль.
 */

/** Прочерк для отсутствующих значений. Единый во всём интерфейсе. */
export const EM_DASH = "—";

const NUMBER_FORMAT = new Intl.NumberFormat("ru-RU");

/** Целое число с разрядами: «12 456». */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return NUMBER_FORMAT.format(value);
}

/**
 * Сумма с единицей измерения.
 *
 * Единица приходит с сервера и не подставляется по умолчанию: не всё
 * измеряется в тенге, а подпись «₸» под количеством объектов была бы враньём.
 */
export function formatAmount(value: number | null | undefined, unit: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  const formatted = NUMBER_FORMAT.format(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

/**
 * Дата в привычном виде: «31.12.2024».
 *
 * Разбор ручной, без `Date`: строка `2024-12-31` в `new Date` трактуется как
 * UTC-полночь, и в поясе восточнее Гринвича дата уезжала бы на сутки назад.
 */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return EM_DASH;
  return `${match[3]}.${match[2]}.${match[1]}`;
}

/** Доля 0..1 в проценты: «85 %». */
export function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  return `${Math.round(value * 100)} %`;
}

/**
 * Русское склонение после числа.
 *
 * Нужно ради счётчика над списком: «найдено 2 объектов» выглядит как недоделка
 * и подрывает доверие к остальным числам на экране.
 */
export function pluralRu(count: number, forms: readonly [string, string, string]): string {
  const abs = Math.abs(count) % 100;
  const tail = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (tail > 1 && tail < 5) return forms[1];
  if (tail === 1) return forms[0];
  return forms[2];
}

/** «12 456 объектов» — число вместе со склонённым словом. */
export function formatObjectCount(count: number): string {
  return `${formatCount(count)} ${pluralRu(count, ["объект", "объекта", "объектов"])}`;
}
