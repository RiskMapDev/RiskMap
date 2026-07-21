"use client";

import { useSyncExternalStore } from "react";

/**
 * Подписка на медиа-запрос.
 *
 * Нужна там, где раскладка меняет не только вид, но и поведение: скрыть
 * элемент правилом CSS недостаточно, если он остаётся в обходе с клавиатуры
 * или его можно выбрать стрелками.
 *
 * Через `useSyncExternalStore`, а не эффектом: на сервере медиа-запросов нет,
 * и серверный снимок обязан быть определённым, иначе разметка разойдётся при
 * гидратации.
 */
export function useMediaQuery(query: string, serverValue = false): boolean {
  const subscribe = (onChange: () => void) => {
    const list = window.matchMedia(query);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  };

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => serverValue,
  );
}
