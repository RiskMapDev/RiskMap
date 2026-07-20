"use client";

/**
 * Синхронизация выборки с адресной строкой.
 *
 * ТЗ (6.4) требует, чтобы «Списком» и «На карте» показывали ОДНУ выборку и
 * чтобы back/forward браузера её восстанавливал. Отсюда решение: состояние
 * фильтров не хранится в React вообще — единственный источник истины это URL.
 * Компонент, которому нужны фильтры, читает их этим хуком; компонент, который
 * их меняет, пишет сюда же. Разъехаться нечему.
 *
 * Побочные выгоды: ссылку можно переслать, страницу можно перезагрузить,
 * серверный рендер видит те же параметры, что и клиент.
 *
 * ВАЖНО: хук построен на `useSearchParams`, а тот при пререндере выбрасывает
 * дерево до ближайшей границы `<Suspense>` в клиентский рендер. Любой
 * компонент, который вызывает этот хук, ОБЯЗАН быть обёрнут в `<Suspense>` с
 * осмысленным fallback — иначе `next build` падает с «Missing Suspense
 * boundary with useSearchParams». В `next dev` этого не видно: там страницы
 * рендерятся по требованию, и всё выглядит рабочим. Альтернатива для заведомо
 * динамических маршрутов — `await connection()` в серверной странице.
 */

import { useCallback, useMemo, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  DEFAULT_QUERY_SPEC,
  clearFilter,
  fromSearchParams,
  toSearchParams,
  withFilters,
  type QuerySpec,
} from "@/lib/query-spec";

/**
 * Имена параметров выборки в адресной строке.
 *
 * Список не выписан руками, а получен из самой `toSearchParams`: ей скармливают
 * выборку, в которой КАЖДОЕ поле отличается от умолчания, и забирают
 * получившиеся ключи. Дублировать таблицу имён из `query-spec.ts` было бы
 * ошибкой — при добавлении фильтра её забыли бы обновить, и параметр начал бы
 * молча теряться при записи.
 */
const SPEC_PARAM_NAMES: readonly string[] = (() => {
  const probe: QuerySpec = {
    dateFrom: "0001-01-01",
    dateTo: "0001-01-02",
    year: 1,
    territoryCodes: ["--probe--"],
    includeChildTerritories: !DEFAULT_QUERY_SPEC.includeChildTerritories,
    objectTypes: ["contract"],
    layers: ["--probe--"],
    industries: ["--probe--"],
    statuses: ["--probe--"],
    amountMin: 1,
    amountMax: 2,
    riskLevels: ["low"],
    completenessMin: 0.1,
    completenessMax: 0.2,
    onlyCategoryA: !DEFAULT_QUERY_SPEC.onlyCategoryA,
    search: "--probe--",
    sort: "name",
    order: "asc",
    page: DEFAULT_QUERY_SPEC.page + 1,
    pageSize: DEFAULT_QUERY_SPEC.pageSize + 1,
  };
  return [...toSearchParams(probe).keys()];
})();

/**
 * Как записать изменение в историю браузера.
 *
 * `replace` — для непрерывных действий (ввод в поле поиска, перетаскивание
 * ползунка): каждый нажатый символ не должен становиться шагом истории, иначе
 * «назад» превращается в стирание по букве.
 *
 * `push` — для завершённых решений (нажали «Применить», сменили страницу,
 * переключили представление). Без этого требование ТЗ «back/forward
 * восстанавливает выборку» было бы невыполнимо: возвращаться станет некуда.
 */
export type HistoryMode = "replace" | "push";

export interface UseQuerySpecResult {
  /** Текущая выборка, прочитанная из адресной строки. */
  spec: QuerySpec;
  /** Строка параметров выборки — ключ для кэша данных и восстановления прокрутки. */
  specKey: string;
  /** Заменить выборку целиком. */
  setSpec: (next: QuerySpec, mode?: HistoryMode) => void;
  /** Изменить часть фильтров. Страница сбрасывается — см. `withFilters`. */
  patch: (patch: Partial<QuerySpec>, mode?: HistoryMode) => void;
  /** Снять один фильтр. */
  clear: (key: keyof QuerySpec, mode?: HistoryMode) => void;
  /** Сбросить все фильтры к умолчанию. */
  reset: (mode?: HistoryMode) => void;
  /** Перейти на страницу выборки. */
  setPage: (page: number, mode?: HistoryMode) => void;
  /** Прочитать посторонний параметр адресной строки (например, режим показа). */
  getParam: (name: string) => string | null;
  /** Записать посторонний параметр, не трогая выборку. Пустое значение удаляет. */
  setParam: (name: string, value: string | null, mode?: HistoryMode) => void;
}

