import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { ClientListItem, MapsClientThreats, MapsThreatsResponse } from '../lib/types'
import { Plus, Globe } from 'lucide-react'

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')
}

// Top competitors outranking this client on the local-pack grid (Maps module).
// Renders nothing for clients without competitor scan data, so non-Maps tiles
// are unchanged.
function ThreatBlock({ threats }: { threats?: MapsClientThreats }) {
  if (!threats || threats.threats.length === 0) return null
  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f1f5f9' }}>
      <div style={threatLabel}>Outranking you on the map</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {threats.threats.map((t, i) => {
          const up = t.delta_pct != null && t.delta_pct > 0
          const down = t.delta_pct != null && t.delta_pct < 0
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, minWidth: 0 }}>
              <span style={{ color: '#334155', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>
                {t.name ?? '—'}
              </span>
              <span style={threatChip}>{t.beats_pct != null ? `${Math.round(t.beats_pct)}%` : '—'}</span>
              {(up || down) && (
                <span style={{ color: up ? '#dc2626' : '#16a34a', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>
                  {up ? '▲' : '▼'}{Math.abs(t.delta_pct as number)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function Home() {
  const { isAdmin } = useAuth()

  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  // Top-threat competitors per client (Maps geo-grid) — one call for all tiles.
  const { data: threatsResp } = useQuery<MapsThreatsResponse>({
    queryKey: ['maps-threats'],
    queryFn: () => api.get<MapsThreatsResponse>('/maps/threats'),
  })
  const threatsByClient = new Map((threatsResp?.clients ?? []).map(c => [c.client_id, c]))

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Dashboard</h1>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px' }}>
        Choose a client to get started.
      </p>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
          {clients.map(c => (
            <Link key={c.id} to={`/clients/${c.id}`} style={tileStyle}>
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
              <ThreatBlock threats={threatsByClient.get(c.id)} />
            </Link>
          ))}

          {isAdmin && (
            <Link to="/clients/new" style={{ ...tileStyle, ...addTileStyle }}>
              <Plus size={20} />
              <span style={{ fontWeight: 600, fontSize: 14 }}>Add Client</span>
            </Link>
          )}
        </div>
      )}

      {!isLoading && clients.length === 0 && !isAdmin && (
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
const threatLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 600, color: '#94a3b8',
  textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 6,
}
const threatChip: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#b91c1c', background: '#fef2f2',
  borderRadius: 999, padding: '1px 7px', flexShrink: 0,
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
