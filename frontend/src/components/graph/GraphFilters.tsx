"use client";

import type { GraphLegend, GraphViewState, RelationTypeCode } from "@/lib/api/graph";
import { RELATION_COLOR } from "@/lib/graph-style";

interface GraphFiltersProps {
  legend: GraphLegend | null;
  value: GraphViewState;
  onChange: (next: GraphViewState) => void;
  onReset: () => void;
}

/**
 * Левая панель: типы связей, достоверность и пределы выборки.
 *
 * Пределы выборки — глубина и число узлов — стоят рядом с фильтрами, а не
 * спрятаны в настройках, потому что это не техническая деталь, а прямое
 * условие того, что пользователь увидит. Человек, не знающий, что показаны
 * 60 узлов из трёх тысяч, делает неверный вывод о разреженности связей.
 *
 * Пустой набор типов означает «все типы», и об этом сказано подписью. Иначе
 * пользователь, снявший все галки, ожидал бы пустой граф, а получил бы полный.
 */
export function GraphFilters({ legend, value, onChange, onReset }: GraphFiltersProps) {
  function toggleRelation(code: RelationTypeCode) {
    const next = value.relationTypes.includes(code)
      ? value.relationTypes.filter((item) => item !== code)
      : [...value.relationTypes, code];
    onChange({ ...value, relationTypes: next });
  }

  return (
    <div className="flex flex-col gap-5 rounded-panel border border-border-base bg-surface p-4 shadow-card">
      <fieldset>
        <legend className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Типы связей
        </legend>
        <p className="mt-1 text-xs text-text-subtle">
          Ни одной отметки — показываются все типы.
        </p>
        <div className="mt-2 space-y-1.5">
          {(legend?.relation_types ?? []).map((item) => (
            <label
              key={item.code}
              className="flex cursor-pointer items-center gap-2 text-sm text-text"
            >
              <input
                type="checkbox"
                checked={value.relationTypes.includes(item.code)}
                onChange={() => toggleRelation(item.code)}
                className="size-4 accent-accent"
              />
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: RELATION_COLOR[item.code] }}
              />
              <span>{item.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Достоверность
        </legend>
        <label className="mt-2 flex cursor-pointer items-start gap-2 text-sm text-text">
          <input
            type="checkbox"
            checked={value.confirmedOnly}
            onChange={(event) => onChange({ ...value, confirmedOnly: event.target.checked })}
            className="mt-0.5 size-4 accent-accent"
          />
          <span>
            Только достоверные
            <span className="mt-0.5 block text-xs text-text-subtle">
              Предположительные связи выведены из совпадения наименования или
              адреса и требуют проверки. На канве они пунктирные.
            </span>
          </span>
        </label>
      </fieldset>

      <fieldset>
        <legend className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Пределы выборки
        </legend>
        <div className="mt-2 space-y-3">
          <label className="block text-sm text-text">
            Глубина связей
            <select
              value={value.depth}
              onChange={(event) =>
                onChange({ ...value, depth: Number.parseInt(event.target.value, 10) })
              }
              className="mt-1 w-full rounded border border-border-base bg-surface px-2 py-1.5 text-sm"
            >
              <option value={1}>1 шаг — прямые связи</option>
              <option value={2}>2 шага — связи связанных</option>
            </select>
          </label>

          <label className="block text-sm text-text">
            Не более узлов: <span className="font-mono tabular-nums">{value.maxNodes}</span>
            <input
              type="range"
              min={10}
              max={legend?.limits.max_nodes ?? 200}
              step={10}
              value={value.maxNodes}
              onChange={(event) =>
                onChange({ ...value, maxNodes: Number.parseInt(event.target.value, 10) })
              }
              className="mt-1 w-full accent-accent"
            />
          </label>

          <p className="text-xs text-text-subtle">
            Граф не отдаётся целиком: сервер возвращает окружение выбранного
            узла в этих пределах. Что не поместилось — сказано под канвой.
          </p>
        </div>
      </fieldset>

      <button
        type="button"
        onClick={onReset}
        className="rounded border border-border-base px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
      >
        Сбросить фильтры
      </button>
    </div>
  );
}
