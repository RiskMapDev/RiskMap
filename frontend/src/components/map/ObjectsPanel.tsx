"use client";

import { useCallback, useEffect, useState } from "react";

import { ResultList } from "@/components/list/ResultList";
import { SortControl } from "@/components/list/SortControl";
import { FilterChips } from "@/components/filters/FilterChips";
import { fetchObjects } from "@/lib/api/objects";
import type { ListItem, ListResponse, LoadState } from "@/lib/api/types";
import {
  activeFilterChips,
  clearFilter,
  withFilters,
  type QuerySpec,
} from "@/lib/query-spec";

interface ObjectsPanelProps {
  spec: QuerySpec;
  onSpecChange: (spec: QuerySpec) => void;
  selectedId?: string | null;
  onOpen?: (item: ListItem) => void;
  onShowOnMap?: (item: ListItem) => void;
  onShowLinks?: (item: ListItem) => void;
}

/**
 * Список объектов выборки.
 *
 * Компонент отвечает за загрузку и состояние, отрисовка — в `ResultList`.
 * Разделение нужно затем, чтобы список можно было проверить тестами без сети:
 * он получает готовые данные пропсами.
 */
export function ObjectsPanel({
  spec,
  onSpecChange,
  selectedId,
  onOpen,
  onShowOnMap,
  onShowLinks,
}: ObjectsPanelProps) {
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<ListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  /*
    Ключ выборки — то, от чего зависит запрос. Собирается строкой, потому что
    объект `spec` пересоздаётся при каждой отрисовке родителя и в списке
    зависимостей эффекта вызывал бы бесконечный цикл запросов.
  */
  const key = JSON.stringify([
    spec.page,
    spec.pageSize,
    spec.sort,
    spec.order,
    spec.search,
    spec.objectTypes,
    spec.territoryCodes,
    spec.riskLevels,
    spec.amountMin,
    spec.amountMax,
  ]);

  useEffect(() => {
    const controller = new AbortController();

    fetchObjects(spec, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setData(payload);
        setError(null);
        // Пустой результат — не отдельное состояние загрузки: список сам
        // различает «ничего не найдено по фильтрам» и «данных нет вовсе».
        setState("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "не удалось загрузить список");
        setState("error");
      });

    return () => controller.abort();
    // spec намеренно не в зависимостях: он меняется по ссылке при каждой
    // отрисовке, а значимая часть уже свёрнута в `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => {
    setState("loading");
    setAttempt((value) => value + 1);
  }, []);

  const resetFilters = useCallback(() => {
    onSpecChange(
      withFilters(spec, {
        search: null,
        objectTypes: [],
        territoryCodes: [],
        amountMin: null,
        amountMax: null,
      }),
    );
  }, [onSpecChange, spec]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg">
      <div className="shrink-0 border-b border-border-base bg-surface px-4 py-3">
        {/*
          Счётчик найденного здесь не дублируется: его показывает сам
          `ResultList`, причём со склонением («2 807 объектов»). Два счётчика
          на одном экране — не просто шум: при расхождении пользователь не
          знает, какому верить.
        */}
        <div className="flex flex-wrap items-center justify-end gap-3">
          <SortControl
            sort={spec.sort}
            order={spec.order}
            onChange={(sort, order) => onSpecChange(withFilters(spec, { sort, order }))}
          />
        </div>

        <div className="mt-2">
          <FilterChips
            chips={activeFilterChips(spec)}
            onClear={(key) => onSpecChange(clearFilter(spec, key))}
            onReset={resetFilters}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <ResultList
          items={data?.items ?? []}
          status={state}
          total={data?.page.total ?? null}
          page={spec.page}
          totalPages={data?.page.totalPages ?? null}
          error={error}
          onPageChange={(page) => onSpecChange(withFilters(spec, { page }))}
          onRetry={retry}
          onResetFilters={resetFilters}
          filtered={
            spec.search !== null ||
            spec.objectTypes.length > 0 ||
            spec.territoryCodes.length > 0
          }
          selectedId={selectedId}
          onOpen={onOpen}
          onShowOnMap={onShowOnMap}
          onShowLinks={onShowLinks}
          scrollKey={key}
        />
      </div>
    </div>
  );
}
