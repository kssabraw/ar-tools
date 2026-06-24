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
import { Rankings } from './pages/Rankings'
import { MapsGeogrid } from './pages/MapsGeogrid'
import { MapsReport } from './pages/MapsReport'
import { RankReport } from './pages/RankReport'
import { Articles } from './pages/Articles'
import { Silos } from './pages/Silos'
import { Team } from './pages/Team'
import { SetPassword } from './pages/SetPassword'

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
            <Route path="/set-password" element={<SetPassword />} />
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
                      <Route path="/clients/:id/rankings" element={<Rankings />} />
                      <Route path="/clients/:id/maps" element={<MapsGeogrid />} />
                      <Route path="/clients/:id/maps/report" element={<MapsReport />} />
                      <Route path="/clients/:id/rankings/report" element={<RankReport />} />
                      <Route path="/clients/:id/rankings/report/:reportId" element={<RankReport />} />
                      <Route path="/clients/:id/edit" element={<AdminRoute><ClientForm /></AdminRoute>} />
                      <Route path="/articles" element={<Articles />} />
                      <Route path="/silos" element={<Silos />} />
                      <Route path="/team" element={<AdminRoute><Team /></AdminRoute>} />
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
