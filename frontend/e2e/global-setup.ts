import { request } from "@playwright/test";

import { API_URL, BASE_URL } from "./helpers/env";

/**
 * Проверка, что оба сервера подняты — до того, как упадёт первый тест.
 *
 * Без неё отсутствие backend выглядело бы как «дашборд показывает нули»: тест
 * упал бы по существу правильно, но причину пришлось бы искать в трассировке.
 * Сообщение ниже называет её сразу и приводит команду запуска.
 */
export default async function globalSetup(): Promise<void> {
  const api = await request.newContext({ ignoreHTTPSErrors: true });

  try {
    const health = await api.get(`${API_URL.replace(/\/api\/v1$/, "")}/health`, {
      timeout: 10_000,
    });
    if (!health.ok()) {
      throw new Error(`ответ ${health.status()}`);
    }
  } catch (cause) {
    throw new Error(
      `Backend недоступен на ${API_URL} (${String(cause)}).\n` +
        "Запустите: cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8100",
    );
  }

  try {
    const page = await api.get(`${BASE_URL}/login`, { timeout: 15_000 });
    if (!page.ok()) {
      throw new Error(`ответ ${page.status()}`);
    }
  } catch (cause) {
    throw new Error(
      `Frontend недоступен на ${BASE_URL} (${String(cause)}).\n` +
        "Запустите: cd frontend && npm run build && npx next start -p 3001",
    );
  }

  await api.dispose();
}
