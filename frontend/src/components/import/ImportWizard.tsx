"use client";

/**
 * Мастер импорта данных — три шага с референса плюс история загрузок справа.
 *
 * Состояние мастера живёт в компоненте, а не в URL: шаги связаны загруженным
 * файлом, и ссылка на «шаг 3» без файла не имеет смысла — восстановить по ней
 * было бы нечего. По той же причине не используется `useSearchParams`.
 *
 * Клиент здесь ничего не решает окончательно. Он показывает предложенное
 * сервером сопоставление, даёт его исправить и отправляет обратно; проверка
 * обязательных полей, типов, дублей и прав выполняется на сервере заново.
 * Кнопка «Далее» гасится, чтобы не провоцировать заведомо неудачный запрос, а
 * не потому, что клиент считает себя источником истины.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { readToken } from "@/lib/api/auth";
import {
  BADGE_LABELS,
  SEVERITY_LABELS,
  confirmImport,
  dryRun,
  fetchJobs,
  fetchKinds,
  rollbackJob,
  saveTemplate,
  uploadFile,
  type DataKindInfo,
  type ImportJobPayload,
  type IssueRow,
  type JobBadge,
  type KindsPayload,
  type MappingTemplate,
  type UploadPayload,
} from "@/lib/api/imports";
import { explain } from "@/lib/api/request";

const STEPS = [
  { number: 1, title: "Загрузка файла" },
  { number: 2, title: "Сопоставление столбцов" },
  { number: 3, title: "Предпросмотр и подтверждение" },
] as const;

/** Классы бейджа. Подпись рядом обязательна: цвет не носитель смысла. */
const BADGE_STYLES: Record<JobBadge, string> = {
  ok: "bg-risk-low-bg text-risk-low-text border-risk-low-border",
  warning: "bg-risk-medium-bg text-risk-medium-text border-risk-medium-border",
  error: "bg-risk-high-bg text-risk-high-text border-risk-high-border",
  rolled_back: "bg-risk-none-bg text-risk-none-text border-risk-none-border",
};

const SEVERITY_STYLES: Record<IssueRow["severity"], string> = {
  error: "text-risk-high-text",
  warning: "text-risk-medium-text",
  info: "text-text-muted",
};

