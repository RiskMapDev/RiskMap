import React from 'react'
import { X } from 'lucide-react'
import { useAppStore } from '../../stores/appStore'

const SPHERES = ['Строительство','ЖКХ','Дороги','Образование','Здравоохранение','АПК','Соц. сфера','Цифровизация']
const DISTRICTS_LIST = ['Іле ауданы','Талғар ауданы','Қарасай ауданы','Алматы қ.','Еңбекшіқазақ','Жамбыл ауданы','Балқаш ауданы','Ақсу ауданы','Ұйғыр ауданы','Райымбек ауданы']
const RISK_LEVELS = [['high','Высокий'],['medium','Средний'],['low','Низкий']]
const STATUSES = [['analysis','Анализ'],['prevention','Превенция'],['erdr','ЕРДР'],['in_progress','В производстве'],['completed','Завершено']]

export function FilterPanel({ onClose }: { onClose: () => void }) {
  const { filters, setFilter, clearFilters, activeYear, setYear } = useAppStore()

  return (
    <div className="fixed inset-0 bg-black/60 flex items-start justify-end z-50 pt-12 pr-0">
      <div className="w-80 bg-[#161b22] border-l border-[#30363d] h-full overflow-y-auto flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-[#30363d] sticky top-0 bg-[#161b22]">
          <span className="text-sm font-bold">Фильтры</span>
          <div className="flex items-center gap-2">
            <button onClick={clearFilters} className="text-xs text-blue-400 hover:text-blue-300">Сбросить</button>
            <button onClick={onClose} className="text-gray-400 hover:text-white"><X size={16}/></button>
          </div>
        </div>
        <div className="p-4 space-y-5 flex-1">

          {/* Year */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Год</label>
            <select value={activeYear} onChange={e => setYear(+e.target.value)}
              className="w-full bg-[#1c2128] border border-[#30363d] rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-blue-500">
              {[2026,2025,2024,2023,2022,2021].map(y => <option key={y}>{y}</option>)}
            </select>
          </div>

          {/* District */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Район / Город</label>
            <select value={filters.district ?? ''} onChange={e => setFilter('district', e.target.value || undefined)}
              className="w-full bg-[#1c2128] border border-[#30363d] rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-blue-500">
              <option value="">Все районы</option>
              {DISTRICTS_LIST.map(d => <option key={d}>{d}</option>)}
            </select>
          </div>

          {/* Sphere */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Сфера</label>
            <div className="flex flex-wrap gap-1.5">
              {SPHERES.map(s => (
                <button key={s} onClick={() => setFilter('sphere', filters.sphere === s ? undefined : s)}
                  className={`px-2 py-1 rounded text-[10px] border transition-colors ${filters.sphere === s ? 'bg-blue-500/20 border-blue-500 text-blue-300' : 'bg-[#1c2128] border-[#30363d] text-gray-400 hover:border-gray-500'}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Risk level */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Уровень риска</label>
            <div className="flex gap-2">
              {RISK_LEVELS.map(([v,l]) => {
                const color = v==='high'?'red':v==='medium'?'yellow':'green'
                const active = filters.level === v
                return (
                  <button key={v} onClick={() => setFilter('level', active ? undefined : v)}
                    className={`flex-1 py-1.5 rounded text-[10px] border transition-colors ${active ? `bg-${color}-500/20 border-${color}-500 text-${color}-300` : 'bg-[#1c2128] border-[#30363d] text-gray-400'}`}
                    style={active ? { background: `${v==='high'?'#f85149':v==='medium'?'#d29922':'#3fb950'}20`, borderColor: v==='high'?'#f85149':v==='medium'?'#d29922':'#3fb950', color: v==='high'?'#f87171':v==='medium'?'#fbbf24':'#4ade80' } : {}}>
                    {l}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Status */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Статус материала</label>
            <div className="space-y-1.5">
              {STATUSES.map(([v,l]) => (
                <label key={v} className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={!!(filters.statuses ?? []).includes(v)}
                    onChange={e => {
                      const cur: string[] = filters.statuses ?? []
                      setFilter('statuses', e.target.checked ? [...cur, v] : cur.filter((x: string) => x !== v))
                    }}
                    className="accent-blue-500 w-3 h-3"/>
                  <span className="text-xs text-gray-400">{l}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Amount range */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">Сумма риска (млн ₸)</label>
            <div className="flex gap-2">
              <input type="number" placeholder="От" value={filters.amountMin ?? ''}
                onChange={e => setFilter('amountMin', e.target.value || undefined)}
                className="flex-1 bg-[#1c2128] border border-[#30363d] rounded-lg px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500"/>
              <input type="number" placeholder="До" value={filters.amountMax ?? ''}
                onChange={e => setFilter('amountMax', e.target.value || undefined)}
                className="flex-1 bg-[#1c2128] border border-[#30363d] rounded-lg px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500"/>
            </div>
          </div>

          {/* BIN/IIN */}
          <div>
            <label className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide block mb-2">БИН / ИИН</label>
            <input type="text" placeholder="Введите БИН или ИИН" value={filters.bin ?? ''}
              onChange={e => setFilter('bin', e.target.value || undefined)}
              className="w-full bg-[#1c2128] border border-[#30363d] rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-blue-500"/>
          </div>

          {/* ERDR */}
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={!!filters.hasErdr}
                onChange={e => setFilter('hasErdr', e.target.checked || undefined)}
                className="accent-blue-500 w-3 h-3"/>
              <span className="text-xs text-gray-400">Только с ЕРДР</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer mt-2">
              <input type="checkbox" checked={!!filters.hasPrevention}
                onChange={e => setFilter('hasPrevention', e.target.checked || undefined)}
                className="accent-blue-500 w-3 h-3"/>
              <span className="text-xs text-gray-400">Только с превентивными мерами</span>
            </label>
          </div>
        </div>

        <div className="p-4 border-t border-[#30363d] sticky bottom-0 bg-[#161b22]">
          <button onClick={onClose}
            className="w-full bg-blue-600 hover:bg-blue-500 text-white rounded-lg py-2 text-sm font-semibold">
            Применить фильтры
          </button>
        </div>
      </div>
    </div>
  )
}
