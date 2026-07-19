import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useTheme } from '../../hooks/useTheme'

const STATUS_CONFIG = {
  connected: { label: 'Подключено',    color: '#3fb950', dot: '#3fb950' },
  no_token:  { label: 'Нужен токен',   color: '#d29922', dot: '#d29922' },
  manual:    { label: 'Ручная загрузка',color: '#58a6ff', dot: '#58a6ff' },
  pending:   { label: 'Ожидает доступ',color: '#484f58', dot: '#484f58' },
}

export function DataSources({ onClose }: { onClose: () => void }) {
  const t = useTheme()
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const { data, refetch } = useQuery({
    queryKey: ['integration-status'],
    queryFn: () => api.get('/integrations/status/').then(r => r.data),
  })

  const saveToken = async () => {
    if (!token.trim()) return
    setSaving(true)
    try {
      const res = await api.post('/integrations/set-token/', { token })
      setMsg(res.data.message)
      refetch()
    } catch {
      setMsg('Ошибка сохранения токена')
    } finally {
      setSaving(false)
    }
  }

  const syncGoszakup = async () => {
    setSaving(true)
    try {
      const res = await api.post('/integrations/sync/goszakup/', {})
      setMsg(`Синхронизировано: ${res.data.synced} записей`)
    } catch (e: any) {
      setMsg(e.response?.data?.message || 'Ошибка синхронизации')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
         style={{ background:'rgba(0,0,0,0.6)' }}>
      <div style={{ background: t.surface, border: `1px solid ${t.border}`, width: 640 }}
           className="rounded-xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div style={{ borderBottom: `1px solid ${t.border}` }}
             className="flex items-center justify-between px-6 py-4">
          <div>
            <div style={{ color: t.text }} className="font-semibold text-sm">Источники данных</div>
            <div style={{ color: t.textDim }} className="text-xs mt-0.5">
              Управление подключениями к государственным базам данных
            </div>
          </div>
          <button onClick={onClose}
            style={{ color: t.textDim, border: `1px solid ${t.border}` }}
            className="w-7 h-7 flex items-center justify-center rounded text-sm hover:opacity-70">
            ✕
          </button>
        </div>

        {/* Token input for goszakup */}
        <div style={{ borderBottom: `1px solid ${t.border}`, background: t.surface2 }}
             className="px-6 py-4">
          <div style={{ color: t.textDim }} className="text-xs font-semibold uppercase tracking-wide mb-2">
            API Токен — goszakup.gov.kz
          </div>
          <div className="flex gap-2">
            <input
              type="password"
              value={token}
              onChange={e => setToken(e.target.value)}
              placeholder="Вставьте токен из личного кабинета goszakup..."
              style={{ background: t.surface, border: `1px solid ${t.border}`, color: t.text }}
              className="flex-1 text-xs px-3 py-2 rounded-lg outline-none focus:border-blue-500"
            />
            <button onClick={saveToken} disabled={saving || !token}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40
                text-white text-xs font-semibold rounded-lg">
              Сохранить
            </button>
            <button onClick={syncGoszakup} disabled={saving}
              className="px-4 py-2 border border-blue-500 text-blue-400 hover:bg-blue-500/10
                disabled:opacity-40 text-xs font-semibold rounded-lg">
              Синхронизировать
            </button>
          </div>
          {msg && <div style={{ color: '#3fb950' }} className="text-xs mt-2">{msg}</div>}
        </div>

        {/* Sources list */}
        <div className="p-6 max-h-96 overflow-y-auto">
          <div className="grid gap-3">
            {(data?.sources ?? []).map((src: any) => {
              const sc = STATUS_CONFIG[src.status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.pending
              return (
                <div key={src.id}
                  style={{ background: t.surface2, border: `1px solid ${t.border}` }}
                  className="rounded-lg p-4">
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <div style={{ background: sc.dot }} className="w-2 h-2 rounded-full"/>
                        <span style={{ color: t.text }} className="text-sm font-semibold">{src.name}</span>
                        <span style={{ color: sc.color }}
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                          dangerouslySetInnerHTML={{__html: `●&nbsp;${sc.label}`}}/>
                      </div>
                      <div style={{ color: t.textDim }} className="text-xs mt-1">{src.description}</div>
                    </div>
                    <a href={src.url} target="_blank" rel="noreferrer"
                       style={{ color: '#58a6ff', border: `1px solid #1f6feb40` }}
                       className="text-[10px] px-2 py-1 rounded hover:bg-blue-500/10">
                      Открыть сайт
                    </a>
                  </div>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {src.data.map((d: string) => (
                      <span key={d}
                        style={{ background: t.surface, border: `1px solid ${t.border}`, color: t.textDim }}
                        className="text-[10px] px-1.5 py-0.5 rounded">
                        {d}
                      </span>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Instructions */}
          <div style={{ border: `1px solid #d29922`, background: '#d2992210' }}
               className="mt-4 rounded-lg p-4">
            <div style={{ color:'#d29922' }} className="text-xs font-semibold mb-2">
              Как получить токен goszakup.gov.kz
            </div>
            <ol style={{ color: '#8b949e' }} className="text-xs space-y-1 list-decimal list-inside">
              <li>Зайдите на <span style={{color:'#58a6ff'}}>goszakup.gov.kz</span> → Вход через ЭЦП</li>
              <li>Перейдите: Профиль → Разработчикам → Получить токен</li>
              <li>Отправьте запрос в ЦЭТ (Центр электронной торговли)</li>
              <li>Получите токен и вставьте его выше</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  )
}
