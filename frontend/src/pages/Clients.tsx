import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { ClientListItem } from '../lib/types'
import { Plus, X, Check, Globe, AlertCircle, Clock, Pencil, Search, ChevronUp, ChevronDown } from 'lucide-react'

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('')
}

function AnalysisStatus({ status }: { status: ClientListItem['website_analysis_status'] }) {
  if (status === 'complete') return <span style={{ fontSize: 12, color: '#16a34a', whiteSpace: 'nowrap' }}>✓ Analyzed</span>
  if (status === 'failed') return <span style={{ fontSize: 12, color: '#dc2626', whiteSpace: 'nowrap' }}><AlertCircle size={11} style={{ verticalAlign: 'middle' }} /> Failed</span>
  return <span style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}><Clock size={11} style={{ verticalAlign: 'middle' }} /> Analyzing…</span>
}

type SortKey = 'name' | 'status' | 'created_at'
type SortDir = 'asc' | 'desc'

// Rank the setup statuses so sorting groups them meaningfully
// (needs-attention first when descending).
const STATUS_RANK: Record<ClientListItem['website_analysis_status'], number> = {
  failed: 2, pending: 1, complete: 0,
}

export function Clients() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { isStaff } = useAuth()
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    refetchInterval: (query) => {
      const list = query.state.data ?? []
      return list.some(c => c.website_analysis_status === 'pending') ? 8000 : false
    },
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/clients/${id}/archive`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clients'] }),
  })

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = q
      ? clients.filter(c => c.name.toLowerCase().includes(q) || c.website_url.toLowerCase().includes(q))
      : clients.slice()
    const dir = sortDir === 'asc' ? 1 : -1
    filtered.sort((a, b) => {
      let cmp = 0
      if (sortKey === 'name') cmp = a.name.localeCompare(b.name)
      else if (sortKey === 'status') cmp = STATUS_RANK[a.website_analysis_status] - STATUS_RANK[b.website_analysis_status]
      else cmp = a.created_at.localeCompare(b.created_at)
      if (cmp === 0) cmp = a.name.localeCompare(b.name)
      return cmp * dir
    })
    return filtered
  }, [clients, search, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir(key === 'name' ? 'asc' : 'desc') }
  }

  function SortHeader({ label, k, align = 'left' }: { label: string; k: SortKey; align?: 'left' | 'right' }) {
    const active = sortKey === k
    return (
      <th
        onClick={() => toggleSort(k)}
        style={{ ...thStyle, textAlign: align, cursor: 'pointer', userSelect: 'none', color: active ? '#0f172a' : '#64748b' }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
          {label}
          {active && (sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
        </span>
      </th>
    )
  }

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Clients</h1>
        {isStaff && (
          <Link to="/clients/new" style={primaryBtn}>
            <Plus size={15} /> Add Client
          </Link>
        )}
      </div>

      <div style={{ position: 'relative', marginBottom: 16, maxWidth: 360 }}>
        <Search size={15} style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search clients or websites…"
          style={searchInput}
        />
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : clients.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No clients yet.{isStaff ? (
            <>
              {' '}
              <Link to="/clients/new" style={{ color: '#6366f1', textDecoration: 'none', fontWeight: 500 }}>
                Add your first client
              </Link>{' '}
              to get started.
            </>
          ) : null}
        </div>
      ) : visible.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 32 }}>
          No clients match “{search}”.
        </div>
      ) : (
        <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <SortHeader label="Client" k="name" />
                <th style={thStyle}>Website</th>
                <SortHeader label="Setup" k="status" />
                <SortHeader label="Added" k="created_at" />
                {isStaff && <th style={{ ...thStyle, textAlign: 'right' }}></th>}
              </tr>
            </thead>
            <tbody>
              {visible.map((c, i) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/clients/${c.id}`)}
                  role="link"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/clients/${c.id}`) }}
                  style={{ borderTop: i === 0 ? 'none' : '1px solid #f1f5f9', cursor: 'pointer' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#f8fafc')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                      {c.logo_url ? (
                        <img src={c.logo_url} alt="" style={{ width: 28, height: 28, borderRadius: 6, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0', flexShrink: 0 }} />
                      ) : (
                        <div style={avatarStyle}>{initials(c.name)}</div>
                      )}
                      <span style={{ fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.name}</span>
                    </div>
                  </td>
                  <td style={tdStyle}>
                    <a href={c.website_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#6366f1', textDecoration: 'none', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 260 }}>
                      <Globe size={12} style={{ flexShrink: 0 }} /> <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.website_url}</span>
                    </a>
                  </td>
                  <td style={tdStyle}><AnalysisStatus status={c.website_analysis_status} /></td>
                  <td style={{ ...tdStyle, color: '#64748b', fontSize: 13, whiteSpace: 'nowrap' }}>
                    {new Date(c.created_at).toLocaleDateString()}
                  </td>
                  {isStaff && (
                    <td style={{ ...tdStyle, textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                        <Link to={`/clients/${c.id}/edit`} style={iconBtn} title="Edit">
                          <Pencil size={14} />
                        </Link>
                        {deleteId === c.id ? (
                          <>
                            <span style={{ fontSize: 12, color: '#dc2626' }}>Archive?</span>
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
                      </div>
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
