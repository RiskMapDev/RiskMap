"use client";

import { useSyncExternalStore } from "react";

import { readUser, type CurrentUser } from "@/lib/api/auth";

/**
 * Текущий пользователь для оболочки интерфейса.
 *
 * Читается из того же хранилища, куда его положил вход. Через
 * `useSyncExternalStore`, а не эффектом с записью состояния: эффект вызывал бы
 * лишний цикл отрисовки, а на сервере — расхождение при гидратации, потому что
 * `localStorage` там недоступен.
 *
 * Серверный снимок намеренно возвращает `null`: сервер не знает, кто открыл
 * страницу, и притворяться, что знает, значит отрисовать чужое имя до
 * гидратации.
 */

function subscribe(onChange: () => void): () => void {
  // `storage` срабатывает в других вкладках: выход в одной вкладке должен
  // отражаться и здесь, иначе пользователь останется «вошедшим» на экране,
  // на котором уже нет доступа.
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

let cached: CurrentUser | null = null;
let cachedRaw: string | null = null;

function getSnapshot(): CurrentUser | null {
  /*
    `useSyncExternalStore` требует, чтобы снимок был стабилен по ссылке, пока
    данные не менялись. `readUser()` каждый раз разбирает JSON заново и
    возвращает новый объект — без кэша React уходил бы в бесконечный цикл.
  */
  let raw: string | null = null;
  try {
    raw = localStorage.getItem("riskmap-user");
  } catch {
    raw = null;
  }

  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cached = readUser();
  }
  return cached;
}

function getServerSnapshot(): CurrentUser | null {
  return null;
}

export function useCurrentUser(): CurrentUser | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
