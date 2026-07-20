import React from 'react'
import { useTheme } from '../../hooks/useTheme'
export function StatBox({ label, value, color }: { label: string; value: any; color?: string }) {
  const t = useTheme()
  return (
    <div style={{ background: t.surface2, border: `1px solid ${t.border}` }} className="rounded-lg p-2.5 transition-colors duration-200">
      <div className={`text-base font-bold ${color ?? ''}`} style={{ color: color ? undefined : t.text }}>{value}</div>
      <div style={{ color: t.textDim }} className="text-[9px] mt-0.5">{label}</div>
    </div>
  )
}
