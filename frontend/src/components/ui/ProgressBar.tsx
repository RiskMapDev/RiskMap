import React from 'react'
export function ProgressBar({ pct }: { pct: number }) {
  const color = pct >= 75 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149'
  return (
    <div className="h-1 bg-white/10 rounded-full overflow-hidden mt-1">
      <div style={{ width: `${Math.min(pct, 100)}%`, background: color }} className="h-full rounded-full" />
    </div>
  )
}
