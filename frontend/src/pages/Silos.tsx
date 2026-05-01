import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Layers,
  Play,
  RefreshCw,
  Search,
  X,
} from 'lucide-react'
import { api } from '../lib/api'
import type {
  ClientListItem,
  IntentType,
  SiloDetail,
  SiloListItem,
  SiloListResponse,
  SiloMetrics,
  SiloRoutedFrom,
  SiloStatus,
  SiloBulkResponse,
  SiloPromoteResponse,
} from '../lib/types'

// ----------------------------------------------------------------------
// Constants & helpers
// ----------------------------------------------------------------------

const STATUS_LABEL: Record<SiloStatus, string> = {
  proposed: 'Proposed',
  approved: 'Approved',
  rejected: 'Rejected',
  in_progress: 'In Progress',
  published: 'Published',
  superseded: 'Superseded',
}

function statusBadge(status: SiloStatus) {
  const map: Record<SiloStatus, { bg: string; color: string }> = {
    proposed:    { bg: '#fef3c7', color: '#92400e' },
    approved:    { bg: '#dbeafe', color: '#1e40af' },
    rejected:    { bg: '#fee2e2', color: '#991b1b' },
    in_progress: { bg: '#e0e7ff', color: '#3730a3' },
    published:   { bg: '#dcfce7', color: '#166534' },
    superseded:  { bg: '#f1f5f9', color: '#64748b' },
  }
  const s = map[status]
  return (
    <span
      style={{
        background: s.bg,
        color: s.color,
        borderRadius: 999,
        padding: '2px 10px',
        fontSize: 12,
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

const ALL_STATUSES: SiloStatus[] = [
  'proposed', 'approved', 'in_progress', 'published', 'superseded', 'rejected',
]

const ALL_INTENTS: IntentType[] = [
  'informational',
  'how-to',
  'listicle',
  'comparison',
  'ecom',
  'local-seo',
  'news',
  'informational-commercial',
]

const ALL_ROUTED_FROM: SiloRoutedFrom[] = ['non_selected_region', 'scope_verification']

function formatDate(iso: string | null | undefined) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function formatScore(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return n.toFixed(2)
}

// ----------------------------------------------------------------------
// Page
// ----------------------------------------------------------------------

export function Silos() {
  const qc = useQueryClient()

  const { data: clients = [] } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  const [clientId, setClientId] = useState('')
  const [statusFilter, setStatusFilter] = useState<SiloStatus[]>([])
  const [intentFilter, setIntentFilter] = useState<IntentType[]>([])
  const [routedFilter, setRoutedFilter] = useState<SiloRoutedFrom[]>([])
  const [viableOnly, setViableOnly] = useState<boolean | null>(null)
  const [search, setSearch] = useState('')
  const [page] = useState(1)
  const [pageSize] = useState(50)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Auto-select the first non-archived client if none chosen yet.
  const activeClients = useMemo(() => clients.filter(c => !c.archived), [clients])
  if (!clientId && activeClients.length > 0) {
    setClientId(activeClients[0].id)
  }

  const queryKey = [
    'silos', clientId, statusFilter, intentFilter, routedFilter, viableOnly, search, page,
  ]

  const { data: listResp, isLoading, refetch } = useQuery<SiloListResponse>({
    queryKey,
    enabled: !!clientId,
    queryFn: () => {
      const params = new URLSearchParams({
        client_id: clientId,
        page: String(page),
        page_size: String(pageSize),
      })
      for (const s of statusFilter) params.append('status', s)
      for (const i of intentFilter) params.append('estimated_intent', i)
      for (const r of routedFilter) params.append('routed_from', r)
      if (viableOnly !== null) params.set('viable_as_standalone_article', String(viableOnly))
      if (search.trim()) params.set('search', search.trim())
      return api.get<SiloListResponse>(`/silos?${params.toString()}`)
    },
  })

  const { data: metrics } = useQuery<SiloMetrics>({
    queryKey: ['silo-metrics', clientId],
    enabled: !!clientId,
    queryFn: () => api.get<SiloMetrics>(`/silos/metrics?client_id=${clientId}`),
  })

  const items = listResp?.items ?? []

  // ---- Mutations ----

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'approved' | 'rejected' }) =>
      api.patch<SiloListItem>(`/silos/${id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['silos', clientId] }),
  })

  const promote = useMutation<SiloPromoteResponse, Error, string>({
    mutationFn: (id) => api.post<SiloPromoteResponse>(`/silos/${id}/promote`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['silos', clientId] })
      qc.invalidateQueries({ queryKey: ['silo-metrics', clientId] })
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const bulkApproveAndGenerate = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) =>
      api.post<SiloBulkResponse>('/silos/bulk-approve-and-generate', { ids }),
    onSuccess: (res) => {
      setSelectedIds(new Set())
      qc.invalidateQueries({ queryKey: ['silos', clientId] })
      qc.invalidateQueries({ queryKey: ['silo-metrics', clientId] })
      qc.invalidateQueries({ queryKey: ['runs'] })
      if (res.failed.length > 0) {
        alert(
          `Dispatched ${res.runs_dispatched.length} runs. ${res.failed.length} failed: ` +
            res.failed.map(f => `${f.id.slice(0, 8)}: ${f.reason}`).join('; ')
        )
      }
    },
  })

  const bulkApprove = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) => api.post<SiloBulkResponse>('/silos/bulk-approve', { ids }),
    onSuccess: () => {
      setSelectedIds(new Set())
      qc.invalidateQueries({ queryKey: ['silos', clientId] })
    },
  })

  const bulkReject = useMutation<SiloBulkResponse, Error, string[]>({
    mutationFn: (ids) => api.post<SiloBulkResponse>('/silos/bulk-reject', { ids }),
    onSuccess: () => {
      setSelectedIds(new Set())
      qc.invalidateQueries({ queryKey: ['silos', clientId] })
    },
  })

  // ---- Selection helpers ----

  function toggleSelected(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (selectedIds.size === items.length && items.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(items.map(i => i.id)))
    }
  }

  // ---- Render ----

  const highFreqVisible =
    metrics && metrics.high_frequency_count > 0

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Layers size={22} color="#6366f1" />
          <h1 style={h1Style}>Silo Candidates</h1>
        </div>
        <button onClick={() => refetch()} style={ghostBtn}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      {/* Client selector */}
      <div style={{ ...cardStyle, padding: 16 }}>
        <label style={{ ...labelStyle, display: 'inline-block', marginRight: 12 }}>Client</label>
        <select
          value={clientId}
          onChange={e => {
            setClientId(e.target.value)
            setSelectedIds(new Set())
            setExpandedId(null)
          }}
          style={{ ...inputStyle, minWidth: 260 }}
        >
          {activeClients.length === 0 && <option value="">No active clients</option>}
          {activeClients.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* High-frequency banner */}
      {highFreqVisible && (
        <div style={{
          ...cardStyle,
          padding: 14,
          background: '#fef3c7',
          borderColor: '#fde68a',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}>
          <AlertCircle size={18} color="#92400e" />
          <span style={{ fontSize: 14, color: '#92400e', fontWeight: 500 }}>
            {metrics!.high_frequency_count} silo{metrics!.high_frequency_count === 1 ? '' : 's'}
            {' '}have appeared in {metrics!.high_frequency_threshold}+ briefs — review now.
          </span>
        </div>
      )}

      {/* Metrics row */}
      {metrics && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          {ALL_STATUSES.map(s => (
            <div key={s} style={metricCard}>
              <div style={{ fontSize: 12, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {STATUS_LABEL[s]}
              </div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>
                {metrics.counts_by_status[s] ?? 0}
              </div>
            </div>
          ))}
          <div style={metricCard}>
            <div style={{ fontSize: 12, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Avg occurrence
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>
              {metrics.average_occurrence_count.toFixed(1)}
            </div>
          </div>
        </div>
      )}

      {/* Filters + search */}
      <div style={{ ...cardStyle, padding: 16, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: 11, color: '#94a3b8' }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search keyword…"
            style={{ ...inputStyle, paddingLeft: 32, width: '100%', boxSizing: 'border-box' }}
          />
        </div>
        <MultiSelect
          label="Status"
          options={ALL_STATUSES.map(s => ({ value: s, label: STATUS_LABEL[s] }))}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v as SiloStatus[])}
        />
        <MultiSelect
          label="Intent"
          options={ALL_INTENTS.map(i => ({ value: i, label: i }))}
          value={intentFilter}
          onChange={(v) => setIntentFilter(v as IntentType[])}
        />
        <MultiSelect
          label="Routed from"
          options={ALL_ROUTED_FROM.map(r => ({ value: r, label: r.replace('_', ' ') }))}
          value={routedFilter}
          onChange={(v) => setRoutedFilter(v as SiloRoutedFrom[])}
        />
        <select
          value={viableOnly === null ? '' : String(viableOnly)}
          onChange={e => {
            const v = e.target.value
            setViableOnly(v === '' ? null : v === 'true')
          }}
          style={inputStyle}
        >
          <option value="">All viable</option>
          <option value="true">Viable only</option>
          <option value="false">Non-viable only</option>
        </select>
      </div>

      {/* Bulk actions toolbar */}
      {selectedIds.size > 0 && (
        <div style={{
          ...cardStyle,
          padding: 12,
          display: 'flex',
          gap: 10,
          alignItems: 'center',
          background: '#eef2ff',
          borderColor: '#c7d2fe',
        }}>
          <span style={{ color: '#3730a3', fontWeight: 600, fontSize: 13 }}>
            {selectedIds.size} selected
          </span>
          <button
            onClick={() => {
              if (confirm(`Approve ${selectedIds.size} candidate(s) and dispatch runs?`)) {
                bulkApproveAndGenerate.mutate(Array.from(selectedIds))
              }
            }}
            disabled={bulkApproveAndGenerate.isPending}
            style={primaryBtn}
          >
            <Play size={14} /> Approve & generate
          </button>
          <button
            onClick={() => bulkApprove.mutate(Array.from(selectedIds))}
            disabled={bulkApprove.isPending}
            style={ghostBtn}
          >
            <Check size={14} /> Approve only
          </button>
          <button
            onClick={() => {
              if (selectedIds.size > 10) {
                const typed = prompt(
                  `You're rejecting ${selectedIds.size} candidates. Type "reject" to confirm:`
                )
                if (typed !== 'reject') return
              } else if (!confirm(`Reject ${selectedIds.size} candidate(s)?`)) {
                return
              }
              bulkReject.mutate(Array.from(selectedIds))
            }}
            disabled={bulkReject.isPending}
            style={dangerBtn}
          >
            <X size={14} /> Reject
          </button>
          <button onClick={() => setSelectedIds(new Set())} style={{ ...ghostBtn, marginLeft: 'auto' }}>
            Clear
          </button>
        </div>
      )}

      {/* List */}
      {!clientId ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          Select a client to view silo candidates.
        </div>
      ) : isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading silos…</div>
      ) : items.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No silo candidates for this client yet. They appear automatically after briefs complete.
        </div>
      ) : (
        <div style={cardStyle}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                <th style={{ ...thStyle, width: 32 }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.size === items.length && items.length > 0}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th style={{ ...thStyle, width: 28 }}></th>
                <th style={thStyle}>Keyword</th>
                <th style={thStyle}>Status</th>
                <th style={thStyle}>Occurrences</th>
                <th style={thStyle}>Demand</th>
                <th style={thStyle}>Coherence</th>
                <th style={thStyle}>Viable</th>
                <th style={thStyle}>Intent</th>
                <th style={thStyle}>Routed from</th>
                <th style={thStyle}>First seen</th>
                <th style={thStyle}>Last seen</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {items.map(silo => (
                <SiloRow
                  key={silo.id}
                  silo={silo}
                  selected={selectedIds.has(silo.id)}
                  expanded={expandedId === silo.id}
                  onToggleSelect={() => toggleSelected(silo.id)}
                  onToggleExpand={() =>
                    setExpandedId(prev => (prev === silo.id ? null : silo.id))
                  }
                  onApprove={() => updateStatus.mutate({ id: silo.id, status: 'approved' })}
                  onReject={() => updateStatus.mutate({ id: silo.id, status: 'rejected' })}
                  onPromote={() => promote.mutate(silo.id)}
                  promoting={promote.isPending && promote.variables === silo.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------
// Row + drawer
// ----------------------------------------------------------------------

function SiloRow(props: {
  silo: SiloListItem
  selected: boolean
  expanded: boolean
  onToggleSelect: () => void
  onToggleExpand: () => void
  onApprove: () => void
  onReject: () => void
  onPromote: () => void
  promoting: boolean
}) {
  const { silo, selected, expanded, promoting } = props
  const canApprove = silo.status === 'proposed' || silo.status === 'published'
  const canReject = silo.status !== 'in_progress' && silo.status !== 'rejected'
  const canPromote =
    silo.status === 'proposed' || silo.status === 'approved' || silo.status === 'published'

  const failed = !!silo.last_promotion_failed_at

  return (
    <>
      <tr style={{ borderBottom: '1px solid #f8fafc', background: selected ? '#fafbff' : undefined }}>
        <td style={tdStyle}>
          <input type="checkbox" checked={selected} onChange={props.onToggleSelect} />
        </td>
        <td style={tdStyle}>
          <button
            onClick={props.onToggleExpand}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#64748b', display: 'flex', alignItems: 'center',
            }}
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        </td>
        <td style={{ ...tdStyle, fontWeight: 500, color: '#0f172a', maxWidth: 360 }}>
          <div>{silo.suggested_keyword}</div>
          {failed && (
            <div style={{ marginTop: 4, fontSize: 12, color: '#b91c1c', display: 'flex', alignItems: 'center', gap: 4 }}>
              <AlertCircle size={12} /> last promotion failed
            </div>
          )}
        </td>
        <td style={tdStyle}>{statusBadge(silo.status)}</td>
        <td style={tdStyle}>{silo.occurrence_count}</td>
        <td style={tdStyle}>{formatScore(silo.search_demand_score)}</td>
        <td style={tdStyle}>{formatScore(silo.cluster_coherence_score)}</td>
        <td style={tdStyle}>{silo.viable_as_standalone_article ? '✓' : '✗'}</td>
        <td style={tdStyle}>{silo.estimated_intent ?? '—'}</td>
        <td style={{ ...tdStyle, fontSize: 12, color: '#64748b' }}>
          {silo.routed_from?.replace('_', ' ') ?? '—'}
        </td>
        <td style={{ ...tdStyle, color: '#64748b', fontSize: 13 }}>{formatDate(silo.created_at)}</td>
        <td style={{ ...tdStyle, color: '#64748b', fontSize: 13 }}>{formatDate(silo.updated_at)}</td>
        <td style={{ ...tdStyle, textAlign: 'right', whiteSpace: 'nowrap' }}>
          {canPromote && (
            <button
              onClick={props.onPromote}
              disabled={promoting}
              style={{ ...rowAction, color: '#3730a3' }}
              title="Approve and generate run"
            >
              {promoting ? '…' : <Play size={14} />}
            </button>
          )}
          {canApprove && (
            <button
              onClick={props.onApprove}
              style={{ ...rowAction, color: '#166534' }}
              title="Approve"
            >
              <Check size={14} />
            </button>
          )}
          {canReject && (
            <button
              onClick={props.onReject}
              style={{ ...rowAction, color: '#991b1b' }}
              title="Reject"
            >
              <X size={14} />
            </button>
          )}
        </td>
      </tr>
      {expanded && <SiloDrawer siloId={silo.id} />}
    </>
  )
}

function SiloDrawer({ siloId }: { siloId: string }) {
  const { data: detail, isLoading } = useQuery<SiloDetail>({
    queryKey: ['silo-detail', siloId],
    queryFn: () => api.get<SiloDetail>(`/silos/${siloId}`),
  })

  return (
    <tr>
      <td colSpan={13} style={{ padding: 0, background: '#f8fafc' }}>
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #f1f5f9' }}>
          {isLoading || !detail ? (
            <div style={{ color: '#64748b', fontSize: 13 }}>Loading detail…</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              <div>
                <h4 style={drawerH4}>Viability reasoning</h4>
                <p style={drawerBody}>
                  {detail.viability_reasoning || <span style={{ color: '#94a3b8' }}>—</span>}
                </p>

                <h4 style={drawerH4}>Discard reason breakdown</h4>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {Object.entries(detail.discard_reason_breakdown ?? {}).length === 0 ? (
                    <span style={{ color: '#94a3b8', fontSize: 13 }}>none</span>
                  ) : (
                    Object.entries(detail.discard_reason_breakdown).map(([reason, count]) => (
                      <span key={reason} style={breakdownPill}>
                        {reason}: <strong>{count}</strong>
                      </span>
                    ))
                  )}
                </div>

                <h4 style={drawerH4}>Source briefs ({detail.source_run_ids.length})</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {detail.source_run_ids.map(runId => (
                    <Link
                      key={runId}
                      to={`/runs/${runId}`}
                      style={{
                        color: '#6366f1', fontSize: 13, textDecoration: 'none',
                        display: 'flex', alignItems: 'center', gap: 4,
                      }}
                    >
                      <ExternalLink size={12} /> {runId.slice(0, 8)}…
                    </Link>
                  ))}
                </div>
              </div>
              <div>
                <h4 style={drawerH4}>Source headings ({detail.source_headings.length})</h4>
                <div style={{ maxHeight: 240, overflowY: 'auto' }}>
                  <table style={{ width: '100%', fontSize: 13 }}>
                    <thead>
                      <tr style={{ color: '#64748b', textAlign: 'left' }}>
                        <th style={{ padding: '4px 0', fontWeight: 600 }}>Heading</th>
                        <th style={{ padding: '4px 0', fontWeight: 600, width: 80 }}>Source</th>
                        <th style={{ padding: '4px 0', fontWeight: 600, width: 60 }}>Rel.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.source_headings.map((h, i) => (
                        <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 0', color: '#0f172a' }}>{h.text}</td>
                          <td style={{ padding: '6px 0', color: '#64748b', fontSize: 12 }}>{h.source}</td>
                          <td style={{ padding: '6px 0', color: '#64748b', fontSize: 12 }}>
                            {h.title_relevance !== undefined ? h.title_relevance.toFixed(2) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </td>
    </tr>
  )
}

// ----------------------------------------------------------------------
// MultiSelect (lightweight inline)
// ----------------------------------------------------------------------

function MultiSelect(props: {
  label: string
  options: { value: string; label: string }[]
  value: string[]
  onChange: (v: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{ ...inputStyle, cursor: 'pointer', minWidth: 140, textAlign: 'left' }}
      >
        {props.label}{props.value.length > 0 ? ` (${props.value.length})` : ''}
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            background: '#fff',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            padding: 8,
            zIndex: 10,
            minWidth: 180,
            boxShadow: '0 4px 14px rgba(15,23,42,0.08)',
          }}
        >
          {props.options.map(opt => (
            <label
              key={opt.value}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '4px 6px',
                cursor: 'pointer',
                fontSize: 13,
                color: '#374151',
              }}
            >
              <input
                type="checkbox"
                checked={props.value.includes(opt.value)}
                onChange={() => {
                  if (props.value.includes(opt.value)) {
                    props.onChange(props.value.filter(v => v !== opt.value))
                  } else {
                    props.onChange([...props.value, opt.value])
                  }
                }}
              />
              {opt.label}
            </label>
          ))}
          {props.value.length > 0 && (
            <button
              type="button"
              onClick={() => props.onChange([])}
              style={{
                marginTop: 4,
                width: '100%',
                background: 'none',
                border: 'none',
                color: '#6366f1',
                fontSize: 12,
                cursor: 'pointer',
                padding: '4px 6px',
                textAlign: 'left',
              }}
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------
// Styles
// ----------------------------------------------------------------------

const h1Style: React.CSSProperties = { fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }
const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }
const inputStyle: React.CSSProperties = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a', background: '#fff' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }
const tdStyle: React.CSSProperties = { padding: '12px 12px', fontSize: 14, color: '#374151', verticalAlign: 'top' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const dangerBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#991b1b', border: '1px solid #fecaca', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const rowAction: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', padding: '4px 6px', marginLeft: 4 }
const metricCard: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 16px', minWidth: 110 }
const drawerH4: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }
const drawerBody: React.CSSProperties = { fontSize: 14, color: '#374151', margin: '0 0 16px', lineHeight: 1.5 }
const breakdownPill: React.CSSProperties = { background: '#f1f5f9', color: '#475569', padding: '3px 10px', borderRadius: 999, fontSize: 12 }
