"use client";

import { X } from "lucide-react";

import type { FilterChip, QuerySpec } from "@/lib/query-spec";

interface FilterChipsProps {
  chips: readonly FilterChip[];
  onClear: (key: keyof QuerySpec) => void;
  onReset: () => void;
  className?: string;
}

/**
 * Чипы активных фильтров.
 *
 * Нужны потому, что панель фильтров на узком экране закрыта, а на широком —
 * длиннее экрана. Без чипов пользователь видит короткий список и не понимает,
 * почему: «пусто» и «отфильтровано до пустоты» выглядят одинаково.
 *
 * Каждый чип снимается независимо — это дешевле, чем открывать панель, искать
 * нужный контрол и возвращать его в исходное положение.
 */
export function FilterChips({ chips, onClear, onReset, className = "" }: FilterChipsProps) {
  if (chips.length === 0) return null;

  return (
    <div
      className={`flex flex-wrap items-center gap-2 ${className}`}
      /*
        Список, а не набор кнопок: скринридер объявит «список, элементов 3»,
        и пользователь узнает, сколько фильтров наложено, не обходя их все.
      */
      role="list"
      aria-label="Активные фильтры"
    >
      {chips.map((chip) => (
        <span
          key={`${chip.key}:${chip.value}`}
          role="listitem"
          className="inline-flex items-center gap-1.5 rounded-full border border-border-base bg-surface py-1 pl-3 pr-1 text-xs text-text"
        >
          <span className="text-text-muted">{chip.label}:</span>
          <span className="font-medium">{chip.value}</span>
          <button
            type="button"
            onClick={() => onClear(chip.key)}
            /*
              Подпись включает и название фильтра, и его значение: список кнопок
              «Убрать» без контекста бесполезен при обходе с клавиатуры.
            */
            aria-label={`Снять фильтр «${chip.label}: ${chip.value}»`}
            className="grid size-5 place-items-center rounded-full text-text-subtle transition-colors hover:bg-surface-hover hover:text-text"
          >
            <X className="size-3.5" aria-hidden="true" />
          </button>
        </span>
      ))}

      <button
        type="button"
        onClick={onReset}
        className="rounded-full px-2 py-1 text-xs font-medium text-accent underline-offset-2 hover:underline"
      >
        Сбросить всё
      </button>
    </div>
  );
}
