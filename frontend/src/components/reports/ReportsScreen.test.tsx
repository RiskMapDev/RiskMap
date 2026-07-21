import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsScreen } from "@/components/reports/ReportsScreen";
import type { ReportFormatInfo, ReportTemplateInfo } from "@/lib/api/reports";

/*
  Данные заведомо тестовые. Названия шаблонов повторяют настоящие: экран
  проверяется на том, что он показывает ровно то, что вернул сервер, и не
  подставляет собственный список из восьми пунктов.
*/

const TEMPLATES: ReportTemplateInfo[] = [
  { code: "region-summary", title: "Сводный отчёт по региону", description: "ТЕСТ 1" },
  { code: "territory", title: "Отчёт по территории", description: "ТЕСТ 2" },
  { code: "organization", title: "Справка по организации", description: "ТЕСТ 3" },
  { code: "project", title: "Отчёт по объекту/проекту", description: "ТЕСТ 4" },
  { code: "industry", title: "Анализ по отрасли", description: "ТЕСТ 5" },
  { code: "risk-category", title: "Отчёт по категории риска", description: "ТЕСТ 6" },
  { code: "ratings", title: "Рейтинги территорий и отраслей", description: "ТЕСТ 7" },
  { code: "high-risk", title: "Перечень высокорисковых объектов", description: "ТЕСТ 8" },
];

const FORMATS_ALL: ReportFormatInfo[] = [
  { code: "docx", title: "Microsoft Word", media_type: "app/docx", available: true, reason: "" },
  { code: "xlsx", title: "Microsoft Excel", media_type: "app/xlsx", available: true, reason: "" },
  { code: "pdf", title: "PDF", media_type: "application/pdf", available: true, reason: "" },
];

const FORMATS_NO_PDF: ReportFormatInfo[] = [
  ...FORMATS_ALL.slice(0, 2),
  {
    code: "pdf",
    title: "PDF",
    media_type: "application/pdf",
    available: false,
    reason: "ТЕСТОВАЯ ПРИЧИНА: не установлен reportlab.",
  },
];

/** Ответ на запрос файла отчёта: поток вместо JSON, как у настоящего сервера. */
function fileResponse(): Response {
  return new Response(new Blob(["ТЕСТОВОЕ СОДЕРЖИМОЕ"]), {
    status: 200,
    headers: {
      "Content-Disposition":
        "attachment; filename=\"Otchet.docx\"; filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82.docx",
    },
  });
}

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Заглушка сети: каталог, форматы и файл различаются по адресу и методу. */
function installFetch(formats: ReportFormatInfo[]) {
  const calls: Array<{ url: string; method: string; body: string | null }> = [];

  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({
      url,
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : null,
    });

    if (url.includes("/reports/templates")) return jsonResponse(TEMPLATES);
    if (url.includes("/reports/formats")) return jsonResponse(formats);
    if (url.includes("/reports/")) return fileResponse();
    throw new Error(`неожиданный адрес: ${url}`);
  });

  vi.stubGlobal("fetch", stub);
  return calls;
}

