import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportWizard } from "@/components/import/ImportWizard";
import type {
  DataKindInfo,
  ImportJobPayload,
  KindsPayload,
  UploadPayload,
} from "@/lib/api/imports";

/*
  Данные заведомо тестовые. Правдоподобные имена файлов и числа строк в тестах
  опасны: их копируют в демонстрацию, и выдуманная загрузка начинает выглядеть
  как настоящая запись журнала импортов.
*/

const KIND: DataKindInfo = {
  code: "organizations",
  title: "Хозяйствующие субъекты",
  description: "ТЕСТОВОЕ ОПИСАНИЕ",
  layer_code: "8.7",
  note: "",
  fields: [
    {
      code: "bin",
      title: "БИН",
      type: "xin",
      required: true,
      hint: "Ровно 12 цифр",
      aliases: [],
    },
    { code: "name", title: "Наименование", type: "text", required: true, hint: "", aliases: [] },
    {
      code: "employees_count",
      title: "Численность",
      type: "integer",
      required: false,
      hint: "",
      aliases: [],
    },
  ],
  targets: ["organizations"],
};

function kindTile(code: string, title: string, note = ""): DataKindInfo {
  return { ...KIND, code, title, note };
}

const KINDS: KindsPayload = {
  kinds: [
    KIND,
    kindTile("procurement", "Государственные закупки"),
    kindTile("budget", "Бюджетные данные", "ТЕСТОВОЕ ПРЕДУПРЕЖДЕНИЕ О ГРАНИЦАХ"),
    kindTile("subsidies", "Субсидии и поддержка"),
    kindTile("infrastructure", "Инфраструктурные проекты"),
    kindTile("socioeconomic", "Соц.-экон. показатели"),
  ],
  accepted_extensions: [".csv", ".xlsx"],
  max_upload_mb: 50,
  background_row_threshold: 5000,
};

const UPLOAD: UploadPayload = {
  upload_id: "ТЕСТ-ХЕШ",
  source_file_id: "ТЕСТ-ФАЙЛ",
  file_name: "тест.xlsx",
  size_bytes: 1024,
  sheet_name: "ТЕСТОВЫЙ ЛИСТ",
  row_count: 3,
  columns: ["Колонка БИН", "Колонка названия", "Колонка численности"],
  preview: [{ "Колонка БИН": "101000000001", "Колонка названия": "ТЕСТОВАЯ СТРОКА" }],
  suggested_mapping: { bin: "Колонка БИН", name: "Колонка названия" },
  background_recommended: false,
  templates: [],
};

function job(overrides: Partial<ImportJobPayload> = {}): ImportJobPayload {
  return {
    id: "ТЕСТ-ЗАДАНИЕ",
    layer_code: "8.7",
    data_kind: "organizations",
    importer: "wizard:organizations",
    status: "dry_run",
    is_dry_run: true,
    data_version: 1,
    file_name: "тест.xlsx",
    started_at: "2001-02-03T10:00:00+00:00",
    finished_at: "2001-02-03T10:00:01+00:00",
    rows_read: 3,
    rows_created: 0,
    rows_updated: 0,
    rows_skipped: 1,
    rows_failed: 1,
    issues: { error: 1 },
    badge: "warning",
    summary: {
      rows_read: 3,
      rows_valid: 2,
      rows_failed: 1,
      duplicates_in_file: 0,
      duplicates_in_db: 1,
      issues: { error: 1, warning: 0, info: 0 },
    },
    progress: null,
    territory: null,
    error_message: null,
    can_rollback: false,
    issue_list: [
      {
        severity: "error",
        code: "invalid_date",
        message: "Поле «Дата регистрации»: «позавчера» не распознано как дата.",
        row: "ТЕСТОВЫЙ ЛИСТ!строка 4",
        column: "Колонка даты",
        raw_value: "позавчера",
        context: null,
      },
    ],
    ...overrides,
  };
}

