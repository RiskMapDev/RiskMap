import React, { useState } from 'react'
import { useLogin } from '../api/queries'

const ROLES = [
  { key: 'admin',   label: 'Администратор', initials: 'АД', color: '#dc2626', bg: '#fef2f2' },
  { key: 'analyst', label: 'Аналитик',       initials: 'АН', color: '#1d6fbc', bg: '#eff6ff' },
  { key: 'manager', label: 'Руководитель',   initials: 'РК', color: '#7c3aed', bg: '#fdf4ff' },
  { key: 'viewer',  label: 'Просмотр',       initials: 'ПР', color: '#64748b', bg: '#f1f5f9' },
]

const FEATURES = [
  { icon: <GlobeIcon/>,  label: 'Мультиуровневая карта' },
  { icon: <ChartIcon/>,  label: 'Аналитика и рейтинги' },
  { icon: <GraphIcon/>,  label: 'Граф связей субъектов' },
  { icon: <DocIcon/>,    label: 'Автоматические отчёты' },
]

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [role, setRole] = useState('analyst')
  const [error, setError] = useState('')
  const login = useLogin()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await login.mutateAsync({ username, password })
      localStorage.setItem('user_role', role)
      onLogin()
    } catch {
      setError('Неверный логин или пароль')
    }
  }

  return (
    <div style={{ display: 'flex', height: '100vh', fontFamily: "'Inter', -apple-system, sans-serif" }}>

      {/* ── Left dark panel ── */}
      <div style={{
        width: '52%', background: 'linear-gradient(160deg, #0b1829 0%, #0d2240 55%, #0f2e55 100%)',
        display: 'flex', flexDirection: 'column', padding: '32px 48px', position: 'relative', overflow: 'hidden'
      }}>
        {/* Decorative blobs */}
        <div style={{ position: 'absolute', top: -120, right: -120, width: 400, height: 400, borderRadius: '50%', background: 'radial-gradient(circle, rgba(29,111,188,0.15) 0%, transparent 70%)' }}/>
        <div style={{ position: 'absolute', bottom: -80, left: -80, width: 280, height: 280, borderRadius: '50%', background: 'radial-gradient(circle, rgba(29,111,188,0.1) 0%, transparent 70%)' }}/>

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 'auto' }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4aa8e8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>
          </div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>Карта рисков</div>
            <div style={{ fontSize: 11, color: '#5a8aaa', marginTop: 1 }}>Алматинская область, Республика Казахстан</div>
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingBottom: 60 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#3a8ac4', letterSpacing: 2, textTransform: 'uppercase', marginBottom: 20 }}>
            Информационно-аналитическая система
          </div>

          <h1 style={{ margin: '0 0 20px', lineHeight: 1.2 }}>
            <span style={{ fontSize: 38, fontWeight: 800, color: '#fff', display: 'block' }}>Интерактивная карта</span>
            <span style={{ fontSize: 38, fontWeight: 800, color: '#4aa8e8', display: 'block' }}>рисков региона</span>
          </h1>

          <p style={{ fontSize: 14, color: '#6a9ab8', lineHeight: 1.7, margin: '0 0 40px', maxWidth: 380 }}>
            Мониторинг социально-экономических и криминогенных рисков. Контроль бюджета, государственных закупок, субсидий и инфраструктурных проектов на территории области.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 24px' }}>
            {FEATURES.map((f, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ color: '#3a8ac4', flexShrink: 0 }}>{f.icon}</div>
                <span style={{ fontSize: 13, color: '#8ab4cc' }}>{f.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ fontSize: 11, color: '#2a4a6a' }}>
          © 2026 Акимат Алматинской области · Ограниченный доступ
        </div>
      </div>

      {/* ── Right white panel ── */}
      <div style={{ flex: 1, background: '#f0f4f8', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
        <div style={{ width: '100%', maxWidth: 420, background: '#fff', borderRadius: 16, padding: '40px 40px 36px', boxShadow: '0 8px 40px rgba(0,0,0,0.10)' }}>
          <h2 style={{ fontSize: 24, fontWeight: 800, color: '#0f172a', margin: '0 0 6px' }}>Вход в систему</h2>
          <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 28px' }}>Учётные данные государственного портала</p>

          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>Логин (e-mail / ИИН)</label>
              <input
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="asanova.g@akim.gov.kz"
                style={{ width: '100%', padding: '11px 14px', borderRadius: 10, fontSize: 14, border: '1.5px solid #e2e8f0', background: '#fff', color: '#1e293b', outline: 'none', boxSizing: 'border-box' }}
                onFocus={e => { e.target.style.borderColor = '#1d6fbc' }}
                onBlur={e => { e.target.style.borderColor = '#e2e8f0' }}
              />
            </div>

            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>Пароль</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••••"
                style={{ width: '100%', padding: '11px 14px', borderRadius: 10, fontSize: 14, border: '1.5px solid #e2e8f0', background: '#fff', color: '#1e293b', outline: 'none', boxSizing: 'border-box' }}
                onFocus={e => { e.target.style.borderColor = '#1d6fbc' }}
                onBlur={e => { e.target.style.borderColor = '#e2e8f0' }}
              />
            </div>

            <div>
              <label style={{ fontSize: 13, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 10 }}>Роль для демонстрации</label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {ROLES.map(r => {
                  const active = role === r.key
                  return (
                    <button
                      key={r.key}
                      type="button"
                      onClick={() => setRole(r.key)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderRadius: 10,
                        border: active ? `2px solid #1d6fbc` : '2px solid #e8edf4',
                        background: active ? '#f0f7ff' : '#fafafa',
                        cursor: 'pointer', textAlign: 'left'
                      }}
                    >
                      <div style={{ width: 28, height: 28, borderRadius: '50%', background: r.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 800, color: r.color, flexShrink: 0, border: active ? `1.5px solid ${r.color}` : 'none' }}>
                        {r.initials}
                      </div>
                      <span style={{ fontSize: 13, fontWeight: active ? 600 : 400, color: active ? '#0f172a' : '#475569' }}>{r.label}</span>
                    </button>
                  )
                })}
              </div>
            </div>

            {error && (
              <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626' }}>{error}</div>
            )}

            <button
              type="submit"
              disabled={login.isPending}
              style={{ width: '100%', padding: '13px', borderRadius: 10, fontSize: 15, fontWeight: 700, background: '#1d6fbc', color: '#fff', border: 'none', cursor: 'pointer', marginTop: 4, opacity: login.isPending ? 0.7 : 1 }}
            >
              {login.isPending ? 'Вход...' : 'Войти в систему'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

function GlobeIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
}
function ChartIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
}
function GraphIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
}
function DocIcon() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
}
