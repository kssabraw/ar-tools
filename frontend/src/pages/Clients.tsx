import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { ClientListItem, ClientRankingHealth, RankingHealthResponse, RankingTrend, VisibilityTrend, UnreadCountsResponse } from '../lib/types'
import { Plus, X, Check, Globe, Bell, Pencil } from 'lucide-react'

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')
}

// Shared row layout: a label, a current-value readout, and a direction chip.
// `direction` "up" always means improved (green up-arrow) regardless of axis —
// the backend normalizes polarity, so lower-is-better rank and higher-is-better
// visibility both map "up" → green.
function MetricRow({ label, value, direction, delta, deltaSuffix = '' }: {
  label: string
  value: string
  direction: 'up' | 'down' | 'flat' | null
  delta: number | null
  deltaSuffix?: string
}) {
  const up = direction === 'up'
  const down = direction === 'down'
  const color = up ? '#16a34a' : down ? '#dc2626' : '#94a3b8'
  const arrow = up ? '▲' : down ? '▼' : '–'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
      <span style={{ color: '#334155', flex: 1 }}>{label}</span>
      <span style={{ color: '#64748b', fontWeight: 600 }}>{value}</span>
      <span style={{ color, fontSize: 11, fontWeight: 700, flexShrink: 0, minWidth: 46, textAlign: 'right' }}>
        {arrow}{delta != null && direction !== 'flat' ? ` ${Math.abs(delta).toFixed(1)}${deltaSuffix}` : ''}
      </span>
    </div>
  )
}

// One average-rank trend (latest run vs first). Lower rank is better; an "up"
// direction (rank number dropped) is the improvement. Renders nothing when
// there's no latest value to show.
function TrendRow({ label, trend }: { label: string; trend: RankingTrend }) {
  if (trend.latest_avg == null) return null
  return (
    <MetricRow
      label={label}
      value={`avg #${trend.latest_avg.toFixed(1)}`}
      direction={trend.direction}
      delta={trend.delta}
    />
  )
}

// AI-visibility share trend (latest scan batch vs first). Higher share is
// better; the backend already normalizes "up" → improved. Renders nothing when
// there's no latest value to show.
function VisibilityRow({ label, trend }: { label: string; trend: VisibilityTrend }) {
  if (trend.latest_pct == null) return null
  return (
    <MetricRow
      label={label}
      value={`${trend.latest_pct.toFixed(0)}% visible`}
      direction={trend.direction}
      delta={trend.delta}
      deltaSuffix="%"
    />
  )
}

// Organic + maps ranking trend and AI-visibility share (most recent run vs the
// first) for a client tile. Renders nothing for clients tracking none of the
// three, so non-ranking tiles are unchanged.
function RankTrendBlock({ health }: { health?: ClientRankingHealth }) {
  if (!health) return null
  const hasOrganic = health.organic.latest_avg != null
  const hasMaps = health.maps.latest_avg != null
  const hasVisibility = health.visibility?.latest_pct != null
  if (!hasOrganic && !hasMaps && !hasVisibility) return null
  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f1f5f9' }}>
      <div style={threatLabel}>Performance · latest vs first</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <TrendRow label="Organic" trend={health.organic} />
        <TrendRow label="Maps" trend={health.maps} />
        {health.visibility && <VisibilityRow label="AI Visibility" trend={health.visibility} />}
      </div>
    </div>
  )
}

