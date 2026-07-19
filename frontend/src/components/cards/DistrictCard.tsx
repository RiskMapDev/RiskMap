import React, { useState } from 'react'
import { X, Building2, DollarSign, ShoppingCart, Hammer, AlertTriangle, GitBranch } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { DraggableGraph } from '../graph/DraggableGraph'
import { ProgressBar } from '../ui/ProgressBar'
import { useTheme } from '../../hooks/useTheme'

const TABS = [
  { id:'info',    label:'Сведения',  icon:Building2 },
  { id:'budget',  label:'Бюджет',    icon:DollarSign },
  { id:'gos',     label:'Закупки',   icon:ShoppingCart },
  { id:'objects', label:'Объекты',   icon:Hammer },
  { id:'risks',   label:'Риски',     icon:AlertTriangle },
  { id:'graph',   label:'Граф',      icon:GitBranch },
]

const INFO: Record<string, { pop:number; area:number; budget:string; official:string; risk:'high'|'medium'|'low' }> = {
  Karasai:  { pop:312400,  area:4628,  budget:'₸78.4 млрд', official:'Асанов Б.М.',        risk:'high'   },
  Ile:      { pop:289400,  area:8620,  budget:'₸63.2 млрд', official:'Мұхамеджанов С.Е.',  risk:'high'   },
  Talgar:   { pop:198200,  area:5040,  budget:'₸41.8 млрд', official:'Жасыбеков Р.Д.',     risk:'medium' },
  Enbek:    { pop:156800,  area:6212,  budget:'₸33.0 млрд', official:'—',                  risk:'medium' },
  Almaty:   { pop:2150000, area:682,   budget:'₸312 млрд',  official:'—',                  risk:'medium' },
  Zhambyl:  { pop:88400,   area:11340, budget:'₸18.6 млрд', official:'—',                  risk:'low'    },
  Balkhash: { pop:52100,   area:73800, budget:'₸11.0 млрд', official:'—',                  risk:'medium' },
  Aksu:     { pop:94300,   area:9600,  budget:'₸19.8 млрд', official:'—',                  risk:'low'    },
  Uygur:    { pop:71200,   area:5780,  budget:'₸15.0 млрд', official:'—',                  risk:'medium' },
  Raiymbek: { pop:38600,   area:22160, budget:'₸8.1 млрд',  official:'—',                  risk:'low'    },
}

const BUDGET_ROWS = [
  { sphere:'Строительство', pct:78 }, { sphere:'Дороги',         pct:55 },
  { sphere:'Образование',   pct:54 }, { sphere:'Здравоохранение',pct:86 },
  { sphere:'ЖКХ',           pct:61 }, { sphere:'АПК',            pct:73 },
  { sphere:'Соц. сфера',    pct:32 },
]

