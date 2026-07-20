import React from 'react'

interface Props {
  title: string
  subtitle?: string
  actions?: React.ReactNode
}

export function AppTopBar({ title, subtitle, actions }: Props) {
  const role = localStorage.getItem('user_role') || 'analyst'
  const roleLabel = { admin: 'Администратор', analyst: 'Аналитик', manager: 'Руководитель', viewer: 'Просмотр' }[role] || 'Аналитик'

  return (
    <div style={{
      height: 56, background: '#fff', borderBottom: '1px solid #e8edf4',
      display: 'flex', alignItems: 'center', paddingLeft: 24, paddingRight: 24,
      gap: 12, flexShrink: 0, fontFamily: "'Inter', -apple-system, sans-serif"
    }}>
      {/* Search */}
      <div style={{ position: 'relative', flex: 1, maxWidth: 360 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }}>
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input placeholder="Поиск по реестрам системы..." style={{
          width: '100%', padding: '7px 12px 7px 32px', borderRadius: 8,
          border: '1px solid #e2e8f0', background: '#f8fafc', fontSize: 13, color: '#475569',
          outline: 'none', boxSizing: 'border-box'
        }}/>
        <span style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 11, color: '#c0ccd8', fontFamily: 'monospace' }}>⌘K</span>
      </div>

      <div style={{ flex: 1 }}/>

      {actions}

      {/* Bell */}
      <div style={{ position: 'relative', cursor: 'pointer' }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        <div style={{ position: 'absolute', top: -4, right: -4, width: 16, height: 16, borderRadius: '50%', background: '#dc2626', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#fff', fontWeight: 700 }}>3</div>
      </div>

      {/* User */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#1d6fbc', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: '#fff' }}>
          АС
        </div>
        <div style={{ lineHeight: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#1e293b' }}>Асанова Г.М.</div>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{roleLabel}</div>
        </div>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </div>
    </div>
  )
}
