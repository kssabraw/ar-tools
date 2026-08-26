import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { session, loading } = useAuth()
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading…</div>
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

export function AdminRoute({ children }: { children: React.ReactNode }) {
  const { session, isAdmin, loading } = useAuth()
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading…</div>
  if (!session) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/clients" replace />
  return <>{children}</>
}

// Senior-operator gate (staff or admin) — matches the backend's require_staff on
// client create/update/archive. Use for client management, which is not
// user/team management and so is not admin-only.
export function StaffRoute({ children }: { children: React.ReactNode }) {
  const { session, isStaff, loading } = useAuth()
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>Loading…</div>
  if (!session) return <Navigate to="/login" replace />
  if (!isStaff) return <Navigate to="/clients" replace />
  return <>{children}</>
}