export function DistrictCard({ districtKey, name, onClose }: { districtKey:string; name:string; onClose:()=>void }) {
  const [tab, setTab] = useState('info')
  const info = INFO[districtKey] ?? { pop:0, area:0, budget:'—', official:'—', risk:'low' as const }
  const t = useTheme()

  const cell = (label: string, value: string, color?: string) => (
    <div key={label} style={{ background: t.surface2, border: `1px solid ${t.border}` }} className="rounded-lg p-2.5">
      <div style={{ color: t.textDim }} className="text-[10px] mb-1">{label}</div>
      <div className={`text-sm font-bold ${color ?? ''}`} style={{ color: color ? undefined : t.text }}>{value}</div>
    </div>
  )

  return (
    <div className="absolute inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div style={{ background: t.surface, border: `1px solid ${t.border}` }}
        className="rounded-xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">

        {/* Header */}
        <div style={{ borderBottom: `1px solid ${t.border}` }} className="flex items-start gap-3 p-4">
          <div className="flex-1">
            <div style={{ color: t.text }} className="text-base font-bold">{name}</div>
            <div style={{ color: t.textDim }} className="text-xs mt-0.5">Алматинская область</div>
          </div>
          <Badge level={info.risk} label={info.risk==='high'?'Высокий риск':info.risk==='medium'?'Средний риск':'Низкий риск'}/>
          <button onClick={onClose} style={{ color: t.textDim }} className="hover:text-red-400 ml-2 transition-colors"><X size={18}/></button>
        </div>

        {/* Tabs */}
        <div style={{ borderBottom: `1px solid ${t.border}` }} className="flex overflow-x-auto flex-shrink-0">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setTab(id)}
              style={{ borderBottomColor: tab===id ? '#1f6feb' : 'transparent', color: tab===id ? '#1f6feb' : t.textDim }}
              className="flex items-center gap-1.5 px-3 py-2 text-xs whitespace-nowrap border-b-2 transition-colors hover:opacity-80">
              <Icon size={12}/> {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">

          {/* INFO */}
          {tab==='info' && (
            <div>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {cell('Население', info.pop.toLocaleString())}
                {cell('Площадь', `${info.area.toLocaleString()} км²`)}
                {cell('Бюджет 2024', info.budget)}
                {cell('Аким', info.official)}
              </div>
              <div style={{ color: t.textDim }} className="text-[10px] font-semibold uppercase tracking-wide mb-2">Должностные лица</div>
              <table className="w-full text-xs">
                <thead><tr style={{ color: t.textDim, borderBottom: `1px solid ${t.border}` }}>
                  <th className="text-left py-1.5 px-2">Должность</th>
                  <th className="text-left py-1.5 px-2">ФИО</th>
                </tr></thead>
                <tbody>
                  <tr style={{ borderBottom: `1px solid ${t.border}` }}>
                    <td className="py-1.5 px-2" style={{ color: t.textDim }}>Аким района</td>
                    <td className="py-1.5 px-2" style={{ color: t.text }}>{info.official}</td>
                  </tr>
                  <tr>
                    <td className="py-1.5 px-2" style={{ color: t.textDim }}>Зам. акима</td>
                    <td className="py-1.5 px-2" style={{ color: t.text }}>—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          {/* BUDGET */}
          {tab==='budget' && (
            <div>
              <div className="grid grid-cols-3 gap-2 mb-4">
                {cell('Бюджет', info.budget)}
                {cell('Освоено', '₸52.1 млрд (66%)', 'text-yellow-500')}
                {cell('Остаток', '₸26.3 млрд', 'text-red-500')}
              </div>
              {BUDGET_ROWS.map(s => (
                <div key={s.sphere} className="mb-3">
                  <div className="flex justify-between text-xs mb-0.5">
                    <span style={{ color: t.textDim }}>{s.sphere}</span>
                    <span style={{ color: s.pct>=75?'#3fb950':s.pct>=50?'#d29922':'#f85149' }}>{s.pct}%</span>
                  </div>
                  <ProgressBar pct={s.pct}/>
                </div>
              ))}
              {!t.dark && (
                <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mt-3 text-xs text-orange-700">
                  Риск неосвоения по «Соц. сфере» — 32% при окончании года через 2 месяца.
                </div>
              )}
              {t.dark && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mt-3 text-xs text-red-300">
                  Риск неосвоения по «Соц. сфере» — 32% при окончании года через 2 месяца.
                </div>
              )}
            </div>
          )}

          {/* ZAKUPKI */}
          {tab==='gos' && (
            <div>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {cell('Всего закупок','247')}
                {cell('Сумма','₸34.7 млрд')}
                {cell('Один поставщик','68%','text-red-500')}
                {cell('Сумма риска','₸4.1 млрд','text-red-500')}
              </div>
              <table className="w-full text-xs">
                <thead><tr style={{ color: t.textDim, borderBottom: `1px solid ${t.border}` }}>
                  <th className="text-left py-1.5 px-2">Поставщик</th>
                  <th className="text-left py-1.5 px-2">Сумма</th>
                  <th className="py-1.5 px-2">Риск</th>
                </tr></thead>
                <tbody>
                  {[['ТОО «Альфа Строй»','₸1.2 млрд','Аффил.','high'],['ТОО «Меридиан»','₸890 млн','Дробление','high'],
                    ['ТОО «Даму Регион»','₸670 млн','1 пост.','medium'],['ИП Сейтқали Б.','₸540 млн','Завышение','medium']].map(([s,a,r,lv])=>(
                    <tr key={s} style={{ borderBottom: `1px solid ${t.border}`, color: t.text }}>
                      <td className="py-1.5 px-2">{s}</td>
                      <td className="py-1.5 px-2">{a}</td>
                      <td className="py-1.5 px-2"><Badge level={lv as any} label={r}/></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* OBJECTS */}
          {tab==='objects' && (
            <table className="w-full text-xs">
              <thead><tr style={{ color: t.textDim, borderBottom: `1px solid ${t.border}` }}>
                <th className="text-left py-1.5 px-2">Объект</th>
                <th className="text-left py-1.5 px-2">Стоимость</th>
                <th className="text-left py-1.5 px-2">%</th>
                <th className="py-1.5 px-2">Риск</th>
              </tr></thead>
              <tbody>
                {[['Школа №4, Қаскелең','₸2.1 млрд',62,'high'],['ФАП, Боралдай','₸180 млн',91,'low'],
                  ['Дорога А-357','₸890 млн',28,'high'],['Водовод Қаскелең','₸340 млн',55,'medium'],
                  ['Дом культуры','₸420 млн',88,'low']].map(([n,s,p,lv])=>(
                  <tr key={n as string} style={{ borderBottom: `1px solid ${t.border}`, color: t.text }}>
                    <td className="py-1.5 px-2">{n}</td>
                    <td className="py-1.5 px-2" style={{ color: t.textDim }}>{s}</td>
                    <td className="py-1.5 px-2" style={{ color: +p>=75?'#3fb950':+p>=50?'#d29922':'#f85149' }}>{p}%</td>
                    <td className="py-1.5 px-2"><Badge level={lv as any} label={lv==='high'?'Выс.':lv==='medium'?'Ср.':'Низ.'}/></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* RISKS */}
          {tab==='risks' && (
            <div className="space-y-2">
              {[
                { title:'Фиктивные ЭСФ',       status:'ЕРДР',           level:'high'   as const, desc:'3 аффилированных ТОО — фиктивный оборот ₸1.2 млрд. Учредитель — Жаксыбеков Р.Т.', amount:'₸1.2 млрд' },
                { title:'Завышение ПСД школы №4', status:'В производстве', level:'high' as const, desc:'Завышение стоимости на ₸340 млн, аффилированность подрядчика.',                     amount:'₸340 млн'   },
              ].map(r => (
                <div key={r.title} style={{ background: t.surface2, border: `1px solid ${t.border}` }} className="rounded-lg p-3">
                  <div className="flex justify-between items-start mb-1.5">
                    <span style={{ color: t.text }} className="text-sm font-semibold">{r.title}</span>
                    <Badge level={r.level} label={r.status}/>
                  </div>
                  <p style={{ color: t.textDim }} className="text-xs mb-2">{r.desc}</p>
                  <div className="flex justify-between text-[10px]">
                    <span style={{ color: t.textDim }}>2024</span>
                    <span className="text-red-500 font-semibold">{r.amount}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* GRAPH */}
          {tab==='graph' && (
            <div>
              <div style={{ color: t.textDim }} className="text-xs mb-3">
                Граф аффилированности — <span className="text-blue-500">перетащите узлы мышкой</span>
              </div>
              <DraggableGraph/>
              <div className="flex gap-4 mt-2 text-[10px]" style={{ color: t.textDim }}>
                <span><span className="text-red-500">——</span> Учредитель / аффил.</span>
                <span><span style={{ color: t.textDim }}>——</span> Контракт</span>
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
