import axios from 'axios'
export const api = axios.create({ baseURL: 'http://localhost:8000/api' })
api.interceptors.request.use((c) => {
  const t = localStorage.getItem('access_token')
  if (t) c.headers.Authorization = `Bearer ${t}`
  return c
})
api.interceptors.response.use(r => r, async (err) => {
  if (err.response?.status === 401) {
    const refresh = localStorage.getItem('refresh_token')
    if (refresh) {
      const res = await axios.post('http://localhost:8000/api/token/refresh/', { refresh })
      localStorage.setItem('access_token', res.data.access)
      err.config.headers.Authorization = `Bearer ${res.data.access}`
      return api.request(err.config)
    }
    localStorage.clear(); window.location.href = '/login'
  }
  return Promise.reject(err)
})
