import { useAppStore } from '../stores/appStore'

export function useTheme() {
  const dark = useAppStore(s => s.darkMode)
  return {
    dark,
    bg:       dark ? '#0d1117'  : '#f6f8fa',
    surface:  dark ? '#161b22'  : '#ffffff',
    surface2: dark ? '#1c2128'  : '#f0f2f5',
    border:   dark ? '#30363d'  : '#d0d7de',
    text:     dark ? '#e6edf3'  : '#1f2328',
    textDim:  dark ? '#8b949e'  : '#656d76',
    // Tailwind class helpers
    tBg:      dark ? 'bg-[#0d1117]'    : 'bg-[#f6f8fa]',
    tSurface: dark ? 'bg-[#161b22]'    : 'bg-white',
    tSurface2:dark ? 'bg-[#1c2128]'    : 'bg-[#f0f2f5]',
    tBorder:  dark ? 'border-[#30363d]': 'border-[#d0d7de]',
    tText:    dark ? 'text-[#e6edf3]'  : 'text-[#1f2328]',
    tTextDim: dark ? 'text-[#8b949e]'  : 'text-[#656d76]',
  }
}
