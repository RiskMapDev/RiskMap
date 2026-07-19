import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from './client'

const get = (url: string, params?: any) => api.get(url, { params }).then(r => r.data)

export const useTerritories = (params?: any) =>
  useQuery({ queryKey: ['territories', params], queryFn: () => get('/territories/', params) })

export const useTerritoryRisk = (params?: any) =>
  useQuery({ queryKey: ['territory-risk', params], queryFn: () => get('/territories/risk/', params) })

export const useLayers = () =>
  useQuery({ queryKey: ['layers'], queryFn: () => get('/layers/') })

export const useGeoObjects = (params?: any) =>
  useQuery({ queryKey: ['geo-objects', params], queryFn: () => get('/geo-objects/', params) })

export const useDashboard = (territoryId?: number) =>
  useQuery({ queryKey: ['dashboard', territoryId], queryFn: () => get('/dashboard/', territoryId ? { territory: territoryId } : undefined) })

export const useLogin = () =>
  useMutation({
    mutationFn: (creds: { username: string; password: string }) => api.post('/token/', creds).then(r => r.data),
    onSuccess: (d) => { localStorage.setItem('access_token', d.access); localStorage.setItem('refresh_token', d.refresh) }
  })
