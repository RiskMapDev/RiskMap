import React, { useState, useRef, useCallback, useLayoutEffect } from 'react'

interface Node { id: string; label: string; color: string; x: number; y: number }
interface Edge { from: string; to: string; label: string; dashed?: boolean; color?: string }

const DEFAULT_NODES: Node[] = [
  { id:'alpha',    label:'ТОО «Альфа»',    color:'#f85149', x:50,  y:50  },
  { id:'founder',  label:'Жаксыбеков Р.',  color:'#1f6feb', x:18,  y:20  },
  { id:'meridian', label:'ТОО «Меридиан»', color:'#f85149', x:75,  y:16  },
  { id:'school',   label:'Школа №4',        color:'#d29922', x:78,  y:68  },
  { id:'damu',     label:'ТОО «Даму»',     color:'#bc8cff', x:14,  y:70  },
  { id:'ip',       label:'ИП Сейтқали',    color:'#6b7280', x:44,  y:10  },
]

const DEFAULT_EDGES: Edge[] = [
  { from:'founder',  to:'alpha',    label:'Учредитель', color:'#f85149' },
  { from:'founder',  to:'meridian', label:'Учредитель', color:'#f85149' },
  { from:'alpha',    to:'meridian', label:'Аффил.',     color:'#f85149', dashed:true },
  { from:'alpha',    to:'school',   label:'Контракт',   color:'#6b7280' },
  { from:'alpha',    to:'damu',     label:'Аффил.',     color:'#f85149', dashed:true },
  { from:'ip',       to:'alpha',    label:'Поставщик',  color:'#6b7280' },
]

const W = 600
const H = 220

export function DraggableGraph({ nodes = DEFAULT_NODES, edges = DEFAULT_EDGES }: { nodes?: Node[]; edges?: Edge[] }) {
  // positions stored in % of W/H → convert to px for rendering
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>(
    () => Object.fromEntries(nodes.map(n => [n.id, { x: n.x / 100 * W, y: n.y / 100 * H }]))
  )
  const [hovered, setHovered] = useState<string | null>(null)
  const dragging = useRef<string | null>(null)
  const offset   = useRef({ x: 0, y: 0 })
  const svgRef   = useRef<SVGSVGElement>(null)

  const getSvgXY = (cx: number, cy: number) => {
    const rect = svgRef.current!.getBoundingClientRect()
    const scaleX = W / rect.width
    const scaleY = H / rect.height
    return { x: (cx - rect.left) * scaleX, y: (cy - rect.top) * scaleY }
  }

  const startDrag = (e: React.MouseEvent | React.TouchEvent, id: string) => {
    e.stopPropagation()
    dragging.current = id
    const client = 'touches' in e ? e.touches[0] : e
    const pt = getSvgXY(client.clientX, client.clientY)
    const pos = positions[id]
    offset.current = { x: pt.x - pos.x, y: pt.y - pos.y }
  }

  const onMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!dragging.current) return
    if ('touches' in e) e.preventDefault()
    const client = 'touches' in e ? e.touches[0] : e
    const pt = getSvgXY(client.clientX, client.clientY)
    const NODE_R = dragging.current === 'alpha' ? 34 : 28
    setPositions(p => ({
      ...p,
      [dragging.current!]: {
        x: Math.max(NODE_R, Math.min(W - NODE_R, pt.x - offset.current.x)),
        y: Math.max(NODE_R, Math.min(H - NODE_R, pt.y - offset.current.y)),
      }
    }))
  }

  const onUp = () => { dragging.current = null }

  const nodeR = (id: string) => id === 'alpha' ? 34 : 28

  return (
    <div className="bg-[#1c2128] border border-[#30363d] rounded-lg overflow-hidden">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        width="100%"
        height="220"
        className="select-none block"
        style={{ cursor: dragging.current ? 'grabbing' : 'default', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' }}
        onMouseMove={onMove as any}
        onMouseUp={onUp}
        onMouseLeave={onUp}
        onTouchMove={onMove as any}
        onTouchEnd={onUp}
      >
        {/* Edges */}
        {edges.map((e, i) => {
          const f = positions[e.from]; const t = positions[e.to]
          if (!f || !t) return null
          const mx = (f.x + t.x) / 2
          const my = (f.y + t.y) / 2
          return (
            <g key={i}>
              <line
                x1={f.x} y1={f.y} x2={t.x} y2={t.y}
                stroke={e.color ?? '#484f58'} strokeWidth="1.5"
                strokeDasharray={e.dashed ? '6 4' : undefined}
                strokeOpacity="0.8"
              />
              <text x={mx} y={my - 4} fontSize="9" fill="#6b7280" textAnchor="middle"
                style={{ pointerEvents: 'none' }}>
                {e.label}
              </text>
            </g>
          )
        })}

        {/* Nodes */}
        {nodes.map(n => {
          const pos = positions[n.id]
          const r   = nodeR(n.id)
          const isHov = hovered === n.id

          // Split label into up to 2 lines at space or «
          const words = n.label.split(' ')
          const line1 = words.slice(0, Math.ceil(words.length / 2)).join(' ')
          const line2 = words.slice(Math.ceil(words.length / 2)).join(' ')

          return (
            <g key={n.id}
              style={{ cursor: 'grab' }}
              onMouseDown={e => startDrag(e, n.id)}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => { setHovered(null) }}
              onTouchStart={e => startDrag(e, n.id)}
            >
              <ellipse
                cx={pos.x} cy={pos.y}
                rx={r} ry={r * 0.6}
                fill={n.color} fillOpacity={isHov ? 0.95 : 0.8}
                stroke={isHov ? 'white' : 'rgba(255,255,255,0.25)'}
                strokeWidth={isHov ? 1.5 : 0.8}
              />
              {line2 ? (
                <>
                  <text x={pos.x} y={pos.y - 5} fontSize="10" fontWeight="700" fill="white"
                    textAnchor="middle" dominantBaseline="middle"
                    style={{ pointerEvents: 'none' }}>
                    {line1}
                  </text>
                  <text x={pos.x} y={pos.y + 7} fontSize="10" fontWeight="700" fill="white"
                    textAnchor="middle" dominantBaseline="middle"
                    style={{ pointerEvents: 'none' }}>
                    {line2}
                  </text>
                </>
              ) : (
                <text x={pos.x} y={pos.y} fontSize="10" fontWeight="700" fill="white"
                  textAnchor="middle" dominantBaseline="middle"
                  style={{ pointerEvents: 'none' }}>
                  {n.label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
