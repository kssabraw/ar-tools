import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth()
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading…</div>
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}
