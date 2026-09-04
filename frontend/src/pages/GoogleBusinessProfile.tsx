import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, MapPin, BarChart3, Building2, Megaphone } from 'lucide-react'
import { api } from '../lib/api'
import { ConnectionBar } from '../components/gbp/GbpConnection'
import { GbpMetrics } from './GbpMetrics'
import { GbpProfileBody } from './GbpProfile'
import { GbpWorkspace } from './GbpPosts'
import type { Client } from '../lib/types'

// Unified Google Business Profile module — one surface with three tabs over the
// three GBP tools (Insights / Profile / Posts), all sharing the one Connect
// flow + listing registry. Each tab renders its existing page body embedded
// (its own per-location handling is unchanged — this is a surface consolidation,
// not a data change). The old per-tool routes redirect here with ?tab=.

const ACCENT = '#1a73e8' // Google blue — signals the shared GBP surface.

type Tab = 'insights' | 'profile' | 'posts'
const TABS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  { key: 'insights', label: 'Insights', icon: <BarChart3 size={15} /> },
  { key: 'profile', label: 'Profile', icon: <Building2 size={15} /> },
  { key: 'posts', label: 'Posts', icon: <Megaphone size={15} /> },
]

// Back-compat: the old per-tool routes (/gbp-posts, /gbp-profile, /gbp-metrics)
// redirect into the unified module on the matching tab, so existing deep-links
// (Action Plan CTAs, notifications) keep working.
export function GbpTabRedirect({ tab }: { tab: Tab }) {
  const { id = '' } = useParams()
  return <Navigate to={`/clients/${id}/gbp?tab=${tab}`} replace />
}

export function GoogleBusinessProfile() {
  const { id: clientId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const raw = (params.get('tab') || 'insights') as Tab
  const tab: Tab = TABS.some((t) => t.key === raw) ? raw : 'insights'

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId], queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const setTab = (t: Tab) => setParams((p) => { p.set('tab', t); return p }, { replace: true })

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 4px' }}>
      <Link to={`/clients/${clientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 14 }}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <MapPin size={22} color={ACCENT} />
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: '#0f172a' }}>Google Business Profile</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 16px', lineHeight: 1.6 }}>
        Performance insights, profile editing (description / services / hours), and posts — for
        {' '}{client?.name ?? 'this client'}'s Google Business Profile, all in one place.
      </p>

      {/* One shared Connect flow above every tab. */}
      <ConnectionBar accent={ACCENT} />

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #e2e8f0' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 16px', border: 'none',
              borderBottom: tab === t.key ? `2px solid ${ACCENT}` : '2px solid transparent',
              background: 'none', color: tab === t.key ? ACCENT : '#64748b',
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Each tab renders its existing tool body, embedded (no duplicate header
          or Connect bar). Keyed by tab so state resets cleanly on switch. */}
      {tab === 'insights' ? (
        <GbpMetrics key="insights" clientId={clientId} embedded />
      ) : tab === 'profile' ? (
        <GbpProfileBody key="profile" clientId={clientId} embedded />
      ) : (
        <GbpWorkspace key="posts" clientId={clientId} embedded />
      )}
    </div>
  )
}
