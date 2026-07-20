import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminScreen } from "@/components/admin/AdminScreen";
import type {
  AdminUser,
  AuditPage,
  ReferencePayload,
  RiskModelInfo,
} from "@/lib/api/admin";

/* Данные заведомо тестовые: см. пояснение в тестах карточки результата. */

const USERS: AdminUser[] = [
  {
    id: "ТЕСТ-1",
    login: "t.analyst",
    full_name: "ТЕСТОВЫЙ АНАЛИТИК",
    email: null,
    role: "analyst",
    role_title: "Аналитик",
    territory_id: "ТЕСТ-РАЙОН",
    territory: "Тестовый район",
    last_login_at: "2001-02-03T10:00:00+00:00",
    is_active: true,
    is_locked: false,
    failed_login_attempts: 0,
  },
  {
    id: "ТЕСТ-2",
    login: "t.manager",
    full_name: "ТЕСТОВЫЙ РУКОВОДИТЕЛЬ",
    email: null,
    role: "manager",
    role_title: "Руководитель",
    territory_id: null,
    territory: "Все районы",
    last_login_at: null,
    is_active: false,
    is_locked: false,
    failed_login_attempts: 0,
  },
];

const REFERENCE: ReferencePayload = {
  territories: [
    {
      id: "ТЕСТ-РАЙОН",
      code: "ТЕСТ-КОД",
      name_ru: "Тестовый район",
      name_kk: "Тест ауданы",
      level: "district",
      parent_id: null,
      is_current: true,
    },
  ],
  roles: [
    {
      code: "analyst",
      title: "Аналитик",
      description: "ТЕСТОВОЕ ОПИСАНИЕ РОЛИ",
      sensitive_data_access: "masked",
      users_count: 3,
      permissions: [
        { code: "data.import", title: "Импорт данных", description: "ТЕСТ" },
        { code: "data.view", title: "Просмотр данных", description: "ТЕСТ" },
      ],
    },
  ],
  sensitive_access_levels: [
    { code: "full", title: "Полное значение" },
    { code: "masked", title: "Маска" },
    { code: "hidden", title: "Скрыто" },
  ],
  risk_levels: [
    { code: "low", title: "Низкий" },
    { code: "unknown", title: "Нет данных" },
  ],
};

const MODELS: RiskModelInfo[] = [
  {
    code: "8.4",
    title: "ТЕСТОВАЯ МОДЕЛЬ ЗАКУПОК",
    version: "1.0",
    base_version: "1.0",
    scale: 100,
    min_completeness: 0.5,
    notes: "",
    indicators: [
      {
        code: "P1",
        name: "ТЕСТОВЫЙ ИНДИКАТОР 1",
        weight: 25,
        direction: "higher_is_riskier",
        source: "тест",
      },
      {
        code: "P2",
        name: "ТЕСТОВЫЙ ИНДИКАТОР 2",
        weight: 15,
        direction: "higher_is_riskier",
        source: "тест",
      },
    ],
    thresholds: [
      { from_score: 0, level: "low", title: "Низкий" },
      { from_score: 50, level: "high", title: "Высокий" },
    ],
    history: [],
  },
];

const AUDIT: AuditPage = {
  total: 1,
  page: 1,
  page_size: 25,
  items: [
    {
      id: "ТЕСТ-ЗАПИСЬ",
      occurred_at: "2001-02-03T10:00:00+00:00",
      user_login: "t.analyst",
      action: "import_finished",
      action_title: "Импорт завершён",
      entity_type: "import_job",
      entity_id: "ТЕСТ-ЗАДАНИЕ",
      ip_address: "127.0.0.1",
      request_id: null,
      details: null,
    },
  ],
  actions: [
    { code: "import_finished", title: "Импорт завершён" },
    { code: "risk_model_changed", title: "Изменение модели риска" },
  ],
};

const api = vi.hoisted(() => ({
  fetchUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  fetchReference: vi.fn(),
  fetchRiskModels: vi.fn(),
  updateRiskModel: vi.fn(),
  fetchAuditLog: vi.fn(),
}));

