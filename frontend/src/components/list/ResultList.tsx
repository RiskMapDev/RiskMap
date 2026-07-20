"use client";

import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronLeft, ChevronRight, Inbox, RefreshCw, TriangleAlert } from "lucide-react";

import type { ListItem, LoadState } from "@/lib/api/types";
import { formatObjectCount } from "@/lib/format";
import { useScrollRestoration } from "@/lib/hooks/useQuerySpec";
import { EmptyState } from "@/components/ui/EmptyState";
import { ResultCard } from "@/components/list/ResultCard";

/** Оценка высоты карточки в пикселях. Виртуализатор уточнит её по факту измерения. */
const ESTIMATED_CARD_HEIGHT = 260;

/**
 * Сколько карточек рисовать за пределами экрана.
 *
 * Не ноль: при быстрой прокрутке пользователь увидел бы пустоту там, где
 * содержимое ещё не успело отрисоваться.
 */
const OVERSCAN = 6;

interface ResultListProps {
  items: ListItem[];
  status: LoadState;
  /** Всего в выборке. `null` — сервер не смог посчитать; показывать «0» нельзя. */
  total: number | null;
  page: number;
  totalPages: number | null;
  /** Текст ошибки для показа. Технические подробности сюда не попадают. */
  error?: string | null;
  onPageChange: (page: number) => void;
  onRetry?: () => void;
  onResetFilters?: () => void;
  /** Признак того, что выборка сужена фильтрами: меняет текст пустого состояния. */
  filtered?: boolean;
  selectedId?: string | null;
  onOpen?: (item: ListItem) => void;
  onShowOnMap?: (item: ListItem) => void;
  onShowLinks?: (item: ListItem) => void;
  /**
   * Ключ выборки. По нему запоминается позиция прокрутки, чтобы «назад»
   * возвращал не только фильтры, но и место, где пользователь остановился.
   */
  scrollKey?: string;
  /** Слот для сортировки и прочих контролов в шапке списка. */
  toolbar?: React.ReactNode;
}

/**
 * Счётчик найденного.
 *
 * Пока данные грузятся, число НЕ показывается. Это прямое требование ТЗ:
 * «найдено 0 объектов» во время загрузки — ложь, которая заставляет
 * пользователя менять фильтры, хотя менять нечего.
 */
function ResultCount({ status, total }: { status: LoadState; total: number | null }) {
  if (status === "loading") {
    return <span className="text-sm text-text-muted">Идёт поиск…</span>;
  }
  if (status === "error") {
    return <span className="text-sm text-text-muted">Число объектов неизвестно</span>;
  }
  if (total === null) {
    // Сервер не посчитал точное число — честнее сказать так, чем выдумать его.
    return <span className="text-sm text-text-muted">Показаны первые результаты</span>;
  }
  return (
    <span className="text-sm text-text">
      Найдено <span className="font-semibold">{formatObjectCount(total)}</span>
    </span>
  );
}

/** Скелетоны вместо содержимого: показывают форму будущего ответа, а не пустоту. */
function ListSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1, 2, 3].map((index) => (
        <div
          key={index}
          className="h-40 animate-pulse rounded-card border border-border-base bg-surface-muted"
        />
      ))}
    </div>
  );
}

