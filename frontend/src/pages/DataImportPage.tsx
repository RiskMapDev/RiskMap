import React, { useState } from 'react'
import { AppTopBar } from '../components/layout/AppTopBar'

const DATA_TYPES = [
  { key: 'budget', label: 'Бюджетные расходы', desc: 'Плановые и фактические показатели' },
  { key: 'procurement', label: 'Госзакупки', desc: 'Договоры и объявления' },
  { key: 'subsidies', label: 'Субсидии', desc: 'Получатели и суммы' },
  { key: 'population', label: 'Население', desc: 'По населённым пунктам' },
  { key: 'infrastructure', label: 'Инфраструктура', desc: 'Объекты и здания' },
  { key: 'land', label: 'Земельные участки', desc: 'Категории и площади' },
]

const HISTORY = [
  { id: 1, file: 'budget_2026_q1.xlsx', type: 'Бюджет', date: '03.07.2026 14:22', rows: 1248, status: 'Успешно' },
  { id: 2, file: 'contracts_june.csv', type: 'Госзакупки', date: '01.07.2026 09:14', rows: 387, status: 'Успешно' },
  { id: 3, file: 'subsidies_2026.xlsx', type: 'Субсидии', date: '28.06.2026 16:45', rows: 892, status: 'Ошибки (12)' },
  { id: 4, file: 'population_data.csv', type: 'Население', date: '25.06.2026 11:30', rows: 543, status: 'Успешно' },
]

const STEPS = ['Загрузка файла', 'Сопоставление столбцов', 'Предпросмотр и подтверждение']