vi.mock("@/lib/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/admin")>();
  return { ...actual, ...api };
});

vi.mock("@/lib/api/auth", () => ({ readToken: () => "ТЕСТ-ТОКЕН" }));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/admin");
  api.fetchUsers.mockResolvedValue(USERS);
  api.fetchReference.mockResolvedValue(REFERENCE);
  api.fetchRiskModels.mockResolvedValue(MODELS);
  api.fetchAuditLog.mockResolvedValue(AUDIT);
  api.updateUser.mockResolvedValue(USERS[0]);
  api.updateRiskModel.mockResolvedValue(MODELS[0]);
  api.createUser.mockResolvedValue(USERS[0]);
});

async function openTab(user: ReturnType<typeof userEvent.setup>, title: string) {
  await user.click(await screen.findByRole("tab", { name: title }));
}

describe("вкладки", () => {
  it("четыре вкладки в порядке референса", async () => {
    render(<AdminScreen />);

    const tabs = await screen.findAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Пользователи",
      "Справочники",
      "Критерии риска",
      "Журнал действий",
    ]);
  });

  it("переключение вкладки попадает в адрес", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await openTab(user, "Журнал действий");

    expect(new URLSearchParams(window.location.search).get("tab")).toBe("audit");
    expect(screen.getByRole("tab", { name: "Журнал действий" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("вкладка из адреса открывается сразу", async () => {
    window.history.replaceState(null, "", "/admin?tab=reference");
    render(<AdminScreen />);

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Справочники" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
  });

  it("неизвестная вкладка в адресе не ломает экран", async () => {
    window.history.replaceState(null, "", "/admin?tab=выдумка");
    render(<AdminScreen />);

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Пользователи" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
  });

  it("переход назад возвращает прежнюю вкладку", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);
    await openTab(user, "Справочники");

    window.history.back();

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Пользователи" })).toHaveAttribute(
        "aria-selected",
        "true",
      ),
    );
  });
});

describe("вкладка «Пользователи»", () => {
  it("колонки таблицы совпадают с референсом", async () => {
    render(<AdminScreen />);

    const headers = await screen.findAllByRole("columnheader");
    expect(headers.map((cell) => cell.textContent)).toEqual([
      "Ф.И.О.",
      "Логин",
      "Роль",
      "Территория",
      "Последний вход",
      "Статус",
      "Действия",
    ]);
  });

  it("доступ ко всем территориям написан словами", async () => {
    render(<AdminScreen />);

    expect(await screen.findByText("Все районы")).toBeInTheDocument();
  });

  it("статус подписан словом, а не только цветом", async () => {
    render(<AdminScreen />);

    expect(await screen.findByText("Активен")).toBeInTheDocument();
    expect(screen.getByText("Неактивен")).toBeInTheDocument();
  });

  it("отсутствие входа показано прочерком, а не пустотой", async () => {
    render(<AdminScreen />);

    const row = (await screen.findByText("ТЕСТОВЫЙ РУКОВОДИТЕЛЬ")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("—")).toBeInTheDocument();
  });

  it("блокировка отправляется на сервер", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await user.click(await screen.findByRole("button", { name: "Заблокировать" }));

    await waitFor(() =>
      expect(api.updateUser).toHaveBeenCalledWith("ТЕСТ-ТОКЕН", "ТЕСТ-1", {
        is_active: false,
      }),
    );
  });

  it("форма новой учётной записи открывается кнопкой заголовка", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await user.click(await screen.findByRole("button", { name: "+ Добавить пользователя" }));

    expect(screen.getByRole("form", { name: "Новая учётная запись" })).toBeInTheDocument();
    expect(screen.getByLabelText("Логин")).toBeInTheDocument();
    expect(screen.getByLabelText("Пароль")).toHaveAttribute("type", "password");
  });

  it("новая учётная запись уходит на сервер вместе с ролью и территорией", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);
    await user.click(await screen.findByRole("button", { name: "+ Добавить пользователя" }));

    await user.type(screen.getByLabelText("Ф.И.О."), "ТЕСТОВЫЙ ПОЛЬЗОВАТЕЛЬ");
    await user.type(screen.getByLabelText("Логин"), "t.новый");
    await user.type(screen.getByLabelText("Пароль"), "ТЕСТОВЫЙ-ПАРОЛЬ-1");
    await user.selectOptions(screen.getByLabelText("Роль"), "analyst");
    await user.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() =>
      expect(api.createUser).toHaveBeenCalledWith("ТЕСТ-ТОКЕН", {
        login: "t.новый",
        full_name: "ТЕСТОВЫЙ ПОЛЬЗОВАТЕЛЬ",
        password: "ТЕСТОВЫЙ-ПАРОЛЬ-1",
        role_code: "analyst",
        territory_id: null,
      }),
    );
  });

  it("нехватка прав объясняется словами", async () => {
    api.fetchUsers.mockRejectedValue(new Error("Недостаточно прав для этой операции."));
    render(<AdminScreen />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Недостаточно прав");
  });
});

