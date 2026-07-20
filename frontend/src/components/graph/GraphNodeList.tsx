"use client";

import { RiskBadge } from "@/components/risk/RiskBadge";
import type { GraphNodePayload, SubgraphPayload } from "@/lib/api/graph";
import { nodeDescription } from "@/lib/graph-style";

interface GraphNodeListProps {
  subgraph: SubgraphPayload;
  onExpand: (node: GraphNodePayload) => void;
}

/**
 * Текстовое зеркало канвы.
 *
 * Канва cytoscape — это `<canvas>`, и вспомогательным технологиям она
 * недоступна в принципе. Без этого списка граф был бы виден только зрячему
 * пользователю с мышью, что нарушает требование ТЗ 18. Список не «версия для
 * слабовидящих», а равноправное представление тех же данных: клавиатурой
 * раскрытие узла делается отсюда.
 *
 * Уровень риска показан плашкой со значком и словом, а не цветной точкой:
 * «высокий» и «критический» по цвету почти неразличимы, и на них смысл
 * держать нельзя.
 */
export function GraphNodeList({ subgraph, onExpand }: GraphNodeListProps) {
  const byKey = new Map(subgraph.nodes.map((node) => [node.key, node]));
  const center = byKey.get(subgraph.center);

  const relationsOf = (key: string) =>
    subgraph.edges.filter((edge) => edge.source === key || edge.target === key);

  return (
    <section aria-label="Узлы подграфа списком" className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        Узлы окружения
      </h3>
      <p className="text-xs text-text-subtle">
        То же содержимое, что на канве. Раскрытие соседа доступно отсюда с
        клавиатуры.
      </p>

      <ul className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
        {subgraph.nodes.map((node) => {
          const relations = relationsOf(node.key);
          const isCenter = node.key === subgraph.center;
          return (
            <li
              key={node.key}
              className={`rounded border p-2 ${
                isCenter ? "border-accent bg-accent-soft" : "border-border-base bg-surface"
              }`}
            >
              <p className="text-sm text-text">
                <span className="text-xs text-text-muted">{node.node_type_label}: </span>
                {node.label}
              </p>
              <span className="sr-only">{nodeDescription(node)}</span>

              <div className="mt-1 flex flex-wrap items-center gap-2">
                <RiskBadge
                  level={node.risk_level}
                  score={node.risk_score}
                  preliminary={node.risk_is_preliminary}
                  size="sm"
                />
                <span className="text-xs text-text-subtle">
                  связей в подграфе: {relations.length} из {node.degree}
                </span>
                {!isCenter && (
                  <button
                    type="button"
                    onClick={() => onExpand(node)}
                    className="rounded border border-border-base px-2 py-0.5 text-xs text-accent hover:bg-surface-hover"
                  >
                    Раскрыть
                  </button>
                )}
              </div>

              {relations.length > 0 && (
                <ul className="mt-1.5 space-y-0.5">
                  {relations.slice(0, 4).map((edge) => (
                    <li key={edge.id} className="text-xs text-text-muted">
                      <span
                        aria-hidden="true"
                        className="mr-1 inline-block w-6 border-t align-middle"
                        style={{
                          borderTopStyle: edge.confidence === "probable" ? "dashed" : "solid",
                        }}
                      />
                      {edge.relation_type_label}
                      {" — "}
                      {/* Достоверность словом: начертание линии на канве
                          глазами читается, но вслух не произносится. */}
                      <span className="text-text-subtle">{edge.confidence_label.toLowerCase()}</span>
                      {edge.confidence === "probable" && (
                        <span className="block pl-7 text-text-subtle">
                          основание: {edge.confidence_basis}
                        </span>
                      )}
                    </li>
                  ))}
                  {relations.length > 4 && (
                    <li className="text-xs text-text-subtle">
                      и ещё {relations.length - 4}
                    </li>
                  )}
                </ul>
              )}
            </li>
          );
        })}
      </ul>

      {center && subgraph.truncated && (
        <p className="rounded border border-risk-medium-border bg-risk-medium-bg p-2 text-xs text-risk-medium-text">
          Показано {subgraph.edges.length} связей из {subgraph.total_neighbors}; узлов не
          поместилось: {subgraph.omitted_nodes}. Увеличьте предел узлов или сузьте типы
          связей — по этой картинке нельзя судить о том, что связей мало.
        </p>
      )}
    </section>
  );
}
