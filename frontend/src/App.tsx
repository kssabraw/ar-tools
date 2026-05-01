import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Layout } from './components/Layout'
import { Login } from './pages/Login'
import { Runs } from './pages/Runs'
import { RunDetail } from './pages/RunDetail'
import { Clients } from './pages/Clients'
import { ClientForm } from './pages/ClientForm'
import { Articles } from './pages/Articles'

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
                      <Route path="/" element={<Runs />} />
                      <Route path="/runs/:id" element={<RunDetail />} />
                      <Route path="/clients" element={<Clients />} />
                      <Route path="/clients/new" element={<ClientForm />} />
                      <Route path="/clients/:id/edit" element={<ClientForm />} />
                      <Route path="/articles" element={<Articles />} />
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
