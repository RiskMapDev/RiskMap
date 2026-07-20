"use client";

import { useEffect, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";

import type { GraphNodePayload, SubgraphPayload } from "@/lib/api/graph";
import {
  CONFIDENCE_LINE_STYLE,
  NODE_FILL,
  NODE_SHAPE,
  RELATION_COLOR,
  RISK_BORDER_STYLE,
  RISK_BORDER_VAR,
  RISK_BORDER_WIDTH,
  edgeLabel,
  nodeLabel,
  readThemeColor,
} from "@/lib/graph-style";
import type { RiskLevel } from "@/lib/risk";

interface GraphCanvasProps {
  subgraph: SubgraphPayload | null;
  onSelect: (node: GraphNodePayload) => void;
  /** Раскрыть окружение соседа — отдельный запрос к серверу, а не разворот кэша. */
  onExpand: (node: GraphNodePayload) => void;
}

const RISK_FALLBACK: Readonly<Record<RiskLevel, string>> = {
  low: "#16a34a",
  medium: "#ca8a04",
  high: "#dc2626",
  critical: "#7f1d1d",
  unknown: "#64748b",
};

function toElements(subgraph: SubgraphPayload): ElementDefinition[] {
  const nodes: ElementDefinition[] = subgraph.nodes.map((node) => ({
    group: "nodes",
    data: {
      id: node.key,
      label: nodeLabel(node),
      shape: NODE_SHAPE[node.node_type],
      fill: NODE_FILL[node.node_type],
      border: readThemeColor(RISK_BORDER_VAR[node.risk_level], RISK_FALLBACK[node.risk_level]),
      borderWidth: RISK_BORDER_WIDTH[node.risk_level],
      borderStyle: RISK_BORDER_STYLE[node.risk_level],
      isCenter: node.key === subgraph.center,
    },
  }));

  const edges: ElementDefinition[] = subgraph.edges.map((edge) => ({
    group: "edges",
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edgeLabel(edge),
      color: RELATION_COLOR[edge.relation_type],
      lineStyle: CONFIDENCE_LINE_STYLE[edge.confidence],
      /*
        Стрелка рисуется только у направленных связей. У «общего адреса» и
        «со-получателя» первенства сторон в данных нет, и стрелка приписала
        бы одной из компаний роль, которой источник не утверждает.
      */
      arrow: edge.direction === "directed" ? "triangle" : "none",
    },
  }));

  return [...nodes, ...edges];
}

/**
 * Канва графа на cytoscape.
 *
 * React-обёртки для cytoscape в проекте нет намеренно: библиотека владеет
 * собственным деревом отрисовки и жизненным циклом, и обёртка, пересоздающая
 * экземпляр на каждый рендер, теряет и раскладку, и положение камеры.
 * Поэтому экземпляр живёт в ref, создаётся один раз и переживает перерисовки
 * родителя, а данные в него заливаются отдельным эффектом.
 *
 * Канва недоступна вспомогательным технологиям в принципе — это `<canvas>`.
 * Поэтому она помечена `aria-hidden`, а рядом всегда стоит список узлов
 * (`GraphNodeList`), который несёт то же содержимое текстом. Граф без такого
 * списка нарушал бы требование ТЗ 18 о доступности.
 */