export function ResultList({
  items,
  status,
  total,
  page,
  totalPages,
  error,
  onPageChange,
  onRetry,
  onResetFilters,
  filtered = false,
  selectedId,
  onOpen,
  onShowOnMap,
  onShowLinks,
  scrollKey = "",
  toolbar,
}: ResultListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const restoreScroll = useScrollRestoration(scrollKey);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_CARD_HEIGHT,
    overscan: OVERSCAN,
  });

  const rows = virtualizer.getVirtualItems();
  const hasPrev = page > 1;
  const hasNext = totalPages === null ? items.length > 0 : page < totalPages;

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Результаты выборки">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-base px-4 py-3">
        {/*
          `aria-live` на счётчике: смена фильтров не двигает фокус, и без
          объявления пользователь скринридера не узнаёт, что выборка изменилась.
        */}
        <div aria-live="polite" aria-atomic="true">
          <ResultCount status={status} total={total} />
        </div>
        {toolbar}
      </div>

      <div
        ref={(element) => {
          scrollRef.current = element;
          const detach = restoreScroll(element);
          // Возврат функции очистки — форма ref-колбэка React 19: она
          // выполняется при отцеплении элемента, и позиция прокрутки
          // дописывается до того, как элемент исчезнет из документа.
          return () => {
            detach?.();
            scrollRef.current = null;
          };
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
      >
        {status === "loading" && <ListSkeleton />}

        {status === "error" && (
          <EmptyState
            icon={TriangleAlert}
            title="Не удалось загрузить список"
            description={
              error ??
              "Сервер не ответил. Выборка сохранена в адресе страницы — после повтора она восстановится."
            }
            action={
              onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
                >
                  <RefreshCw className="size-4" aria-hidden="true" />
                  Повторить
                </button>
              )
            }
          />
        )}

        {status === "ready" && items.length === 0 && (
          <EmptyState
            icon={Inbox}
            title={filtered ? "Под фильтры ничего не подошло" : "Объектов пока нет"}
            description={
              filtered
                ? "Попробуйте расширить период или снять часть условий."
                : "Данные ещё не загружены в систему."
            }
            action={
              filtered &&
              onResetFilters && (
                <button
                  type="button"
                  onClick={onResetFilters}
                  className="rounded-md border border-border-base px-3 py-1.5 text-sm font-medium text-text-muted hover:bg-surface-hover hover:text-text"
                >
                  Сбросить фильтры
                </button>
              )
            }
          />
        )}

        {status === "ready" && items.length > 0 && (
          /*
            Виртуализация: в выборке могут быть сотни строк на странице, а карточка
            тяжёлая — плашка риска, список фактов, три кнопки. Рисовать их все
            значит вешать прокрутку.

            Список объявлен ролью `list`, а распорка высотой — `presentation`:
            иначе скринридер посчитает пустой div элементом списка.
          */
          <ul
            role="list"
            className="relative"
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {rows.map((row) => {
              const item = items[row.index];
              if (!item) return null;

              return (
                <li
                  key={item.id}
                  ref={virtualizer.measureElement}
                  data-index={row.index}
                  className="absolute inset-x-0 top-0 pb-3"
                  style={{ transform: `translateY(${row.start}px)` }}
                >
                  <ResultCard
                    item={item}
                    selected={item.id === selectedId}
                    onOpen={onOpen}
                    onShowOnMap={onShowOnMap}
                    onShowLinks={onShowLinks}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/*
        Пагинация серверная: страница — часть выборки в адресе, а не позиция
        внутри уже загруженного массива. Поэтому кнопки меняют выборку, а не
        листают локальные данные.
      */}
      {status === "ready" && items.length > 0 && (
        <nav
          aria-label="Страницы результатов"
          className="flex shrink-0 items-center justify-between gap-3 border-t border-border-base px-4 py-2.5"
        >
          <button
            type="button"
            onClick={() => onPageChange(page - 1)}
            disabled={!hasPrev}
            className="inline-flex items-center gap-1 rounded-md border border-border-base px-2.5 py-1.5 text-sm text-text-muted transition-colors hover:bg-surface-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
            Назад
          </button>

          <span className="text-xs text-text-muted">
            Страница {page}
            {totalPages !== null && ` из ${totalPages}`}
          </span>

          <button
            type="button"
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNext}
            className="inline-flex items-center gap-1 rounded-md border border-border-base px-2.5 py-1.5 text-sm text-text-muted transition-colors hover:bg-surface-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          >
            Вперёд
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </nav>
      )}
    </section>
  );
}
