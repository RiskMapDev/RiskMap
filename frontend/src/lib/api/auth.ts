/**
 * Вход и хранение токена.
 *
 * Токен кладётся в `localStorage`, а не в cookie: интерфейс и API работают на
 * разных источниках, и cookie между ними не передалась бы без ослабления
 * настроек безопасности. Для развёртывания за общим доменом это решение
 * стоит пересмотреть в пользу httpOnly-cookie — она недоступна из скриптов и
 * потому устойчивее к краже через XSS.
 */

import { API_BASE } from "@/lib/api/territories";

const TOKEN_KEY = "riskmap-token";
const USER_KEY = "riskmap-user";

export interface CurrentUser {
  login: string;
  full_name: string;
  role: string;
  role_title: string;
  territory: string | null;
}

export interface LoginResult {
  token: string;
  user: CurrentUser;
}

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function readUser(): CurrentUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as CurrentUser) : null;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    // Приватный режим может запрещать запись — не повод ронять выход.
  }
}

export async function login(loginName: string, password: string): Promise<LoginResult> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ login: loginName, password }),
  });

  if (!response.ok) {
    /*
      Причину отказа выводим ровно ту, что вернул сервер, и не дополняем
      догадками. «Пользователь не найден» вместо «неверный логин или пароль»
      позволило бы перебором выяснить список существующих логинов.
    */
    let message = "Не удалось войти";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      // Ответ без тела — оставляем общее сообщение.
    }
    throw new Error(message);
  }

  const payload = (await response.json()) as {
    access_token: string;
    user?: CurrentUser;
  };

  const user = payload.user ?? {
    login: loginName,
    full_name: loginName,
    role: "viewer",
    role_title: "Просмотр",
    territory: null,
  };

  try {
    localStorage.setItem(TOKEN_KEY, payload.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // Токен останется только в памяти вкладки.
  }

  return { token: payload.access_token, user };
}
