"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "light" | "dark";

const STORAGE_KEY = "riskmap-theme";

/**
 * Переключатель светлой и тёмной темы.
 *
 * Начальное состояние читается из уже проставленного атрибута `data-theme`, а
 * не вычисляется заново. Атрибут выставляет встроенный скрипт в layout до
 * первой отрисовки, и если компонент начнёт вычислять тему сам, при гидратации
 * возникнет расхождение с разметкой сервера.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    setTheme(current === "dark" ? "dark" : "light");
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Приватный режим браузера может запрещать запись. Тема применится
      // на текущую сессию, просто не переживёт перезагрузку — это не повод
      // ронять интерфейс.
    }
  }

  const label = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="grid size-9 place-items-center rounded-lg border border-border-base bg-surface text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
    >
      {/*
        До монтирования показываем один и тот же значок на сервере и клиенте:
        иначе первая отрисовка разойдётся с разметкой сервера.
      */}
      {mounted && theme === "dark" ? (
        <Sun className="size-4.5" aria-hidden="true" />
      ) : (
        <Moon className="size-4.5" aria-hidden="true" />
      )}
    </button>
  );
}
