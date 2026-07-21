import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

/*
  jsdom не реализует `matchMedia`. Компоненты, у которых поведение зависит от
  раскладки (а не только вид), обращаются к нему при отрисовке и падают.

  Заглушка отвечает «условие не выполнено»: тесты идут в узкой раскладке, где
  сдвоенный режим недоступен. Тесту, которому нужна широкая, следует
  переопределить `matchMedia` явно — так видно, что раскладка часть условий.
*/
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

afterEach(() => {
  cleanup();
});
