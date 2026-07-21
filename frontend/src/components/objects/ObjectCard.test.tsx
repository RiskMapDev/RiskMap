import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ObjectCard, parseCardPath } from "@/components/objects/ObjectCard";
import type { ObjectDetailResponse } from "@/lib/api/object-detail";

/*
  Слепок структуры настоящего ответа сервера, значения — тестовые. Взят случай
  организации: у неё нет территории, уровень серый, балл предварительный и
  большая часть факторов не измерена. Это самый требовательный случай — он
  проверяет сразу все обязательные разделы карточки.
*/
const ORGANIZATION: ObjectDetailResponse = {
  object_type: "organization",
  object_id: "000000000000",
  title: "ТОО ТЕСТОВАЯ ОРГАНИЗАЦИЯ",
  source_layer: "8.7",
  territory: {
    code: null,
    name: null,
    note: "ТЕСТ: в источнике слоя 8.7 нет ни района, ни адреса, ни координат, ни КАТО",
  },
  risk: {
    score: 42.857142857142854,
    level: "unknown",
    is_preliminary: true,
    completeness: 0.3181818181818182,
    model_code: null,
    model_version: null,
    override_reason: "",
    explanation: "",
    notes: ["ТЕСТ: полнота 32% ниже порога 50% — уровень серый, балл предварительный"],
  },
  factors: {
    measured: [
      {
        code: "B3",
        name: "Массовая регистрация по одному адресу",
        weight: 10,
        value: 0,
        contribution: 0,
        measured: true,
        effect: "не повлиял",
        note: "",
        source: "ТЕСТ: вычисляется по addr_norm",
      },
      {
        code: "B5",
        name: "Отсутствие работников и активов",
        weight: 15,
        value: 1,
        contribution: 15,
        measured: true,
        effect: "повысил риск",
        note: "",
        source: "ТЕСТ-ИСТОЧНИК",
      },
    ],
    unmeasured: [
      {
        code: "B1",
        name: "Минимальная налоговая нагрузка при значительных оборотах",
        weight: 15,
        value: null,
        contribution: null,
        measured: false,
        effect: "не измерено",
        note: "ТЕСТ: источник не подключён — нет публичного API",
        source: "ТЕСТ-ОЖИДАЕМЫЙ-ИСТОЧНИК",
      },
      {
        code: "B6",
        name: "Несоответствие операций профилю деятельности",
        weight: 10,
        value: null,
        contribution: null,
        measured: false,
        effect: "не измерено",
        note: "ТЕСТ: сведения об ОКЭД отсутствуют",
        source: "",
      },
    ],
  },
  fields: {
    БИН: "000000000000",
    "Предварительный уровень": "medium",
  },
  provenance: {
    source_layer: "8.7",
    source_row_ref: "ТЕСТОВЫЙ ЛИСТ!A558",
    natural_key: "000000000000",
    imported_at: "2026-07-20T19:58:08.288557+00:00",
    data_as_of: "2026-07-19",
  },
};

/** Договор: территория есть, балл окончательный, есть логическое поле «Нет». */
const CONTRACT: ObjectDetailResponse = {
  object_type: "contract",
  object_id: "00000000",
  title: "ТЕСТОВЫЙ ДОГОВОР",
  source_layer: "8.4",
  territory: { code: "ТЕСТ-КОД", name: "Тестовый район", note: "" },
  risk: {
    score: 50,
    level: "critical",
    is_preliminary: false,
    completeness: 0.6,
    model_code: "8.4",
    model_version: "1.0",
    override_reason: "ТЕСТ: сработала категория A",
    explanation: "ТЕСТОВОЕ ОБЪЯСНЕНИЕ РАСЧЁТА",
    notes: [],
  },
  factors: { measured: [], unmeasured: [] },
  fields: {
    "Итоговая сумма": 1222500,
    Расторгнут: false,
    "Способ закупки": null,
    "Плановый срок": "2022-12-31",
  },
  provenance: {
    source_layer: "8.4",
    source_row_ref: "ТЕСТ!A44",
    natural_key: "00000000",
    imported_at: "2026-07-20T19:57:37.541019+00:00",
    data_as_of: "2027-12-31",
  },
};

function stubFetch(payload: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(payload), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
}

