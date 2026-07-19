import React from 'react'
import { useAppStore } from '../../stores/appStore'
import { useTheme } from '../../hooks/useTheme'
import { StatBox } from '../ui/StatBox'
import { useDashboard } from '../../api/queries'

const LAYERS = [
  { key:'admin',        label:'Административный', color:'#58a6ff' },
  { key:'budget',       label:'Бюджет',           color:'#3fb950' },
  { key:'procurement',  label:'Госзакупки',        color:'#d29922' },
  { key:'construction', label:'Инфраструктура',    color:'#bc8cff' },
  { key:'agro',         label:'АПК / Субсидии',   color:'#39d353' },
  { key:'risks',        label:'Риски / Крим.',     color:'#f85149' },
  { key:'osms',         label:'ОСМС',              color:'#ff7b72' },
  { key:'subsoil',      label:'Недропользование',  color:'#ffa657' },
] as const

export function LeftPanel() {
  const { activeLayers, toggleLayer, activeYear, setYear } = useAppStore()
  const { data } = useDashboard(activeYear)
  const t = useTheme()
  const fmt = (n: number) =>
    n >= 1e9 ? `₸${(n/1e9).toFixed(1)} млрд` : n >= 1e6 ? `₸${(n/1e6).toFixed(0)} млн` : '—'

  return (
    <aside style={{ background: t.surface, borderRight: `1px solid ${t.border}` }}
      className="w-[210px] flex-shrink-0 flex flex-col overflow-hidden transition-colors duration-200">
      <div style={{ borderBottom: `1px solid ${t.border}` }} className="p-3">
        <div style={{ color: t.textDim }} className="text-[10px] font-bold uppercase tracking-widest mb-2">Слои карты</div>
        {LAYERS.map(({ key, label, color }) => {
          const on = activeLayers[key as keyof typeof activeLayers]
          return (
            <div key={key} onClick={() => toggleLayer(key as any)}
              style={{ background: on ? 'rgba(31,111,235,0.1)' : undefined }}
              className="flex items-center gap-2 px-1.5 py-1 rounded cursor-pointer text-xs mb-0.5 hover:opacity-80 transition-all">
              <div style={{ background: color }} className="w-2 h-2 rounded-full flex-shrink-0"/>
              <span style={{ color: t.text }} className="flex-1">{label}</span>
              <div style={{ background: on ? '#1f6feb' : t.border }} className="w-7 h-3.5 rounded-full relative transition-colors">
                <div style={{ left: on ? 14 : 2 }} className="absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all shadow-sm"/>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ borderBottom: `1px solid ${t.border}` }} className="p-3">
        <div style={{ color: t.textDim }} className="text-[10px] font-bold uppercase tracking-widest mb-2">Год</div>
        <select value={activeYear} onChange={e => setYear(+e.target.value)}
          style={{ background: t.surface2, borderColor: t.border, color: t.text }}
          className="w-full border rounded text-xs px-2 py-1 outline-none">
          {[2026,2025,2024,2023,2022,2021].map(y => <option key={y}>{y}</option>)}
        </select>
      </div>
      <div className="p-3 overflow-y-auto flex-1">
        <div style={{ color: t.textDim }} className="text-[10px] font-bold uppercase tracking-widest mb-2">Показатели</div>
        <div className="grid grid-cols-2 gap-1.5">
          <StatBox label="Районов"      value={data?.district_count ?? '—'}/>
          <StatBox label="Бюджет"       value={data ? fmt(data.budget.total) : '—'} color="text-yellow-500"/>
          <StatBox label="Сумма рисков" value={data ? fmt(data.risks.total_amount) : '—'} color="text-red-500"/>
          <StatBox label="Материалов"   value={data?.risks.count ?? '—'} color="text-red-500"/>
          <StatBox label="В ЕРДР"       value={data?.risks.erdr_count ?? '—'} color="text-yellow-500"/>
          <StatBox label="Превенция"    value={data?.risks.prevention_count ?? '—'}/>
          <StatBox label="Завершено"    value={data?.risks.completed_count ?? '—'} color="text-green-500"/>
          <StatBox label="Закупки"      value={data ? fmt(data.procurement.total) : '—'}/>
        </div>
      </div>
    </aside>
  )
}
