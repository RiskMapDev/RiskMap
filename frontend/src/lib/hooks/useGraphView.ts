"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";

import { buildViewSearch, parseViewState, type GraphViewState } from "@/lib/api/graph";

/**
 * Состояние выборки графа, живущее в адресной строке.
 *
 * **Почему не `useSearchParams`.** На этом проекте связка `useSearchParams` с
 * границей Suspense приводила к тому, что заглушка не сменялась никогда: экран
 * оставался в состоянии загрузки навсегда. Адрес здесь читается напрямую.
 *
 * **Почему `useSyncExternalStore`, а не эффект с `setState`.** Адресная строка —
 * внешнее по отношению к React хранилище, и именно для чтения таких хранилищ
 * этот хук и предназначен. Вариант «прочитать адрес эффектом и записать в
 * состояние» вызывает каскад перерисовок и запрещён правилом
 * `react-hooks/set-state-in-effect`, а чтение в инициализаторе состояния
 * невозможно: на сервере `window` не существует, и разметка сервера разошлась
 * бы с клиентской. `getServerSnapshot` возвращает пустую строку — на сервере
 * выборки нет, и это честное значение, а не заглушка.
 *
 * **Почему свои слушатели рядом с `popstate`.** `history.pushState` события не
 * порождает: браузер считает, что тот, кто его вызвал, и так всё знает. Наша
 * собственная навигация поэтому уведомляет подписчиков сама, а `popstate`
 * остаётся для кнопок «назад» и «вперёд».
 */
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("popstate", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("popstate", listener);
  };
}

function getSnapshot(): string {
  return window.location.search;
}

function getServerSnapshot(): string {
  return "";
}

export function useGraphView(): [GraphViewState, (next: GraphViewState) => void] {
  const search = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const view = useMemo(() => parseViewState(search), [search]);

  const navigate = useCallback((next: GraphViewState) => {
    // Ссылка обязана воспроизводить выборку целиком — это общее требование
    // проекта ко всем выборкам, и граф не исключение.
    window.history.pushState(null, "", `/graph${buildViewSearch(next)}`);
    notify();
  }, []);

  return [view, navigate];
}
