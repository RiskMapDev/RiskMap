"use client";

import { MapPin, Network, SquareArrowOutUpRight } from "lucide-react";

import type { ListItem } from "@/lib/api/types";
import { EM_DASH, formatAmount, formatDate, formatShare } from "@/lib/format";
import { OBJECT_TYPE_LABELS } from "@/lib/query-spec";
import { RiskBadge } from "@/components/risk/RiskBadge";

/**
 * Порог, ниже которого неполнота данных подписывается словами, а не процентом.
 *
 * Число «41 %» само по себе ничего не говорит человеку, который не знает,
 * сколько полей у объекта. Явная подпись «данных мало» говорит.
 */
const LOW_COMPLETENESS = 0.6;

interface ResultCardProps {
  item: ListItem;
  /** Объект выбран на карте или в списке — выборка у представлений общая. */
  selected?: boolean;
  onOpen?: (item: ListItem) => void;
  onShowOnMap?: (item: ListItem) => void;
  onShowLinks?: (item: ListItem) => void;
}

/** Подпись объекта: название, а если его нет — идентификатор. */
function title(item: ListItem): string {
  return item.name?.trim() || item.identifier?.trim() || `Объект ${item.id}`;
}

/**
 * Карточка объекта в списке.
 *
 * Состав полей задан ТЗ (6.4, п. 4) и не сокращается «для компактности»:
 * решение по объекту принимается прямо здесь, и полнота данных с источником
 * нужны рядом с баллом, а не в отдельной карточке через два перехода.
 */
export function ResultCard({
  item,
  selected = false,
  onOpen,
  onShowOnMap,
  onShowLinks,
}: ResultCardProps) {
  const heading = title(item);
  const lowCompleteness = item.completeness !== null && item.completeness < LOW_COMPLETENESS;

  return (
    <article
      aria-label={`${OBJECT_TYPE_LABELS[item.objectType]}: ${heading}`}
      aria-current={selected ? "true" : undefined}
      className={`rounded-card border bg-surface p-4 shadow-[var(--shadow-card)] transition-colors ${
        selected ? "border-accent ring-1 ring-accent" : "border-border-base hover:bg-surface-hover"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
            {OBJECT_TYPE_LABELS[item.objectType]}
          </p>
          <h3 className="mt-0.5 truncate text-sm font-semibold text-text">{heading}</h3>
          {/* Идентификатор показывается и тогда, когда есть название: по нему ищут в первоисточнике. */}
          {item.identifier && item.name && (
            <p className="mt-0.5 font-mono text-xs text-text-subtle">{item.identifier}</p>
          )}
        </div>

        <RiskBadge
          level={item.riskLevel}
          score={item.riskScore}
          preliminary={item.riskScorePreliminary}
        />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-text-muted">Территория</dt>
          <dd className="text-text">{item.territoryName ?? EM_DASH}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Сумма</dt>
          <dd className="font-mono tabular-nums text-text">
            {formatAmount(item.amount, item.amountUnit)}
          </dd>
        </div>
        <div>
          <dt className="text-text-muted">Полнота данных</dt>
          <dd className={lowCompleteness ? "font-medium text-warn" : "text-text"}>
            {formatShare(item.completeness)}
            {lowCompleteness && <span className="ml-1 text-text-muted">данных мало</span>}
          </dd>
        </div>
        <div>
          <dt className="text-text-muted">Статус</dt>
          <dd className="text-text">{item.statusLabel ?? item.status ?? EM_DASH}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Источник</dt>
          <dd className="truncate text-text">{item.source?.title ?? EM_DASH}</dd>
        </div>
        <div>
          <dt className="text-text-muted">Актуальность</dt>
          <dd className="text-text">{formatDate(item.actualAt)}</dd>
        </div>
      </dl>

      {/*
        Предварительность балла продублирована видимой подписью. В `RiskBadge`
        она есть только тильдой и текстом для скринридера, а зрячий пользователь
        обязан увидеть словами, что балл не является основанием для вывода.
      */}
      {item.riskScorePreliminary && (
        <p className="mt-2 rounded border border-risk-none-border bg-risk-none-bg px-2 py-1 text-xs text-risk-none-text">
          Балл предварительный: данных недостаточно для окончательной оценки.
        </p>
      )}

      {item.topFactors.length > 0 && (
        <div className="mt-3">
          <p className="text-xs text-text-muted">Главные факторы риска</p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {/* Не больше трёх: карточка перечисляет причины, а не воспроизводит расчёт. */}
            {item.topFactors.slice(0, 3).map((factor) => (
              <li
                key={factor.code}
                className="rounded border border-border-base bg-surface-muted px-2 py-0.5 text-xs text-text"
              >
                {factor.label}
                {factor.weight !== null && (
                  <span className="ml-1 font-mono text-text-muted">
                    {formatShare(factor.weight)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onOpen?.(item)}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1.5 text-xs font-medium text-accent-fg transition-colors hover:bg-accent-hover"
        >
          <SquareArrowOutUpRight className="size-3.5" aria-hidden="true" />
          Открыть карточку
        </button>
        <button
          type="button"
          onClick={() => onShowOnMap?.(item)}
          /*
            Кнопка недоступна, если у объекта нет привязки к территории: увести
            карту в никуда хуже, чем честно показать, что показывать нечего.
          */
          disabled={!item.territoryCode}
          title={item.territoryCode ? undefined : "У объекта нет привязки к территории"}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-base px-2.5 py-1.5 text-xs font-medium text-text-muted transition-colors hover:bg-surface-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
        >
          <MapPin className="size-3.5" aria-hidden="true" />
          Показать на карте
        </button>
        <button
          type="button"
          onClick={() => onShowLinks?.(item)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-base px-2.5 py-1.5 text-xs font-medium text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
        >
          <Network className="size-3.5" aria-hidden="true" />
          Показать связи
        </button>
      </div>
    </article>
  );
}