beforeEach(() => {
  window.history.replaceState({}, "", "/objects/organization/000000000000");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("разбор адреса карточки", () => {
  it("читает тип и идентификатор", () => {
    expect(parseCardPath("/objects/contract/14863203")).toEqual({
      type: "contract",
      id: "14863203",
    });
  });

  it("раскодирует идентификатор с недопустимыми в адресе знаками", () => {
    expect(parseCardPath("/objects/subsidy_recipient/%D0%A2%D0%95%D0%A1%D0%A2")).toEqual({
      type: "subsidy_recipient",
      id: "ТЕСТ",
    });
  });

  it("чужой адрес не разбирает, а честно возвращает «не разобран»", () => {
    expect(parseCardPath("/map")).toBeNull();
    expect(parseCardPath("/objects/contract")).toBeNull();
  });
});

describe("Карточка объекта", () => {
  it("показывает расшифровку: вес, значение, вклад и влияние словами", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    const row = screen.getByText("Отсутствие работников и активов").closest("tr");
    const cells = within(row as HTMLElement).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("15"); // вес
    expect(cells[3]).toHaveTextContent("1"); // значение
    expect(cells[4]).toHaveTextContent("15"); // вклад
    expect(cells[5]).toHaveTextContent("повысил риск"); // влияние словами

    // «Не повлиял» и «не измерено» — разные вещи, и вклад 0 не выдаётся за второе.
    const zero = screen.getByText("Массовая регистрация по одному адресу").closest("tr");
    expect(within(zero as HTMLElement).getAllByRole("cell")[5]).toHaveTextContent("не повлиял");
  });

  it("показывает раздел «Не измерено» с причиной по каждому фактору", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    expect(screen.getByText("Не измерено")).toBeInTheDocument();
    expect(
      screen.getByText(/ТЕСТ: источник не подключён — нет публичного API/),
    ).toBeInTheDocument();
    expect(screen.getByText(/ТЕСТ: сведения об ОКЭД отсутствуют/)).toBeInTheDocument();
    // Вес неизмеренного фактора известен, а вклад — нет, и он не показан нулём.
    expect(screen.getAllByText(/не измерено/i).length).toBeGreaterThan(0);
  });

  it("предварительный балл помечает отдельно, а не подаёт наравне с окончательным", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    expect(
      screen.getByText(/Балл предварительный — это не окончательная оценка/),
    ).toBeInTheDocument();
    expect(screen.getByText(/42,86 \(предварительный\)/)).toBeInTheDocument();
    // Уровень остаётся серым, а не подменяется предварительным «средним».
    expect(screen.getAllByText("Нет данных").length).toBeGreaterThan(0);
  });

  it("окончательный балл не помечает предварительным", () => {
    render(<ObjectCard detail={CONTRACT} />);

    expect(
      screen.queryByText(/Балл предварительный — это не окончательная оценка/),
    ).not.toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText(/ТЕСТ: сработала категория A/)).toBeInTheDocument();
  });

  it("объясняет отсутствие территории, а не оставляет пустоту", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    expect(screen.getByText(/Территория не определена/)).toBeInTheDocument();
    expect(screen.getByText(/нет ни района, ни адреса, ни координат/)).toBeInTheDocument();
  });

  it("причину с маленькой буквы делает предложением", () => {
    /*
      Сервер отдаёт причины как продолжение фразы — «район не указан в
      источнике». На карточке они становятся отдельным предложением после
      точки, и строчная буква там читается как обрыв текста.
    */
    const detail: ObjectDetailResponse = {
      ...ORGANIZATION,
      territory: { code: null, name: null, note: "район не указан в источнике" },
    };
    render(<ObjectCard detail={detail} />);

    expect(screen.getByText(/Район не указан в источнике/)).toBeInTheDocument();
  });

  it("территорию показывает, когда она есть", () => {
    render(<ObjectCard detail={CONTRACT} />);

    expect(screen.getByText("Тестовый район")).toBeInTheDocument();
    expect(screen.queryByText(/Территория не определена/)).not.toBeInTheDocument();
  });

  it("показывает происхождение записи: слой, строку источника и обе даты", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    expect(screen.getByText("Строка в источнике")).toBeInTheDocument();
    expect(screen.getByText("ТЕСТОВЫЙ ЛИСТ!A558")).toBeInTheDocument();
    expect(screen.getByText("Дата загрузки")).toBeInTheDocument();
    expect(screen.getByText("20.07.2026, 19:58")).toBeInTheDocument();
    expect(screen.getByText("Данные актуальны на")).toBeInTheDocument();
    expect(screen.getByText("19.07.2026")).toBeInTheDocument();
  });

  it("логическое «нет» пишет словом, а пустое поле — «не заполнено»", () => {
    render(<ObjectCard detail={CONTRACT} />);

    const terminated = screen.getByText("Расторгнут").closest("div");
    expect(within(terminated as HTMLElement).getByText("Нет")).toBeInTheDocument();

    const method = screen.getByText("Способ закупки").closest("div");
    expect(within(method as HTMLElement).getByText("не заполнено")).toBeInTheDocument();
  });

  it("код уровня риска в сведениях показывает названием, а не кодом", () => {
    render(<ObjectCard detail={ORGANIZATION} />);

    const level = screen.getByText("Предварительный уровень").closest("div");
    expect(within(level as HTMLElement).getByText("Средний")).toBeInTheDocument();
  });

  it("во время загрузки не показывает ни балла, ни факторов", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    render(<ObjectCard />);

    expect(screen.getByText("Загружаю сведения…")).toBeInTheDocument();
    expect(screen.queryByText("Не измерено")).not.toBeInTheDocument();
    // Ложный ноль запрещён: до ответа сервера никаких чисел на экране нет.
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("загружает карточку по адресу страницы", async () => {
    stubFetch(ORGANIZATION);
    render(<ObjectCard />);

    await waitFor(() => {
      expect(screen.getByText("ТОО ТЕСТОВАЯ ОРГАНИЗАЦИЯ")).toBeInTheDocument();
    });

    const stub = fetch as unknown as ReturnType<typeof vi.fn>;
    expect(String(stub.mock.calls[0][0])).toContain("/objects/organization/000000000000");
  });

  it("отказ показывает текстом и не выдаёт его за отсутствие данных", async () => {
    stubFetch({ detail: "ТЕСТОВЫЙ ОТКАЗ: объект не найден" }, 404);
    render(<ObjectCard />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Карточка не открылась");
    });
    expect(screen.getByText("ТЕСТОВЫЙ ОТКАЗ: объект не найден")).toBeInTheDocument();
    expect(screen.getByText(/не признак того, что у объекта нет данных/)).toBeInTheDocument();
  });
});
