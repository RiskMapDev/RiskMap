/**
 * Адреса и учётные данные демо-стенда в одном месте.
 *
 * Пароли лежат в коде тестов сознательно: это учётные записи наполненного
 * демо-стенда, они заводятся seed-скриптом и одинаковы у всех, кто разворачивает
 * систему локально. Прятать их в переменные окружения значило бы усложнить
 * запуск тестов, ничего при этом не защитив. Для стенда с настоящими данными
 * значения переопределяются переменными окружения.
 */

export const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:3001";

/** Тот же адрес, что зашит в `NEXT_PUBLIC_API_URL` фронтенда. */
export const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8100/api/v1";

export type RoleKey = "admin" | "analyst" | "analystKarasay" | "manager" | "viewer";

export interface DemoUser {
  login: string;
  password: string;
  /** Как роль называется в интерфейсе — по нему тесты и опознают вход. */
  roleTitle: string;
  /** Территориальное ограничение словами, для читаемости отчёта о падении. */
  scope: string;
}

export const USERS: Record<RoleKey, DemoUser> = {
  admin: {
    login: "admin",
    password: process.env.E2E_PASSWORD_ADMIN ?? "ppsq7@T88eG_",
    roleTitle: "Администратор",
    scope: "все территории",
  },
  analyst: {
    login: "analyst",
    password: process.env.E2E_PASSWORD_ANALYST ?? "Ec+Jdkzt87X!",
    roleTitle: "Аналитик",
    scope: "Алматинская область целиком",
  },
  analystKarasay: {
    login: "analyst.karasay",
    password: process.env.E2E_PASSWORD_ANALYST_KARASAY ?? "nAvKGC7b#e7#",
    roleTitle: "Аналитик",
    scope: "только Карасайский район",
  },
  manager: {
    login: "manager",
    password: process.env.E2E_PASSWORD_MANAGER ?? "jRVd$EB29qoU",
    roleTitle: "Руководитель",
    scope: "Алматинская область целиком",
  },
  viewer: {
    login: "viewer",
    password: process.env.E2E_PASSWORD_VIEWER ?? "CLkf^*R37J7&",
    roleTitle: "Просмотр",
    scope: "Алматинская область целиком",
  },
};
