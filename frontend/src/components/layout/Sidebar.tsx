import React from 'react'

type Page = 'dashboard' | 'map' | 'import' | 'reports' | 'graph' | 'admin'

interface Props {
  active: Page
  onNavigate: (p: Page) => void
}

const NAV = [
  { key: 'dashboard', label: 'Дашборд', icon: DashIcon },
  { key: 'map', label: 'Карта', icon: MapIcon },
  { key: 'import', label: 'Данные (импорт)', icon: ImportIcon },
  { key: 'reports', label: 'Отчёты', icon: ReportIcon },
  { key: 'graph', label: 'Граф связей', icon: GraphIcon },
  { key: 'admin', label: 'Администрирование', icon: AdminIcon },
] as const

export function Sidebar({ active, onNavigate }: Props) {
  return (
    <div style={{
      width: 232, background: '#0d1b2a', display: 'flex', flexDirection: 'column',
      height: '100vh', flexShrink: 0, fontFamily: "'Inter', -apple-system, sans-serif"
    }}>
      {/* Logo */}
      <div style={{ padding: '20px 20px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 8, background: '#1d6fbc', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="3 11 22 2 13 21 11 13 3 11"/>
            </svg>
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#fff', lineHeight: 1.2 }}>Карта рисков</div>
            <div style={{ fontSize: 10, color: '#4a7a9b', marginTop: 1 }}>Preview</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <div style={{ flex: 1, padding: '16px 12px', overflowY: 'auto' }}>
        <div style={{ fontSize: 10, color: '#3a5a78', fontWeight: 600, letterSpacing: 1.2, textTransform: 'uppercase', padding: '0 8px', marginBottom: 8 }}>
          Навигация
        </div>
        {NAV.map(({ key, label, icon: Icon }) => {
          const isActive = active === key
          return (
            <button
              key={key}
              onClick={() => onNavigate(key as Page)}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '9px 10px', borderRadius: 8, border: 'none',
                background: isActive ? 'rgba(29,111,188,0.18)' : 'transparent',
                color: isActive ? '#4aa8e8' : '#7a9ab8',
                cursor: 'pointer', fontSize: 13, fontWeight: isActive ? 600 : 400,
                marginBottom: 2, textAlign: 'left',
                borderLeft: isActive ? '3px solid #1d6fbc' : '3px solid transparent',
                transition: 'all 0.15s'
              }}
            >
              <Icon active={isActive}/>
              {label}
            </button>
          )
        })}
      </div>

      <div style={{ padding: '16px 20px', borderTop: '1px solid rgba(255,255,255,0.06)', fontSize: 11, color: '#2a4560' }}>
        © 2026 Акимат
      </div>
    </div>
  )
}

function DashIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
}
function MapIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>
}
function ImportIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="21 15 21 21 3 21 3 15"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
}
function ReportIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
}
function GraphIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
}
function AdminIcon({ active }: { active: boolean }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? '#4aa8e8' : '#5a7a98'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M4.93 19.07l1.41-1.41M19.07 19.07l-1.41-1.41M12 2v2M12 20v2M2 12h2M20 12h2"/></svg>
}
