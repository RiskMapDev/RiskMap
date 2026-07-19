import React from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar
} from 'recharts'
import { AppTopBar } from '../components/layout/AppTopBar'
import { useDashboard } from '../api/queries'

const lineData = [
  { month: 'Янв', budget: 6.2, procurement: 1.8, subsidies: 0.4 },
  { month: 'Фев', budget: 5.8, procurement: 2.1, subsidies: 0.5 },
  { month: 'Мар', budget: 7.1, procurement: 2.4, subsidies: 0.6 },
  { month: 'Апр', budget: 6.5, procurement: 2.0, subsidies: 0.5 },
  { month: 'Май', budget: 8.2, procurement: 2.8, subsidies: 0.7 },
  { month: 'Июн', budget: 7.6, procurement: 2.5, subsidies: 0.6 },
  { month: 'Июл', budget: 9.0, procurement: 3.1, subsidies: 0.8 },
]

const pieData = [
  { name: 'Низкий', value: 52, color: '#22c55e' },
  { name: 'Средний', value: 35, color: '#f59e0b' },
  { name: 'Высокий', value: 10, color: '#f87171' },
  { name: 'Критический', value: 3, color: '#dc2626' },
]

const districtData = [
  { name: 'Карасайский', score: 87 },
  { name: 'Талгарский', score: 74 },
  { name: 'Илийский', score: 68 },
  { name: 'Енбекшиказахский', score: 61 },
  { name: 'Жамбылский', score: 55 },
  { name: 'Балхашский', score: 48 },
  { name: 'Уйгурский', score: 42 },
]

const PROBLEM_OBJECTS = [
  { id: 1, name: 'Школа №12 — капремонт', district: 'Карасайский р-н', type: 'Строительство', risk: 'Высокий', amount: '124.5 млн' },
  { id: 2, name: 'Водопровод с. Отеген', district: 'Илийский р-н', type: 'Инфраструктура', risk: 'Критический', amount: '89.2 млн' },
  { id: 3, name: 'ФАП с. Бесагаш', district: 'Талгарский р-н', type: 'Здравоохранение', risk: 'Высокий', amount: '42.0 млн' },
  { id: 4, name: 'Дорога Кегень—Текес', district: 'Райымбекский р-н', type: 'Дороги', risk: 'Средний', amount: '312.8 млн' },
]

const RECENT_CONTRACTS = [
  { num: 'ДГЗ-2026-1842', subject: 'Строительство школы с. Жетыген', amount: '487.3 млн', customer: 'ГУ Карасайский р-н', supplier: 'ТОО КазСтройИнвест', status: 'В работе', risk: 'Высокий' },
  { num: 'ДГЗ-2026-1756', subject: 'Реконструкция водопровода', amount: '234.1 млн', customer: 'ГУ Илийский р-н', supplier: 'ТОО АкваСтрой', status: 'Завершён', risk: 'Низкий' },
  { num: 'ДГЗ-2026-1698', subject: 'Поставка медоборудования', amount: '98.6 млн', customer: 'ЦРБ Талгарский р-н', supplier: 'ТОО МедТехника', status: 'В работе', risk: 'Средний' },
  { num: 'ДГЗ-2026-1601', subject: 'Субсидии на с/х технику', amount: '156.4 млн', customer: 'УСХ Алматинской обл.', supplier: 'Получатели субсидий', status: 'Проверка', risk: 'Критический' },
]

const riskColor = (r: string) => ({ 'Высокий': '#f87171', 'Критический': '#dc2626', 'Средний': '#f59e0b', 'Низкий': '#22c55e' }[r] || '#94a3b8')
const statusColor = (s: string) => ({ 'В работе': { bg: '#eff6ff', color: '#1d6fbc' }, 'Завершён': { bg: '#f0fdf4', color: '#16a34a' }, 'Проверка': { bg: '#fefce8', color: '#ca8a04' } }[s] || { bg: '#f1f5f9', color: '#64748b' })

