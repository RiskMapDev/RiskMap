"use client";

import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api/territories";
import { readToken } from "@/lib/api/auth";

/**
 * Права текущего пользователя.
 *
 * Запрашиваются у сервера, а не выводятся из кода роли. Роли настраиваются
 * администратором в базе, и захардкоженная таблица «роль → разделы» разошлась
 * бы с действительностью при первой же перенастройке — интерфейс показывал бы
 * разделы, куда сервер не пускает, или прятал доступные.
 *
 * `null` означает «ещё не знаем». Это не то же самое, что пустой список: до
 * ответа сервера скрывать разделы нельзя, иначе меню мигает при каждой
 * загрузке страницы.
 */
export function usePermissions(): Set<string> | null {
  const [permissions, setPermissions] = useState<Set<string> | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const token = readToken();
    if (!token) {
      /*
        Без сессии прав нет вовсе — это определённое состояние, а не незнание.
        Запись отложена на микрозадачу: синхронная запись состояния прямо в
        теле эффекта вызывает лишний каскад перерисовок.
      */
      queueMicrotask(() => {
        if (!controller.signal.aborted) setPermissions(new Set());
      });
      return () => controller.abort();
    }

    fetch(`${API_BASE}/auth/permissions`, {
      signal: controller.signal,
      cache: "no-store",
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
    })
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((payload: unknown) => {
        if (controller.signal.aborted) return;

        // Сервер может отдать как список кодов, так и объект со списком —
        // принимаем оба вида, чтобы не ломаться от формы ответа.
        const codes = Array.isArray(payload)
          ? payload
          : ((payload as { permissions?: unknown }).permissions ?? []);

        const normalized = (Array.isArray(codes) ? codes : []).map((item) =>
          typeof item === "string" ? item : String((item as { code?: unknown }).code ?? ""),
        );

        setPermissions(new Set(normalized.filter(Boolean)));
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        /*
          Не смогли узнать права — считаем, что их нет. Показать раздел «на
          всякий случай» значит привести пользователя к отказу сервера; это
          хуже, чем не показать раздел, который на самом деле доступен.
        */
        setPermissions(new Set());
      });

    return () => controller.abort();
  }, []);

  return permissions;
}