beforeEach(() => {
  /*
    jsdom не умеет ни настоящую загрузку файла, ни object URL. Подменяем ровно
    их, а не сам `saveFile`: проверить надо, что скачивание запускается, а не
    что вызвана наша же функция.
  */
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:тест"),
    revokeObjectURL: vi.fn(),
  }));
  window.history.replaceState({}, "", "/reports");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Экран «Отчёты и экспорт»", () => {
  it("показывает восемь шаблонов из каталога сервера", async () => {
    installFetch(FORMATS_ALL);
    render(<ReportsScreen />);

    await waitFor(() => {
      expect(screen.getByText("Сводный отчёт по региону")).toBeInTheDocument();
    });

    for (const template of TEMPLATES) {
      expect(screen.getByText(template.title)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("button", { name: /Сформировать/ })).toHaveLength(8);
  });

  it("во время загрузки не показывает ни одного шаблона и ни одного формата", () => {
    // Запрос, который никогда не завершится: состояние загрузки застывает.
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<ReportsScreen />);

    expect(screen.queryByText("Сводный отчёт по региону")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Сформировать/ })).not.toBeInTheDocument();
    // Ложный ноль запрещён: пустой каталог не должен выглядеть как загруженный.
    expect(screen.queryByText(/не вернул ни одного шаблона/)).not.toBeInTheDocument();
  });

  it("сообщает о недоступности PDF до нажатия, а не после отказа сервера", async () => {
    installFetch(FORMATS_NO_PDF);
    render(<ReportsScreen />);

    await waitFor(() => {
      expect(screen.getByText("Сводный отчёт по региону")).toBeInTheDocument();
    });

    expect(screen.getByText(/ТЕСТОВАЯ ПРИЧИНА/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /PDF/ })).toBeDisabled();
    // Word и Excel остаются рабочими — отказ касается только PDF.
    expect(screen.getByRole("radio", { name: /Microsoft Word/ })).toBeEnabled();
  });

  it("выбирает по умолчанию доступный формат, а не первый из списка", async () => {
    installFetch([
      { ...FORMATS_ALL[0], available: false, reason: "ТЕСТ: Word отключён." },
      FORMATS_ALL[1],
      FORMATS_ALL[2],
    ]);
    render(<ReportsScreen />);

    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Microsoft Excel/ })).toBeChecked();
    });
  });

  it("скачивает файл: запрос POST с телом выборки и имя из заголовка", async () => {
    const calls = installFetch(FORMATS_ALL);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<ReportsScreen />);
    await waitFor(() => {
      expect(screen.getByText("Перечень высокорисковых объектов")).toBeInTheDocument();
    });

    const card = screen.getByText("Перечень высокорисковых объектов").closest("div");
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Сформировать/ }));

    await waitFor(() => {
      expect(screen.getByText(/Файл сохранён: Отчёт\.docx/)).toBeInTheDocument();
    });

    const generate = calls.find((call) => call.method === "POST");
    expect(generate?.url).toContain("/reports/high-risk?format=docx");
    // Выборка пустая — это «всё, что есть», и сервер трактует её именно так.
    expect(generate?.body).toBe("{}");
    expect(click).toHaveBeenCalled();
  });

  it("передаёт в отчёт текущую выборку из адреса", async () => {
    window.history.replaceState({}, "", "/reports?search=%D0%A2%D0%95%D0%A1%D0%A2");
    const calls = installFetch(FORMATS_ALL);
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<ReportsScreen />);
    await waitFor(() => {
      expect(screen.getByText("Отчёт по территории")).toBeInTheDocument();
    });

    // Пользователь предупреждён, что отчёт будет неполным.
    expect(screen.getByText(/Отчёт будет построен по текущей выборке/)).toBeInTheDocument();

    const card = screen.getByText("Отчёт по территории").closest("div");
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Сформировать/ }));

    await waitFor(() => {
      const generate = calls.find((call) => call.method === "POST");
      expect(generate?.body).toBe(JSON.stringify({ search: "ТЕСТ" }));
    });
  });

  it("без заголовка с именем сохраняет файл под названием шаблона, а не под кодом", async () => {
    /*
      Так ведёт себя настоящее развёртывание: `Content-Disposition` не входит в
      число заголовков, доступных межисточниковому запросу, пока сервер не
      перечислит его явно. Имя файла при этом теряться не должно.
    */
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/reports/templates")) return jsonResponse(TEMPLATES);
        if (url.includes("/reports/formats")) return jsonResponse(FORMATS_ALL);
        return new Response(new Blob(["ТЕСТ"]), { status: 200 });
      }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<ReportsScreen />);
    await waitFor(() => {
      expect(screen.getByText("Рейтинги территорий и отраслей")).toBeInTheDocument();
    });

    const card = screen.getByText("Рейтинги территорий и отраслей").closest("div");
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Сформировать/ }));

    await waitFor(() => {
      expect(
        screen.getByText("Файл сохранён: Рейтинги территорий и отраслей.docx"),
      ).toBeInTheDocument();
    });
  });

  it("отказ сервера показывает текстом, а не молчанием", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/reports/templates")) return jsonResponse(TEMPLATES);
        if (url.includes("/reports/formats")) return jsonResponse(FORMATS_ALL);
        return new Response(JSON.stringify({ detail: "ТЕСТОВЫЙ ОТКАЗ СЕРВЕРА" }), { status: 501 });
      }),
    );

    render(<ReportsScreen />);
    await waitFor(() => {
      expect(screen.getByText("Анализ по отрасли")).toBeInTheDocument();
    });

    const card = screen.getByText("Анализ по отрасли").closest("div");
    await userEvent.click(within(card as HTMLElement).getByRole("button", { name: /Сформировать/ }));

    await waitFor(() => {
      expect(screen.getByText("ТЕСТОВЫЙ ОТКАЗ СЕРВЕРА")).toBeInTheDocument();
    });
  });

  it("сбой каталога отличается от пустого каталога", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
    render(<ReportsScreen />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Каталог отчётов не загрузился");
    });
    expect(screen.getByText(/не отсутствие шаблонов/)).toBeInTheDocument();
  });

  it("пустой каталог называет пустым ответом, а не разделом в разработке", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/reports/templates")) return jsonResponse([]);
        return jsonResponse(FORMATS_ALL);
      }),
    );

    render(<ReportsScreen />);
    await waitFor(() => {
      expect(screen.getByText(/Сервер не вернул ни одного шаблона/)).toBeInTheDocument();
    });
  });
});