function KpiCard({ label, value, sub, iconBg, icon }: { label: string; value: string; sub?: string; iconBg: string; icon: React.ReactNode }) {
  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: '18px 20px', border: '1px solid #e8edf4', display: 'flex', alignItems: 'flex-start', gap: 14 }}>
      <div style={{ width: 44, height: 44, borderRadius: 10, background: iconBg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        {icon}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', lineHeight: 1.2 }}>{value}</div>
        {sub && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{sub}</div>}
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { data } = useDashboard()
  const budget = data?.budget_total ? `${(data.budget_total / 1e9).toFixed(2)} млрд` : '45.2 млрд'
  const procTotal = data?.procurement_total ? `${(data.procurement_total / 1e9).toFixed(2)} млрд` : '12.85 млрд'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f4f6f9', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      <AppTopBar title="Дашборд"/>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        {/* Page title */}
        <div style={{ marginBottom: 20 }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>Дашборд</h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>Аналитинская область — сводная информация за 2026 год</p>
        </div>

        {/* KPI Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 20 }}>
          <KpiCard label="Бюджет региона" value={budget} sub="тыс. тенге" iconBg="#eff6ff" icon={<BudgetIcon/>}/>
          <KpiCard label="Госзакупки" value={procTotal} sub={`${data?.contract_count ?? 995} договоров`} iconBg="#f0fdf4" icon={<ProcIcon/>}/>
          <KpiCard label="Субсидии" value="3.42 млрд" sub="346 получателей" iconBg="#fefce8" icon={<SubsIcon/>}/>
          <KpiCard label="Инфраструктурных проектов" value={String(data?.construction_count ?? 47)} sub="Объектов" iconBg="#fdf4ff" icon={<InfraIcon/>}/>
          <KpiCard label="Хозяйствующих субъектов" value="12 456" sub="Организации и ИП" iconBg="#fff7ed" icon={<OrgIcon/>}/>
          <KpiCard label="Высокий / Критический риск" value={String(data?.high_risk_count ?? 127)} sub="Объектов требуют внимания" iconBg="#fef2f2" icon={<RiskIcon/>}/>
          <KpiCard label="Сумма финансовых рисков" value="8.75 млрд" sub="Потенциальные потери" iconBg="#fff1f2" icon={<MoneyRiskIcon/>}/>
          <KpiCard label="Аналитических материалов" value={String(data?.risk_material_count ?? 23)} sub="Актуальных" iconBg="#f0f9ff" icon={<DocIcon/>}/>
        </div>

        {/* Charts row */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 14, marginBottom: 20 }}>
          {/* Line chart */}
          <div style={{ background: '#fff', borderRadius: 12, padding: '20px 20px 12px', border: '1px solid #e8edf4' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>Динамика финансовых показателей (млрд тенге)</div>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={lineData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9"/>
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}/>
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}/>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}/>
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }}/>
                <Line type="monotone" dataKey="budget" stroke="#1d6fbc" strokeWidth={2} dot={false} name="Бюджет"/>
                <Line type="monotone" dataKey="procurement" stroke="#22c55e" strokeWidth={2} dot={false} name="Госзакупки"/>
                <Line type="monotone" dataKey="subsidies" stroke="#f59e0b" strokeWidth={2} dot={false} name="Субсидии"/>
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Pie chart */}
          <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 12 }}>Объекты по уровню риска</div>
            <ResponsiveContainer width="100%" height={160}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" paddingAngle={2}>
                  {pieData.map((entry, i) => <Cell key={i} fill={entry.color}/>)}
                </Pie>
                <Tooltip formatter={(v: any, n: any) => [`${v}%`, n]} contentStyle={{ fontSize: 12, borderRadius: 8 }}/>
              </PieChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
              {pieData.map(d => (
                <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: d.color, flexShrink: 0 }}/>
                  <span style={{ color: '#475569', flex: 1 }}>{d.name}</span>
                  <span style={{ color: '#1e293b', fontWeight: 600 }}>{d.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* District rating + problem objects */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 }}>
          {/* Bar chart */}
          <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>Рейтинг районов по уровню риска</div>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={districtData} layout="vertical">
                <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false}/>
                <YAxis dataKey="name" type="category" width={140} tick={{ fontSize: 11, fill: '#475569' }} axisLine={false} tickLine={false}/>
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }}/>
                <Bar dataKey="score" fill="#1d6fbc" radius={[0, 4, 4, 0]} name="Индекс риска"/>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Problem objects */}
          <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b' }}>Проблемные объекты</div>
              <button style={{ fontSize: 12, color: '#1d6fbc', background: 'none', border: 'none', cursor: 'pointer' }}>Все объекты</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {PROBLEM_OBJECTS.map(o => (
                <div key={o.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, paddingBottom: 10, borderBottom: '1px solid #f1f5f9' }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: riskColor(o.risk), marginTop: 5, flexShrink: 0 }}/>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: '#1e293b', marginBottom: 2 }}>{o.name}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>{o.district} • {o.type}</div>
                  </div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#1e293b', flexShrink: 0 }}>{o.amount}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Contracts table */}
        <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b' }}>Актуальные госзакупки</div>
            <button style={{ fontSize: 12, color: '#1d6fbc', background: 'none', border: 'none', cursor: 'pointer' }}>Перейти к реестру</button>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                {['Номер договора', 'Предмет закупки', 'Сумма', 'Заказчик', 'Поставщик', 'Статус', 'Риск'].map(h => (
                  <th key={h} style={{ textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#94a3b8', padding: '0 12px 10px', textTransform: 'uppercase', letterSpacing: 0.5 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RECENT_CONTRACTS.map(c => {
                const sc = statusColor(c.status)
                return (
                  <tr key={c.num} style={{ borderBottom: '1px solid #f8fafc' }}>
                    <td style={{ padding: '10px 12px', fontSize: 13, color: '#1d6fbc', fontWeight: 500, whiteSpace: 'nowrap' }}>{c.num}</td>
                    <td style={{ padding: '10px 12px', fontSize: 13, color: '#1e293b', maxWidth: 200 }}>{c.subject}</td>
                    <td style={{ padding: '10px 12px', fontSize: 13, color: '#1e293b', fontWeight: 600, whiteSpace: 'nowrap' }}>{c.amount}</td>
                    <td style={{ padding: '10px 12px', fontSize: 12, color: '#475569' }}>{c.customer}</td>
                    <td style={{ padding: '10px 12px', fontSize: 12, color: '#475569' }}>{c.supplier}</td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ fontSize: 12, fontWeight: 500, padding: '3px 10px', borderRadius: 20, background: sc.bg, color: sc.color }}>{c.status}</span>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ fontSize: 12, fontWeight: 500, padding: '3px 10px', borderRadius: 20, background: riskColor(c.risk) + '22', color: riskColor(c.risk) }}>{c.risk}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function BudgetIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1d6fbc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg> }
function ProcIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg> }
function SubsIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ca8a04" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg> }
function InfraIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9333ea" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg> }
function OrgIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ea580c" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> }
function RiskIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> }
function MoneyRiskIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#e11d48" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg> }
function DocIcon() { return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0284c7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg> }