describe("вкладка «Справочники»", () => {
  it("территория показана с казахским названием", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await openTab(user, "Справочники");

    expect(await screen.findByText("Тестовый район")).toBeInTheDocument();
    expect(screen.getByText("Тест ауданы")).toBeInTheDocument();
  });

  it("роль показана с расшифрованными правами", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await openTab(user, "Справочники");

    expect(await screen.findByText("Аналитик")).toBeInTheDocument();
    expect(screen.getByText("Импорт данных")).toBeInTheDocument();
    expect(screen.getByText("Просмотр данных")).toBeInTheDocument();
  });

  it("степень доступа к персональным данным названа словом", async () => {
    const user = userEvent.setup();
    render(<AdminScreen />);

    await openTab(user, "Справочники");

    expect(await screen.findByText(/Персональные данные: Маска/)).toBeInTheDocument();
  });
});

describe("вкладка «Критерии риска»", () => {
  async function open(user: ReturnType<typeof userEvent.setup>) {
    render(<AdminScreen />);
    await openTab(user, "Критерии риска");
  }

  it("веса и пороги видны", async () => {
    const user = userEvent.setup();
    await open(user);

    expect(await screen.findByText("ИНДИКАТОРЫ И ВЕСА")).toBeInTheDocument();
    expect(screen.getByText("ТЕСТОВЫЙ ИНДИКАТОР 1")).toBeInTheDocument();
    expect(screen.getByText("ПОРОГИ УРОВНЕЙ")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
  });

  it("сказано, что прошлые оценки не переписываются", async () => {
    const user = userEvent.setup();
    await open(user);

    expect(
      await screen.findByText(/прошлые оценки остаются воспроизводимыми/),
    ).toBeInTheDocument();
  });

  it("новая редакция требует номера версии", async () => {
    const user = userEvent.setup();
    await open(user);

    const submit = await screen.findByRole("button", { name: "Сохранить редакцию" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Номер новой версии"), "2.0");
    expect(submit).toBeEnabled();
  });

  it("редакция отправляется с весами и порогами", async () => {
    const user = userEvent.setup();
    await open(user);

    await user.type(await screen.findByLabelText("Номер новой версии"), "2.0");
    await user.type(screen.getByLabelText("Основание изменения"), "ТЕСТОВОЕ ОСНОВАНИЕ");
    await user.clear(screen.getByLabelText("P1"));
    await user.type(screen.getByLabelText("P1"), "30");
    await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));

    await waitFor(() =>
      expect(api.updateRiskModel).toHaveBeenCalledWith("ТЕСТ-ТОКЕН", "8.4", {
        version: "2.0",
        comment: "ТЕСТОВОЕ ОСНОВАНИЕ",
        weights: [
          { code: "P1", weight: 30 },
          { code: "P2", weight: 15 },
        ],
        thresholds: [
          { from_score: 0, level: "low" },
          { from_score: 50, level: "high" },
        ],
      }),
    );
  });

  it("после сохранения сказано о журнале и неизменности прошлых оценок", async () => {
    const user = userEvent.setup();
    await open(user);

    await user.type(await screen.findByLabelText("Номер новой версии"), "2.0");
    await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));

    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("занесена в журнал действий");
    expect(status).toHaveTextContent("Прошлые оценки не изменены");
  });

  it("отказ сервера при повторе версии показывается пользователю", async () => {
    const user = userEvent.setup();
    api.updateRiskModel.mockRejectedValue(
      new Error("Версия совпадает с действующей."),
    );
    await open(user);

    await user.type(await screen.findByLabelText("Номер новой версии"), "1.0");
    await user.click(screen.getByRole("button", { name: "Сохранить редакцию" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Версия совпадает");
  });

  it("история редакций показывает, кто и когда менял", async () => {
    const user = userEvent.setup();
    api.fetchRiskModels.mockResolvedValue([
      {
        ...MODELS[0],
        version: "2.0",
        history: [
          {
            version: "2.0",
            based_on: "1.0",
            comment: "ТЕСТОВОЕ ОСНОВАНИЕ",
            weights: [],
            thresholds: [],
            changed_by: "t.admin",
            changed_at: "2001-02-03T10:00:00+00:00",
          },
        ],
      },
    ]);
    await open(user);

    expect(await screen.findByText("История редакций")).toBeInTheDocument();
    expect(screen.getByText(/на основе 1.0/)).toBeInTheDocument();
    expect(screen.getByText(/t\.admin/)).toBeInTheDocument();
  });
});

describe("вкладка «Журнал действий»", () => {
  async function open(user: ReturnType<typeof userEvent.setup>) {
    render(<AdminScreen />);
    await openTab(user, "Журнал действий");
  }

  it("фильтры по пользователю, действию и периоду присутствуют", async () => {
    const user = userEvent.setup();
    await open(user);

    expect(await screen.findByLabelText("Пользователь")).toBeInTheDocument();
    expect(screen.getByLabelText("Действие")).toBeInTheDocument();
    expect(screen.getByLabelText("Период с")).toBeInTheDocument();
    expect(screen.getByLabelText("Период по")).toBeInTheDocument();
  });

  it("фильтр по действию уходит на сервер", async () => {
    const user = userEvent.setup();
    await open(user);

    await user.selectOptions(await screen.findByLabelText("Действие"), "risk_model_changed");

    await waitFor(() =>
      expect(api.fetchAuditLog).toHaveBeenCalledWith(
        "ТЕСТ-ТОКЕН",
        expect.objectContaining({ action: "risk_model_changed", page: 1 }),
        expect.anything(),
      ),
    );
  });

  it("действие показано по-русски", async () => {
    const user = userEvent.setup();
    await open(user);

    expect(await screen.findByRole("cell", { name: "Импорт завершён" })).toBeInTheDocument();
  });

  it("сказано, что журнал только на чтение", async () => {
    const user = userEvent.setup();
    await open(user);

    expect(await screen.findByText(/Журнал доступен только на чтение/)).toBeInTheDocument();
  });

  it("кнопок изменения и удаления записей нет", async () => {
    const user = userEvent.setup();
    await open(user);

    await screen.findByText(/Журнал доступен только на чтение/);
    for (const name of [/удалить/i, /изменить/i, /редактировать/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("пустой период объясняется словами", async () => {
    const user = userEvent.setup();
    api.fetchAuditLog.mockResolvedValue({ ...AUDIT, total: 0, items: [] });
    await open(user);

    expect(await screen.findByText(/Записей за выбранный период нет/)).toBeInTheDocument();
  });

  it("страницы переключаются", async () => {
    const user = userEvent.setup();
    api.fetchAuditLog.mockResolvedValue({ ...AUDIT, total: 60 });
    await open(user);

    await user.click(await screen.findByRole("button", { name: "Вперёд" }));

    await waitFor(() =>
      expect(api.fetchAuditLog).toHaveBeenCalledWith(
        "ТЕСТ-ТОКЕН",
        expect.objectContaining({ page: 2 }),
        expect.anything(),
      ),
    );
  });
});