const api = vi.hoisted(() => ({
  fetchKinds: vi.fn(),
  uploadFile: vi.fn(),
  dryRun: vi.fn(),
  confirmImport: vi.fn(),
  fetchJobs: vi.fn(),
  rollbackJob: vi.fn(),
  saveTemplate: vi.fn(),
}));

vi.mock("@/lib/api/imports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/imports")>();
  return { ...actual, ...api };
});

vi.mock("@/lib/api/auth", () => ({ readToken: () => "ТЕСТ-ТОКЕН" }));

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchKinds.mockResolvedValue(KINDS);
  api.fetchJobs.mockResolvedValue([]);
  api.uploadFile.mockResolvedValue(UPLOAD);
  api.dryRun.mockResolvedValue(job());
  api.confirmImport.mockResolvedValue(
    job({ status: "succeeded", is_dry_run: false, data_version: 4, rows_created: 2 }),
  );
  api.rollbackJob.mockResolvedValue(job({ status: "rolled_back", badge: "rolled_back" }));
});

function testFile(name = "тест.xlsx"): File {
  return new File(["ТЕСТОВОЕ СОДЕРЖИМОЕ"], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

/** Пройти шаг 1 целиком: выбрать тип, приложить файл, нажать «Далее». */
async function passStepOne(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Хозяйствующие субъекты/ }));
  await user.upload(screen.getByLabelText("Файл для загрузки"), testFile());
  await user.click(screen.getByRole("button", { name: "Далее" }));
}

describe("шаг 1: тип данных и файл", () => {
  it("показаны шесть плиток референса", async () => {
    render(<ImportWizard />);

    await waitFor(() => expect(screen.getByText("Хозяйствующие субъекты")).toBeInTheDocument());
    for (const title of [
      "Государственные закупки",
      "Бюджетные данные",
      "Субсидии и поддержка",
      "Хозяйствующие субъекты",
      "Инфраструктурные проекты",
      "Соц.-экон. показатели",
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it("степпер перечисляет три шага", async () => {
    render(<ImportWizard />);

    const steps = await screen.findByRole("list", { name: "Шаги мастера" });
    expect(within(steps).getByText("Загрузка файла")).toBeInTheDocument();
    expect(within(steps).getByText("Сопоставление столбцов")).toBeInTheDocument();
    expect(within(steps).getByText("Предпросмотр и подтверждение")).toBeInTheDocument();
  });

  it("«Далее» неактивна, пока не выбраны тип и файл", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    const next = await screen.findByRole("button", { name: "Далее" });
    expect(next).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Хозяйствующие субъекты/ }));
    expect(next).toBeDisabled();
    expect(screen.getByText("Выберите файл")).toBeInTheDocument();

    await user.upload(screen.getByLabelText("Файл для загрузки"), testFile());
    expect(next).toBeEnabled();
  });

  it("подпись зоны перетаскивания повторяет ограничения сервера", async () => {
    render(<ImportWizard />);

    expect(
      await screen.findByText(/Excel \(\.xlsx, \.xls\), CSV, JSON, GeoJSON/),
    ).toBeInTheDocument();
    expect(screen.getByText(/50 МБ/)).toBeInTheDocument();
  });

  it("предупреждение о границах загрузки видно до выбора файла", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await user.click(await screen.findByRole("button", { name: /Бюджетные данные/ }));

    expect(screen.getByText("ТЕСТОВОЕ ПРЕДУПРЕЖДЕНИЕ О ГРАНИЦАХ")).toBeInTheDocument();
  });

  it("выбранная плитка помечена для программ чтения с экрана", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    const tile = await screen.findByRole("button", { name: /Хозяйствующие субъекты/ });
    await user.click(tile);

    expect(tile).toHaveAttribute("aria-pressed", "true");
  });
});

