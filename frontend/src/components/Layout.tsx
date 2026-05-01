import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LayoutDashboard, Users, UserPlus, LogOut, FileText } from 'lucide-react'

interface NavItem {
  label: string
  to: string
  icon: React.ReactNode
}

const nav: NavItem[] = [
  { label: 'Runs', to: '/', icon: <LayoutDashboard size={18} /> },
  { label: 'Clients', to: '/clients', icon: <Users size={18} /> },
  { label: 'New Client', to: '/clients/new', icon: <UserPlus size={18} /> },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'system-ui, sans-serif' }}>
      <aside style={{
        width: 220,
        background: '#0f172a',
        color: '#e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        padding: '24px 0',
      }}>
        <div style={{ padding: '0 20px 24px', borderBottom: '1px solid #1e293b' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileText size={20} color="#6366f1" />
            <span style={{ fontWeight: 700, fontSize: 16, color: '#f1f5f9' }}>AR Tools</span>
          </div>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{user?.email}</div>
        </div>
        <nav style={{ flex: 1, padding: '16px 0' }}>
          {nav.map(item => (
            <Link
              key={item.to}
              to={item.to}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 20px',
                color: location.pathname === item.to ? '#a5b4fc' : '#94a3b8',
                background: location.pathname === item.to ? '#1e293b' : 'transparent',
                textDecoration: 'none',
                fontSize: 14,
                fontWeight: location.pathname === item.to ? 600 : 400,
                transition: 'background 0.15s',
              }}
            >
              {item.icon}
              {item.label}
            </Link>
          ))}
        </nav>
        <div style={{ padding: '16px 20px', borderTop: '1px solid #1e293b' }}>
          <button
            onClick={handleSignOut}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              background: 'none',
              border: 'none',
              color: '#64748b',
              cursor: 'pointer',
              fontSize: 13,
              padding: 0,
            }}
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </aside>
      <main style={{ flex: 1, background: '#f8fafc', overflow: 'auto' }}>
        {children}
      </main>
    </div>
  )
}
