import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Run, RunListResponse, ClientListItem, RunStatus } from '../lib/types'
import { Plus, RefreshCw } from 'lucide-react'

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']

function isRunning(status: RunStatus) {
  return !TERMINAL.includes(status)
}

function statusBadge(status: RunStatus) {
  const map: Record<RunStatus, { bg: string; color: string; label: string }> = {
    queued:                  { bg: '#f1f5f9', color: '#475569', label: 'Queued' },
    brief_running:           { bg: '#dbeafe', color: '#1e40af', label: 'Brief' },
    sie_running:             { bg: '#dbeafe', color: '#1e40af', label: 'SIE' },
    research_running:        { bg: '#dbeafe', color: '#1e40af', label: 'Research' },
    writer_running:          { bg: '#dbeafe', color: '#1e40af', label: 'Writing' },
    sources_cited_running:   { bg: '#dbeafe', color: '#1e40af', label: 'Citations' },
    complete:                { bg: '#dcfce7', color: '#166534', label: 'Complete' },
    failed:                  { bg: '#fee2e2', color: '#991b1b', label: 'Failed' },
    cancelled:               { bg: '#f1f5f9', color: '#475569', label: 'Cancelled' },
  }
  const s = map[status] ?? { bg: '#f1f5f9', color: '#475569', label: status }
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '2px 10px', fontSize: 12, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

export function Runs() {
  const qc = useQueryClient()
  const [showNewRun, setShowNewRun] = useState(false)
  const [clientId, setClientId] = useState('')
  const [keyword, setKeyword] = useState('')
  const [creating, setCreating] = useState(false)

  const { data: runsResp, isLoading: runsLoading, refetch } = useQuery<RunListResponse>({
    queryKey: ['runs'],
    queryFn: () => api.get<RunListResponse>('/runs'),
    refetchInterval: (query) => {
      const runs = query.state.data?.data ?? []
      return runs.some(r => isRunning(r.status)) ? 8000 : false
    },
  })

  const runs = runsResp?.data ?? []

  const { data: clients = [] } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  const createRun = useMutation({
    mutationFn: (body: { client_id: string; keyword: string; sie_outlier_mode: string; sie_force_refresh: boolean }) =>
      api.post('/runs', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      setShowNewRun(false)
      setKeyword('')
      setClientId('')
    },
  })

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      await createRun.mutateAsync({
        client_id: clientId,
        keyword,
        sie_outlier_mode: 'safe',
        sie_force_refresh: false,
      })
    } finally {
      setCreating(false)
    }
  }

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={h1Style}>Content Runs</h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={() => refetch()} style={ghostBtn}>
            <RefreshCw size={15} /> Refresh
          </button>
          <button onClick={() => setShowNewRun(true)} style={primaryBtn}>
            <Plus size={15} /> New Run
          </button>
        </div>
      </div>

      {showNewRun && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 16px', color: '#0f172a' }}>New Run</h2>
          <form onSubmit={handleCreate} style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div>
              <label style={labelStyle}>Client</label>
              <select value={clientId} onChange={e => setClientId(e.target.value)} required style={inputStyle}>
                <option value="">Select client…</option>
                {clients.filter(c => !c.archived).map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 240 }}>
              <label style={labelStyle}>Keyword</label>
              <input
                value={keyword}
                onChange={e => setKeyword(e.target.value)}
                required
                maxLength={150}
                placeholder="e.g. best hvac systems 2026"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" disabled={creating} style={primaryBtn}>
                {creating ? 'Starting…' : 'Start'}
              </button>
              <button type="button" onClick={() => setShowNewRun(false)} style={ghostBtn}>
                Cancel
              </button>
            </div>
          </form>
          {createRun.error && (
            <div style={{ marginTop: 12, color: '#dc2626', fontSize: 13 }}>
              {(createRun.error as Error).message}
            </div>
          )}
        </div>
      )}

      {runsLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading runs…</div>
      ) : runs.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No runs yet. Create one to get started.
        </div>
      ) : (
        <div style={cardStyle}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                {['Client', 'Keyword', 'Status', 'Created', ''].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <tr key={run.id} style={{ borderBottom: '1px solid #f8fafc' }}>
                  <td style={tdStyle}>{run.client_name}</td>
                  <td style={{ ...tdStyle, fontWeight: 500, color: '#0f172a' }}>{run.keyword}</td>
                  <td style={tdStyle}>{statusBadge(run.status)}</td>
                  <td style={{ ...tdStyle, color: '#64748b', fontSize: 13 }}>
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                  <td style={tdStyle}>
                    <Link to={`/runs/${run.id}`} style={{ color: '#6366f1', fontSize: 13, textDecoration: 'none', fontWeight: 500 }}>
                      View →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const h1Style: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }
const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }
const inputStyle: React.CSSProperties = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }
const tdStyle: React.CSSProperties = { padding: '12px 12px', fontSize: 14, color: '#374151' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
