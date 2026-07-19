import React, { useState } from 'react'
import { X, FileText, Table, Download } from 'lucide-react'

const REPORT_TYPES = [
  { id:'district',  label:'Справка по району',         desc:'Основные показатели, бюджет, риски' },
  { id:'risks',     label:'Реестр рисков',              desc:'Все выявленные риски с деталями' },
  { id:'budget',    label:'Бюджетное освоение',         desc:'По направлениям и районам' },
  { id:'supplier',  label:'Рейтинг поставщиков',       desc:'ТОП поставщиков с признаками риска' },
  { id:'subsidy',   label:'Получатели субсидий',        desc:'АПК субсидии по районам' },
  { id:'regional',  label:'Сводный отчёт по региону',  desc:'Полный отчёт по Алматинской обл.' },
]

export function ExportModal({ onClose }: { onClose: () => void }) {
  const [selected, setSelected] = useState('regional')
  const [format,   setFormat]   = useState<'excel'|'pdf'|'word'>('excel')
  const [loading,  setLoading]  = useState(false)

  const doExport = async () => {
    setLoading(true)
    await new Promise(r => setTimeout(r, 1500))
    setLoading(false)
    // In production: trigger API download
    alert(`Отчёт "${REPORT_TYPES.find(r=>r.id===selected)?.label}" в формате ${format.toUpperCase()} будет доступен после подключения бэкенда.\n\nEndpoint: GET /api/v1/analytics/export/?type=${selected}&format=${format}`)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl w-full max-w-md overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-[#30363d]">
          <span className="text-sm font-bold">Экспорт отчёта</span>
          <button onClick={onClose} className="text-gray-400 hover:text-white"><X size={16}/></button>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Тип отчёта</label>
            <div className="space-y-1.5">
              {REPORT_TYPES.map(r => (
                <button key={r.id} onClick={() => setSelected(r.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${selected===r.id ? 'bg-blue-500/15 border-blue-500/60' : 'bg-[#1c2128] border-[#30363d] hover:border-gray-500'}`}>
                  <div className="text-xs font-semibold">{r.label}</div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{r.desc}</div>
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Формат</label>
            <div className="flex gap-2">
              {([['excel','Excel',Table],['pdf','PDF',FileText],['word','Word',FileText]] as const).map(([v,l,Icon]) => (
                <button key={v} onClick={() => setFormat(v)}
                  className={`flex-1 flex flex-col items-center gap-1 py-3 rounded-lg border text-xs transition-colors ${format===v ? 'bg-blue-500/15 border-blue-500/60 text-blue-300' : 'bg-[#1c2128] border-[#30363d] text-gray-400 hover:border-gray-500'}`}>
                  <Icon size={16}/>
                  {l}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="p-4 border-t border-[#30363d]">
          <button onClick={doExport} disabled={loading}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white rounded-lg py-2.5 text-sm font-semibold">
            <Download size={15}/>{loading ? 'Формирование...' : 'Скачать отчёт'}
          </button>
        </div>
      </div>
    </div>
  )
}
