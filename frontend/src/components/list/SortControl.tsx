"use client";

import { ArrowDown, ArrowUp } from "lucide-react";

import {
  SORT_FIELDS,
  SORT_FIELD_LABELS,
  type SortField,
  type SortOrder,
} from "@/lib/query-spec";

/**
 * Что означает «по возрастанию» для каждого поля.
 *
 * Без этих подписей направление читается как загадка: «по риску, по возрастанию»
 * не говорит, где окажутся критические объекты. Формулировка описывает результат,
 * а не механику сортировки.
 */
const ORDER_LABELS: Record<SortField, Record<SortOrder, string>> = {
  risk: { desc: "сначала опасные", asc: "сначала спокойные" },
  amount: { desc: "сначала крупные", asc: "сначала мелкие" },
  relevance: { desc: "сначала свежие", asc: "сначала давние" },
  name: { desc: "от Я до А", asc: "от А до Я" },
};

interface SortControlProps {
  sort: SortField;
  order: SortOrder;
  onChange: (sort: SortField, order: SortOrder) => void;
  className?: string;
}

/**
 * Сортировка списка.
 *
 * Поле и направление разведены на два контрола: смена поля не должна менять
 * направление, а нажатие на направление не должно перебирать поля. Направление
 * по умолчанию задаётся полем — «по риску» осмысленно начинать с опасных,
 * «по названию» с начала алфавита.
 */
export function SortControl({ sort, order, onChange, className = "" }: SortControlProps) {
  const naturalOrder = (field: SortField): SortOrder => (field === "name" ? "asc" : "desc");

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <label htmlFor="sort-field" className="text-xs text-text-muted">
        Сортировка
      </label>

      <select
        id="sort-field"
        value={sort}
        onChange={(event) => {
          const field = event.target.value as SortField;
          onChange(field, naturalOrder(field));
        }}
        className="rounded-md border border-border-base bg-surface px-2 py-1.5 text-sm text-text"
      >
        {SORT_FIELDS.map((field) => (
          <option key={field} value={field}>
            {SORT_FIELD_LABELS[field]}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={() => onChange(sort, order === "asc" ? "desc" : "asc")}
        /*
          Подпись называет и текущее состояние, и смысл: иконка со стрелкой без
          текста читается скринридером как ничто, а «по убыванию» без указания
          поля не объясняет, что окажется сверху.
        */
        aria-label={`Направление: ${ORDER_LABELS[sort][order]}. Изменить`}
        title={ORDER_LABELS[sort][order]}
        className="inline-flex items-center gap-1 rounded-md border border-border-base bg-surface px-2 py-1.5 text-sm text-text-muted transition-colors hover:bg-surface-hover hover:text-text"
      >
        {order === "asc" ? (
          <ArrowUp className="size-4" aria-hidden="true" />
        ) : (
          <ArrowDown className="size-4" aria-hidden="true" />
        )}
        <span aria-hidden="true">{ORDER_LABELS[sort][order]}</span>
      </button>
    </div>
  );
}
