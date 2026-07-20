import React, { useState } from 'react'
import { AlmatyMap } from '../components/map/AlmatyMap'
import { useAppStore } from '../stores/appStore'
import { useTerritoryRisk, useDashboard, useGeoObjects } from '../api/queries'

// Освоение бюджета по направлениям и риски по сферам — данные пока нет
// реального эндпоинта (нужен бюджетный слой, задача Асии, неделя 5+),
// оставлено как заглушка сознательно, не выдаём за реальное.
const BUDGET_SECTORS = [
  { label: 'АПК', value: 75, color: '#22c55e' },
  { label: 'Строительство', value: 81, color: '#22c55e' },
  { label: 'Цифровизация', value: 75, color: '#22c55e' },
  { label: 'Образование', value: 72, color: '#f59e0b' },
  { label: 'Здравоохранение', value: 77, color: '#22c55e' },
  { label: 'ЖКХ', value: 71, color: '#f59e0b' },
  { label: 'Дороги', value: 87, color: '#22c55e' },
  { label: 'Соц. сфера', value: 78, color: '#22c55e' },
]

const RISK_TAGS = [
  { label: 'agro', amount: '₸651 млн', color: '#f59e0b', bg: '#fefce8' },
  { label: 'budget', amount: '₸752 млн', color: '#dc2626', bg: '#fef2f2' },
  { label: 'Строительство', amount: '₸380 млн', color: '#dc2626', bg: '#fef2f2' },
  { label: 'oehs', amount: '₸1.1 млрд', color: '#dc2626', bg: '#fef2f2' },
  { label: 'procurement', amount: '₸626 млн', color: '#f59e0b', bg: '#fefce8' },
]

const riskLevelColor = (level: string | null) =>
  ({ low: '#22c55e', medium: '#f59e0b', high: '#f87171', critical: '#7f1d1d' } as any)[level || ''] || '#94a3b8'
const riskLevelLabel = (level: string | null) =>
  ({ low: 'Низкий', medium: 'Средний', high: 'Высокий', critical: 'Критический' } as any)[level || ''] || 'Нет данных'

const S: React.CSSProperties = { fontFamily: "'Inter', -apple-system, sans-serif" }

