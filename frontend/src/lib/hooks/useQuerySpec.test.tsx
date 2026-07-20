import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useQuerySpec, useScrollRestoration } from "@/lib/hooks/useQuerySpec";
import { DEFAULT_QUERY_SPEC } from "@/lib/query-spec";

/**
 * Роутер Next подменён целиком: проверяется не навигация, а то, ЧТО хук
 * собирается записать в адрес. Настоящий роутер здесь только помешал бы.
 */
const routerState = { pathname: "/map", query: "" };
const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => routerState.pathname,
  useSearchParams: () => new URLSearchParams(routerState.query),
}));

/** Разобрать адрес, который хук передал роутеру. */
function writtenParams(call: unknown[] | undefined): URLSearchParams {
  const href = String(call?.[0] ?? "");
  return new URLSearchParams(href.split("?")[1] ?? "");
}

beforeEach(() => {
  routerState.pathname = "/map";
  routerState.query = "";
  push.mockClear();
  replace.mockClear();
});

describe("чтение выборки из адреса", () => {
  it("пустой адрес даёт умолчания", () => {
    const { result } = renderHook(() => useQuerySpec());
    expect(result.current.spec).toEqual(DEFAULT_QUERY_SPEC);
  });

  it("параметры адреса попадают в выборку", () => {
    routerState.query = "search=ТЕСТ&page=3&sort=amount";
    const { result } = renderHook(() => useQuerySpec());

    expect(result.current.spec.search).toBe("ТЕСТ");
    expect(result.current.spec.page).toBe(3);
    expect(result.current.spec.sort).toBe("amount");
  });
});

describe("запись выборки в адрес", () => {
  it("по умолчанию пишется через replace — история не засоряется", () => {
    const { result } = renderHook(() => useQuerySpec());
    result.current.patch({ search: "ТЕСТ" });

    expect(replace).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    expect(writtenParams(replace.mock.calls[0]).get("search")).toBe("ТЕСТ");
  });

  it("режим push доступен для завершённых решений", () => {
    // Иначе back/forward нечего было бы восстанавливать: записи в истории нет.
    const { result } = renderHook(() => useQuerySpec());
    result.current.patch({ search: "ТЕСТ" }, "push");

    expect(push).toHaveBeenCalledTimes(1);
    expect(replace).not.toHaveBeenCalled();
  });

  it("прокрутка страницы не сбрасывается при записи", () => {
    // scroll: true утащил бы окно к началу документа вместе с позицией списка.
    const { result } = renderHook(() => useQuerySpec());
    result.current.patch({ search: "ТЕСТ" });

    expect(replace.mock.calls[0]?.[1]).toEqual({ scroll: false });
  });

  it("посторонние параметры адреса сохраняются", () => {
    // Режим показа и выбранный объект живут в том же адресе и не должны
    // исчезать от щелчка по фильтру.
    routerState.query = "view=split&selected=ТЕСТ-1";
    const { result } = renderHook(() => useQuerySpec());
    result.current.patch({ search: "ТЕСТ" });

    const params = writtenParams(replace.mock.calls[0]);
    expect(params.get("view")).toBe("split");
    expect(params.get("selected")).toBe("ТЕСТ-1");
  });

  it("снятый фильтр исчезает из адреса", () => {
    routerState.query = "search=ТЕСТ&view=list";
    const { result } = renderHook(() => useQuerySpec());
    result.current.clear("search");

    const params = writtenParams(replace.mock.calls[0]);
    expect(params.has("search")).toBe(false);
    expect(params.get("view")).toBe("list");
  });

  it("сброс убирает все фильтры, но не режим показа", () => {
    routerState.query = "search=ТЕСТ&risk_levels=high&amount_min=1&view=map";
    const { result } = renderHook(() => useQuerySpec());
    result.current.reset();

    const params = writtenParams(replace.mock.calls[0]);
    expect([...params.keys()]).toEqual(["view"]);
  });

  it("смена страницы попадает в историю: это осознанное действие", () => {
    const { result } = renderHook(() => useQuerySpec());
    result.current.setPage(4);

    expect(push).toHaveBeenCalledTimes(1);
    expect(writtenParams(push.mock.calls[0]).get("page")).toBe("4");
  });

  it("смена фильтра возвращает на первую страницу", () => {
    routerState.query = "page=7";
    const { result } = renderHook(() => useQuerySpec());
    result.current.patch({ search: "ТЕСТ" });

    expect(writtenParams(replace.mock.calls[0]).has("page")).toBe(false);
  });

  it("посторонний параметр пишется, не задевая выборку", () => {
    routerState.query = "search=ТЕСТ";
    const { result } = renderHook(() => useQuerySpec());
    result.current.setParam("view", "map");

    const params = writtenParams(push.mock.calls[0]);
    expect(params.get("view")).toBe("map");
    expect(params.get("search")).toBe("ТЕСТ");
  });
});

describe("сохранение позиции прокрутки", () => {
  function Harness({ storageKey }: { storageKey: string }) {
    const ref = useScrollRestoration(storageKey);
    return <div data-testid="scroller" ref={ref} />;
  }

  beforeEach(() => {
    window.sessionStorage.clear();
    // rAF выполняется немедленно: тест проверяет логику, а не расписание кадров.
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("позиция запоминается при прокрутке", () => {
    render(<Harness storageKey="ключ-теста" />);
    const element = screen.getByTestId("scroller");

    element.scrollTop = 250;
    fireEvent.scroll(element);

    expect(window.sessionStorage.getItem("risk-map:scroll:ключ-теста")).toBe("250");
  });

  it("позиция восстанавливается при возврате к той же выборке", () => {
    window.sessionStorage.setItem("risk-map:scroll:ключ-теста", "250");

    render(<Harness storageKey="ключ-теста" />);

    expect(screen.getByTestId("scroller").scrollTop).toBe(250);
  });

  it("у другой выборки своя позиция", () => {
    // Иначе список после смены фильтров открылся бы посреди чужих результатов.
    window.sessionStorage.setItem("risk-map:scroll:ключ-теста", "250");

    render(<Harness storageKey="другой-ключ" />);

    expect(screen.getByTestId("scroller").scrollTop).toBe(0);
  });

  it("позиция дописывается при отцеплении элемента", () => {
    const { unmount } = render(<Harness storageKey="ключ-теста" />);
    const element = screen.getByTestId("scroller");
    element.scrollTop = 700;

    unmount();

    expect(window.sessionStorage.getItem("risk-map:scroll:ключ-теста")).toBe("700");
  });
});
