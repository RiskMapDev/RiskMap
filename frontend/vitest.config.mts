import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/*
  Алиас `@/*` из tsconfig резолвится встроенной поддержкой Vite
  (`resolve.tsconfigPaths`). Отдельный плагин для этого больше не нужен — он
  сам сообщает об этом при запуске.

  Серверные компоненты с `async` Vitest не умеет — они проверяются в Playwright.
  Здесь только клиентские компоненты и чистые модули.
*/
export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
