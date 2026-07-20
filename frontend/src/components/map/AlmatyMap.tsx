import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useAppStore } from '../../stores/appStore'

// Палитра ТЗ п.7.3: зелёный/жёлтый/красный/тёмно-красный, серый — нет данных.
const RISK_COLOR = { low: '#3fb950', medium: '#e3a330', high: '#f85149', critical: '#7f1d1d', none: '#8b949e' } as const
const RISK_FILL  = { low: '#3fb95020', medium: '#e3a33020', high: '#f8514928', critical: '#7f1d1d40', none: '#8b949e18' } as const
const RISK_LABEL = { low: 'Низкий', medium: 'Средний', high: 'Высокий', critical: 'Критический', none: 'Нет данных' } as const

type RiskKey = keyof typeof RISK_COLOR

function riskKey(level: string | null | undefined): RiskKey {
  return (level && level in RISK_COLOR ? level : 'none') as RiskKey
}

function buildTiles(dark: boolean) {
  return {
    base:  dark ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
                : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  }
}

export function AlmatyMap({ data }: { data?: any }) {
  const mapRef  = useRef<HTMLDivElement>(null)
  const mapInst = useRef<L.Map | null>(null)
  const geoRef  = useRef<L.GeoJSON | null>(null)
  const { darkMode } = useAppStore()

  // Инициализация карты (один раз)
  useEffect(() => {
    if (!mapRef.current || mapInst.current) return

    const map = L.map(mapRef.current, {
      center: [43.8, 77.0],
      zoom: 7,
      zoomControl: false,
      minZoom: 5,
      maxZoom: 14,
      renderer: L.svg(),
    })
    mapInst.current = map

    const { base } = buildTiles(darkMode)
    L.tileLayer(base, { subdomains:'abcd', maxZoom:19, attribution:'© CARTO' }).addTo(map)
    L.control.zoom({ position:'bottomright' }).addTo(map)

    return () => {
      map.remove()
      mapInst.current = null
      geoRef.current  = null
    }
  }, [])

  // Перерисовка районов при получении реальных данных с бэкенда
  // (GET /api/territories/risk/?layer=subsidies) — было: статический
  // GeoJSON-файл с зашитым property.risk, вместо реального риска.
  useEffect(() => {
    const map = mapInst.current
    if (!map || !data) return

    if (geoRef.current) {
      map.removeLayer(geoRef.current)
      geoRef.current = null
    }

    const geo = L.geoJSON(data, {
      style: (f: any) => {
        const risk = riskKey(f?.properties?.risk_level)
        return {
          color:       RISK_COLOR[risk],
          fillColor:   RISK_FILL[risk],
          weight:      2,
          opacity:     0.9,
          fillOpacity: 1,
        }
      },
      onEachFeature(feature, layer) {
        const p    = feature.properties as any
        const risk = riskKey(p.risk_level)
        const col  = RISK_COLOR[risk]

        layer.on('mouseover', (e: any) => {
          e.target.setStyle({ weight: 3, color: col, fillOpacity: 0.5 })
        })
        layer.on('mouseout', (e: any) => {
          geo.resetStyle(e.target)
        })
        layer.on('click', (e: any) => {
          map.fitBounds(e.target.getBounds(), { padding:[60,60], maxZoom:10 })
        })

        const popup = `
          <div style="min-width:220px;font-family:system-ui,-apple-system,sans-serif">
            <div style="font-weight:700;font-size:13px;color:#e6edf3;
              padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid #30363d">
              ${p.name_ru}
            </div>
            <div style="font-size:10px;color:#8b949e;margin-bottom:8px">${p.name_kz ?? ''}</div>
            <table style="width:100%;border-collapse:collapse;font-size:11px">
              <tr><td style="color:#8b949e;padding:3px 0">Население</td>
                  <td style="color:#e6edf3;text-align:right">${p.population ? Number(p.population).toLocaleString('ru-RU') + ' чел.' : '—'}</td></tr>
              <tr><td style="color:#8b949e;padding:3px 0">Площадь</td>
                  <td style="color:#e6edf3;text-align:right">${p.area_km2 ? Number(p.area_km2).toLocaleString('ru-RU') + ' км²' : '—'}</td></tr>
              <tr><td style="color:#8b949e;padding:3px 0">Получателей субсидий</td>
                  <td style="color:#e6edf3;text-align:right;font-weight:600">${p.objects_count}</td></tr>
              <tr><td style="color:#8b949e;padding:3px 0">Сумма субсидий</td>
                  <td style="color:#58a6ff;text-align:right;font-weight:700">${p.paid_total ? (p.paid_total / 1e6).toLocaleString('ru-RU', {maximumFractionDigits:0}) + ' млн ₸' : '—'}</td></tr>
              <tr><td style="color:#8b949e;padding:3px 0">Уровень риска</td>
                  <td style="color:${col};text-align:right;font-weight:700">${RISK_LABEL[risk]}${p.risk_score != null ? ` (${p.risk_score})` : ''}</td></tr>
            </table>
            <div style="margin-top:10px;text-align:center;color:#484f58;font-size:10px">
              Нажмите для приближения
            </div>
          </div>`

        layer.bindPopup(popup, { className:'akm-popup', closeButton:false, maxWidth:260 })
        layer.on('mouseover', () => layer.openPopup())
        layer.on('mouseout',  () => layer.closePopup())
      },
    })

    geo.addTo(map)
    geoRef.current = geo
    map.fitBounds(geo.getBounds(), { padding:[20,20] })
  }, [data])

  // Смена темы
  useEffect(() => {
    const map = mapInst.current
    if (!map) return
    const old: L.TileLayer[] = []
    map.eachLayer(l => { if ((l as any)._url) old.push(l as L.TileLayer) })
    old.forEach(l => map.removeLayer(l))
    const { base } = buildTiles(darkMode)
    L.tileLayer(base, { subdomains:'abcd', maxZoom:19, attribution:'© CARTO' }).addTo(map)
    geoRef.current?.bringToFront()
  }, [darkMode])

  return (
    <>
      <style>{`
        .akm-popup .leaflet-popup-content-wrapper {
          background: #161b22 !important;
          border: 1px solid #30363d !important;
          border-radius: 10px !important;
          box-shadow: 0 16px 48px rgba(0,0,0,0.65) !important;
          padding: 0 !important;
        }
        .akm-popup .leaflet-popup-content { margin: 14px 16px !important; }
        .akm-popup .leaflet-popup-tip     { background: #30363d !important; }
        .leaflet-control-attribution {
          background: rgba(13,17,23,0.75) !important;
          color: #484f58 !important;
          font-size: 9px !important;
        }
        .leaflet-control-attribution a { color: #484f58 !important; }
        .leaflet-bar a {
          background: #161b22 !important;
          color: #8b949e !important;
          border-color: #30363d !important;
        }
        .leaflet-bar a:hover {
          background: #1c2128 !important;
          color: #e6edf3 !important;
        }
      `}</style>
      <div ref={mapRef} className="w-full h-full" />
    </>
  )
}
