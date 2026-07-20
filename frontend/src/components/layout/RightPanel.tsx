import React from 'react'
import { useAppStore } from '../../stores/appStore'
import { useTheme } from '../../hooks/useTheme'
import { useDashboard, useGeoObjects } from '../../api/queries'
import { ProgressBar } from '../ui/ProgressBar'
import { Badge } from '../ui/Badge'

const SPHERES: Record<string, string> = {
  construction:'Строительство', housing:'ЖКХ', roads:'Дороги',
  education:'Образование', healthcare:'Здравоохранение',
  agriculture:'АПК', social:'Соц. сфера', digitalization:'Цифровизация',
}
const STATUS_MAP: Record<string, string> = {
  erdr:'ЕРДР', prevention:'Превенция', analysis:'Анализ',
  in_progress:'В работе', completed:'Завершено',
}
const LEVEL: Record<string,'high'|'medium'|'low'> = { high:'high', medium:'medium', low:'low' }

export function RightPanel() {
  const { sidebarTab, setSidebarTab, activeYear } = useAppStore()
  const { data: dash } = useDashboard({ year: activeYear })
  const { data: risks } = useGeoObjects({ page_size: 5 })
  const t = useTheme()
  const fmt = (n: number) => n >= 1e9 ? `₸${(n/1e9).toFixed(1)} млрд` : n >= 1e6 ? `₸${(n/1e6).toFixed(0)} млн` : '—'

  const TABS = ['dashboard','risks','top'] as const
  const TAB_LABELS = { dashboard:'Дашборд', risks:'Риски', top:'ТОП' }

  return (
    <aside style={{ background: t.surface, borderLeft: `1px solid ${t.border}` }}
      className="w-[285px] flex-shrink-0 flex flex-col overflow-hidden transition-colors duration-200">
      {/* Tab bar */}
      <div style={{ borderBottom: `1px solid ${t.border}` }} className="flex flex-shrink-0">
        {TABS.map(tab => (
          <button key={tab} onClick={() => setSidebarTab(tab)}
            style={{ borderBottomColor: sidebarTab === tab ? '#1f6feb' : 'transparent', color: sidebarTab === tab ? '#1f6feb' : t.textDim }}
            className="flex-1 py-2 text-[11px] border-b-2 transition-colors hover:opacity-80">
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* DASHBOARD */}
        {sidebarTab === 'dashboard' && (
          <div className="p-3">
            <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mb-2">
              Освоение бюджета {activeYear}
            </div>
            {(dash?.budget.by_sphere ?? []).map(s => {
              const pct = s.allocated > 0 ? Math.round(s.spent / s.allocated * 100) : 0
              return (
                <div key={s.sphere} className="mb-3">
                  <div className="flex justify-between text-xs mb-0.5">
                    <span style={{ color: t.textDim }}>{SPHERES[s.sphere] ?? s.sphere}</span>
                    <span style={{ color: t.text }}>{pct}%</span>
                  </div>
                  <ProgressBar pct={pct}/>
                </div>
              )
            })}
            <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mt-4 mb-2">Риски по сферам</div>
            <div className="flex flex-wrap gap-1.5 mb-4">
              {(dash?.risks.by_sphere ?? []).slice(0, 5).map((s: any) => (
                <div key={s.sphere} className="bg-red-500/10 border border-red-500/30 rounded px-1.5 py-1 text-[10px] text-red-400">
                  {SPHERES[s.sphere] ?? s.sphere} {fmt(s.total)}
                </div>
              ))}
            </div>
            <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mb-2">Статусы материалов</div>
            <div className="grid grid-cols-3 gap-1.5">
              {([['Превенция', dash?.risks.prevention_count, 'text-yellow-500'],
                 ['В ЕРДР',    dash?.risks.erdr_count,       'text-red-500'],
                 ['Завершено', dash?.risks.completed_count,  'text-green-500']] as const).map(([l, v, c]) => (
                <div key={l} style={{ background: t.surface2, border: `1px solid ${t.border}` }} className="rounded-lg p-2 text-center">
                  <div className={`text-lg font-bold ${c}`}>{v ?? '—'}</div>
                  <div style={{ color: t.textDim }} className="text-[9px]">{l}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* RISKS */}
        {sidebarTab === 'risks' && (
          <div className="p-3">
            <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mb-2">Актуальные риски</div>
            {(risks?.results ?? []).map((r: any) => (
              <div key={r.id}
                style={{ background: t.surface2, border: `1px solid ${t.border}` }}
                className="rounded-lg p-2.5 mb-2 cursor-pointer hover:border-blue-500 transition-colors">
                <div className="flex justify-between items-start mb-1">
                  <span style={{ color: t.text }} className="text-xs font-semibold leading-tight">{r.sphere_display} — {r.district_name}</span>
                  <Badge level={LEVEL[r.level] ?? 'medium'} label={STATUS_MAP[r.status] ?? r.status}/>
                </div>
                <p style={{ color: t.textDim }} className="text-[10px] leading-snug mb-1.5">{r.description?.slice(0, 90)}…</p>
                <div className="flex justify-between text-[10px]">
                  <span style={{ color: t.textDim }}>{r.detected_at}</span>
                  <span className="text-red-500 font-semibold">{fmt(r.amount)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* TOP */}
        {sidebarTab === 'top' && (
          <div className="p-3">
            {[
              { title:'ТОП районов по рискам', items: dash?.top_districts ?? [], name: (d: any) => d.district__name, val: (d: any) => fmt(d.total_risk), valColor:'text-yellow-500' },
              { title:'ТОП поставщиков (риск)', items: dash?.top_suppliers ?? [], name: (d: any) => d.supplier_name, val: (d: any) => fmt(d.total), valColor:'text-red-500' },
              { title:'ТОП субсидий', items: dash?.top_subsidy_recipients ?? [], name: (d: any) => d.name, val: (d: any) => fmt(d.total), valColor:'text-gray-400' },
            ].map(section => (
              <div key={section.title}>
                <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mb-2 mt-3">{section.title}</div>
                {(section.items as any[]).map((item, i) => (
                  <div key={i} className="flex items-center gap-2 py-1.5 text-xs" style={{ borderBottom: `1px solid ${t.border}` }}>
                    <div style={{ background: t.surface2, color: t.textDim }} className="w-4 h-4 rounded-full flex items-center justify-center text-[9px]">{i+1}</div>
                    <span style={{ color: t.text }} className="flex-1 truncate">{section.name(item)}</span>
                    <span className={`${section.valColor} font-semibold`}>{section.val(item)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}
