"use client";

import { Moon, Sun } from "lucide-react";

const STORAGE_KEY = "riskmap-theme";

/**
 * Переключатель светлой и тёмной темы.
 *
 * Компонент намеренно не хранит тему в состоянии React. Тема живёт в атрибуте
 * `data-theme` на `<html>`, который проставляет встроенный скрипт до первой
 * отрисовки. Любая попытка продублировать её состоянием даёт две проблемы:
 * расхождение при гидратации (сервер не знает настройку пользователя) и
 * лишний цикл перерисовки в эффекте.
 *
 * Поэтому оба значка присутствуют в разметке всегда, а нужный показывается
 * правилами CSS по тому же атрибуту. Разметка сервера и клиента совпадает
 * побайтово, состояние не требуется вовсе.
 */
export function ThemeToggle() {
  function toggle() {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Приватный режим браузера может запрещать запись. Тема применится на
      // текущую сессию, просто не переживёт перезагрузку — это не повод
      // ронять интерфейс.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Переключить тему оформления"
      className="grid size-9 place-items-center rounded-lg border border-border-base bg-surface text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
    >
      <Moon className="size-4.5 theme-icon-light" aria-hidden="true" />
      <Sun className="size-4.5 theme-icon-dark" aria-hidden="true" />
    </button>
  );
}
