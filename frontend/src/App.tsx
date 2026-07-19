import React, { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'
import { MapPage } from './pages/MapPage'
import { DataImportPage } from './pages/DataImportPage'
import { ReportsPage } from './pages/ReportsPage'
import { GraphPage } from './pages/GraphPage'
import { AdminPage } from './pages/AdminPage'
import { Sidebar } from './components/layout/Sidebar'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } })

type Page = 'dashboard' | 'map' | 'import' | 'reports' | 'graph' | 'admin'

function Inner() {
  const [auth, setAuth] = useState(!!localStorage.getItem('access_token'))
  const [page, setPage] = useState<Page>('dashboard')

  if (!auth) return <LoginPage onLogin={() => setAuth(true)}/>

  const content = {
    dashboard: <DashboardPage/>,
    map: <MapPage/>,
    import: <DataImportPage/>,
    reports: <ReportsPage/>,
    graph: <GraphPage/>,
    admin: <AdminPage/>,
  }[page]

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar active={page} onNavigate={setPage}/>
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {content}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <Inner/>
    </QueryClientProvider>
  )
}
