"use client";

import { useEffect, useState } from "react";

import { readToken } from "@/lib/api/auth";

/**
 * Пропускает дальше только с начатой сессией.
 *
 * Без этой проверки человек, открывший закладку после истечения сессии,
 * попадал на рабочий экран, где меню пусто, пользователь подписан «Гость», а
 * панель показывает ошибку. Выглядит как поломка системы, хотя нужно просто
 * войти заново.
 *
 * Проверка клиентская и заменой серверной не является: данные защищает API,
 * который без токена отвечает отказом. Здесь решается только вопрос
 * «что показать человеку», а не «что ему отдать».
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  /*
    Три состояния, а не два. «Ещё не знаем» отличается от «нет сессии»:
    на сервере `localStorage` недоступен, и если считать незнание
    отсутствием сессии, при первой отрисовке мигнёт экран входа даже у
    вошедшего пользователя.

    Проверка живёт в эффекте, а не в ленивом инициализаторе `useState`:
    инициализатор выполняется и на сервере, где токена нет, поэтому
    сервер отрисовывал бы «Проверяем сессию…», а клиент сразу рабочий
    экран — это расхождение гидрации, и React выбрасывает и перерисовывает
    всё поддерево. Лишний рендер здесь дешевле, чем повторная сборка.
  */
  const [state, setState] = useState<"unknown" | "authorized">("unknown");

  useEffect(() => {
    if (readToken()) {
      setState("authorized");
      return;
    }

    // Адрес запоминается, чтобы после входа вернуть человека туда, куда он
    // шёл, а не на общий дашборд.
    const target = window.location.pathname + window.location.search;
    const back = target === "/dashboard" ? "" : `?back=${encodeURIComponent(target)}`;
    window.location.replace(`/login${back}`);
  }, []);

  if (state !== "authorized") {
    return (
      <div className="grid min-h-dvh place-items-center bg-bg">
        <p className="text-sm text-text-muted">Проверяем сессию…</p>
      </div>
    );
  }

  return <>{children}</>;
}