export function DataImportPage() {
  const [step, setStep] = useState(0)
  const [selectedType, setSelectedType] = useState('budget')
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) { setFile(f); setTimeout(() => setStep(1), 500) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f4f6f9', fontFamily: "'Inter', -apple-system, sans-serif" }}>
      <AppTopBar title="Данные (импорт)"/>
      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
        <div style={{ marginBottom: 20 }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>Импорт данных</h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>Загрузка и верификация данных из внешних источников</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16 }}>
          {/* Main area */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* Steps */}
            <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', border: '1px solid #e8edf4' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: step === 0 ? 24 : 0 }}>
                {STEPS.map((s, i) => (
                  <React.Fragment key={i}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: i < STEPS.length - 1 ? 0 : 'none' }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 13, fontWeight: 700, flexShrink: 0,
                        background: i < step ? '#22c55e' : i === step ? '#1d6fbc' : '#e2e8f0',
                        color: i <= step ? '#fff' : '#94a3b8'
                      }}>
                        {i < step ? <svg width="12" height="10" viewBox="0 0 12 10" fill="none"><path d="M1 5L4.5 8.5L11 1" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg> : i + 1}
                      </div>
                      <span style={{ fontSize: 13, fontWeight: i === step ? 600 : 400, color: i === step ? '#1e293b' : '#94a3b8', whiteSpace: 'nowrap' }}>{s}</span>
                    </div>
                    {i < STEPS.length - 1 && (
                      <div style={{ flex: 1, height: 1, background: i < step ? '#22c55e' : '#e2e8f0', margin: '0 12px' }}/>
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>

            {step === 0 && (
              <>
                {/* Type selection */}
                <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 14 }}>Тип данных</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                    {DATA_TYPES.map(t => (
                      <button key={t.key} onClick={() => setSelectedType(t.key)} style={{
                        padding: '12px 14px', borderRadius: 10, textAlign: 'left',
                        border: selectedType === t.key ? '2px solid #1d6fbc' : '2px solid #e2e8f0',
                        background: selectedType === t.key ? '#eff6ff' : '#fafafa',
                        cursor: 'pointer'
                      }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: selectedType === t.key ? '#1d6fbc' : '#1e293b', marginBottom: 3 }}>{t.label}</div>
                        <div style={{ fontSize: 11, color: '#94a3b8' }}>{t.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Drop zone */}
                <div
                  onDragOver={e => { e.preventDefault(); setDragging(true) }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={handleDrop}
                  style={{
                    background: dragging ? '#eff6ff' : '#fff', borderRadius: 12, padding: '48px 24px',
                    border: `2px dashed ${dragging ? '#1d6fbc' : '#d1dbe8'}`,
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12,
                    cursor: 'pointer', transition: 'all 0.2s'
                  }}
                  onClick={() => { const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.xlsx,.csv,.xls'; inp.onchange = (e: any) => { const f = e.target.files[0]; if (f) { setFile(f); setTimeout(() => setStep(1), 400) } }; inp.click() }}
                >
                  <div style={{ width: 52, height: 52, borderRadius: 12, background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1d6fbc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/>
                      <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
                    </svg>
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', textAlign: 'center' }}>Перетащите файл или нажмите для выбора</div>
                    <div style={{ fontSize: 12, color: '#94a3b8', textAlign: 'center', marginTop: 4 }}>Поддерживаются: XLSX, CSV, XLS (до 50 МБ)</div>
                  </div>
                  <button style={{ padding: '8px 20px', borderRadius: 8, background: '#1d6fbc', color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
                    Выбрать файл
                  </button>
                </div>
              </>
            )}

            {step === 1 && (
              <div style={{ background: '#fff', borderRadius: 12, padding: '24px', border: '1px solid #e8edf4' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>Сопоставление столбцов</div>
                <div style={{ background: '#f8fafc', borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 13, color: '#475569' }}>
                  Файл: <strong>{file?.name}</strong> — автоматически определено {Math.floor(Math.random() * 5) + 8} столбцов
                </div>
                {['Дата', 'Район', 'Сумма (тенге)', 'Статус', 'Организация'].map((col, i) => (
                  <div key={col} style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 12 }}>
                    <div style={{ width: 160, fontSize: 13, fontWeight: 500, color: '#1e293b' }}>{col}</div>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                    <select style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, color: '#1e293b', background: '#fff' }}>
                      <option>{['date_column', 'district', 'amount', 'status', 'org_name'][i]}</option>
                    </select>
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
                  <button onClick={() => setStep(0)} style={{ padding: '10px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', fontSize: 13, cursor: 'pointer', color: '#475569' }}>Назад</button>
                  <button onClick={() => setStep(2)} style={{ padding: '10px 20px', borderRadius: 8, background: '#1d6fbc', color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Далее</button>
                </div>
              </div>
            )}

            {step === 2 && (
              <div style={{ background: '#fff', borderRadius: 12, padding: '24px', border: '1px solid #e8edf4' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>Предпросмотр и подтверждение</div>
                <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 13, color: '#15803d' }}>
                  Проверка завершена: найдено 1 248 записей. Ошибок не обнаружено.
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                      {['Дата', 'Район', 'Сумма', 'Статус', 'Организация'].map(h => (
                        <th key={h} style={{ textAlign: 'left', padding: '6px 10px', color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', fontSize: 10 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ['01.01.2026', 'Карасайский', '124 500 000', 'Исполнен', 'ГУ Карасайский р-н'],
                      ['05.01.2026', 'Талгарский', '89 200 000', 'В работе', 'ТОО КазСтройИнвест'],
                      ['10.01.2026', 'Илийский', '42 000 000', 'Завершён', 'ГУ Илийский р-н'],
                    ].map((row, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #f8fafc' }}>
                        {row.map((cell, j) => <td key={j} style={{ padding: '8px 10px', color: '#1e293b' }}>{cell}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
                  <button onClick={() => setStep(1)} style={{ padding: '10px 20px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', fontSize: 13, cursor: 'pointer', color: '#475569' }}>Назад</button>
                  <button onClick={() => { setStep(0); setFile(null) }} style={{ padding: '10px 20px', borderRadius: 8, background: '#22c55e', color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Подтвердить импорт</button>
                </div>
              </div>
            )}
          </div>

          {/* History sidebar */}
          <div style={{ background: '#fff', borderRadius: 12, padding: '20px', border: '1px solid #e8edf4', alignSelf: 'start' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#1e293b', marginBottom: 14 }}>История загрузок</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {HISTORY.map(h => (
                <div key={h.id} style={{ padding: '12px', borderRadius: 8, background: '#f8fafc', border: '1px solid #f1f5f9' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#1e293b', wordBreak: 'break-all' }}>{h.file}</div>
                    <span style={{
                      fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 20, flexShrink: 0, marginLeft: 6,
                      background: h.status === 'Успешно' ? '#f0fdf4' : '#fff7ed',
                      color: h.status === 'Успешно' ? '#16a34a' : '#ea580c'
                    }}>{h.status}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>{h.type} • {h.rows} строк</div>
                  <div style={{ fontSize: 11, color: '#c0ccd8', marginTop: 2 }}>{h.date}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
