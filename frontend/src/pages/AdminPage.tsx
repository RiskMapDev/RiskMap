import React, { useState } from 'react'
import { AppTopBar } from '../components/layout/AppTopBar'

const USERS = [
  { name: 'Асанова Гулмира М.', login: 'asanova.g', role: 'Аналитик', initials: 'АС', roleColor: '#1d6fbc', territory: 'Алматинская обл.', lastLogin: '04.07.2026 09:14', active: true },
  { name: 'Петров Кирилл С.', login: 'petrov.k', role: 'Просмотр', initials: 'ПР', roleColor: '#64748b', territory: 'Алматинский р-н', lastLogin: '04.07.2026 08:52', active: true },
  { name: 'Нуров Даниар К.', login: 'nurov.d', role: 'Руководитель', initials: 'РК', roleColor: '#7c3aed', territory: 'Все районы', lastLogin: '03.07.2026 16:08', active: true },
  { name: 'Тастанов Ерлан А.', login: 'tastanov.e', role: 'Аналитик', initials: 'АС', roleColor: '#1d6fbc', territory: 'Карасайский р-н', lastLogin: '03.07.2026 14:22', active: true },
  { name: 'Сапарова Айгерим Н.', login: 'saparova.a', role: 'Просмотр', initials: 'ПР', roleColor: '#64748b', territory: 'Талгарский р-н', lastLogin: '01.07.2026 11:05', active: false },
]

const TABS = ['Пользователи', 'Справочники', 'Критерии риска', 'Журнал действий']

export function AdminPage() {
  const [tab, setTab] = useState(0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f4f6f9', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      <AppTopBar title="Администрирование"/>
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>Администрирование</div>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>Администрирование системы</h1>
          </div>
          {tab === 0 && (
            <button style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 8, background: '#1d6fbc', color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Добавить пользователя
            </button>
          )}
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #e8edf4', marginBottom: 20 }}>
          {TABS.map((t, i) => (
            <button key={t} onClick={() => setTab(i)} style={{
              padding: '10px 20px', fontSize: 13, fontWeight: tab === i ? 600 : 400,
              color: tab === i ? '#1d6fbc' : '#64748b', background: 'none', border: 'none',
              borderBottom: tab === i ? '2px solid #1d6fbc' : '2px solid transparent',
              cursor: 'pointer', marginBottom: -1
            }}>{t}</button>
          ))}
        </div>

        {tab === 0 && (
          <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e8edf4', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #f1f5f9', background: '#fafbfc' }}>
                  {['Ф.И.О.', 'Логин', 'Роль', 'Территория', 'Последний вход', 'Статус', 'Действия'].map(h => (
                    <th key={h} style={{ textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#94a3b8', padding: '12px 16px', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {USERS.map(u => (
                  <tr key={u.login} style={{ borderBottom: '1px solid #f8fafc' }}>
                    <td style={{ padding: '14px 16px', fontSize: 14, fontWeight: 600, color: '#1e293b' }}>{u.name}</td>
                    <td style={{ padding: '14px 16px', fontSize: 13, color: '#94a3b8', fontFamily: 'monospace' }}>{u.login}</td>
                    <td style={{ padding: '14px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 24, height: 24, borderRadius: '50%', background: u.roleColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#fff' }}>{u.initials}</div>
                        <span style={{ fontSize: 13, fontWeight: 500, color: u.roleColor }}>{u.role}</span>
                      </div>
                    </td>
                    <td style={{ padding: '14px 16px', fontSize: 13, color: '#475569' }}>{u.territory}</td>
                    <td style={{ padding: '14px 16px', fontSize: 12, color: '#64748b' }}>{u.lastLogin}</td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ fontSize: 12, fontWeight: 600, padding: '4px 12px', borderRadius: 20, background: u.active ? '#f0fdf4' : '#f1f5f9', color: u.active ? '#16a34a' : '#94a3b8' }}>
                        {u.active ? 'Активен' : 'Неактивен'}
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px' }}>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4 }}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </button>
                        <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: 4 }}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 1 && (
          <div style={{ background: '#fff', borderRadius: 12, padding: '32px', border: '1px solid #e8edf4', textAlign: 'center', color: '#94a3b8' }}>
            <div style={{ fontSize: 14 }}>Справочники — раздел в разработке</div>
          </div>
        )}
        {tab === 2 && (
          <div style={{ background: '#fff', borderRadius: 12, padding: '32px', border: '1px solid #e8edf4', textAlign: 'center', color: '#94a3b8' }}>
            <div style={{ fontSize: 14 }}>Критерии риска — раздел в разработке</div>
          </div>
        )}
        {tab === 3 && (
          <div style={{ background: '#fff', borderRadius: 12, border: '1px solid #e8edf4', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #f1f5f9', background: '#fafbfc' }}>
                  {['Время', 'Пользователь', 'Действие', 'Объект', 'IP-адрес'].map(h => (
                    <th key={h} style={{ textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#94a3b8', padding: '12px 16px', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  ['04.07.2026 09:14', 'asanova.g', 'Вход в систему', '—', '10.11.22.5'],
                  ['04.07.2026 08:52', 'petrov.k', 'Просмотр отчёта', 'Сводный отчёт 2026', '10.11.22.8'],
                  ['03.07.2026 16:08', 'nurov.d', 'Экспорт данных', 'Реестр госзакупок', '10.11.22.3'],
                  ['03.07.2026 14:22', 'tastanov.e', 'Импорт данных', 'budget_2026_q1.xlsx', '10.11.22.9'],
                ].map((row, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #f8fafc' }}>
                    {row.map((cell, j) => <td key={j} style={{ padding: '12px 16px', fontSize: 13, color: j === 2 ? '#1e293b' : '#64748b' }}>{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
