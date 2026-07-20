"use client";

import { useMemo, useState } from "react";
import { X } from "lucide-react";

import type { FilterOptions } from "@/lib/api/types";
import { DEFAULT_QUERY_SPEC, toSearchParams, type QuerySpec } from "@/lib/query-spec";
import { RISK_LEVELS_DISPLAY_ORDER, riskMeta, type RiskLevel } from "@/lib/risk";

/**
 * Цветная точка уровня. Дублирует, но не заменяет подпись и значок:
 * подписи «высокого» и «критического» по палитре ТЗ различаются слишком слабо,
 * чтобы цвет нёс смысл в одиночку (см. комментарий в `lib/risk.ts`).
 */
const RISK_DOT_CLASSES: Record<RiskLevel, string> = {
  low: "bg-risk-low",
  medium: "bg-risk-medium",
  high: "bg-risk-high",
  critical: "bg-risk-critical",
  unknown: "bg-risk-none",
};

interface FilterPanelProps {
  /** Применённая выборка. Панель правит свою копию и отдаёт её по «Применить». */
  spec: QuerySpec;
  /** Справочники с сервера. Пока их нет, соответствующие блоки показываются пустыми. */
  options?: FilterOptions;
  onApply: (next: QuerySpec) => void;
  onReset: () => void;
  /** Сравнение периодов. Без обработчика кнопка показывается недоступной, а не прячется. */
  onComparePeriods?: (spec: QuerySpec) => void;
  /** Закрыть выдвижную панель. На мобильном обязателен. */
  onClose?: () => void;
  className?: string;
}

/** Подпись выборки: меняется ровно тогда, когда меняется сама выборка. */
function signature(spec: QuerySpec): string {
  return toSearchParams(spec).toString();
}

/**
 * Левая панель фильтров.
 *
 * Правки копятся в черновике и уходят наружу только по «Применить». Причина в
 * пагинации: выборка серверная, и применение каждого щелчка по чекбоксу
 * означало бы запрос на каждый щелчок. Пользователь, выставляющий четыре
 * уровня риска, вызвал бы четыре перезагрузки списка и увидел бы три
 * промежуточных состояния, которые ему не нужны.
 *
 * Черновик пересобирается, когда выборка изменилась снаружи (кнопка «назад»,
 * снятие чипа, ссылка от коллеги) — иначе панель показывала бы одно, а список
 * другое.
 */
