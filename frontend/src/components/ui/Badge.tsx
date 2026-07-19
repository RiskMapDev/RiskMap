import React from 'react'
type Level = 'high'|'medium'|'low'|'info'
const S: Record<Level,string> = {
  high: 'bg-red-500/20 text-red-400 border border-red-500/40',
  medium: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40',
  low: 'bg-green-500/20 text-green-400 border border-green-500/40',
  info: 'bg-blue-500/20 text-blue-400 border border-blue-500/40',
}
export function Badge({ level, label }: { level: Level; label: string }) {
  return <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold ${S[level]}`}>{label}</span>
}