describe("шаг 2: сопоставление столбцов", () => {
  it("подставляется сопоставление, предложенное сервером", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await passStepOne(user);

    expect(await screen.findByLabelText(/БИН/)).toHaveValue("Колонка БИН");
    expect(screen.getByLabelText(/Наименование/)).toHaveValue("Колонка названия");
  });

  it("несопоставленное поле остаётся пустым, а не угадывается", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await passStepOne(user);

    expect(await screen.findByLabelText("Численность")).toHaveValue("");
  });

  it("проверка файла блокируется без обязательного поля", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);
    await passStepOne(user);

    await user.selectOptions(await screen.findByLabelText(/Наименование/), "");

    expect(screen.getByRole("button", { name: "Проверить файл" })).toBeDisabled();
    expect(
      screen.getByText(/Не сопоставлены обязательные поля: Наименование/),
    ).toBeInTheDocument();
  });

  it("показан предпросмотр строк файла", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await passStepOne(user);

    expect(await screen.findByText("ПРЕДПРОСМОТР")).toBeInTheDocument();
    expect(screen.getByText("ТЕСТОВАЯ СТРОКА")).toBeInTheDocument();
  });

  it("шаблон сопоставления сохраняется под названием", async () => {
    const user = userEvent.setup();
    api.saveTemplate.mockResolvedValue({
      id: "ТЕСТ-ШАБЛОН",
      name: "ТЕСТОВЫЙ ШАБЛОН",
      data_kind: "organizations",
      mapping: UPLOAD.suggested_mapping,
      created_at: null,
    });
    render(<ImportWizard />);
    await passStepOne(user);

    await user.type(
      await screen.findByLabelText("Сохранить сопоставление как"),
      "ТЕСТОВЫЙ ШАБЛОН",
    );
    await user.click(screen.getByRole("button", { name: "Сохранить шаблон" }));

    await waitFor(() =>
      expect(api.saveTemplate).toHaveBeenCalledWith(
        "ТЕСТ-ТОКЕН",
        expect.objectContaining({ name: "ТЕСТОВЫЙ ШАБЛОН", data_kind: "organizations" }),
      ),
    );
  });
});

describe("шаг 3: сухой прогон и подтверждение", () => {
  async function reachStepThree(user: ReturnType<typeof userEvent.setup>) {
    await passStepOne(user);
    await user.click(await screen.findByRole("button", { name: "Проверить файл" }));
  }

  it("сводка показывает числа сухого прогона", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await reachStepThree(user);

    expect(await screen.findByText("Строк прочитано")).toBeInTheDocument();
    expect(screen.getByText("Готовы к записи")).toBeInTheDocument();
    expect(screen.getByText("Обновятся в базе")).toBeInTheDocument();
    expect(screen.getByText(/данные ещё не записаны/i)).toBeInTheDocument();
  });

  it("замечание указывает строку и колонку", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);

    await reachStepThree(user);

    expect(await screen.findByText("ТЕСТОВЫЙ ЛИСТ!строка 4")).toBeInTheDocument();
    expect(screen.getByText("Колонка даты")).toBeInTheDocument();
    expect(screen.getByText(/не распознано как дата/)).toBeInTheDocument();
    expect(screen.getByText("Ошибка")).toBeInTheDocument();
  });

  it("подтверждение отправляет сопоставление и показывает версию", async () => {
    const user = userEvent.setup();
    render(<ImportWizard />);
    await reachStepThree(user);

    await user.click(await screen.findByRole("button", { name: "Подтвердить загрузку" }));

    await waitFor(() =>
      expect(api.confirmImport).toHaveBeenCalledWith(
        "ТЕСТ-ТОКЕН",
        {
          upload_id: "ТЕСТ-ХЕШ",
          data_kind: "organizations",
          mapping: { bin: "Колонка БИН", name: "Колонка названия" },
        },
        false,
      ),
    );
    expect(await screen.findByText(/Версия данных 4/)).toBeInTheDocument();
  });

  it("подтверждение недоступно, когда ни одна строка не прошла проверку", async () => {
    const user = userEvent.setup();
    api.dryRun.mockResolvedValue(
      job({
        summary: {
          rows_read: 3,
          rows_valid: 0,
          rows_failed: 3,
          duplicates_in_file: 0,
          duplicates_in_db: 0,
          issues: { error: 3, warning: 0, info: 0 },
        },
      }),
    );
    render(<ImportWizard />);

    await reachStepThree(user);

    expect(await screen.findByRole("button", { name: "Подтвердить загрузку" })).toBeDisabled();
    expect(screen.getByText(/записывать нечего/)).toBeInTheDocument();
  });

  it("фоновый режим предлагается только для большого файла", async () => {
    const user = userEvent.setup();
    api.uploadFile.mockResolvedValue({ ...UPLOAD, background_recommended: true });
    render(<ImportWizard />);
    await reachStepThree(user);

    await user.click(await screen.findByRole("button", { name: "Обработать в фоне" }));

    await waitFor(() =>
      expect(api.confirmImport).toHaveBeenCalledWith(
        "ТЕСТ-ТОКЕН",
        expect.anything(),
        true,
      ),
    );
  });
});

