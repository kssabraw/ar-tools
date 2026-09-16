import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { ClientListItem } from '../lib/types'
import { Plus, Globe, Radar, Search, Pencil } from 'lucide-react'

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')
}

export function Prospects() {
  const navigate = useNavigate()
  const { isStaff } = useAuth()
  const [search, setSearch] = useState('')

  const { data: prospects = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['prospects'],
    queryFn: () => api.get<ClientListItem[]>('/clients?kind=prospect'),
  })

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? prospects.filter(p => p.name.toLowerCase().includes(q) || (p.website_url ?? '').toLowerCase().includes(q))
      : prospects.slice()
    filtered.sort((a, b) => a.name.localeCompare(b.name))
    return filtered
  }, [prospects, search])

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Radar size={20} color="#6366f1" />
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Prospects</h1>
        </div>
        {isStaff && (
          <Link to="/prospects/new" style={primaryBtn}>
            <Plus size={15} /> Add Prospect
          </Link>
        )}
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Lightweight prospecting records — run one-off Organic, Maps, AI-Visibility & Competitive reports without building a full client profile.
      </p>

      <div style={{ position: 'relative', marginBottom: 16, maxWidth: 360 }}>
        <Search size={15} style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search prospects or websites…"
          style={searchInput}
        />
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading prospects…</div>
      ) : prospects.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No prospects yet.{isStaff ? (
            <>
              {' '}
              <Link to="/prospects/new" style={{ color: '#6366f1', textDecoration: 'none', fontWeight: 500 }}>
                Add your first prospect
              </Link>{' '}
              to run a report.
            </>
          ) : null}
        </div>
      ) : visible.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 32 }}>
          No prospects match “{search}”.
        </div>
      ) : (
        <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={thStyle}>Prospect</th>
                <th style={thStyle}>Website</th>
                <th style={thStyle}>Added</th>
                {isStaff && <th style={{ ...thStyle, textAlign: 'right' }}></th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((p, i) => (
                <tr
                  key={p.id}
                  onClick={() => navigate(`/clients/${p.id}`)}
                  role="link"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/clients/${p.id}`) }}
                  style={{ borderTop: i === 0 ? 'none' : '1px solid #f1f5f9', cursor: 'pointer' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#f8fafc')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                      <div style={avatarStyle}>{p.name ? initials(p.name) : <Radar size={16} />}</div>
                      <span style={{ fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.name}</span>
                    </div>
                  </td>
                  <td style={tdStyle}>
                    {p.website_url ? (
                      <a href={p.website_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#6366f1', textDecoration: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 260 }}>
                        <Globe size={12} style={{ flexShrink: 0 }} /> <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.website_url}</span>
                      </a>
                    ) : (
                      <span style={{ fontSize: 13, color: '#94a3b8' }}>No website</span>
                    )}
                  </td>
                  <td style={{ ...tdStyle, color: '#64748b', fontSize: 13, whiteSpace: 'nowrap' }}>
                    {new Date(p.created_at).toLocaleDateString()}
                  </td>
                  {isStaff && (
                    <td style={{ ...tdStyle, textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <Link to={`/prospects/${p.id}/edit`} style={iconBtn} title="Edit">
                        <Pencil size={14} />
                      </Link>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24 }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer', textDecoration: 'none', whiteSpace: 'nowrap' }
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', textDecoration: 'none' }
const searchInput: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: '9px 12px 9px 34px', fontSize: 14, color: '#0f172a', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 16px', fontSize: 12, fontWeight: 600, color: '#64748b', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '10px 16px', verticalAlign: 'middle' }
const avatarStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 28, height: 28, borderRadius: 6, flexShrink: 0,
  background: '#eef2ff', color: '#6366f1', fontWeight: 700, fontSize: 12,
}