export function Clients() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { isStaff } = useAuth()
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  // Per-client average-ranking trend (organic + maps, latest vs first) — one
  // call for all tiles.
  const { data: rankingResp } = useQuery<RankingHealthResponse>({
    queryKey: ['ranking-health'],
    queryFn: () => api.get<RankingHealthResponse>('/dashboard/ranking-health'),
  })
  const healthByClient = new Map((rankingResp?.clients ?? []).map(c => [c.client_id, c]))

  // Unread notification count per client → the card badge.
  const { data: unreadResp } = useQuery<UnreadCountsResponse>({
    queryKey: ['notification-unread-counts'],
    queryFn: () => api.get<UnreadCountsResponse>('/notifications/unread-counts'),
    refetchInterval: 60000,
  })
  const unreadByClient = new Map((unreadResp?.counts ?? []).map(u => [u.client_id, u.count]))

  const archiveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/clients/${id}/archive`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clients'] }),
  })

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Clients</h1>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px' }}>
        Choose a client to get started.
      </p>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
          {clients.map(c => {
            const unread = unreadByClient.get(c.id) ?? 0
            return (
              <div
                key={c.id}
                onClick={() => navigate(`/clients/${c.id}`)}
                role="link"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/clients/${c.id}`) }}
                style={{ ...tileStyle, position: 'relative', cursor: 'pointer' }}
              >
                <div style={topRightCluster} onClick={(e) => e.stopPropagation()}>
                  {unread > 0 && (
                    <span style={notifyBadge} title={`${unread} new alert${unread === 1 ? '' : 's'}`}>
                      <Bell size={11} /> {unread}
                    </span>
                  )}
                  {isStaff && (
                    <>
                      <Link to={`/clients/${c.id}/edit`} style={iconBtn} title="Edit">
                        <Pencil size={14} />
                      </Link>
                      {deleteId === c.id ? (
                        <>
                          <button onClick={() => { archiveMutation.mutate(c.id); setDeleteId(null) }}
                            style={{ ...iconBtn, color: '#dc2626', borderColor: '#fca5a5' }} title="Confirm archive">
                            <Check size={14} />
                          </button>
                          <button onClick={() => setDeleteId(null)} style={iconBtn} title="Cancel"><X size={14} /></button>
                        </>
                      ) : (
                        <button onClick={() => setDeleteId(c.id)} style={{ ...iconBtn, color: '#dc2626' }} title="Archive">
                          <X size={14} />
                        </button>
                      )}
                    </>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {c.logo_url ? (
                    <img
                      src={c.logo_url}
                      alt=""
                      style={{ width: 44, height: 44, borderRadius: 10, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0' }}
                    />
                  ) : (
                    <div style={avatarStyle}>{initials(c.name)}</div>
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {c.name}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      <Globe size={11} /> {c.website_url}
                    </div>
                  </div>
                </div>
                <RankTrendBlock health={healthByClient.get(c.id)} />
              </div>
            )
          })}

          {isStaff && (
            <Link to="/clients/new" style={{ ...tileStyle, ...addTileStyle }}>
              <Plus size={20} />
              <span style={{ fontWeight: 600, fontSize: 14 }}>Add Client</span>
            </Link>
          )}
        </div>
      )}

      {!isLoading && clients.length === 0 && !isStaff && (
        <div style={{ color: '#64748b', fontSize: 14, marginTop: 8 }}>
          No clients yet. Ask an admin to add one.
        </div>
      )}
    </div>
  )
}

const tileStyle: React.CSSProperties = {
  display: 'block',
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 20,
  textDecoration: 'none',
}
const topRightCluster: React.CSSProperties = {
  position: 'absolute', top: 10, right: 10,
  display: 'inline-flex', alignItems: 'center', gap: 6,
}
const notifyBadge: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 3,
  fontSize: 11, fontWeight: 700, color: '#fff', background: '#dc2626',
  borderRadius: 999, padding: '2px 8px',
}
const threatLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 600, color: '#94a3b8',
  textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 6,
}
const avatarStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 44, height: 44, borderRadius: 10, flexShrink: 0,
  background: '#eef2ff', color: '#6366f1', fontWeight: 700, fontSize: 15,
}
const addTileStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
  gap: 8, color: '#6366f1', border: '1px dashed #c7d2fe', background: '#f8faff',
  minHeight: 84,
}
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', textDecoration: 'none' }
