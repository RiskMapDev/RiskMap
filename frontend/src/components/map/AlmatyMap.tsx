import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useAppStore } from '../../stores/appStore'

const RISK_COLOR = { high:'#f85149', medium:'#e3a330', low:'#3fb950' } as const
const RISK_FILL  = { high:'#f8514928', medium:'#e3a33020', low:'#3fb95020' } as const
const RISK_LABEL = { high:'Высокий', medium:'Средний', low:'Низкий' } as const

function buildTiles(dark: boolean) {
  return {
    base:  dark ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
                : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  }
}

export function AlmatyMap() {
  const mapRef  = useRef<HTMLDivElement>(null)
  const mapInst = useRef<L.Map | null>(null)
  const geoRef  = useRef<L.GeoJSON | null>(null)
  const { darkMode } = useAppStore()

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

    fetch('/almaty_districts.geojson')
      .then(r => r.json())
      .then(data => {
        const geo = L.geoJSON(data, {
          style: (f: any) => {
            const risk = (f?.properties?.risk ?? 'medium') as keyof typeof RISK_COLOR
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
            const risk = (p.risk ?? 'medium') as keyof typeof RISK_COLOR
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

            // Простой HTML попап без внешних зависимостей
            const popup = `
              <div style="min-width:220px;font-family:system-ui,-apple-system,sans-serif">
                <div style="font-weight:700;font-size:13px;color:#e6edf3;
                  padding-bottom:8px;margin-bottom:8px;border-bottom:1px solid #30363d">
                  ${p.name}
                </div>
                <div style="font-size:10px;color:#8b949e;margin-bottom:8px">${p.name_kz ?? ''}</div>
                <table style="width:100%;border-collapse:collapse;font-size:11px">
                  <tr><td style="color:#8b949e;padding:3px 0">Адм. центр</td>
                      <td style="color:#e6edf3;text-align:right;font-weight:600">${p.center ?? '—'}</td></tr>
                  <tr><td style="color:#8b949e;padding:3px 0">Население</td>
                      <td style="color:#e6edf3;text-align:right">${Number(p.pop||0).toLocaleString('ru-RU')} чел.</td></tr>
                  <tr><td style="color:#8b949e;padding:3px 0">Площадь</td>
                      <td style="color:#e6edf3;text-align:right">${Number(p.area_km2||0).toLocaleString('ru-RU')} км²</td></tr>
                  <tr><td style="color:#8b949e;padding:3px 0">Бюджет</td>
                      <td style="color:#58a6ff;text-align:right;font-weight:700">${p.budget ?? '—'}</td></tr>
                  <tr><td style="color:#8b949e;padding:3px 0">Уровень риска</td>
                      <td style="color:${col};text-align:right;font-weight:700">${RISK_LABEL[risk]}</td></tr>
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
      })
      .catch(err => console.error('GeoJSON load error:', err))

    return () => {
      map.remove()
      mapInst.current = null
      geoRef.current  = null
    }
  }, [])

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
