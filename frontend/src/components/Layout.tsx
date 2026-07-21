import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { NotificationBell } from './NotificationBell'
import { LayoutDashboard, Home, Users, LogOut, FileText, BookOpen, Layers, UserCog, Gauge, Library, LibraryBig, LifeBuoy, Sparkles, Link2, ListChecks, ListTodo, Menu, X, Radar, Loader2, ShieldCheck } from 'lucide-react'

interface NavItem {
  label: string
  to: string
  icon: React.ReactNode
}

const nav: NavItem[] = [
  { label: 'My Tasks', to: '/my-tasks', icon: <ListChecks size={18} /> },
  { label: 'Runs', to: '/runs', icon: <LayoutDashboard size={18} /> },
  { label: 'Articles', to: '/articles', icon: <BookOpen size={18} /> },
  { label: 'Silos', to: '/silos', icon: <Layers size={18} /> },
  { label: 'Clients', to: '/clients', icon: <Users size={18} /> },
  { label: 'LeadOff', to: '/leadoff', icon: <Radar size={18} /> },
  { label: 'Backlinks', to: '/backlinks', icon: <Link2 size={18} /> },
  { label: 'Workload', to: '/workload', icon: <Gauge size={18} /> },
  { label: 'Task Library', to: '/asana/task-library', icon: <LibraryBig size={18} /> },
  { label: 'Playbook', to: '/playbook', icon: <Library size={18} /> },
  { label: 'Guides', to: '/guides', icon: <LifeBuoy size={18} /> },
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

  // Mobile (PWA, PRD §13): the sidebar collapses behind a hamburger and slides
  // over the content; it closes on any navigation.
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 768px)').matches)
  const [mobileOpen, setMobileOpen] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    const onChange = () => setIsMobile(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  // Team management is admin-only (matches the /team AdminRoute guard).
  const mainNav: NavItem[] = [
    ...nav,
    ...(isAdmin ? [{ label: 'Team', to: '/team', icon: <UserCog size={18} /> }] : []),
  ]

  async function handleSignOut() {
    await signOut()
    navigate('/login')
  }

  // PACE (delivery-PM chat) is gated behind the server-side pace_enabled flag —
  // hide the sidebar entry until an admin turns it on, so we never surface a
  // dead chatbot.
  const { data: paceStatus } = useQuery<{ enabled: boolean }>({
    queryKey: ['pace-status'],
    queryFn: () => api.get<{ enabled: boolean }>('/pace/status'),
    staleTime: 5 * 60_000,
  })

  // QA (quality-reviewer chat) is gated behind the server-side qa_chat_enabled
  // flag — same pattern as PACE, so the sidebar entry only appears once an admin
  // turns it on.
  const { data: qaStatus } = useQuery<{ enabled: boolean }>({
    queryKey: ['qa-status'],
    queryFn: () => api.get<{ enabled: boolean }>('/qa/status'),
    staleTime: 5 * 60_000,
  })

  // Live count of the user's in-flight content generation (ecommerce / Local
  // SEO pages, blog runs), so a long batch they navigated away from stays
  // visible everywhere. Polls in the background; the Activity page polls faster.
  const { data: activity } = useQuery<{ count: number }>({
    queryKey: ['activity-count'],
    queryFn: () => api.get<{ count: number }>('/activity'),
    refetchInterval: 15_000,
    staleTime: 10_000,
  })
  const activityCount = activity?.count ?? 0

  const clientId = currentClientId(location.pathname)
  const quickNav: NavItem[] = [
    { label: 'Home', to: '/', icon: <Home size={18} /> },
    { label: 'Activity', to: '/activity', icon: <Loader2 size={18} className={activityCount > 0 ? 'spin' : undefined} /> },
    { label: 'SerMaStr', to: '/assistant', icon: <Sparkles size={18} /> },
    ...(paceStatus?.enabled
      ? [{ label: 'PACE', to: '/pace', icon: <ListTodo size={18} /> }]
      : []),
    ...(qaStatus?.enabled
      ? [{ label: 'QA', to: '/qa', icon: <ShieldCheck size={18} /> }]
      : []),
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
        <span style={{ flex: 1 }}>{item.label}</span>
        {item.to === '/activity' && activityCount > 0 && (
          <span
            style={{
              minWidth: 20, height: 20, padding: '0 6px', borderRadius: 999,
              background: '#6366f1', color: '#fff', fontSize: 11, fontWeight: 700,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            {activityCount}
          </span>
        )}
      </Link>
    )
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: 'system-ui, sans-serif' }}>
      {isMobile && (
        <button
          onClick={() => setMobileOpen((v) => !v)}
          aria-label="Menu"
          style={{
            position: 'fixed', top: 12, left: 12, zIndex: 70,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 38, height: 38, borderRadius: 10, border: '1px solid #e2e8f0',
            background: '#fff', color: '#0f172a', cursor: 'pointer', boxShadow: '0 1px 3px rgba(15,23,42,0.12)',
          }}
        >
          {mobileOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
      )}
      {isMobile && mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 55 }}
        />
      )}
      <aside style={{
        width: 220,
        background: '#0f172a',
        color: '#e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        padding: '24px 0',
        ...(isMobile
          ? {
              position: 'fixed', top: 0, bottom: 0, left: 0, zIndex: 60,
              transform: mobileOpen ? 'translateX(0)' : 'translateX(-100%)',
              transition: 'transform 0.2s ease', overflowY: 'auto',
            }
          : {}),
      }}>
        <div style={{ padding: '0 20px 24px', borderBottom: '1px solid #1e293b' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileText size={20} color="#6366f1" />
              <span style={{ fontWeight: 700, fontSize: 16, color: '#f1f5f9' }}>AR Tools</span>
            </div>
            <NotificationBell />
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
      <main style={{ flex: 1, background: '#f8fafc', overflow: 'auto', ...(isMobile ? { paddingTop: 48 } : {}) }}>
        {children}
      </main>
    </div>
  )
}
