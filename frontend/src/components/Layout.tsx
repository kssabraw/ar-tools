import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LayoutDashboard, Home, Users, LogOut, FileText, BookOpen, Layers, UserCog, Gauge, Library } from 'lucide-react'

interface NavItem {
  label: string
  to: string
  icon: React.ReactNode
}

const nav: NavItem[] = [
  { label: 'Runs', to: '/runs', icon: <LayoutDashboard size={18} /> },
  { label: 'Articles', to: '/articles', icon: <BookOpen size={18} /> },
  { label: 'Silos', to: '/silos', icon: <Layers size={18} /> },
  { label: 'Clients', to: '/clients', icon: <Users size={18} /> },
  { label: 'Workload', to: '/workload', icon: <Gauge size={18} /> },
  { label: 'Playbook', to: '/playbook', icon: <Library size={18} /> },
]

function isActive(pathname: string, to: string): boolean {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(to + '/')
}

// The client whose workspace we're currently inside, if any. Drives the
// contextual "Dashboard" shortcut back to that client's workspace. `/clients/new`
// is the create-client form, not a real client, so it's excluded.
function currentClientId(pathname: string): string | null {
  const m = pathname.match(/^\/clients\/([^/]+)/)
  if (!m || m[1] === 'new') return null
  return m[1]
}

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, signOut, isAdmin } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  // Team management is admin-only (matches the /team AdminRoute guard).
  const mainNav: NavItem[] = [
    ...nav,
    ...(isAdmin ? [{ label: 'Team', to: '/team', icon: <UserCog size={18} /> }] : []),
  ]

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  const clientId = currentClientId(location.pathname)
  const quickNav: NavItem[] = [
    { label: 'Home', to: '/', icon: <Home size={18} /> },
    ...(clientId
      ? [{ label: 'Dashboard', to: `/clients/${clientId}`, icon: <LayoutDashboard size={18} /> }]
      : []),
  ]

  const renderLink = (item: NavItem) => {
    const active = isActive(location.pathname, item.to)
    return (
      <Link
        key={item.to}
        to={item.to}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 20px',
          color: active ? '#a5b4fc' : '#94a3b8',
          background: active ? '#1e293b' : 'transparent',
          textDecoration: 'none',
          fontSize: 14,
          fontWeight: active ? 600 : 400,
          transition: 'background 0.15s',
        }}
      >
        {item.icon}
        {item.label}
      </Link>
    )
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
          <div style={{ paddingBottom: 12, marginBottom: 12, borderBottom: '1px solid #1e293b' }}>
            {quickNav.map(renderLink)}
          </div>
          {mainNav.map(renderLink)}
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