describe("история загрузок", () => {
  it("карточка показывает файл, число строк и статусный бейдж", async () => {
    api.fetchJobs.mockResolvedValue([
      job({ id: "ТЕСТ-1", badge: "ok", is_dry_run: false, status: "succeeded" }),
    ]);
    render(<ImportWizard />);

    const panel = await screen.findByRole("complementary", { name: "История загрузок" });
    expect(within(panel).getByText("тест.xlsx")).toBeInTheDocument();
    expect(within(panel).getByText(/3 строк/)).toBeInTheDocument();
    expect(within(panel).getByText("ОК")).toBeInTheDocument();
  });

  it("бейдж предупреждения подписан словом, а не только цветом", async () => {
    api.fetchJobs.mockResolvedValue([job({ badge: "warning" })]);
    render(<ImportWizard />);

    const panel = await screen.findByRole("complementary", { name: "История загрузок" });
    expect(within(panel).getByText("Предупрежд.")).toBeInTheDocument();
  });

  it("прогресс фоновой обработки показан полосой", async () => {
    api.fetchJobs.mockResolvedValue([
      job({ progress: { processed: 300, total: 1000, percent: 30 } }),
    ]);
    render(<ImportWizard />);

    const bar = await screen.findByRole("progressbar", { name: "Прогресс обработки" });
    expect(bar).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText(/обработано 300 из 1000/)).toBeInTheDocument();
  });

  it("откат доступен только у завершённой загрузки", async () => {
    api.fetchJobs.mockResolvedValue([job({ can_rollback: false })]);
    render(<ImportWizard />);

    await screen.findByRole("complementary", { name: "История загрузок" });
    expect(screen.queryByRole("button", { name: "Откатить версию" })).not.toBeInTheDocument();
  });

  it("откат сообщает, что данные не удалены", async () => {
    const user = userEvent.setup();
    api.fetchJobs.mockResolvedValue([job({ can_rollback: true, data_version: 7 })]);
    render(<ImportWizard />);

    await user.click(await screen.findByRole("button", { name: "Откатить версию" }));

    await waitFor(() => expect(api.rollbackJob).toHaveBeenCalled());
    expect(await screen.findByText(/Данные не удалены/)).toBeInTheDocument();
    expect(screen.getByText(/Версия 7 отозвана/)).toBeInTheDocument();
  });

  it("объяснение отката видно и без единой загрузки", async () => {
    render(<ImportWizard />);

    expect(
      await screen.findByText(/снимает признак актуальности с логической версии/),
    ).toBeInTheDocument();
  });
});

describe("ошибки", () => {
  it("отказ сервера показывается сообщением, а не молчанием", async () => {
    const user = userEvent.setup();
    api.uploadFile.mockRejectedValue(new Error("Файл больше 50 МБ"));
    render(<ImportWizard />);

    await passStepOne(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Файл больше 50 МБ");
  });

  it("сбой истории загрузок не мешает работать с мастером", async () => {
    api.fetchJobs.mockRejectedValue(new Error("ТЕСТОВЫЙ СБОЙ"));
    render(<ImportWizard />);

    expect(await screen.findByText("Загрузок пока не было.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
