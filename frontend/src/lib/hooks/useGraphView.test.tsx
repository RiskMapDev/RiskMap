import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { useGraphView } from "@/lib/hooks/useGraphView";

function Probe() {
  const [view, navigate] = useGraphView();
  return (
    <div>
      <p data-testid="node">{view.node ?? "нет"}</p>
      <p data-testid="depth">{view.depth}</p>
      <button type="button" onClick={() => navigate({ ...view, node: "person:zzz", depth: 2 })}>
        Открыть узел
      </button>
    </div>
  );
}

afterEach(() => {
  window.history.replaceState(null, "", "/graph");
});

describe("состояние графа в адресной строке", () => {
  it("читает выбранный узел из адреса без useSearchParams", () => {
    window.history.replaceState(null, "", "/graph?node=organization:aaa&depth=2");

    render(<Probe />);

    expect(screen.getByTestId("node")).toHaveTextContent("organization:aaa");
    expect(screen.getByTestId("depth")).toHaveTextContent("2");
  });

  it("пустой адрес даёт отсутствие узла, а не выдуманный узел", () => {
    window.history.replaceState(null, "", "/graph");
    render(<Probe />);
    expect(screen.getByTestId("node")).toHaveTextContent("нет");
  });

  it("навигация пишет выборку в адрес — ссылка воспроизводима", async () => {
    window.history.replaceState(null, "", "/graph");
    render(<Probe />);

    await userEvent.click(screen.getByRole("button", { name: "Открыть узел" }));

    expect(window.location.search).toContain("node=person%3Azzz");
    expect(window.location.search).toContain("depth=2");
    expect(screen.getByTestId("node")).toHaveTextContent("person:zzz");
  });

  it("кнопка «назад» браузера возвращает прежнюю выборку", () => {
    window.history.replaceState(null, "", "/graph?node=contract:1");
    render(<Probe />);
    expect(screen.getByTestId("node")).toHaveTextContent("contract:1");

    /*
      jsdom не выполняет саму навигацию по popstate, поэтому адрес меняется
      вручную, а затем возбуждается событие — проверяется именно то, что
      компонент на него подписан. Без подписки экран остался бы показывать
      окружение узла, из которого пользователь уже ушёл.
    */
    act(() => {
      window.history.replaceState(null, "", "/graph?node=contract:2");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(screen.getByTestId("node")).toHaveTextContent("contract:2");
  });
});
