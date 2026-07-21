"use client";

import { Bell, LogOut, Search } from "lucide-react";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { clearSession } from "@/lib/api/auth";
import { useCurrentUser } from "@/lib/hooks/useCurrentUser";

interface TopbarProps {
  /** Действия, специфичные для экрана: «Фильтры», «Экспорт», «Обновить». */
  actions?: React.ReactNode;
  unreadCount?: number;
}

export function Topbar({ actions, unreadCount = 0 }: TopbarProps) {
  const user = useCurrentUser();

  /*
    Пока пользователь не прочитан — «Гость». Это не заглушка: до входа
    пользователя действительно нет, и подписать панель чужим именем было бы
    хуже, чем честно сказать, что сессия не начата.
  */
  const userName = user?.full_name ?? user?.login ?? "Гость";
  const userRole = user?.role_title ?? "сессия не начата";

  const initials = userName
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <header className="flex h-16 shrink-0 items-center gap-4 border-b border-border-base bg-surface px-6">
      {/*
        Поиск по ТЗ покрывает БИН/ИИН, ФИО, организацию, объект, договор и
        территорию. Плейсхолдер называет области поиска явно: пользователь не
        обязан угадывать, что сюда можно вводить.
      */}
      <div className="relative max-w-md flex-1">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-subtle"
          aria-hidden="true"
        />
        <label htmlFor="global-search" className="sr-only">
          Поиск по реестрам системы
        </label>
        <input
          id="global-search"
          type="search"
          placeholder="Поиск по БИН, ФИО, организации, объекту, договору…"
          className="w-full rounded-lg border border-border-base bg-surface-muted py-2 pl-9 pr-16 text-sm text-text placeholder:text-text-subtle focus:border-accent focus:bg-surface"
        />
        <kbd
          aria-hidden="true"
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded border border-border-base bg-surface px-1.5 py-0.5 font-mono text-[11px] text-text-subtle"
        >
          Ctrl K
        </kbd>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {actions}

        <ThemeToggle />

        <button
          type="button"
          className="relative grid size-9 place-items-center rounded-lg border border-border-base bg-surface text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
          aria-label={
            unreadCount > 0 ? `Уведомления, непрочитанных: ${unreadCount}` : "Уведомления"
          }
        >
          <Bell className="size-4.5" aria-hidden="true" />
          {unreadCount > 0 && (
            <span
              aria-hidden="true"
              className="absolute -right-1 -top-1 grid min-w-4.5 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>

        <div className="flex items-center gap-2.5 rounded-lg border border-border-base bg-surface py-1.5 pl-2 pr-3">
          <span
            aria-hidden="true"
            className="grid size-7 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-fg"
          >
            {initials || "?"}
          </span>
          <span className="leading-tight">
            <span className="block text-sm font-medium text-text">{userName}</span>
            <span className="block text-xs text-text-muted">{userRole}</span>
          </span>
        </div>

        {user && (
          <button
            type="button"
            onClick={() => {
              clearSession();
              // Полная навигация, а не переход роутером: после выхода в памяти
              // не должно остаться ни данных, ни загруженных экранов.
              window.location.href = "/login";
            }}
            aria-label="Выйти из системы"
            title="Выйти из системы"
            className="grid size-9 place-items-center rounded-lg border border-border-base bg-surface text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
          >
            <LogOut className="size-4.5" aria-hidden="true" />
          </button>
        )}
      </div>
    </header>
  );
}
