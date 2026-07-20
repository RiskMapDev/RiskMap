import React, { useState } from 'react'
import { AppTopBar } from '../components/layout/AppTopBar'

function ReportIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
}
function MapPinIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
}
function BuildingIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
}
function HardHatIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 18a1 1 0 0 0 1 1h18a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1H3a1 1 0 0 0-1 1v2z"/><path d="M10 10V5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v5"/><path d="M4 15v-3a8 8 0 0 1 16 0v3"/></svg>
}
function BarChartIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
}
function AlertIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
}
function TrophyIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="8 22 12 18 16 22"/><path d="M7 2h10v5a5 5 0 0 1-5 5 5 5 0 0 1-5-5V2z"/><path d="M7 6H4a2 2 0 0 0-2 2v1a2 2 0 0 0 2 2h3"/><path d="M17 6h3a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2h-3"/><line x1="12" y1="13" x2="12" y2="18"/></svg>
}
function ShieldIcon({ color }: { color: string }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
}

const REPORTS = [
  { key: 'region', title: 'Сводный отчёт по региону', desc: 'Комплексный анализ рисков, бюджета и госзакупок по всей Алматинской области', Icon: ReportIcon, color: '#1d6fbc', bg: '#eff6ff', tags: ['Бюджет', 'Риски', 'Закупки'] },
  { key: 'territory', title: 'Отчёт по территории', desc: 'Детальный анализ по выбранному району: объекты, показатели, динамика', Icon: MapPinIcon, color: '#7c3aed', bg: '#fdf4ff', tags: ['Район', 'Объекты', 'Динамика'] },
  { key: 'org', title: 'Справка по организации', desc: 'Профиль организации: договоры, риски, связи с другими субъектами', Icon: BuildingIcon, color: '#0891b2', bg: '#f0f9ff', tags: ['Организация', 'Контракты'] },
  { key: 'object', title: 'Отчёт по объекту/проекту', desc: 'Мониторинг отдельного строительного или инфраструктурного объекта', Icon: HardHatIcon, color: '#16a34a', bg: '#f0fdf4', tags: ['Объект', 'Прогресс'] },
  { key: 'industry', title: 'Анализ по отрасли', desc: 'Сравнительный анализ рисков и расходов в разрезе отраслей экономики', Icon: BarChartIcon, color: '#ea580c', bg: '#fff7ed', tags: ['Отрасль', 'Сравнение'] },
  { key: 'risk_cat', title: 'Отчёт по категории риска', desc: 'Перечень объектов по типу выявленного риска с рекомендациями', Icon: AlertIcon, color: '#dc2626', bg: '#fef2f2', tags: ['Риски', 'Рекомендации'] },
  { key: 'ratings', title: 'Рейтинги территорий и отраслей', desc: 'Сводный рейтинг районов и отраслей по индексу эффективности', Icon: TrophyIcon, color: '#ca8a04', bg: '#fefce8', tags: ['Рейтинг', 'Индекс'] },
  { key: 'highrisk', title: 'Перечень высокорискных объектов', desc: 'Список объектов с критическим и высоким уровнем риска для контроля', Icon: ShieldIcon, color: '#be185d', bg: '#fdf2f8', tags: ['Критический', 'Высокий'] },
]

export function ReportsPage() {
  const [generating, setGenerating] = useState<string | null>(null)

  const generate = (key: string) => {
    setGenerating(key)
    setTimeout(() => setGenerating(null), 2000)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f4f6f9', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      <AppTopBar title="Отчёты"/>
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>Отчёты</h1>
            <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>Формирование аналитических справок и сводных документов</p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <select style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, color: '#475569', background: '#fff' }}>
              <option>2026 год</option>
              <option>2025 год</option>
              <option>2024 год</option>
              <option>2023 год</option>
              <option>2022 год</option>
              <option>2021 год</option>
              <option>2020 год</option>
            </select>
            <select style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, color: '#475569', background: '#fff' }}>
              <option>Все районы</option>
              <option>Карасайский р-н</option>
              <option>Талгарский р-н</option>
              <option>Илийский р-н</option>
            </select>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
          {REPORTS.map(r => (
            <div key={r.key} style={{ background: '#fff', borderRadius: 12, padding: '22px', border: '1px solid #e8edf4', display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ width: 48, height: 48, borderRadius: 12, background: r.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <r.Icon color={r.color}/>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#1e293b', marginBottom: 8, lineHeight: 1.4 }}>{r.title}</div>
                <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.6, marginBottom: 12 }}>{r.desc}</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {r.tags.map(tag => (
                    <span key={tag} style={{ fontSize: 10, fontWeight: 600, padding: '3px 8px', borderRadius: 20, background: r.bg, color: r.color }}>{tag}</span>
                  ))}
                </div>
              </div>
              <button onClick={() => generate(r.key)} style={{
                width: '100%', padding: '10px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                background: generating === r.key ? r.bg : r.color,
                color: generating === r.key ? r.color : '#fff',
                border: `1px solid ${r.color}`, cursor: 'pointer', transition: 'all 0.2s'
              }}>
                {generating === r.key ? 'Формирование...' : 'Сформировать'}
              </button>
            </div>
          ))}
        </div>

        <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4', marginTop: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 14 }}>Недавно сформированные отчёты</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                {['Отчёт', 'Параметры', 'Дата формирования', 'Пользователь', ''].map(h => (
                  <th key={h} style={{ textAlign: 'left', fontSize: 10, fontWeight: 600, color: '#94a3b8', padding: '0 12px 10px', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                ['Сводный отчёт по региону', '2026 год, все районы', '04.07.2026 14:22', 'Асанова Г.М.'],
                ['Отчёт по территории', 'Карасайский р-н, 2026', '03.07.2026 09:15', 'Нуров Д.К.'],
                ['Рейтинги территорий', '2026 год', '01.07.2026 16:40', 'Тастанов Е.А.'],
              ].map((row, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f8fafc' }}>
                  <td style={{ padding: '10px 12px', fontSize: 13, fontWeight: 500, color: '#1e293b' }}>{row[0]}</td>
                  <td style={{ padding: '10px 12px', fontSize: 12, color: '#64748b' }}>{row[1]}</td>
                  <td style={{ padding: '10px 12px', fontSize: 12, color: '#64748b' }}>{row[2]}</td>
                  <td style={{ padding: '10px 12px', fontSize: 12, color: '#64748b' }}>{row[3]}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <button style={{ fontSize: 12, color: '#1d6fbc', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 500 }}>Скачать</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
