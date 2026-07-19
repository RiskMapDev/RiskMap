import React, { useRef, useEffect, useState } from 'react'
import { AppTopBar } from '../components/layout/AppTopBar'

interface Node { id: string; label: string; type: 'org' | 'person' | 'contract' | 'subsidy'; x: number; y: number; risk?: 'high' | 'medium' | 'low' }
interface Edge { from: string; to: string; label: string; color: string }

const LINK_TYPES = [
  { key: 'head', label: 'руководитель', color: '#64748b', checked: true },
  { key: 'founder', label: 'учредитель', color: '#94a3b8', checked: true },
  { key: 'supplier', label: 'поставщик', color: '#f59e0b', checked: true },
  { key: 'contractor', label: 'подрядчик', color: '#dc2626', checked: true },
  { key: 'recipient', label: 'получатель', color: '#22c55e', checked: true },
  { key: 'co_recipient', label: 'со-получатель', color: '#94a3b8', checked: true },
]

const NODE_TYPES = [
  { key: 'org', label: 'Организация', color: '#1d6fbc' },
  { key: 'person', label: 'Физ. лицо', color: '#94a3b8' },
  { key: 'contract', label: 'Договор', color: '#f59e0b' },
  { key: 'subsidy', label: 'Субсидия', color: '#22c55e' },
]

const INITIAL_NODES: Node[] = [
  { id: 'n1', label: 'РегионСтрой', type: 'org', x: 160, y: 180, risk: 'medium' },
  { id: 'n2', label: 'КазСтройИнвест', type: 'org', x: 420, y: 260, risk: 'high' },
  { id: 'n3', label: 'АлматыЖолСервис', type: 'org', x: 680, y: 140, risk: 'high' },
  { id: 'n4', label: 'КоммунСервис', type: 'org', x: 820, y: 360, risk: 'low' },
  { id: 'n5', label: 'Сейткали М.Б.', type: 'person', x: 280, y: 420 },
  { id: 'n6', label: 'Ахметов Н.К.', type: 'person', x: 820, y: 180 },
  { id: 'n7', label: 'ДГЗ-2026-1842', type: 'contract', x: 550, y: 400 },
  { id: 'n8', label: 'Субсидия ИП-2026', type: 'subsidy', x: 670, y: 560 },
]

const EDGES: Edge[] = [
  { from: 'n5', to: 'n1', label: 'учредитель', color: '#94a3b8' },
  { from: 'n5', to: 'n2', label: 'руководитель', color: '#64748b' },
  { from: 'n2', to: 'n7', label: 'поставщик', color: '#f59e0b' },
  { from: 'n3', to: 'n7', label: 'подрядчик', color: '#dc2626' },
  { from: 'n7', to: 'n4', label: 'получатель', color: '#22c55e' },
  { from: 'n4', to: 'n8', label: 'со-получатель', color: '#94a3b8' },
  { from: 'n6', to: 'n3', label: 'руководитель', color: '#64748b' },
]

const TYPE_COLOR = { org: '#1d6fbc', person: '#94a3b8', contract: '#f59e0b', subsidy: '#22c55e' }
const TYPE_LABEL = { org: 'ТОО', person: '', contract: 'ДГЗ', subsidy: 'СУБ' }
const RISK_STROKE = { high: '#dc2626', medium: '#f59e0b', low: '#22c55e' }
const RISK_STROKE_W = { high: 2.5, medium: 2, low: 1.5 }

