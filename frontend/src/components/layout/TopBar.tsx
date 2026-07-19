import React, { useState } from 'react'
import { useAppStore } from '../../stores/appStore'
import { Search, Download, SlidersHorizontal, User, Sun, Moon, Database } from 'lucide-react'
import { DataSources } from '../ui/DataSources'

export function TopBar() {
  const { selectedDistrictId, setSelectedDistrict, darkMode, toggleDarkMode } = useAppStore()
  const [search, setSearch]   = useState('')
  const [showDS, setShowDS]   = useState(false)

  const surface  = darkMode ? 'bg-[#161b22]'     : 'bg-white'
  const surface2 = darkMode ? 'bg-[#1c2128]'     : 'bg-[#f0f2f5]'
  const border   = darkMode ? 'border-[#30363d]' : 'border-[#d0d7de]'
  const textDim  = darkMode ? 'text-gray-500'    : 'text-gray-500'
  const textMain = darkMode ? 'text-gray-300'    : 'text-gray-700'

  return (
    <>
      <div className={`h-11 ${surface} border-b ${border} flex items-center gap-3 px-4 flex-shrink-0`}>
        <div className="text-sm font-bold text-blue-500 tracking-widest">АКМ</div>

        <div className={`flex items-center gap-1.5 text-xs ${textDim}`}>
          <span className="cursor-pointer hover:text-blue-500 transition-colors"
            onClick={() => setSelectedDistrict(null)}>
            Алматинская обл.
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {/* Search */}
          <div className={`flex items-center gap-2 ${surface2} border ${border} rounded-md px-2.5 py-1.5`}>
            <Search size={13} className={textDim}/>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Поиск по БИН, ФИО, объекту..."
              className={`bg-transparent text-xs ${darkMode ? 'text-white placeholder-gray-600' : 'text-gray-800 placeholder-gray-400'} outline-none w-52`}/>
          </div>

          {/* Export */}
          <button className={`flex items-center gap-1.5 text-xs ${textDim} border ${border} ${surface2} rounded-md px-2 py-1.5 hover:border-blue-500 hover:text-blue-500 transition-colors`}>
            <Download size={13}/> Экспорт
          </button>

          {/* Filters */}
          <button className={`flex items-center gap-1.5 text-xs ${textDim} border ${border} ${surface2} rounded-md px-2 py-1.5 hover:border-blue-500 hover:text-blue-500 transition-colors`}>
            <SlidersHorizontal size={13}/> Фильтры
          </button>

          {/* Data Sources */}
          <button onClick={() => setShowDS(true)}
            className={`flex items-center gap-1.5 text-xs border rounded-md px-2 py-1.5 transition-colors
              border-yellow-500/40 text-yellow-500 bg-yellow-500/10 hover:bg-yellow-500/20`}>
            <Database size={13}/> Источники
          </button>

          {/* Theme toggle */}
          <button onClick={toggleDarkMode} title={darkMode ? 'Светлая тема' : 'Тёмная тема'}
            className={`w-8 h-8 flex items-center justify-center rounded-md border ${border} ${surface2} ${textDim} hover:border-blue-500 hover:text-blue-500 transition-colors`}>
            {darkMode ? <Sun size={14}/> : <Moon size={14}/>}
          </button>

          {/* User */}
          <div className="flex items-center gap-1.5 text-xs text-blue-500 border border-blue-500/40 bg-blue-500/10 rounded-md px-2 py-1.5">
            <User size={13}/> Аналитик
          </div>
        </div>
      </div>

      {showDS && <DataSources onClose={() => setShowDS(false)}/>}
    </>
  )
}
