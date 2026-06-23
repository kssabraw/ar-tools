import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunListResponse, ClientListItem, RunStatus, SiloListResponse, SiloStatus } from '../lib/types'
import { Plus, RefreshCw, ArrowLeft, Layers, ArrowRight } from 'lucide-react'
import {
  BriefCacheDecisionModal,
  type BriefCacheStatus,
} from '../components/BriefCacheDecisionModal'

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

function siloStatusBadge(status: SiloStatus) {
  const map: Record<SiloStatus, { bg: string; color: string; label: string }> = {
    proposed:    { bg: '#fef3c7', color: '#92400e', label: 'Proposed' },
    approved:    { bg: '#dbeafe', color: '#1e40af', label: 'Approved' },
    rejected:    { bg: '#fee2e2', color: '#991b1b', label: 'Rejected' },
    in_progress: { bg: '#e0e7ff', color: '#3730a3', label: 'In Progress' },
    published:   { bg: '#dcfce7', color: '#166534', label: 'Published' },
    superseded:  { bg: '#f1f5f9', color: '#64748b', label: 'Superseded' },
  }
  const s = map[status] ?? { bg: '#f1f5f9', color: '#475569', label: status }
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '2px 10px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {s.label}
    </span>
  )
}

export function Runs() {
  const qc = useQueryClient()
  const [searchParams] = useSearchParams()
  const scopedClientId = searchParams.get('client') ?? undefined
  const [showNewRun, setShowNewRun] = useState(searchParams.get('new') === '1')
  const [keyword, setKeyword] = useState('')
  const [creating, setCreating] = useState(false)

  const { data: runsResp, isLoading: runsLoading, isFetching: runsFetching, refetch } = useQuery<RunListResponse>({
    queryKey: ['runs', scopedClientId ?? null],
    queryFn: () => api.get<RunListResponse>(scopedClientId ? `/runs?client_id=${scopedClientId}` : '/runs'),
    refetchInterval: (query) => {
      const runs = query.state.data?.data ?? []
      return runs.some(r => isRunning(r.status)) ? 8000 : false
    },
  })

  const runs = runsResp?.data ?? []

  // Silo candidates discovered while generating blog posts for this client.
  // Only meaningful when the page is scoped to a single client — the
  // /silos endpoint requires a client_id. page_size is bumped so we show
  // all of them ("see all silo pages") rather than the default first page.
  const { data: silosResp } = useQuery<SiloListResponse>({
    queryKey: ['silos', 'runs-scoped', scopedClientId ?? null],
    queryFn: () => api.get<SiloListResponse>(`/silos?client_id=${scopedClientId}&page_size=200`),
    enabled: Boolean(scopedClientId),
  })
  const silos = silosResp?.items ?? []

  const { data: clients = [] } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  const createRun = useMutation({
    mutationFn: (body: {
      client_id: string
      keyword: string
      sie_outlier_mode: string
      sie_force_refresh: boolean
      brief_force_refresh: boolean
    }) => api.post('/runs', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['runs'] })
      setShowNewRun(false)
      setKeyword('')
    },
  })

  // PRD v2.6 — cache-decision modal state. When the user submits the
  // form, we first check whether a cached brief already exists for the
  // (keyword, location_code). If yes, the modal opens and lets them
  // pick "reuse" or "regenerate" — that choice flows into
  // `brief_force_refresh` on the eventual create call. If no, we
  // skip the modal entirely.
  const [cacheStatus, setCacheStatus] = useState<BriefCacheStatus | null>(null)
  const [showCacheModal, setShowCacheModal] = useState(false)

  async function submitCreate(briefForceRefresh: boolean) {
    if (!scopedClientId) return
    setCreating(true)
    try {
      await createRun.mutateAsync({
        client_id: scopedClientId,
        keyword,
        sie_outlier_mode: 'safe',
        sie_force_refresh: false,
        brief_force_refresh: briefForceRefresh,
      })
    } finally {
      setCreating(false)
      setShowCacheModal(false)
      setCacheStatus(null)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    try {
      // Pre-flight cache check. Failure to fetch is non-fatal —
      // proceed with the run as if no cache existed (worst case the
      // user gets the cached result silently, the prior behavior).
      let status: BriefCacheStatus | null = null
      try {
        status = await api.get<BriefCacheStatus>(
          `/briefs/cache-status?keyword=${encodeURIComponent(keyword)}&location_code=2840`
        )
      } catch {
        status = null
      }
      if (status?.exists) {
        setCacheStatus(status)
        setShowCacheModal(true)
        return // wait for the user's modal choice
      }
      // No cache → straight to create.
      await submitCreate(false)
    } finally {
      // Only release the spinner here when we DIDN'T open the modal.
      // The modal path manages `creating` itself via submitCreate.
      if (!showCacheModal) setCreating(false)
    }
  }

  const scopedClient = clients.find(c => c.id === scopedClientId)

  return (
    <div style={{ padding: 32 }}>
      {scopedClientId && (
        <Link to={`/clients/${scopedClientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 16 }}>
          <ArrowLeft size={14} /> Back to {scopedClient?.name ?? 'client'}
        </Link>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={h1Style}>{scopedClientId ? `Content Runs · ${scopedClient?.name ?? ''}` : 'Content Runs'}</h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={() => refetch()}
            disabled={runsFetching}
            style={{ ...ghostBtn, ...(runsFetching ? { opacity: 0.7, cursor: 'default' } : {}) }}
          >
            <RefreshCw size={15} style={runsFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
            {runsFetching ? 'Refreshing…' : 'Refresh'}
          </button>
          {scopedClientId && !showNewRun && (
            <button onClick={() => setShowNewRun(true)} style={primaryBtn}>
              <Plus size={15} /> New Run
            </button>
          )}
        </div>
      </div>

      {scopedClientId && showNewRun && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 16px', color: '#0f172a' }}>New Run</h2>
          <form onSubmit={handleCreate} style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div>
              <label style={labelStyle}>Client</label>
              {/* Content is always written for the client whose workspace you
                  came from — the client is fixed, not chosen here. */}
              <div style={readonlyClientStyle}>{scopedClient?.name ?? 'This client'}</div>
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
          {scopedClientId
            ? 'No runs yet. Create one to get started.'
            : 'No runs yet. Open a client to create content.'}
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

      {scopedClientId && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 15, fontWeight: 600, margin: 0, color: '#0f172a' }}>
              <Layers size={17} /> Content Silos
            </h2>
            <Link to="/silos" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#6366f1', fontSize: 13, fontWeight: 500, textDecoration: 'none' }}>
              Manage silos <ArrowRight size={14} />
            </Link>
          </div>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 16px' }}>
            Standalone-article topics discovered while generating blog posts for this client.
          </p>
          {silos.length === 0 ? (
            <div style={{ color: '#64748b', fontSize: 14, padding: '8px 0' }}>
              No silo pages yet. They appear here as the Brief Generator discovers them during content runs.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                  {['Keyword', 'Status', 'Occurrences', 'Intent', ''].map(h => (
                    <th key={h} style={thStyle}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {silos.map(silo => (
                  <tr key={silo.id} style={{ borderBottom: '1px solid #f8fafc' }}>
                    <td style={{ ...tdStyle, fontWeight: 500, color: '#0f172a' }}>{silo.suggested_keyword}</td>
                    <td style={tdStyle}>{siloStatusBadge(silo.status)}</td>
                    <td style={{ ...tdStyle, color: '#64748b' }}>{silo.occurrence_count}</td>
                    <td style={{ ...tdStyle, color: '#64748b', fontSize: 13 }}>{silo.estimated_intent ?? '—'}</td>
                    <td style={tdStyle}>
                      {silo.promoted_to_run_id ? (
                        <Link to={`/runs/${silo.promoted_to_run_id}`} style={{ color: '#6366f1', fontSize: 13, textDecoration: 'none', fontWeight: 500 }}>
                          View run →
                        </Link>
                      ) : (
                        <Link to="/silos" style={{ color: '#6366f1', fontSize: 13, textDecoration: 'none', fontWeight: 500 }}>
                          Review →
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <BriefCacheDecisionModal
        open={showCacheModal}
        cacheStatus={cacheStatus}
        busy={creating}
        onReuse={() => submitCreate(false)}
        onRegenerate={() => submitCreate(true)}
        onCancel={() => {
          setShowCacheModal(false)
          setCacheStatus(null)
          setCreating(false)
        }}
      />
    </div>
  )
}

const h1Style: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }
const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }
const inputStyle: React.CSSProperties = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a' }
const readonlyClientStyle: React.CSSProperties = { padding: '8px 12px', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 14, color: '#0f172a', fontWeight: 500, background: '#f8fafc' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }
const tdStyle: React.CSSProperties = { padding: '12px 12px', fontSize: 14, color: '#374151' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