export function GraphPage() {
  const [nodes, setNodes] = useState<Node[]>(INITIAL_NODES)
  const [links, setLinks] = useState(LINK_TYPES.map(l => ({ ...l })))
  const dragRef = useRef<{ id: string; ox: number; oy: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const [svgSize, setSvgSize] = useState({ w: 900, h: 640 })
  const containerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const obs = new ResizeObserver(() => {
      if (containerRef.current) {
        setSvgSize({ w: containerRef.current.clientWidth, h: containerRef.current.clientHeight })
      }
    })
    if (containerRef.current) obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  const onMouseDown = (e: React.MouseEvent, id: string) => {
    e.preventDefault()
    const node = nodes.find(n => n.id === id)!
    dragRef.current = { id, ox: e.clientX - node.x, oy: e.clientY - node.y }
  }
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragRef.current) return
    const { id, ox, oy } = dragRef.current
    setNodes(prev => prev.map(n => n.id === id ? { ...n, x: e.clientX - ox, y: e.clientY - oy } : n))
  }
  const onMouseUp = () => { dragRef.current = null }

  const visibleLinks = new Set(links.filter(l => l.checked).map(l => l.label))
  const visibleEdges = EDGES.filter(e => visibleLinks.has(e.label))

  const getPos = (id: string) => nodes.find(n => n.id === id) || { x: 0, y: 0 }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f4f6f9', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      <AppTopBar title="Граф связей"/>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left legend panel */}
        <div style={{ width: 220, background: '#fff', borderRight: '1px solid #e8edf4', padding: '16px', display: 'flex', flexDirection: 'column', gap: 20, overflowY: 'auto' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>Типы связей</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {links.map((l, i) => (
                <label key={l.key} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: '#1e293b' }}>
                  <input type="checkbox" checked={l.checked} onChange={() => setLinks(prev => prev.map((x, j) => j === i ? { ...x, checked: !x.checked } : x))}
                    style={{ accentColor: l.color }}/>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: l.color, flexShrink: 0 }}/>
                  {l.label}
                </label>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>Типы узлов</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {NODE_TYPES.map(t => (
                <div key={t.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#1e293b' }}>
                  <div style={{ width: 14, height: 14, background: t.color, borderRadius: 2, flexShrink: 0 }}/>
                  {t.label}
                </div>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button style={{ padding: '9px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', fontSize: 13, color: '#475569', cursor: 'pointer' }}>
              Сбросить
            </button>
            <button style={{ padding: '9px', borderRadius: 8, border: 'none', background: '#1d6fbc', fontSize: 13, color: '#fff', cursor: 'pointer', fontWeight: 600 }}>
              Экспорт
            </button>
          </div>
        </div>

        {/* Graph area */}
        <div ref={containerRef} style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          {/* Zoom controls */}
          <div style={{ position: 'absolute', top: 12, left: 12, zIndex: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {['+', '−', '⤢'].map(btn => (
              <button key={btn} style={{ width: 30, height: 30, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, fontSize: 15, cursor: 'pointer', color: '#475569' }}>{btn}</button>
            ))}
          </div>

          <svg ref={svgRef} width={svgSize.w} height={svgSize.h} style={{ userSelect: 'none', background: '#f4f6f9' }}
            onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
            <defs>
              <marker id="arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 Z" fill="#c0ccd8"/>
              </marker>
            </defs>

            {/* Edges */}
            {visibleEdges.map((e, i) => {
              const from = getPos(e.from), to = getPos(e.to)
              const mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2
              return (
                <g key={i}>
                  <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={e.color} strokeWidth={1.5} strokeDasharray="4 2" markerEnd="url(#arrow)" opacity={0.6}/>
                  <text x={mx} y={my - 6} fontSize={11} fill={e.color} textAnchor="middle" style={{ pointerEvents: 'none' }}>{e.label}</text>
                </g>
              )
            })}

            {/* Nodes */}
            {nodes.map(node => {
              const c = TYPE_COLOR[node.type]
              const tag = TYPE_LABEL[node.type]
              const isRect = node.type !== 'person'
              const stroke = node.risk ? RISK_STROKE[node.risk] : c
              const sw = node.risk ? RISK_STROKE_W[node.risk] : 1.5
              return (
                <g key={node.id} style={{ cursor: 'grab' }} onMouseDown={e => onMouseDown(e, node.id)}>
                  {isRect ? (
                    <rect x={node.x - 38} y={node.y - 24} width={76} height={48} rx={6} fill="#fff" stroke={stroke} strokeWidth={sw}/>
                  ) : (
                    <circle cx={node.x} cy={node.y} r={26} fill="#e2e8f0" stroke="#b0bec8" strokeWidth={1.5}/>
                  )}
                  {tag && <text x={node.x} y={node.y - 6} fontSize={11} fontWeight="700" fill={c} textAnchor="middle" style={{ pointerEvents: 'none' }}>{tag}</text>}
                  {node.type === 'person' && (
                    <g transform={`translate(${node.x - 8}, ${node.y - 9})`} style={{ pointerEvents: 'none' }}>
                      <circle cx="8" cy="5" r="4" fill="#94a3b8"/>
                      <path d="M0 18c0-4.4 3.6-8 8-8s8 3.6 8 8" fill="#94a3b8"/>
                    </g>
                  )}
                  {node.risk && isRect && (
                    <circle cx={node.x + 34} cy={node.y - 20} r={5} fill={stroke}/>
                  )}
                  <text x={node.x} y={isRect ? node.y + 38 : node.y + 36} fontSize={11} fill="#475569" textAnchor="middle" style={{ pointerEvents: 'none' }}>{node.label}</text>
                </g>
              )
            })}
          </svg>
        </div>
      </div>
    </div>
  )
}