export function useQuerySpec(): UseQuerySpecResult {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const raw = searchParams?.toString() ?? "";

  const spec = useMemo(() => fromSearchParams(new URLSearchParams(raw)), [raw]);
  const specKey = useMemo(() => toSearchParams(spec).toString(), [spec]);

  /*
    Запись идёт от текущей строки параметров, а не с чистого листа: в адресе
    живут и посторонние значения — режим показа, выбранный объект, метки
    рассылки. Перезаписать всё целиком значило бы стереть их при первом же
    щелчке по фильтру.
  */
  const navigate = useCallback(
    (mutate: (params: URLSearchParams) => void, mode: HistoryMode) => {
      const params = new URLSearchParams(raw);
      mutate(params);

      const query = params.toString();
      const href = query ? `${pathname}?${query}` : pathname;

      /*
        `scroll: false` обязателен. Иначе смена фильтра или страницы утаскивает
        окно к началу документа, а вместе с ним — позицию прокрутки списка,
        которую ТЗ требует сохранять.
      */
      if (mode === "push") router.push(href, { scroll: false });
      else router.replace(href, { scroll: false });
    },
    [pathname, raw, router],
  );

  const setSpec = useCallback(
    (next: QuerySpec, mode: HistoryMode = "replace") => {
      navigate((params) => {
        for (const name of SPEC_PARAM_NAMES) params.delete(name);
        for (const [name, value] of toSearchParams(next)) params.set(name, value);
      }, mode);
    },
    [navigate],
  );

  const patch = useCallback(
    (values: Partial<QuerySpec>, mode: HistoryMode = "replace") => {
      setSpec(withFilters(spec, values), mode);
    },
    [setSpec, spec],
  );

  const clear = useCallback(
    (key: keyof QuerySpec, mode: HistoryMode = "replace") => {
      setSpec(clearFilter(spec, key), mode);
    },
    [setSpec, spec],
  );

  const reset = useCallback(
    (mode: HistoryMode = "replace") => {
      setSpec({ ...DEFAULT_QUERY_SPEC }, mode);
    },
    [setSpec],
  );

  const setPage = useCallback(
    (page: number, mode: HistoryMode = "push") => {
      setSpec({ ...spec, page: Math.max(1, Math.floor(page)) }, mode);
    },
    [setSpec, spec],
  );

  const getParam = useCallback((name: string) => searchParams?.get(name) ?? null, [searchParams]);

  const setParam = useCallback(
    (name: string, value: string | null, mode: HistoryMode = "push") => {
      navigate((params) => {
        if (value === null || value === "") params.delete(name);
        else params.set(name, value);
      }, mode);
    },
    [navigate],
  );

  return { spec, specKey, setSpec, patch, clear, reset, setPage, getParam, setParam };
}

/** Префикс в sessionStorage. Отдельный, чтобы не столкнуться с чужими ключами. */
const SCROLL_PREFIX = "risk-map:scroll:";

/**
 * Сохранение и восстановление позиции прокрутки списка.
 *
 * ТЗ требует, чтобы «назад» возвращал не только выборку, но и место, где
 * пользователь остановился. Штатное восстановление браузера здесь не работает:
 * список виртуализирован, к моменту возврата в DOM нет ни строк, ни высоты.
 *
 * Поэтому позиция пишется в `sessionStorage` под ключом выборки. Именно
 * sessionStorage, а не localStorage: позиция прокрутки — состояние текущей
 * вкладки, через неделю она бессмысленна.
 *
 * Возвращается ref-функция. Смена ключа меняет её тождество, React отцепляет
 * старый элемент (позиция дописывается) и прицепляет заново (позиция
 * восстанавливается) — ровно то, что нужно при back/forward.
 */
export function useScrollRestoration(key: string) {
  const frame = useRef<number | null>(null);

  return useCallback(
    (element: HTMLElement | null) => {
      if (!element || typeof window === "undefined") return;

      const storageKey = `${SCROLL_PREFIX}${key}`;

      const read = (): number => {
        try {
          const saved = window.sessionStorage.getItem(storageKey);
          const parsed = saved === null ? Number.NaN : Number(saved);
          return Number.isFinite(parsed) ? parsed : 0;
        } catch {
          // Приватный режим запрещает хранилище. Потерять позицию не страшно,
          // уронить страницу — страшно.
          return 0;
        }
      };

      const write = (offset: number) => {
        try {
          window.sessionStorage.setItem(storageKey, String(offset));
        } catch {
          /* см. выше */
        }
      };

      const onScroll = () => {
        // Прокрутка сыплет событиями десятками в секунду; запись раз в кадр.
        if (frame.current !== null) return;
        frame.current = window.requestAnimationFrame(() => {
          frame.current = null;
          write(element.scrollTop);
        });
      };

      element.addEventListener("scroll", onScroll, { passive: true });

      /*
        Восстановление откладывается на кадр: виртуализатор к моменту
        подключения ещё не выставил высоту распорки, и присвоение scrollTop
        было бы обрезано до нуля.
      */
      const restore = window.requestAnimationFrame(() => {
        const offset = read();
        if (offset > 0) element.scrollTop = offset;
      });

      return () => {
        window.cancelAnimationFrame(restore);
        if (frame.current !== null) {
          window.cancelAnimationFrame(frame.current);
          frame.current = null;
        }
        write(element.scrollTop);
        element.removeEventListener("scroll", onScroll);
      };
    },
    [key],
  );
}