export function FilterPanel({
  spec,
  options,
  onApply,
  onReset,
  onComparePeriods,
  onClose,
  className = "",
}: FilterPanelProps) {
  const [draft, setDraft] = useState<QuerySpec>(spec);
  const appliedSignature = signature(spec);

  /*
    Пересборка черновика при внешней смене выборки — прямо в рендере, а не в
    эффекте. Эффект сработал бы после отрисовки, и кадр показывал бы старые
    значения фильтров рядом с новым списком.

    Сравнение по подписи, а не по ссылке: `spec` приходит новым объектом на
    каждый рендер, и сравнение по ссылке затирало бы черновик постоянно.
  */
  const [seenSignature, setSeenSignature] = useState(appliedSignature);
  if (seenSignature !== appliedSignature) {
    setSeenSignature(appliedSignature);
    setDraft(spec);
  }

  const dirty = useMemo(() => signature(draft) !== appliedSignature, [draft, appliedSignature]);

  const years = options?.years ?? [];

  const update = (patch: Partial<QuerySpec>) => setDraft((prev) => ({ ...prev, ...patch }));

  /*
    Год и пара дат — два способа задать одно и то же. Держать их одновременно
    нельзя: чипы показывают только год, и заданный диапазон дат стал бы
    невидимым фильтром. Поэтому выбор одного гасит другое.
  */
  const selectYear = (year: number) =>
    update({ year: draft.year === year ? null : year, dateFrom: null, dateTo: null });

  const setDate = (field: "dateFrom" | "dateTo", value: string) =>
    update({ [field]: value || null, year: null } as Partial<QuerySpec>);

  const toggleRiskLevel = (level: RiskLevel) => {
    const next = draft.riskLevels.includes(level)
      ? draft.riskLevels.filter((item) => item !== level)
      : [...draft.riskLevels, level];

    /*
      Снять последний уровень нельзя: выборка стала бы заведомо пустой, а
      пользователь увидел бы «ничего не найдено» и не понял бы, что сам это
      устроил. `fromSearchParams` трактует пустой список так же.
    */
    update({ riskLevels: next.length > 0 ? next : [...DEFAULT_QUERY_SPEC.riskLevels] });
  };

  const setAmount = (field: "amountMin" | "amountMax", value: string) => {
    const parsed = value.trim() === "" ? null : Number(value);
    update({ [field]: parsed !== null && Number.isFinite(parsed) ? parsed : null });
  };

  /** Одиночный выбор из справочника: пустое значение — «все». */
  const setSingle = (field: "territoryCodes" | "industries" | "statuses", value: string) =>
    update({ [field]: value ? [value] : [] } as Partial<QuerySpec>);

  return (
    <form
      className={`flex h-full flex-col bg-surface ${className}`}
      aria-label="Фильтры выборки"
      onSubmit={(event) => {
        event.preventDefault();
        onApply(draft);
      }}
    >
      <div className="flex items-center justify-between border-b border-border-base px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-text">ФИЛЬТРЫ</h2>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть панель фильтров"
            className="grid size-8 place-items-center rounded-md text-text-muted hover:bg-surface-hover hover:text-text"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-4">
        {/* ПЕРИОД */}
        <fieldset>
          <legend className="mb-2 text-xs font-semibold tracking-wide text-text-muted">
            ПЕРИОД
          </legend>

          {years.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {years.map((year) => {
                const active = draft.year === year;
                return (
                  <button
                    key={year}
                    type="button"
                    aria-pressed={active}
                    onClick={() => selectYear(year)}
                    className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                      active
                        ? "border-accent bg-accent text-accent-fg"
                        : "border-border-base bg-surface text-text-muted hover:bg-surface-hover hover:text-text"
                    }`}
                  >
                    {year}
                  </button>
                );
              })}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <label className="block text-xs text-text-muted">
              с
              <input
                type="date"
                value={draft.dateFrom ?? ""}
                onChange={(event) => setDate("dateFrom", event.target.value)}
                className="mt-1 w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
              />
            </label>
            <label className="block text-xs text-text-muted">
              по
              <input
                type="date"
                value={draft.dateTo ?? ""}
                onChange={(event) => setDate("dateTo", event.target.value)}
                className="mt-1 w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
              />
            </label>
          </div>

          <button
            type="button"
            disabled={!onComparePeriods}
            onClick={() => onComparePeriods?.(draft)}
            title={
              onComparePeriods
                ? undefined
                : "Сравнение периодов станет доступно после подключения API"
            }
            className="mt-2 w-full rounded-md border border-border-base px-3 py-1.5 text-sm text-text-muted transition-colors hover:bg-surface-hover hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          >
            Сравнить периоды
          </button>
        </fieldset>

        {/* ТЕРРИТОРИЯ */}
        <div>
          <label
            htmlFor="filter-territory"
            className="mb-2 block text-xs font-semibold tracking-wide text-text-muted"
          >
            ТЕРРИТОРИЯ
          </label>
          <select
            id="filter-territory"
            value={draft.territoryCodes[0] ?? ""}
            onChange={(event) => setSingle("territoryCodes", event.target.value)}
            className="w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
          >
            <option value="">Все районы</option>
            {(options?.territories ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="mt-2 flex items-center gap-2 text-sm text-text-muted">
            <input
              type="checkbox"
              checked={draft.includeChildTerritories}
              onChange={(event) => update({ includeChildTerritories: event.target.checked })}
              className="size-4 accent-[var(--accent)]"
            />
            {/* Выбор области без районов дал бы пустую выборку — отсюда умолчание «включать». */}
            Включая подчинённые территории
          </label>
        </div>

        {/* ОТРАСЛЬ */}
        <div>
          <label
            htmlFor="filter-industry"
            className="mb-2 block text-xs font-semibold tracking-wide text-text-muted"
          >
            ОТРАСЛЬ
          </label>
          <select
            id="filter-industry"
            value={draft.industries[0] ?? ""}
            onChange={(event) => setSingle("industries", event.target.value)}
            className="w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
          >
            <option value="">Все отрасли</option>
            {(options?.industries ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* УРОВЕНЬ РИСКА */}
        <fieldset>
          <legend className="mb-2 text-xs font-semibold tracking-wide text-text-muted">
            УРОВЕНЬ РИСКА
          </legend>
          <div className="space-y-1.5">
            {RISK_LEVELS_DISPLAY_ORDER.map((level) => {
              const meta = riskMeta(level);
              return (
                <label
                  key={level}
                  className="flex items-center gap-2 text-sm text-text"
                  title={meta.description}
                >
                  <input
                    type="checkbox"
                    checked={draft.riskLevels.includes(level)}
                    onChange={() => toggleRiskLevel(level)}
                    className="size-4 accent-[var(--accent)]"
                  />
                  <span
                    aria-hidden="true"
                    className={`size-2.5 shrink-0 rounded-full ${RISK_DOT_CLASSES[level]}`}
                  />
                  <span aria-hidden="true" className="text-xs text-text-muted">
                    {meta.glyph}
                  </span>
                  {meta.label}
                </label>
              );
            })}
          </div>
          {/*
            «Нет данных» стоит в общем ряду намеренно: по ТЗ это полноправный
            уровень, а не служебное состояние. Вынести его в «дополнительно»
            значило бы спрятать неизмеренные объекты от того, кто туда не залезет.
          */}
        </fieldset>

        {/* СУММА */}
        <fieldset>
          <legend className="mb-2 text-xs font-semibold tracking-wide text-text-muted">
            СУММА, ₸
          </legend>
          {/*
            Единица — тенге, а не миллиарды, как на референсе: пересчёт на
            клиенте разошёлся бы с серверным полем и незаметно округлял бы
            границы диапазона.
          */}
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-xs text-text-muted">
              от
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={draft.amountMin ?? ""}
                onChange={(event) => setAmount("amountMin", event.target.value)}
                className="mt-1 w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
              />
            </label>
            <label className="block text-xs text-text-muted">
              до
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={draft.amountMax ?? ""}
                onChange={(event) => setAmount("amountMax", event.target.value)}
                className="mt-1 w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
              />
            </label>
          </div>
        </fieldset>

        {/* СТАТУС ОБЪЕКТА */}
        <div>
          <label
            htmlFor="filter-status"
            className="mb-2 block text-xs font-semibold tracking-wide text-text-muted"
          >
            СТАТУС ОБЪЕКТА
          </label>
          <select
            id="filter-status"
            value={draft.statuses[0] ?? ""}
            onChange={(event) => setSingle("statuses", event.target.value)}
            className="w-full rounded-md border border-border-base bg-surface-muted px-2 py-1.5 text-sm text-text"
          >
            <option value="">Все статусы</option>
            {(options?.statuses ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/*
        Кнопки закреплены внизу: панель длиннее экрана, и «Применить» не должна
        уезжать за нижнюю границу — иначе выставленные фильтры некуда применить.
      */}
      <div className="shrink-0 border-t border-border-base bg-surface px-4 py-3">
        <p aria-live="polite" className="mb-2 min-h-4 text-xs text-text-muted">
          {dirty ? "Есть непринятые изменения" : ""}
        </p>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onReset}
            className="flex-1 rounded-md border border-border-base px-3 py-2 text-sm font-medium text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
          >
            Сбросить
          </button>
          <button
            type="submit"
            className="flex-1 rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover"
          >
            Применить
          </button>
        </div>
      </div>
    </form>
  );
}
