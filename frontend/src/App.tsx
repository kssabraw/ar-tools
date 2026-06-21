import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute, AdminRoute } from './components/ProtectedRoute'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Home } from './pages/Home'
import { Runs } from './pages/Runs'
import { RunDetail } from './pages/RunDetail'
import { Clients } from './pages/Clients'
import { ClientForm } from './pages/ClientForm'
import { ClientWorkspace } from './pages/ClientWorkspace'
import { BrandVoice } from './pages/BrandVoice'
import { Icp } from './pages/Icp'
import { LocalSeoContent } from './pages/LocalSeoContent'
import { Articles } from './pages/Articles'
import { Silos } from './pages/Silos'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout>
                    <Routes>
                      <Route path="/" element={<Home />} />
                      <Route path="/runs" element={<Runs />} />
                      <Route path="/runs/:id" element={<RunDetail />} />
                      <Route path="/clients" element={<Clients />} />
                      <Route path="/clients/new" element={<AdminRoute><ClientForm /></AdminRoute>} />
                      <Route path="/clients/:id" element={<ClientWorkspace />} />
                      <Route path="/clients/:id/brand-voice" element={<BrandVoice />} />
                      <Route path="/clients/:id/icp" element={<Icp />} />
                      <Route path="/clients/:id/local-seo" element={<LocalSeoContent />} />
                      <Route path="/clients/:id/edit" element={<AdminRoute><ClientForm /></AdminRoute>} />
                      <Route path="/articles" element={<Articles />} />
                      <Route path="/silos" element={<Silos />} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Routes>
                  </Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
