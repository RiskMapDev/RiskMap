import { create } from 'zustand'
type Layer = 'admin'|'budget'|'procurement'|'construction'|'agro'|'risks'|'osms'|'subsoil'
interface AppState {
  selectedDistrictId: number|null; activeYear: number
  activeLayers: Record<Layer, boolean>; sidebarTab: 'dashboard'|'risks'|'top'
  filters: Record<string, any>
  darkMode: boolean
  setSelectedDistrict: (id: number|null) => void
  toggleLayer: (l: Layer) => void
  setYear: (y: number) => void
  setSidebarTab: (t: 'dashboard'|'risks'|'top') => void
  setFilter: (k: string, v: any) => void
  clearFilters: () => void
  toggleDarkMode: () => void
}
export const useAppStore = create<AppState>((set) => ({
  selectedDistrictId: null, activeYear: 2024, sidebarTab: 'dashboard', filters: {},
  darkMode: true,
  activeLayers: { admin:true, budget:false, procurement:false, construction:false, agro:false, risks:true, osms:false, subsoil:false },
  setSelectedDistrict: (id) => set({ selectedDistrictId: id }),
  toggleLayer: (l) => set(s => ({ activeLayers: { ...s.activeLayers, [l]: !s.activeLayers[l] } })),
  setYear: (y) => set({ activeYear: y }),
  setSidebarTab: (t) => set({ sidebarTab: t }),
  setFilter: (k, v) => set(s => ({ filters: { ...s.filters, [k]: v } })),
  clearFilters: () => set({ filters: {} }),
  toggleDarkMode: () => set(s => {
    const next = !s.darkMode
    if (next) document.documentElement.classList.add('dark')
    else document.documentElement.classList.remove('dark')
    return { darkMode: next }
  }),
}))
