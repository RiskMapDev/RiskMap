"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, Share2 } from "lucide-react";

import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { GraphFilters } from "@/components/graph/GraphFilters";
import { GraphNodeList } from "@/components/graph/GraphNodeList";
import { PageHeader } from "@/components/layout/PageHeader";
import { RiskBadge } from "@/components/risk/RiskBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { readToken } from "@/lib/api/auth";
import {
  DEFAULT_VIEW_STATE,
  fetchGraphLegend,
  fetchGraphNode,
  fetchNeighbors,
  searchGraphNodes,
  type GraphLegend,
  type GraphNodePayload,
  type RelationBreakdownRow,
  type SubgraphPayload,
} from "@/lib/api/graph";
import { useGraphView } from "@/lib/hooks/useGraphView";

/** Пояснение к ошибке: 401 — не сбой, а отсутствие или истечение сессии. */
function explain(cause: unknown, fallback: string): string {
  const message = cause instanceof Error ? cause.message : fallback;
  return message.includes("401")
    ? "Сессия не начата или истекла — войдите в систему заново."
    : message;
}

/** Результат запроса окружения вместе с узлом, для которого он получен. */
interface NeighborhoodResult {
  node: string;
  data: SubgraphPayload | null;
  breakdown: RelationBreakdownRow[];
  card: GraphNodePayload | null;
  error: string | null;
}

/** Результат поиска вместе со строкой запроса, которой он соответствует. */
interface SearchResult {
  query: string;
  items: GraphNodePayload[];
}

/**
 * Экран графа взаимосвязей.
 *
 * **Состояние выборки живёт в адресе** — см. `useGraphView`, где объяснено,
 * почему это не `useSearchParams`.
 *
 * **Загрузка и ошибка выводятся, а не хранятся отдельным состоянием.** Ответ
 * запоминается вместе с ключом узла, для которого он получен, и «идёт
 * загрузка» — это просто «ответ ещё не про тот узел, который выбран сейчас».
 * Отдельные флаги `loading`/`error` пришлось бы взводить синхронно в эффекте,
 * что порождает каскад перерисовок; хуже того, при быстрой смене узлов они
 * рассинхронизировались бы с данными, и экран показал бы окружение одного
 * субъекта под заголовком другого.
 *
 * **Граф не показывается по умолчанию.** Показать «что-нибудь» при входе
 * значило бы либо отдать весь граф (запрещено ТЗ 20), либо выбрать узел
 * произвольно и выдать случайность за результат. Пользователь называет
 * субъект сам.
 *
 * **Раскрытие соседа — запрос к серверу, а не разворот кэша.** У соседа могут
 * быть связи, которых нет в текущем подграфе именно потому, что он усечён.
 */
