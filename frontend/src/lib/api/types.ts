/**
 * Форма ответов API списка объектов.
 *
 * API ещё не написан, поэтому здесь зафиксирован контракт, на который
 * рассчитывает интерфейс. Он выведен из требований ТЗ к карточке объекта
 * (раздел 6.4, пункт 4), а не из того, что «удобно отдать» серверу: если поле
 * должно быть видно пользователю, оно обязано быть в ответе.
 *
 * Соглашение по «неизвестно»: `null` означает «значения нет или оно не
 * измерено», и это НЕ то же самое, что `0`. Ноль — это измеренный ноль.
 * Поэтому суммы, баллы и полнота типизированы как `number | null`, а не
 * получают умолчание `0` — иначе интерфейс покажет ложный ноль, что ТЗ
 * прямо запрещает.
 */

import type { ObjectType } from "@/lib/query-spec";
import type { RiskLevel } from "@/lib/risk";

/** Источник данных: ТЗ требует показывать, откуда взята запись. */
export interface DataSourceRef {
  /** Код источника, например код реестра или загрузки. */
  code: string;
  /** Человекочитаемое название источника. */
  title: string;
}

/**
 * Фактор риска — вклад отдельного индикатора в общий балл.
 *
 * `weight` — доля вклада (0..1), а не сам балл: карточка показывает, ЧТО
 * повлияло сильнее всего, а не арифметику расчёта.
 */
export interface RiskFactor {
  code: string;
  label: string;
  weight: number | null;
}

/**
 * Объект в списке.
 *
 * Идентификация раздвоена намеренно: у договора есть номер, но может не быть
 * названия, у территории наоборот. Карточка показывает то, что есть, и не
 * выдумывает подпись вида «Без названия» вместо номера.
 */
export interface ListItem {
  id: string;
  objectType: ObjectType;
  name: string | null;
  /** Номер договора, БИН, кадастровый номер — то, чем объект опознаётся. */
  identifier: string | null;

  territoryCode: string | null;
  territoryName: string | null;

  amount: number | null;
  /** Единица суммы приходит с сервера: не все объекты измеряются в тенге. */
  amountUnit: string | null;

  /** Балл риска. `null` — не рассчитан; это не ноль. */
  riskScore: number | null;
  riskLevel: RiskLevel;
  /**
   * Балл рассчитан на неполных данных.
   * Такой балл нельзя показывать наравне с обычным — см. `RiskBadge`.
   */
  riskScorePreliminary: boolean;

  /** Доля заполненных обязательных полей, 0..1. `null` — не считалась. */
  completeness: number | null;

  /** Главные факторы риска. Сервер отдаёт их уже отсортированными по вкладу. */
  topFactors: RiskFactor[];

  status: string | null;
  statusLabel: string | null;

  source: DataSourceRef | null;
  /** Дата актуальности данных, ISO-8601 (YYYY-MM-DD). */
  actualAt: string | null;
}

/** Метаданные страницы. Пагинация серверная — клиент их не вычисляет. */
export interface PageMeta {
  page: number;
  pageSize: number;
  /**
   * Всего объектов в выборке.
   *
   * `null` допустим: если сервер не смог посчитать точное число за отведённое
   * время, честнее сказать «неизвестно», чем показать неверное число.
   */
  total: number | null;
  totalPages: number | null;
}

/**
 * Агрегаты по всей выборке, а не по текущей странице.
 *
 * Нужны, чтобы счётчики над списком и легенда карты показывали одно и то же:
 * это два представления одной выборки.
 */
export interface ListAggregates {
  byRiskLevel: Record<RiskLevel, number>;
  totalAmount: number | null;
  /** Доля объектов с рассчитанным баллом, 0..1. */
  measuredShare: number | null;
}

export interface ListResponse {
  items: ListItem[];
  page: PageMeta;
  aggregates: ListAggregates | null;
}

/** Вариант выбора в фильтре. `count` — сколько объектов подходит, если сервер посчитал. */
export interface FilterOption {
  value: string;
  label: string;
  count?: number | null;
}

/**
 * Справочники для панели фильтров.
 *
 * Приходят отдельным запросом, а не зашиты в код: перечень районов, отраслей и
 * статусов задаётся данными региона и меняется без пересборки фронтенда.
 */
export interface FilterOptions {
  territories: FilterOption[];
  industries: FilterOption[];
  statuses: FilterOption[];
  /** Годы, за которые вообще есть данные — для пилюль периода. */
  years: number[];
}

/** Состояние загрузки. Отдельный тип, чтобы «пусто» и «ещё грузится» не смешивались. */
export type LoadState = "loading" | "error" | "ready";
