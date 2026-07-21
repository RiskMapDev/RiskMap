"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  BarChart3,
  Building2,
  Download,
  Factory,
  FileSpreadsheet,
  FileText,
  FileType,
  HardHat,
  Info,
  ListChecks,
  Loader2,
  Map as MapIcon,
  MapPin,
  type LucideIcon,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { readToken } from "@/lib/api/auth";
import { explain } from "@/lib/api/request";
import {
  fallbackFileName,
  fetchReportFormats,
  fetchReportTemplates,
  generateReport,
  saveFile,
  type ReportFormatInfo,
  type ReportTemplateInfo,
} from "@/lib/api/reports";
import {
  DEFAULT_QUERY_SPEC,
  activeFilterChips,
  fromSearchParams,
  hasActiveFilters,
  type QuerySpec,
} from "@/lib/query-spec";

/**
 * Значки шаблонов.
 *
 * Ключи — коды сервера. Отдельный словарь, а не поле в ответе API: значок
 * относится к оформлению, и держать его в базе значило бы менять данные ради
 * смены иконки. Неизвестный шаблон получает нейтральный значок, а не пустоту —
 * карточка не должна разъезжаться из-за того, что на сервере появился девятый
 * отчёт, о котором интерфейс ещё не знает.
 */
const TEMPLATE_ICONS: Record<string, LucideIcon> = {
  "region-summary": MapIcon,
  territory: MapPin,
  organization: Building2,
  project: HardHat,
  industry: Factory,
  "risk-category": AlertTriangle,
  ratings: BarChart3,
  "high-risk": ListChecks,
};

const FORMAT_ICONS: Record<string, LucideIcon> = {
  docx: FileText,
  xlsx: FileSpreadsheet,
  pdf: FileType,
};

type Phase = "loading" | "error" | "ready";

/** Скелетон карточки: место занято, но ни одного числа не показано. */
function TemplateSkeleton() {
  return (
    <div className="rounded-card border border-border-base bg-surface p-4">
      <div className="size-8 animate-pulse rounded bg-surface-hover" />
      <div className="mt-3 h-4 w-3/4 animate-pulse rounded bg-surface-hover" />
      <div className="mt-2 h-3 w-full animate-pulse rounded bg-surface-hover" />
      <div className="mt-1.5 h-3 w-2/3 animate-pulse rounded bg-surface-hover" />
      <div className="mt-4 h-8 w-full animate-pulse rounded bg-surface-hover" />
    </div>
  );
}

/**
 * Выбор формата выгрузки.
 *
 * Недоступный формат не прячется и не выключается молча: он остаётся в списке,
 * помечен значком запрета и подписью с причиной. Спрятать его значило бы
 * оставить пользователя в убеждении, что PDF в системе не предусмотрен, а
 * выключить без объяснения — заставить гадать, что он сделал не так.
 */
function FormatChoice({
  formats,
  value,
  onChange,
}: {
  formats: ReportFormatInfo[];
  value: string;
  onChange: (code: string) => void;
}) {
  return (
    <fieldset className="rounded-panel border border-border-base bg-surface p-4">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wider text-text-muted">
        Формат выгрузки
      </legend>

      <div className="flex flex-wrap gap-2">
        {formats.map((format) => {
          const Icon = FORMAT_ICONS[format.code] ?? FileText;
          const active = format.code === value && format.available;
          const hintId = `format-hint-${format.code}`;

          return (
            <label
              key={format.code}
              className={`flex cursor-pointer items-center gap-2 rounded border px-3 py-2 text-sm transition-colors ${
                format.available
                  ? active
                    ? "border-accent bg-accent text-accent-fg"
                    : "border-border-base bg-surface text-text hover:bg-surface-hover"
                  : "cursor-not-allowed border-dashed border-border-strong bg-surface-muted text-text-subtle"
              }`}
            >
              <input
                type="radio"
                name="report-format"
                value={format.code}
                checked={active}
                disabled={!format.available}
                onChange={() => onChange(format.code)}
                aria-describedby={format.available ? undefined : hintId}
                className="sr-only"
              />
              {format.available ? (
                <Icon className="size-4 shrink-0" aria-hidden="true" />
              ) : (
                <Ban className="size-4 shrink-0" aria-hidden="true" />
              )}
              <span>{format.title}</span>
              {!format.available && <span className="text-xs">— недоступен</span>}
            </label>
          );
        })}
      </div>

      {/*
        Причина недоступности сообщается ДО нажатия. Узнать о ней из отказа
        сервера после ожидания — значит потратить время пользователя на
        операцию, о невозможности которой было известно заранее.
      */}
      {formats
        .filter((format) => !format.available)
        .map((format) => (
          <p
            key={`hint-${format.code}`}
            id={`format-hint-${format.code}`}
            className="mt-2 flex items-start gap-1.5 text-xs text-text-subtle"
          >
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>
              <span className="font-medium">{format.title}</span>:{" "}
              {format.reason || "формат не поддерживается в этом развёртывании"} Отчёт можно
              выгрузить в другом формате — данные в нём те же.
            </span>
          </p>
        ))}
    </fieldset>
  );
}