export function GraphScreen() {
  const [token] = useState<string | null>(() => readToken());
  const [view, navigate] = useGraphView();

  const [legend, setLegend] = useState<GraphLegend | null>(null);
  const [result, setResult] = useState<NeighborhoodResult | null>(null);
  const [selected, setSelected] = useState<GraphNodePayload | null>(null);

  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null);

  // Всё ниже выведено из ответа, а не хранится: расхождение состояний
  // невозможно по построению.
  const fresh = result !== null && result.node === view.node;
  const subgraph = fresh ? result.data : null;
  const breakdown = fresh ? result.breakdown : [];
  const error = fresh ? result.error : null;
  const loading = view.node !== null && !fresh;

  const trimmedQuery = query.trim();
  const candidates =
    searchResult && searchResult.query === trimmedQuery && trimmedQuery.length >= 2
      ? searchResult.items
      : [];

  useEffect(() => {
    const controller = new AbortController();
    fetchGraphLegend(token, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setLegend(payload);
      })
      .catch(() => {
        // Легенда — вспомогательный запрос. Её падение не должно вытеснять с
        // экрана сам граф: панель фильтров просто останется без списка типов.
      });
    return () => controller.abort();
  }, [token]);

  /*
    Подграф перезапрашивается при любом изменении выборки: фильтры применяет
    сервер, а не клиент. Фильтрация на клиенте означала бы, что скрытые
    сервером связи всё-таки доехали до браузера, — а весь смысл серверной
    выборки в том, чтобы они туда не попадали.
  */
  useEffect(() => {
    const node = view.node;
    if (!node) return;

    const controller = new AbortController();

    Promise.all([
      fetchNeighbors(
        {
          node,
          depth: view.depth,
          maxNodes: view.maxNodes,
          relationTypes: view.relationTypes,
          confirmedOnly: view.confirmedOnly,
        },
        token,
        controller.signal,
      ),
      fetchGraphNode(node, token, controller.signal),
    ])
      .then(([neighbors, card]) => {
        if (controller.signal.aborted) return;
        setResult({
          node,
          data: neighbors,
          breakdown: card.relations,
          card: card.node,
          error: null,
        });
        setSelected(card.node);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setResult({
          node,
          data: null,
          breakdown: [],
          card: null,
          error: explain(cause, "граф не загрузился"),
        });
      });

    return () => controller.abort();
  }, [token, view]);

  /*
    Поиск с задержкой: запрос на каждое нажатие клавиши создаёт нагрузку,
    которой норматив ТЗ «поиск ≤ 3 с» не переживёт.
  */
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (trimmedQuery.length < 2) return;

    const controller = new AbortController();
    timerRef.current = setTimeout(() => {
      searchGraphNodes(trimmedQuery, token, controller.signal)
        .then((payload) => {
          if (!controller.signal.aborted) {
            setSearchResult({ query: trimmedQuery, items: payload.items });
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) setSearchResult({ query: trimmedQuery, items: [] });
        });
    }, 300);

    return () => {
      controller.abort();
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [trimmedQuery, token]);

  const openNode = useCallback(
    (node: GraphNodePayload) => {
      setQuery("");
      navigate({ ...view, node: node.key });
    },
    [navigate, view],
  );

  const centerCard = useMemo(() => (fresh ? result.card : null), [fresh, result]);
  const shownCard = selected ?? centerCard;

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Главная" }, { label: "Граф связей" }]}
        title="Граф связей"
        subtitle="Организации, физические лица, договоры, субсидии и проекты"
      />

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-panel border border-risk-high-border bg-risk-high-bg p-4"
        >
          <p className="text-sm font-medium text-risk-high-text">Граф не загрузился</p>
          <p className="mt-1 text-sm text-text-muted">{error}</p>
          <p className="mt-1 text-xs text-text-subtle">
            Это сбой связи с сервером или отсутствие доступа, а не отсутствие связей.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
        <GraphFilters
          legend={legend}
          value={view}
          onChange={navigate}
          onReset={() => navigate({ ...DEFAULT_VIEW_STATE, node: view.node })}
        />

        <div className="flex min-h-[32rem] flex-col gap-3">
          <label className="relative block">
            <span className="sr-only">Поиск узла по наименованию или ФИО</span>
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-subtle"
            />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Организация, ФИО, договор, программа…"
              className="w-full rounded border border-border-base bg-surface py-2 pl-9 pr-3 text-sm text-text"
            />
          </label>

          {candidates.length > 0 && (
            <ul
              aria-label="Найденные узлы"
              className="max-h-56 divide-y divide-border-base overflow-y-auto rounded-panel border border-border-base bg-surface shadow-card"
            >
              {candidates.map((node) => (
                <li key={node.key}>
                  <button
                    type="button"
                    onClick={() => openNode(node)}
                    className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-surface-hover"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-text">{node.label}</span>
                      <span className="text-xs text-text-muted">
                        {node.node_type_label} · связей: {node.degree}
                      </span>
                    </span>
                    <RiskBadge level={node.risk_level} size="sm" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="min-h-[28rem] flex-1">
            {loading && (
              <div
                role="status"
                aria-label="Граф загружается"
                className="h-full animate-pulse rounded-panel bg-surface-hover"
              />
            )}

            {!view.node && (
              <EmptyState
                icon={Share2}
                title="Выберите узел, чтобы построить окружение"
                description={
                  "Граф не отдаётся целиком: сервер возвращает окружение одного " +
                  "субъекта с ограничением глубины и числа узлов. Найдите " +
                  "организацию, лицо, договор или программу в строке поиска выше."
                }
              />
            )}

            {subgraph && (
              <GraphCanvas
                subgraph={subgraph}
                onSelect={setSelected}
                onExpand={(node) => navigate({ ...view, node: node.key })}
              />
            )}
          </div>

          {subgraph && (
            <p className="text-xs text-text-subtle">
              {subgraph.scope_note} Показано узлов: {subgraph.nodes.length}, связей:{" "}
              {subgraph.edges.length}.
              {subgraph.truncated && (
                <span className="text-risk-medium-text">
                  {" "}
                  Выборка усечена: скрыто узлов {subgraph.omitted_nodes}, всего связей у
                  центра {subgraph.total_neighbors}.
                </span>
              )}
            </p>
          )}
        </div>

        <div className="space-y-4">
          {shownCard && (
            <section
              aria-label="Карточка узла"
              className="rounded-panel border border-border-base bg-surface p-4 shadow-card"
            >
              <p className="text-xs uppercase tracking-wide text-text-muted">
                {shownCard.node_type_label}
              </p>
              <h2 className="mt-1 text-sm font-semibold text-text">{shownCard.label}</h2>
              {shownCard.sublabel && (
                <p className="mt-0.5 text-xs text-text-muted">{shownCard.sublabel}</p>
              )}

              <div className="mt-2">
                <RiskBadge
                  level={shownCard.risk_level}
                  score={shownCard.risk_score}
                  preliminary={shownCard.risk_is_preliminary}
                  size="sm"
                />
              </div>

              {/*
                Идентификатор различает три состояния, и все три должны быть
                видны: значения нет в данных, значение скрыто по роли,
                значение показано (полностью или маской). Иначе пользователь
                считает данные неполными и заводит обращения о пропаже.
              */}
              {shownCard.identifier && (
                <p className="mt-2 text-xs text-text-muted">
                  {shownCard.identifier_kind === "iin" ? "ИИН" : "БИН"}:{" "}
                  {shownCard.identifier.value ? (
                    <span className="font-mono">{shownCard.identifier.value}</span>
                  ) : (
                    <span className="text-text-subtle">
                      {shownCard.identifier.present
                        ? "скрыт — недостаточно прав"
                        : "нет в данных"}
                    </span>
                  )}
                </p>
              )}

              <p className="mt-2 text-xs text-text-subtle">
                Источник: слой {shownCard.source_layer}. Всего связей: {shownCard.degree}.
              </p>

              {breakdown.length > 0 && shownCard.key === view.node && (
                <ul className="mt-3 space-y-1">
                  {breakdown.map((row) => (
                    <li key={row.relation_type} className="flex justify-between gap-2 text-xs">
                      <span className="text-text">{row.label}</span>
                      <span className="tabular-nums text-text-muted">
                        {row.confirmed > 0 && <span title="достоверных">{row.confirmed}</span>}
                        {row.confirmed > 0 && row.probable > 0 && " + "}
                        {row.probable > 0 && (
                          <span title="предположительных" className="italic">
                            {row.probable}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {shownCard.key !== view.node && (
                <button
                  type="button"
                  onClick={() => openNode(shownCard)}
                  className="mt-3 w-full rounded bg-accent px-3 py-1.5 text-sm text-accent-fg hover:bg-accent-hover"
                >
                  Раскрыть окружение
                </button>
              )}
            </section>
          )}

          {legend && (
            <section
              aria-label="Условные обозначения"
              className="rounded-panel border border-border-base bg-surface p-4 shadow-card"
            >
              <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                Достоверность связи
              </h2>
              <ul className="mt-2 space-y-2">
                {legend.confidence.map((item) => (
                  <li key={item.code} className="text-xs">
                    <span className="flex items-center gap-2 text-text">
                      <span
                        aria-hidden="true"
                        className="inline-block w-8 border-t-2 border-text-muted"
                        style={{ borderTopStyle: item.style }}
                      />
                      {item.label}
                    </span>
                    <span className="mt-0.5 block pl-10 text-text-subtle">{item.note}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {subgraph && <GraphNodeList subgraph={subgraph} onExpand={openNode} />}
        </div>
      </div>
    </>
  );
}
