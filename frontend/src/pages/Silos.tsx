import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Layers,
  RefreshCw,
  Search,
} from 'lucide-react'
import { api } from '../lib/api'
import type {
  ClientListItem,
  IntentType,
  SiloListResponse,
  SiloMetrics,
  SiloRoutedFrom,
  SiloStatus,
} from '../lib/types'
import {
  SiloBulkToolbar,
  SiloRow,
  SiloTableHead,
} from '../components/silos/SiloTable'
import { useSiloMutations } from '../components/silos/siloShared'

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

// ----------------------------------------------------------------------
// Page
// ----------------------------------------------------------------------

export function Silos() {
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

  // Auto-select the first non-archived client when the clients list
  // first arrives. The previous `setClientId` call sat directly in the
  // function body, which is a setState-during-render anti-pattern —
  // React would warn and drop the update, leaving clientId='' so the
  // silos query never fired (`enabled: !!clientId`). Effect form
  // applies the update after render so the next render has the value.
  const activeClients = useMemo(() => clients.filter(c => !c.archived), [clients])
  useEffect(() => {
    if (!clientId && activeClients.length > 0) {
      setClientId(activeClients[0].id)
    }
  }, [clientId, activeClients])

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

  const mutations = useSiloMutations()

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
      <SiloBulkToolbar
        selectedIds={selectedIds}
        mutations={mutations}
        onClear={() => setSelectedIds(new Set())}
      />

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
            <SiloTableHead
              allChecked={selectedIds.size === items.length && items.length > 0}
              onToggleAll={toggleSelectAll}
            />
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
                  onApprove={() => mutations.updateStatus.mutate({ id: silo.id, status: 'approved' })}
                  onReject={() => mutations.updateStatus.mutate({ id: silo.id, status: 'rejected' })}
                  onPromote={() => mutations.promote.mutate(silo.id)}
                  promoting={mutations.promote.isPending && mutations.promote.variables === silo.id}
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
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const metricCard: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 16px', minWidth: 110 }
