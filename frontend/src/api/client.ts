import axios from 'axios'

// Один бэкенд на всё: и токен, и данные слоёв.
// Относительный /api — nginx проксирует на Django, поэтому порт в коде
// не зашит. Для dev (npm start) можно задать REACT_APP_API_URL.
const baseURL = process.env.REACT_APP_API_URL || '/api'

export const api = axios.create({ baseURL })

api.interceptors.request.use((c) => {
  const t = localStorage.getItem('access_token')
  if (t) c.headers.Authorization = `Bearer ${t}`
  return c
})

api.interceptors.response.use(r => r, async (err) => {
  if (err.response?.status === 401) {
    const refresh = localStorage.getItem('refresh_token')
    if (refresh) {
      try {
        const res = await axios.post(`${baseURL}/token/refresh/`, { refresh })
        localStorage.setItem('access_token', res.data.access)
        err.config.headers.Authorization = `Bearer ${res.data.access}`
        return api.request(err.config)
      } catch {
        localStorage.clear()
        window.location.reload()
      }
    } else {
      localStorage.clear()
      window.location.reload()
    }
  }
  return Promise.reject(err)
})
