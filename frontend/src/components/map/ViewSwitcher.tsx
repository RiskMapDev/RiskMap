"use client";

import { Columns2, List, Map } from "lucide-react";

import { useMediaQuery } from "@/lib/hooks/useMediaQuery";

/**
 * Режим показа выборки.
 *
 * Это НЕ часть `QuerySpec`: способ смотреть на данные не меняет сами данные.
 * Смешать их значило бы отправлять на сервер параметр, который серверу не нужен,
 * и пересчитывать выборку при переключении вкладки.
 */
export const VIEW_MODES = ["list", "map", "split"] as const;
export type ViewMode = (typeof VIEW_MODES)[number];

/** Имя параметра в адресной строке. Режим живёт там же, где выборка — ссылка воспроизводит экран целиком. */
export const VIEW_MODE_PARAM = "view";

export const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  list: "Списком",
  map: "На карте",
  split: "Карта + список",
};

const VIEW_MODE_ICONS = { list: List, map: Map, split: Columns2 } as const;

/**
 * Разобрать режим из адресной строки.
 *
 * Умолчание — список. По ТЗ на мобильном список основной режим, а карта на
 * узком экране бесполезна; к тому же список отрисуется и без данных геометрии.
 */
export function parseViewMode(raw: string | null | undefined): ViewMode {
  return VIEW_MODES.includes(raw as ViewMode) ? (raw as ViewMode) : "list";
}

interface ViewSwitcherProps {
  value: ViewMode;
  onChange: (mode: ViewMode) => void;
  /**
   * Показывать вариант «Карта + список».
   * На узких экранах он скрыт средствами CSS: две колонки там не помещаются.
   * `display: none` заодно убирает кнопку из порядка обхода с клавиатуры.
   */
  allowSplit?: boolean;
  className?: string;
}

/**
 * Переключатель представления.
 *
 * Реализован как группа радиокнопок, а не как набор самостоятельных кнопок:
 * варианты взаимоисключающие, и скринридер должен объявлять «2 из 3», а не
 * читать три несвязанные кнопки. Отсюда же перемещение стрелками и роверный
 * tabindex — по шаблону radiogroup из WAI-ARIA.
 */
export function ViewSwitcher({
  value,
  onChange,
  allowSplit = true,
  className = "",
}: ViewSwitcherProps) {
  /*
    Сдвоенный режим убирается из набора на узких экранах, а не прячется
    правилом CSS. Раньше он прятался классом `hidden lg:inline-flex`, но
    `hidden` и `inline-flex` — обе утилиты `display`, и в собранном CSS
    побеждала вторая: кнопка оставалась видимой и фокусируемой на телефоне.

    Убирая режим из набора, мы заодно чиним обход стрелками: на узком экране
    в него нельзя попасть с клавиатуры, и выбрать раскладку, которая всё
    равно не поместится, невозможно.
  */
  const wideEnough = useMediaQuery("(min-width: 64rem)", true);
  const modes: ViewMode[] =
    allowSplit && wideEnough ? [...VIEW_MODES] : ["list", "map"];

  const move = (delta: number) => {
    const current = modes.indexOf(value);
    // По кругу: с последнего вправо — на первый. Так шаблон radiogroup и работает.
    const next = modes[(current + delta + modes.length) % modes.length];
    if (next) onChange(next);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="Представление выборки"
      onKeyDown={onKeyDown}
      className={`inline-flex items-center gap-0.5 rounded-lg border border-border-base bg-surface-muted p-0.5 ${className}`}
    >
      {modes.map((mode) => {
        const Icon = VIEW_MODE_ICONS[mode];
        const active = mode === value;

        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={active}
            /* Роверный tabindex: в группу входят одним Tab, дальше — стрелками. */
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(mode)}
            className={[
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-accent text-accent-fg"
                : "text-text-muted hover:bg-surface-hover hover:text-text",
            ].join(" ")}
          >
            <Icon className="size-4" aria-hidden="true" />
            {VIEW_MODE_LABELS[mode]}
          </button>
        );
      })}
    </div>
  );
}