export function MapPage() {
  const [tab, setTab] = useState<'dashboard' | 'risks' | 'top'>('dashboard')
  const [showFilters, setShowFilters] = useState(false)
  const [year, setYear] = useState(2026)
  const { darkMode: darkMap, toggleDarkMode } = useAppStore()

  // Реальные данные слоя субсидий — заливка карты, топ районов,
  // топ получателей по риску и список высокорисковых объектов.
  const { data: riskGeo } = useTerritoryRisk({ layer: 'subsidies' })
  const { data: dashboard } = useDashboard({ layer: 'subsidies' })
  const { data: highRisk } = useGeoObjects({
    layer: 'subsidies', risk_level: 'high,critical', ordering: '-risk_score', page_size: 6,
  })

  const topDistricts = (riskGeo?.features ?? [])
    .filter((f: any) => f.properties.risk_score != null)
    .sort((a: any, b: any) => b.properties.risk_score - a.properties.risk_score)
    .slice(0, 7)
    .map((f: any) => ({
      name: f.properties.name_ru, score: f.properties.risk_score,
      color: riskLevelColor(f.properties.risk_level),
    }))

  return (
    <div style={{ ...S, display: 'flex', flexDirection: 'column', height: '100vh' }}>

      {/* ── Top bar ── */}
      <div style={{ height: 52, background: '#fff', borderBottom: '1px solid #e8edf4', display: 'flex', alignItems: 'center', padding: '0 16px', gap: 8, flexShrink: 0 }}>
        <div style={{ position: 'relative', flex: 1, maxWidth: 340 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)' }}>
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input placeholder="Поиск по БИН, ФИО, объекту..." style={{ width: '100%', padding: '7px 12px 7px 30px', borderRadius: 20, border: '1px solid #e2e8f0', background: '#f8fafc', fontSize: 13, color: '#475569', outline: 'none', boxSizing: 'border-box' }}/>
        </div>
        <div style={{ flex: 1 }}/>

        <button style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 20, border: '1px solid #e2e8f0', background: '#fff', fontSize: 13, color: '#475569', cursor: 'pointer', fontWeight: 500 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#475569" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="8 17 12 21 16 17"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"/></svg>
          Экспорт
        </button>

        <button onClick={() => setShowFilters(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 20, border: showFilters ? '1px solid #1d6fbc' : '1px solid #e2e8f0', background: showFilters ? '#eff6ff' : '#fff', fontSize: 13, color: showFilters ? '#1d6fbc' : '#475569', cursor: 'pointer', fontWeight: 500 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={showFilters ? '#1d6fbc' : '#475569'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/></svg>
          Фильтры
        </button>

        <button style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 20, border: '1px solid #f59e0b', background: '#fefce8', fontSize: 13, color: '#b45309', cursor: 'pointer', fontWeight: 600 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
          Источники
        </button>

        <button onClick={toggleDarkMode} title={darkMap ? 'Светлая карта' : 'Тёмная карта'} style={{ width: 34, height: 34, borderRadius: '50%', border: darkMap ? '1px solid #1d6fbc' : '1px solid #e2e8f0', background: darkMap ? '#0d1b2a' : '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', transition: 'all 0.2s' }}>
          {darkMap
            ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#4aa8e8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#475569" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          }
        </button>

        <button style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 20, border: '1px solid #e2e8f0', background: '#fff', fontSize: 13, color: '#475569', cursor: 'pointer', fontWeight: 500 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#475569" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Аналитик
        </button>
      </div>

      {/* ── Body row: [filters] [map + right panel] ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

        {/* Left filter panel */}
        {showFilters && (
          <div style={{ width: 280, flexShrink: 0, background: '#fff', borderRight: '1px solid #e8edf4', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', borderBottom: '1px solid #e8edf4', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 15, fontWeight: 700, color: '#1e293b' }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1e293b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="11" y1="18" x2="13" y2="18"/></svg>
                Фильтры
              </div>
              <button onClick={() => setShowFilters(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', fontSize: 20, lineHeight: 1, padding: '0 2px' }}>×</button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
              {/* Период */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Период</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 5, marginBottom: 10 }}>
                  {[2020, 2021, 2022, 2023, 2024, 2025, 2026].map(y => (
                    <button key={y} onClick={() => setYear(y)} style={{ padding: '7px 4px', borderRadius: 7, fontSize: 12, fontWeight: 500, border: year === y ? '2px solid #1d6fbc' : '1.5px solid #e2e8f0', background: year === y ? '#eff6ff' : '#fff', color: year === y ? '#1d6fbc' : '#475569', cursor: 'pointer' }}>{y}</button>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                  <input type="text" defaultValue="01/01/2026" key={year} style={{ flex: 1, padding: '8px 10px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 12, color: '#475569', outline: 'none' }}/>
                  <input type="text" defaultValue="30/06/2026" style={{ flex: 1, padding: '8px 10px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 12, color: '#475569', outline: 'none' }}/>
                </div>
                <button style={{ width: '100%', padding: '8px', borderRadius: 8, border: '1.5px dashed #c0ccd8', background: 'none', fontSize: 13, color: '#64748b', cursor: 'pointer' }}>Сравнить периоды</button>
              </div>

              {/* Территория */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Территория</div>
                <select style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, color: '#1e293b', background: '#fff', outline: 'none' }}>
                  <option>Все районы</option>
                  <option>Карасайский р-н</option><option>Талгарский р-н</option><option>Илийский р-н</option>
                  <option>Енбекшиказахский р-н</option><option>Жамбылский р-н</option><option>Балхашский р-н</option>
                  <option>Уйгурский р-н</option><option>Райымбекский р-н</option><option>Алакольский р-н</option>
                </select>
              </div>

              {/* Отрасль */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Отрасль</div>
                <select style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, color: '#1e293b', background: '#fff', outline: 'none' }}>
                  <option>Все отрасли</option><option>АПК</option><option>Строительство</option>
                  <option>Образование</option><option>Здравоохранение</option><option>ЖКХ</option>
                  <option>Дороги</option><option>Цифровизация</option><option>Соц. сфера</option>
                </select>
              </div>

              {/* Уровень риска */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Уровень риска</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {[
                    { label: 'Низкий', color: '#22c55e' },
                    { label: 'Средний', color: '#f59e0b' },
                    { label: 'Высокий', color: '#f87171' },
                    { label: 'Критический', color: '#dc2626' },
                    { label: 'Нет данных', color: '#94a3b8' },
                  ].map(r => (
                    <label key={r.label} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', fontSize: 13, fontWeight: 500, color: '#1e293b' }}>
                      <input type="checkbox" defaultChecked style={{ width: 16, height: 16, accentColor: r.color, cursor: 'pointer' }}/>
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: r.color, flexShrink: 0 }}/>
                      {r.label}
                    </label>
                  ))}
                </div>
              </div>

              {/* Сумма */}
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Сумма, млрд ₸</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input type="number" defaultValue={0} style={{ flex: 1, padding: '8px 10px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, color: '#1e293b', outline: 'none' }}/>
                  <span style={{ color: '#94a3b8' }}>—</span>
                  <input type="number" defaultValue={100} style={{ flex: 1, padding: '8px 10px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, color: '#1e293b', outline: 'none' }}/>
                </div>
              </div>

              {/* Статус объекта */}
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Статус объекта</div>
                <select style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, color: '#1e293b', background: '#fff', outline: 'none' }}>
                  <option>Все статусы</option><option>В работе</option><option>Завершён</option>
                  <option>Проверка</option><option>Приостановлен</option>
                </select>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 8, padding: '12px 16px', borderTop: '1px solid #e8edf4', flexShrink: 0 }}>
              <button style={{ flex: 1, padding: '10px', borderRadius: 8, border: '1.5px solid #e2e8f0', background: '#fff', fontSize: 13, fontWeight: 600, color: '#475569', cursor: 'pointer' }}>Сбросить</button>
              <button style={{ flex: 1.5, padding: '10px', borderRadius: 8, border: 'none', background: '#1d6fbc', fontSize: 13, fontWeight: 600, color: '#fff', cursor: 'pointer' }}>Применить</button>
            </div>
          </div>
        )}

        {/* Map area */}
        <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
          <div style={{ position: 'absolute', inset: 0 }}>
            <AlmatyMap data={riskGeo}/>
          </div>

          {/* Right floating panel */}
          <div style={{ position: 'absolute', top: 12, right: 12, bottom: 12, width: 280, background: '#fff', borderRadius: 12, boxShadow: '0 4px 24px rgba(0,0,0,0.12)', display: 'flex', flexDirection: 'column', zIndex: 1000, overflow: 'hidden' }}>
            <div style={{ display: 'flex', borderBottom: '1px solid #e8edf4', flexShrink: 0 }}>
              {(['dashboard', 'risks', 'top'] as const).map((t, i) => {
                const labels = ['Дашборд', 'Риски', 'ТОП']
                const active = tab === t
                return (
                  <button key={t} onClick={() => setTab(t)} style={{ flex: 1, padding: '12px 4px', fontSize: 13, fontWeight: active ? 600 : 400, color: active ? '#1d6fbc' : '#94a3b8', background: 'none', border: 'none', borderBottom: active ? '2px solid #1d6fbc' : '2px solid transparent', cursor: 'pointer', marginBottom: -1 }}>{labels[i]}</button>
                )
              })}
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
              {tab === 'dashboard' && (
                <>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12 }}>Освоение бюджета 2026</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
                    {BUDGET_SECTORS.map(s => (
                      <div key={s.label}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 12, color: '#475569' }}>{s.label}</span>
                          <span style={{ fontSize: 12, fontWeight: 600, color: '#1e293b' }}>{s.value}%</span>
                        </div>
                        <div style={{ height: 5, background: '#f1f5f9', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${s.value}%`, height: '100%', background: s.color, borderRadius: 3 }}/>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>Риски по сферам</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
                    {RISK_TAGS.map(r => (
                      <span key={r.label} style={{ fontSize: 11, fontWeight: 500, padding: '4px 10px', borderRadius: 20, background: r.bg, color: r.color, border: `1px solid ${r.color}33` }}>{r.label} {r.amount}</span>
                    ))}
                  </div>

                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>Статусы материалов</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                    {[{ count: 15, label: 'Превенция', color: '#f59e0b' }, { count: 17, label: 'В ЕРДР', color: '#dc2626' }, { count: 15, label: 'Завершено', color: '#22c55e' }].map(s => (
                      <div key={s.label} style={{ background: '#f8fafc', borderRadius: 10, padding: '12px 8px', textAlign: 'center', border: '1px solid #f1f5f9' }}>
                        <div style={{ fontSize: 22, fontWeight: 700, color: s.color, lineHeight: 1.2 }}>{s.count}</div>
                        <div style={{ fontSize: 10, color: '#64748b', marginTop: 4, lineHeight: 1.3 }}>{s.label}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}

              {tab === 'risks' && (
                <>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12 }}>Получатели субсидий с высоким риском</div>
                  {(highRisk?.results ?? []).length === 0 && (
                    <div style={{ fontSize: 12, color: '#94a3b8' }}>Нет объектов с высоким/критическим риском</div>
                  )}
                  {(highRisk?.results ?? []).map((o: any) => {
                    const isCrit = o.risk_level === 'critical'
                    return (
                      <div key={o.id} style={{ padding: '10px 0', borderBottom: '1px solid #f1f5f9' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: '#1e293b', marginBottom: 2, lineHeight: 1.4 }}>{o.name}</div>
                            <div style={{ fontSize: 11, color: '#94a3b8' }}>{o.territory_name}</div>
                          </div>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20, flexShrink: 0, background: isCrit ? '#fef2f2' : '#fff7ed', color: isCrit ? '#dc2626' : '#ea580c' }}>{riskLevelLabel(o.risk_level)}</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>Сумма: ₸{o.paid_total != null ? (o.paid_total / 1e6).toLocaleString('ru-RU', {maximumFractionDigits: 1}) + ' млн' : '—'}</div>
                      </div>
                    )
                  })}
                </>
              )}

              {tab === 'top' && (
                <>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 12 }}>Рейтинг районов по риску (субсидии)</div>
                  {topDistricts.map((d: any, i: number) => (
                    <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
                      <div style={{ width: 22, height: 22, borderRadius: '50%', background: i < 3 ? '#1d6fbc' : '#f1f5f9', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, color: i < 3 ? '#fff' : '#94a3b8', flexShrink: 0 }}>{i + 1}</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 500, color: '#1e293b', marginBottom: 4 }}>{d.name}</div>
                        <div style={{ height: 4, background: '#f1f5f9', borderRadius: 2, overflow: 'hidden' }}>
                          <div style={{ width: `${d.score}%`, height: '100%', background: d.color, borderRadius: 2 }}/>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: d.color, flexShrink: 0, minWidth: 28, textAlign: 'right' }}>{d.score}</div>
                    </div>
                  ))}

                  <div style={{ marginTop: 20 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>Топ получателей субсидий по риску</div>
                    {(dashboard?.top_risk ?? []).map((s: any) => (
                      <div key={s.id} style={{ padding: '8px 0', borderBottom: '1px solid #f1f5f9' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: 12, fontWeight: 500, color: '#1e293b' }}>{s.name}</span>
                          <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 20, background: s.risk_level === 'high' || s.risk_level === 'critical' ? '#fef2f2' : '#fff7ed', color: s.risk_level === 'high' || s.risk_level === 'critical' ? '#dc2626' : '#ea580c' }}>{riskLevelLabel(s.risk_level)}</span>
                        </div>
                        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{s.territory_name} • R={s.risk_score}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