function formatBytes(size: number): string {
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / 1024 / 1024).toFixed(1)} МБ`;
}

function formatMoment(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ImportWizard() {
  /*
    Токен читается лениво при первом рендере, а не записывается состоянием в
    эффекте: запись состояния прямо в теле эффекта вызывает лишний каскад
    перерисовок.
  */
  const [token] = useState<string | null>(() => readToken());

  const [kinds, setKinds] = useState<KindsPayload | null>(null);
  const [kindCode, setKindCode] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<UploadPayload | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [templateName, setTemplateName] = useState("");
  const [templates, setTemplates] = useState<MappingTemplate[]>([]);
  const [preview, setPreview] = useState<ImportJobPayload | null>(null);
  const [confirmed, setConfirmed] = useState<ImportJobPayload | null>(null);
  const [history, setHistory] = useState<ImportJobPayload[]>([]);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const kind: DataKindInfo | null = useMemo(
    () => kinds?.kinds.find((item) => item.code === kindCode) ?? null,
    [kinds, kindCode],
  );

  /*
    История перечитывается после каждого шага, который её меняет. Обновление
    состояния живёт в колбэке промиса, а не в теле эффекта: синхронная запись
    состояния прямо в эффекте вызывает каскад перерисовок.

    Сбой самой истории не показывается как ошибка шага: это вспомогательная
    колонка, и её недоступность не должна перекрывать сообщение о том, что
    случилось с загрузкой.
  */
  const refreshHistory = useCallback(
    (signal?: AbortSignal) =>
      fetchJobs(token, { limit: 12, signal })
        .then((jobs) => {
          if (!signal?.aborted) setHistory(jobs);
        })
        .catch(() => {
          if (!signal?.aborted) setHistory([]);
        }),
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();

    fetchKinds(token, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setKinds(payload);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(explain(cause));
      });

    void refreshHistory(controller.signal);
    return () => controller.abort();
  }, [token, refreshHistory]);

  const requiredMissing = useMemo(() => {
    if (!kind) return [];
    return kind.fields.filter((item) => item.required && !mapping[item.code]);
  }, [kind, mapping]);

  function resetFrom(nextStep: 1 | 2 | 3) {
    setError(null);
    setNotice(null);
    if (nextStep <= 2) {
      setPreview(null);
      setConfirmed(null);
    }
    if (nextStep === 1) {
      setUpload(null);
      setMapping({});
    }
    setStep(nextStep);
  }

  async function handleUpload() {
    if (!file || !kindCode) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await uploadFile(token, kindCode, file);
      setUpload(payload);
      setMapping(payload.suggested_mapping);
      setTemplates(payload.templates);
      setStep(2);
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleDryRun() {
    if (!upload || !kindCode) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await dryRun(token, {
        upload_id: upload.upload_id,
        data_kind: kindCode,
        mapping,
      });
      setPreview(payload);
      setStep(3);
      void refreshHistory();
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(background: boolean) {
    if (!upload || !kindCode) return;
    setBusy(true);
    setError(null);
    try {
      const payload = await confirmImport(
        token,
        { upload_id: upload.upload_id, data_kind: kindCode, mapping },
        background,
      );
      setConfirmed(payload);
      setNotice(
        background
          ? "Файл принят в обработку. Прогресс виден в истории загрузок."
          : `Загрузка завершена. Версия данных ${payload.data_version}.`,
      );
      void refreshHistory();
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveTemplate() {
    if (!upload || !kindCode || !templateName.trim()) return;
    setBusy(true);
    try {
      const saved = await saveTemplate(token, {
        upload_id: upload.upload_id,
        data_kind: kindCode,
        mapping,
        name: templateName.trim(),
      });
      setTemplates((previous) => [
        saved,
        ...previous.filter((item) => item.name !== saved.name),
      ]);
      setTemplateName("");
      setNotice(`Шаблон «${saved.name}» сохранён.`);
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleRollback(job: ImportJobPayload) {
    setBusy(true);
    setError(null);
    try {
      await rollbackJob(token, job.id, "Отозвано из мастера импорта");
      setNotice(
        `Версия ${job.data_version} отозвана. Данные не удалены — снят признак актуальности.`,
      );
      void refreshHistory();
    } catch (cause) {
      setError(explain(cause));
    } finally {
      setBusy(false);
    }
  }

  const issues = preview?.issue_list ?? [];
  const summary = preview?.summary ?? null;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Главная" }, { label: "Данные" }]}
        title="Загрузка и импорт данных"
        subtitle="Мастер загрузки в 3 шага"
      />

      <ol className="mb-6 flex flex-wrap items-center gap-3" aria-label="Шаги мастера">
        {STEPS.map((item) => {
          const active = step === item.number;
          const done = step > item.number;
          return (
            <li key={item.number} className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={`flex size-7 items-center justify-center rounded-full text-xs font-semibold ${
                  active || done
                    ? "bg-accent text-accent-fg"
                    : "bg-surface-hover text-text-subtle"
                }`}
              >
                {item.number}
              </span>
              <span
                className={`text-sm ${active ? "font-semibold text-text" : "text-text-muted"}`}
                aria-current={active ? "step" : undefined}
              >
                {item.title}
              </span>
            </li>
          );
        })}
      </ol>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-panel border border-risk-high-border bg-risk-high-bg p-4"
        >
          <p className="text-sm font-medium text-risk-high-text">Шаг не выполнен</p>
          <p className="mt-1 text-sm text-text-muted">{error}</p>
        </div>
      )}

      {notice && (
        <div
          role="status"
          className="mb-4 rounded-panel border border-risk-low-border bg-risk-low-bg p-4 text-sm text-risk-low-text"
        >
          {notice}
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div>
          {step === 1 && (
            <section
              aria-label="Шаг 1: загрузка файла"
              className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
            >
              <h2 className="text-xs font-semibold tracking-wide text-text-muted">
                ТИП ЗАГРУЖАЕМЫХ ДАННЫХ
              </h2>

              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {(kinds?.kinds ?? []).map((item) => (
                  <button
                    key={item.code}
                    type="button"
                    aria-pressed={kindCode === item.code}
                    onClick={() => setKindCode(item.code)}
                    className={`rounded-card border p-3 text-left transition ${
                      kindCode === item.code
                        ? "border-accent bg-accent-soft"
                        : "border-border-base bg-surface hover:bg-surface-hover"
                    }`}
                  >
                    <span className="block text-sm font-medium text-text">{item.title}</span>
                    <span className="mt-0.5 block text-xs text-text-muted">
                      {item.description}
                    </span>
                  </button>
                ))}
              </div>

              {/*
                Предупреждение о границах загрузки показывается до выбора файла,
                а не после отказа: узнать, что факты бюджета так не грузятся,
                правильнее до того, как человек собрал файл.
              */}
              {kind?.note && (
                <p className="mt-3 rounded-card border border-risk-medium-border bg-risk-medium-bg p-3 text-xs text-risk-medium-text">
                  {kind.note}
                </p>
              )}

              <label
                htmlFor="import-file"
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  const dropped = event.dataTransfer.files?.[0];
                  if (dropped) setFile(dropped);
                }}
                className={`mt-5 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-panel border border-dashed px-6 py-10 text-center ${
                  dragging ? "border-accent bg-accent-soft" : "border-border-strong bg-surface-muted"
                }`}
              >
                <span className="text-sm font-medium text-text">
                  Перетащите файл или нажмите для выбора
                </span>
                <span className="text-xs text-text-muted">
                  Excel (.xlsx, .xls), CSV, JSON, GeoJSON · Макс.{" "}
                  {kinds?.max_upload_mb ?? 50} МБ
                </span>
                {file && (
                  <span className="mt-1 text-xs text-accent">
                    {file.name} · {formatBytes(file.size)}
                  </span>
                )}
              </label>
              <input
                id="import-file"
                type="file"
                /* Своя подпись, а не текст подложки: подпись зоны
                   перетаскивания содержит перечень форматов и предел размера,
                   и целиком в имени поля она читалась бы как каша. */
                aria-label="Файл для загрузки"
                className="sr-only"
                accept={(kinds?.accepted_extensions ?? []).join(",")}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />

              <div className="mt-5 flex items-center gap-3">
                <button
                  type="button"
                  disabled={!file || !kindCode || busy}
                  onClick={() => void handleUpload()}
                  className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
                >
                  Далее
                </button>
                {!kindCode && (
                  <span className="text-xs text-text-subtle">Выберите тип данных</span>
                )}
                {kindCode && !file && (
                  <span className="text-xs text-text-subtle">Выберите файл</span>
                )}
              </div>
            </section>
          )}

          {step === 2 && upload && kind && (
            <section
              aria-label="Шаг 2: сопоставление столбцов"
              className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
            >
              <h2 className="text-sm font-semibold text-text">Сопоставление столбцов</h2>
              <p className="mt-0.5 text-xs text-text-muted">
                {upload.file_name} · лист «{upload.sheet_name}» · строк:{" "}
                {upload.row_count.toLocaleString("ru-RU")}
              </p>

              {templates.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-text-muted">Готовые шаблоны:</span>
                  {templates.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setMapping(item.mapping)}
                      className="rounded-card border border-border-base px-2 py-1 text-xs text-text hover:bg-surface-hover"
                    >
                      {item.name}
                    </button>
                  ))}
                </div>
              )}

              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-text-muted">
                      <th className="py-2 pr-4 font-medium">Поле Системы</th>
                      <th className="py-2 pr-4 font-medium">Колонка файла</th>
                    </tr>
                  </thead>
                  <tbody>
                    {kind.fields.map((item) => (
                      <tr key={item.code} className="border-t border-border-base">
                        <td className="py-2 pr-4 align-top">
                          <label htmlFor={`map-${item.code}`} className="text-text">
                            {item.title}
                            {item.required && (
                              <span className="ml-1 text-risk-high-text" title="Обязательное поле">
                                *
                              </span>
                            )}
                          </label>
                          {item.hint && (
                            <p className="mt-0.5 text-xs text-text-subtle">{item.hint}</p>
                          )}
                        </td>
                        <td className="py-2 pr-4 align-top">
                          <select
                            id={`map-${item.code}`}
                            value={mapping[item.code] ?? ""}
                            onChange={(event) =>
                              setMapping((previous) => {
                                const next = { ...previous };
                                if (event.target.value) next[item.code] = event.target.value;
                                else delete next[item.code];
                                return next;
                              })
                            }
                            className="w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                          >
                            <option value="">— не сопоставлено —</option>
                            {upload.columns.map((column) => (
                              <option key={column} value={column}>
                                {column}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h3 className="mt-6 text-xs font-semibold tracking-wide text-text-muted">
                ПРЕДПРОСМОТР
              </h3>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-text-muted">
                      {upload.columns.map((column) => (
                        <th key={column} className="whitespace-nowrap px-2 py-1 font-medium">
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {upload.preview.slice(0, 5).map((row, index) => (
                      <tr key={index} className="border-t border-border-base">
                        {upload.columns.map((column) => (
                          <td key={column} className="whitespace-nowrap px-2 py-1 text-text">
                            {cellText(row[column])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-2">
                <label htmlFor="template-name" className="text-xs text-text-muted">
                  Сохранить сопоставление как
                </label>
                <input
                  id="template-name"
                  value={templateName}
                  onChange={(event) => setTemplateName(event.target.value)}
                  placeholder="Название шаблона"
                  className="rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                />
                <button
                  type="button"
                  disabled={!templateName.trim() || busy}
                  onClick={() => void handleSaveTemplate()}
                  className="rounded-card border border-border-base px-3 py-1 text-sm text-text disabled:opacity-40"
                >
                  Сохранить шаблон
                </button>
              </div>

              {requiredMissing.length > 0 && (
                <p className="mt-4 text-xs text-risk-high-text">
                  Не сопоставлены обязательные поля:{" "}
                  {requiredMissing.map((item) => item.title).join(", ")}.
                </p>
              )}

              <div className="mt-5 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => resetFrom(1)}
                  className="rounded-card border border-border-base px-4 py-2 text-sm text-text"
                >
                  Назад
                </button>
                <button
                  type="button"
                  disabled={requiredMissing.length > 0 || busy}
                  onClick={() => void handleDryRun()}
                  className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
                >
                  Проверить файл
                </button>
              </div>
            </section>
          )}

          {step === 3 && preview && (
            <section
              aria-label="Шаг 3: предпросмотр и подтверждение"
              className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
            >
              <h2 className="text-sm font-semibold text-text">Сводка проверки</h2>
              <p className="mt-0.5 text-xs text-text-muted">
                Сухой прогон: данные ещё не записаны.
              </p>

              {summary && (
                <dl className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
                  {[
                    ["Строк прочитано", summary.rows_read],
                    ["Готовы к записи", summary.rows_valid],
                    ["С ошибками", summary.rows_failed],
                    ["Дубли в файле", summary.duplicates_in_file],
                    ["Обновятся в базе", summary.duplicates_in_db],
                  ].map(([label, value]) => (
                    <div
                      key={String(label)}
                      className="rounded-card border border-border-base p-3"
                    >
                      <dt className="text-xs text-text-muted">{label}</dt>
                      <dd className="mt-1 text-lg font-semibold tabular-nums text-text">
                        {Number(value).toLocaleString("ru-RU")}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}

              <h3 className="mt-6 text-xs font-semibold tracking-wide text-text-muted">
                ЗАМЕЧАНИЯ ({issues.length})
              </h3>
              {issues.length === 0 ? (
                <p className="mt-2 text-sm text-text-muted">Замечаний нет.</p>
              ) : (
                <div className="mt-2 max-h-80 overflow-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-text-muted">
                        <th className="px-2 py-1 font-medium">Уровень</th>
                        <th className="px-2 py-1 font-medium">Строка</th>
                        <th className="px-2 py-1 font-medium">Колонка</th>
                        <th className="px-2 py-1 font-medium">Замечание</th>
                      </tr>
                    </thead>
                    <tbody>
                      {issues.slice(0, 100).map((item, index) => (
                        <tr key={index} className="border-t border-border-base align-top">
                          <td className={`px-2 py-1 ${SEVERITY_STYLES[item.severity]}`}>
                            {SEVERITY_LABELS[item.severity]}
                          </td>
                          <td className="whitespace-nowrap px-2 py-1 font-mono text-text-muted">
                            {item.row ?? "—"}
                          </td>
                          <td className="px-2 py-1 text-text-muted">{item.column ?? "—"}</td>
                          <td className="px-2 py-1 text-text">{item.message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {confirmed ? (
                <div className="mt-6 rounded-card border border-border-base p-4">
                  <p className="text-sm font-medium text-text">
                    {confirmed.background
                      ? "Обработка идёт в фоне"
                      : `Загрузка завершена, версия ${confirmed.data_version}`}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">
                    Создано: {confirmed.rows_created.toLocaleString("ru-RU")}, обновлено:{" "}
                    {confirmed.rows_updated.toLocaleString("ru-RU")}, пропущено:{" "}
                    {confirmed.rows_skipped.toLocaleString("ru-RU")}.
                  </p>
                  <button
                    type="button"
                    onClick={() => resetFrom(1)}
                    className="mt-3 rounded-card border border-border-base px-3 py-1.5 text-sm text-text"
                  >
                    Загрузить ещё файл
                  </button>
                </div>
              ) : (
                <div className="mt-6 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => resetFrom(2)}
                    className="rounded-card border border-border-base px-4 py-2 text-sm text-text"
                  >
                    Назад
                  </button>
                  <button
                    type="button"
                    disabled={busy || (summary?.rows_valid ?? 0) === 0}
                    onClick={() => void handleConfirm(false)}
                    className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
                  >
                    Подтвердить загрузку
                  </button>
                  {/*
                    Фоновый режим предлагается, но не навязывается: оператор
                    должен понимать, дождётся он результата или будет следить
                    за прогрессом в истории.
                  */}
                  {upload?.background_recommended && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleConfirm(true)}
                      className="rounded-card border border-accent px-4 py-2 text-sm text-accent disabled:opacity-40"
                    >
                      Обработать в фоне
                    </button>
                  )}
                  {(summary?.rows_valid ?? 0) === 0 && (
                    <span className="text-xs text-text-subtle">
                      Ни одна строка не прошла проверку — записывать нечего.
                    </span>
                  )}
                </div>
              )}
            </section>
          )}
        </div>

        <aside
          aria-label="История загрузок"
          className="rounded-panel border border-border-base bg-surface p-4 shadow-card"
        >
          <h2 className="text-xs font-semibold tracking-wide text-text-muted">
            ИСТОРИЯ ЗАГРУЗОК
          </h2>

          {history.length === 0 ? (
            <p className="mt-3 text-sm text-text-muted">Загрузок пока не было.</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {history.map((job) => (
                <li key={job.id} className="rounded-card border border-border-base p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm text-text" title={job.file_name ?? ""}>
                      {job.file_name ?? "без имени"}
                    </span>
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${BADGE_STYLES[job.badge]}`}
                    >
                      {BADGE_LABELS[job.badge]}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-text-muted">
                    {job.rows_read.toLocaleString("ru-RU")} строк · {formatMoment(job.started_at)}
                  </p>
                  <p className="mt-0.5 text-xs text-text-subtle">
                    версия {job.data_version}
                    {job.is_dry_run ? " · сухой прогон" : ""}
                  </p>
                  {job.progress && job.progress.percent < 100 && (
                    <div className="mt-2">
                      <div
                        role="progressbar"
                        aria-valuenow={job.progress.percent}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-label="Прогресс обработки"
                        className="h-1.5 w-full overflow-hidden rounded bg-surface-hover"
                      >
                        <div
                          className="h-full bg-accent"
                          style={{ width: `${job.progress.percent}%` }}
                        />
                      </div>
                      <p className="mt-1 text-[10px] text-text-subtle">
                        обработано {job.progress.processed} из {job.progress.total}
                      </p>
                    </div>
                  )}
                  {job.can_rollback && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void handleRollback(job)}
                      className="mt-2 text-xs text-accent underline disabled:opacity-40"
                    >
                      Откатить версию
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <p className="mt-4 text-[10px] leading-relaxed text-text-subtle">
            Откат не удаляет данные: он снимает признак актуальности с логической
            версии, чтобы прежние оценки остались объяснимыми.
          </p>
        </aside>
      </div>
    </>
  );
}