/**
 * Экран «Отчёты и экспорт».
 *
 * Восемь шаблонов приходят с сервера, а не перечислены здесь: их состав задан
 * ТЗ и продублировать его в интерфейсе значило бы завести второй источник
 * правды, который однажды разойдётся с первым.
 */
export function ReportsScreen() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [templates, setTemplates] = useState<ReportTemplateInfo[]>([]);
  const [formats, setFormats] = useState<ReportFormatInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [format, setFormat] = useState<string>("docx");

  /** Код шаблона, который сейчас формируется. `null` — ни один. */
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ template: string; message: string } | null>(null);
  const [done, setDone] = useState<{ template: string; fileName: string } | null>(null);

  /*
    Выборка читается из адреса напрямую, без `useSearchParams`: этот хук
    заставляет ближайшую границу Suspense ждать, и на этом проекте ожидание не
    заканчивалось никогда — дерево отрисовывалось в скрытом контейнере,
    эффекты не запускались, запросы не уходили. Подробности — в `MapScreen`.
  */
  const [spec, setSpec] = useState<QuerySpec>(DEFAULT_QUERY_SPEC);

  useEffect(() => {
    const apply = () => setSpec(fromSearchParams(new URLSearchParams(window.location.search)));
    apply();
    window.addEventListener("popstate", apply);
    return () => window.removeEventListener("popstate", apply);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const token = readToken();

    Promise.all([
      fetchReportTemplates(token, controller.signal),
      fetchReportFormats(token, controller.signal),
    ])
      .then(([templateList, formatList]) => {
        if (controller.signal.aborted) return;
        setTemplates(templateList);
        setFormats(formatList);
        /*
          Умолчание выбирается среди доступных, а не берётся первым из списка:
          иначе при отключённом PDF предвыбранной оказалась бы кнопка, которая
          заведомо не сработает.
        */
        const firstAvailable = formatList.find((item) => item.available);
        if (firstAvailable) setFormat(firstAvailable.code);
        setError(null);
        setPhase("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(explain(cause));
        setPhase("error");
      });

    return () => controller.abort();
  }, [attempt]);

  const chosenFormat = formats.find((item) => item.code === format) ?? null;
  const canGenerate = chosenFormat?.available === true;

  const run = useCallback(
    async (template: ReportTemplateInfo) => {
      setBusy(template.code);
      setFailure(null);
      setDone(null);
      try {
        const file = await generateReport(
          template.code,
          format,
          spec,
          readToken(),
          undefined,
          fallbackFileName(template.title, template.code, format),
        );
        saveFile(file);
        setDone({ template: template.code, fileName: file.fileName });
      } catch (cause) {
        setFailure({ template: template.code, message: explain(cause) });
      } finally {
        setBusy(null);
      }
    },
    [format, spec],
  );

  const chips = activeFilterChips(spec);

  return (
    <>
      <PageHeader
        title="Отчёты и экспорт"
        subtitle="Формирование аналитических справок и выгрузка данных"
      />

      {phase === "error" ? (
        <div
          role="alert"
          className="rounded-panel border border-border-strong bg-surface-muted p-6 text-center"
        >
          <p className="text-sm font-medium text-text">Каталог отчётов не загрузился</p>
          <p className="mt-1 text-sm text-text-muted">{error}</p>
          <p className="mt-1 text-xs text-text-subtle">
            Это сбой связи с сервером, а не отсутствие шаблонов: их состав задан ТЗ.
          </p>
          <button
            type="button"
            onClick={() => {
              setPhase("loading");
              setAttempt((value) => value + 1);
            }}
            className="mt-3 rounded border border-border-base bg-surface px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
          >
            Повторить
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          {phase === "loading" ? (
            /* Пока форматы не получены, выбор не показывается вовсе: показать
               три кнопки и потом погасить PDF значило бы соврать дважды. */
            <div className="h-24 animate-pulse rounded-panel bg-surface-hover" />
          ) : (
            <FormatChoice formats={formats} value={format} onChange={setFormat} />
          )}

          {/*
            Какая именно выборка уйдёт в отчёт — сказано прямо. Отчёт по
            отфильтрованным данным, выданный за полный, — худший из возможных
            исходов этого экрана.
          */}
          <p className="text-xs text-text-subtle">
            {hasActiveFilters(spec)
              ? `Отчёт будет построен по текущей выборке: ${chips
                  .map((chip) => `${chip.label} — ${chip.value}`)
                  .join("; ")}.`
              : "Фильтры не заданы — отчёт будет построен по всем доступным вам данным."}
          </p>

          {phase === "ready" && templates.length === 0 ? (
            <div className="rounded-panel border border-dashed border-border-strong bg-surface-muted px-6 py-12 text-center">
              <FileText className="mx-auto size-8 text-text-subtle" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium text-text">Сервер не вернул ни одного шаблона</p>
              <p className="mt-1 text-sm text-text-muted">
                Это не пустой раздел, а пустой ответ каталога — обратитесь к администратору.
              </p>
            </div>
          ) : (
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {phase === "loading"
                ? Array.from({ length: 8 }, (_, index) => (
                    <li key={`skeleton-${index}`}>
                      <TemplateSkeleton />
                    </li>
                  ))
                : templates.map((template) => {
                    const Icon = TEMPLATE_ICONS[template.code] ?? FileText;
                    const running = busy === template.code;
                    const templateFailure =
                      failure?.template === template.code ? failure.message : null;
                    const templateDone = done?.template === template.code ? done.fileName : null;

                    return (
                      <li key={template.code}>
                        <div className="flex h-full flex-col rounded-card border border-border-base bg-surface p-4 shadow-card">
                          <Icon className="size-8 text-accent" aria-hidden="true" />
                          <h2 className="mt-3 text-sm font-semibold text-text">{template.title}</h2>
                          <p className="mt-1 flex-1 text-xs text-text-muted">
                            {template.description}
                          </p>

                          <button
                            type="button"
                            onClick={() => void run(template)}
                            disabled={running || busy !== null || !canGenerate}
                            className="mt-4 flex items-center justify-center gap-1.5 rounded border border-border-base bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {running ? (
                              <>
                                <Loader2
                                  className="size-4 animate-spin"
                                  aria-hidden="true"
                                />
                                Формирую…
                              </>
                            ) : (
                              <>
                                <Download className="size-4" aria-hidden="true" />
                                Сформировать
                              </>
                            )}
                          </button>

                          {!canGenerate && (
                            <p className="mt-2 text-xs text-text-subtle">
                              Выберите доступный формат выгрузки.
                            </p>
                          )}

                          {templateFailure && (
                            <p role="alert" className="mt-2 text-xs text-risk-critical-text">
                              {templateFailure}
                            </p>
                          )}

                          {templateDone && (
                            <p role="status" className="mt-2 text-xs text-text-muted">
                              Файл сохранён: {templateDone}
                            </p>
                          )}
                        </div>
                      </li>
                    );
                  })}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