export function GraphCanvas({ subgraph, onSelect, onExpand }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  /*
    Обработчики держатся в ref, а не переприсоединяются эффектом: иначе
    каждое обновление родителя снимало бы и вешало слушатели cytoscape
    заново, а при быстрых кликах успевало бы потерять событие. Запись идёт
    в эффекте, а не в теле рендера: ref во время рендера трогать нельзя,
    рендер обязан оставаться чистым.
  */
  const handlersRef = useRef({ onSelect, onExpand });
  useEffect(() => {
    handlersRef.current = { onSelect, onExpand };
  }, [onSelect, onExpand]);

  // Обработчик клика cytoscape получает только идентификатор узла, а вернуть
  // родителю нужно всю запись. Карта заполняется тем же эффектом, что заливает
  // элементы, — так она не может разойтись с тем, что нарисовано.
  const nodesRef = useRef<Map<string, GraphNodePayload>>(new Map());

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const cy = cytoscape({
      container,
      style: [
        {
          selector: "node",
          style: {
            shape: "data(shape)" as cytoscape.Css.PropertyValueNode<cytoscape.Css.NodeShape>,
            "background-color": "data(fill)",
            "border-color": "data(border)",
            "border-width": "data(borderWidth)",
            "border-style": "data(borderStyle)" as cytoscape.Css.PropertyValueNode<"solid">,
            label: "data(label)",
            "text-wrap": "wrap",
            "text-valign": "center",
            "font-size": 10,
            "line-height": 1.3,
            color: "#0f172a",
            width: 116,
            height: 56,
            "text-max-width": "108px",
          },
        },
        {
          // Центр выделен размером и добавочной обводкой: пользователь должен
          // видеть, чьё окружение он смотрит, не сверяясь с панелью.
          selector: "node[?isCenter]",
          style: { width: 140, height: 68, "font-weight": "bold", "overlay-opacity": 0.12 },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "data(color)",
            "line-style": "data(lineStyle)" as cytoscape.Css.PropertyValueEdge<"solid">,
            "target-arrow-color": "data(color)",
            "target-arrow-shape": "data(arrow)" as cytoscape.Css.PropertyValueEdge<"triangle">,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 9,
            "text-rotation": "autorotate",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
            color: "#334155",
          },
        },
      ],
      // Пользовательские масштаб и панорамирование — требование ТЗ 13.
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.2,
    });

    cy.on("tap", "node", (event) => {
      const node = nodesRef.current.get(String(event.target.id()));
      if (node) handlersRef.current.onSelect(node);
    });
    cy.on("dbltap", "node", (event) => {
      const node = nodesRef.current.get(String(event.target.id()));
      if (node) handlersRef.current.onExpand(node);
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    nodesRef.current = new Map((subgraph?.nodes ?? []).map((node) => [node.key, node]));

    cy.batch(() => {
      cy.elements().remove();
      if (subgraph) cy.add(toElements(subgraph));
    });

    if (!subgraph || subgraph.nodes.length === 0) return;

    /*
      Концентрическая раскладка, а не силовая: у окружения одного узла есть
      естественный центр, и ставить его в случайное место значит скрывать то,
      ради чего экран открыт. Соседи ложатся кольцами по числу их связей —
      узлы-концентраторы оказываются ближе к центру.
    */
    cy.layout({
      name: "concentric",
      concentric: (node) => (node.data("isCenter") ? 100 : node.degree(false)),
      levelWidth: () => 1,
      minNodeSpacing: 36,
      animate: false,
      padding: 24,
    }).run();
    cy.fit(undefined, 32);
  }, [subgraph]);

  function zoomBy(factor: number) {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        data-testid="graph-canvas"
        /*
          Канва — это <canvas>, и для скринридера она пуста по определению.
          Содержимое графа читается из списка узлов рядом; помечать канву
          доступной значило бы обещать доступность, которой нет.
        */
        aria-hidden="true"
        className="h-full w-full rounded-panel border border-border-base bg-surface-muted"
      />
      <div
        className="absolute left-3 top-3 flex flex-col overflow-hidden rounded border border-border-base bg-surface shadow-card"
        role="group"
        aria-label="Масштаб графа"
      >
        <button
          type="button"
          onClick={() => zoomBy(1.3)}
          className="px-2.5 py-1.5 text-sm text-text hover:bg-surface-hover"
        >
          <span aria-hidden="true">+</span>
          <span className="sr-only">Приблизить</span>
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1 / 1.3)}
          className="border-t border-border-base px-2.5 py-1.5 text-sm text-text hover:bg-surface-hover"
        >
          <span aria-hidden="true">−</span>
          <span className="sr-only">Отдалить</span>
        </button>
        <button
          type="button"
          onClick={() => cyRef.current?.fit(undefined, 32)}
          className="border-t border-border-base px-2.5 py-1.5 text-xs text-text hover:bg-surface-hover"
        >
          Вписать
        </button>
      </div>
    </div>
  );
}
