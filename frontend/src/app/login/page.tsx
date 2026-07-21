"use client";

import { useState } from "react";
import { LogIn, Map } from "lucide-react";

import { login } from "@/lib/api/auth";

export default function LoginPage() {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      await login(loginName, password);

      /*
        Возврат туда, откуда человека отправили входить. Адрес берётся только
        как путь внутри приложения: подставить в него чужой сайт нельзя, иначе
        ссылка на страницу входа стала бы способом перебросить пользователя
        куда угодно после успешного входа.
      */
      const requested = new URLSearchParams(window.location.search).get("back");
      const safe = requested && requested.startsWith("/") && !requested.startsWith("//");

      // Полная навигация, а не router.push: после входа нужно, чтобы все
      // экраны прочитали новый токен при монтировании.
      window.location.href = safe ? requested : "/dashboard";
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось войти");
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-bg p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-lg bg-accent text-accent-fg"
          >
            <Map className="size-5" strokeWidth={2.5} />
          </span>
          <span className="text-lg font-semibold text-text">Карта рисков</span>
        </div>

        <form
          onSubmit={submit}
          className="rounded-panel border border-border-base bg-surface p-6 shadow-panel"
        >
          <h1 className="text-base font-semibold text-text">Вход в систему</h1>
          <p className="mt-1 text-sm text-text-muted">
            Информационно-аналитическая система оценки рисков
          </p>

          <label htmlFor="login" className="mt-5 block text-sm font-medium text-text">
            Логин
          </label>
          <input
            id="login"
            name="login"
            autoComplete="username"
            required
            value={loginName}
            onChange={(e) => setLoginName(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border-base bg-surface-muted px-3 py-2 text-sm text-text focus:border-accent focus:bg-surface"
          />

          <label htmlFor="password" className="mt-4 block text-sm font-medium text-text">
            Пароль
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border-base bg-surface-muted px-3 py-2 text-sm text-text focus:border-accent focus:bg-surface"
          />

          {error && (
            <p
              role="alert"
              className="mt-4 rounded border border-risk-high-border bg-risk-high-bg px-3 py-2 text-sm text-risk-high-text"
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover disabled:opacity-60"
          >
            <LogIn className="size-4" aria-hidden="true" />
            {busy ? "Проверяем…" : "Войти"}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-text-subtle">
          Доступ ограничен ролью и территорией. Действия журналируются.
        </p>
      </div>
    </div>
  );
}
