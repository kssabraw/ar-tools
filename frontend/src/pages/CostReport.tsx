import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DollarSign, RefreshCw, Download, X } from 'lucide-react'
import { api } from '../lib/api'
import type { CostReport, CostDay, CostMetrics } from '../lib/types'

// Admin Cost & Usage Report — agency-wide SPEND (USD) + LLM token usage, broken
// down by type / client / team member over a date range, with previous-period
// comparison. Backed by GET /admin/cost-report (services/cost_analytics.py)
// reading the cost_events view. Admin-only (matches the /cost-report AdminRoute).
// Sibling of ActivityReport.tsx (which counts produced deliverables).

interface ClientListItem { id: string; name: string }
type Metric = 'cost' | 'tokens'

function isoDay(d: Date): string { return d.toISOString().slice(0, 10) }
function daysAgo(n: number): string { const d = new Date(); d.setDate(d.getDate() - n); return isoDay(d) }

type Preset = { key: string; label: string; from: () => string; to: () => string }
const PRESETS: Preset[] = [
  { key: '30d', label: 'Last 30 days', from: () => daysAgo(29), to: () => isoDay(new Date()) },
  { key: '60d', label: 'Last 60 days', from: () => daysAgo(59), to: () => isoDay(new Date()) },
  { key: '90d', label: 'Last 90 days', from: () => daysAgo(89), to: () => isoDay(new Date()) },
]
const GROUP_ORDER = ['Content pages', 'Research', 'Automation', 'Other']

function qs(params: Record<string, string>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ── formatting ────────────────────────────────────────────────────────────────
function fmtUsd(n: number): string { return '$' + n.toFixed(2) }
function fmtTok(n: number): string {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1) + 'M'
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1) + 'K'
  return String(n)
}
const fmt = (metric: Metric, n: number) => (metric === 'cost' ? fmtUsd(n) : fmtTok(n))
const rowValue = (metric: Metric, r: CostMetrics) => (metric === 'cost' ? r.cost : r.tokens)
const rowDelta = (metric: Metric, r: CostMetrics) => (metric === 'cost' ? r.cost_delta : r.tokens_delta)

// ── CSV export ────────────────────────────────────────────────────────────────
function csvCell(v: string | number): string {
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
function buildCsv(data: CostReport, clientLabel: string, cmp: boolean): string {
  const L: string[] = []
  L.push('Cost & Usage Report')
  L.push(['Range', data.from, data.to].map(csvCell).join(','))
  if (cmp && data.prev_from) L.push(['Previous period', data.prev_from, data.prev_to ?? ''].map(csvCell).join(','))
  L.push(['Client', clientLabel].map(csvCell).join(','))
  L.push(['Total cost USD', data.total.cost, ...(cmp ? ['Prev', data.total.prev_cost, 'Delta', data.total.cost_delta] : [])].map(csvCell).join(','))
  L.push(['Total tokens', data.total.tokens, 'Input', data.total.input_tokens, 'Output', data.total.output_tokens].map(csvCell).join(','))
  L.push('')
  const head = ['Breakdown', 'Name', 'Group', 'Cost USD', 'Input tokens', 'Output tokens', ...(cmp ? ['Prev cost USD', 'Cost delta USD', 'Tokens delta'] : [])]
  L.push(head.map(csvCell).join(','))
  const line = (bd: string, name: string, group: string, r: CostMetrics) =>
    L.push([bd, name, group, r.cost, r.input_tokens, r.output_tokens, ...(cmp ? [r.prev_cost, r.cost_delta, r.tokens_delta] : [])].map(csvCell).join(','))
  for (const r of data.by_type) line('Type', r.label, r.group, r)
  for (const r of data.by_client) line('Client', r.client_name, '', r)
  for (const r of data.by_member) line('Member', r.member, '', r)
  return L.join('\n')
}
function csvFilename(from: string, to: string, clientLabel: string | null): string {
  const c = clientLabel ? '_' + clientLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') : ''
  return `cost-report_${from}_${to}${c}.csv`
}
function downloadCsv(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function CostReport() {
  const [preset, setPreset] = useState('30d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [compare, setCompare] = useState(true)
  const [clientId, setClientId] = useState('')
  const [metric, setMetric] = useState<Metric>('cost')

  const active = PRESETS.find((p) => p.key === preset)
  const from = preset === 'custom' ? customFrom : active?.from() ?? daysAgo(29)
  const to = preset === 'custom' ? customTo : active?.to() ?? isoDay(new Date())
  const rangeValid = !!from && !!to

  const { data: clients } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    staleTime: 5 * 60_000,
  })
  const clientName = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of clients ?? []) m[c.id] = c.name
    return m
  }, [clients])

  const { data, isLoading, isFetching, refetch, error } = useQuery<CostReport>({
    queryKey: ['cost-report', from, to, compare, clientId],
    queryFn: () => api.get<CostReport>(`/admin/cost-report${qs({ date_from: from, date_to: to, compare: String(compare), client_id: clientId })}`),
    enabled: rangeValid,
  })
  const cmp = !!data?.compare
  const drilled = !!clientId
  const drilledName = clientName[clientId] || data?.by_client?.[0]?.client_name || 'Client'

  const byGroup = useMemo(() => {
    const groups: Record<string, CostReport['by_type']> = {}
    for (const r of data?.by_type ?? []) (groups[r.group] ||= []).push(r)
    return groups
  }, [data])

  const typeMax = Math.max(1, ...(data?.by_type ?? []).map((r) => rowValue(metric, r)))
  const clientMax = Math.max(1, ...(data?.by_client ?? []).map((r) => rowValue(metric, r)))
  const memberMax = Math.max(1, ...(data?.by_member ?? []).map((r) => rowValue(metric, r)))

  return (
    <div style={{ padding: 32, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <DollarSign size={22} />
        <h1 style={{ margin: 0, fontSize: 22 }}>Cost & Usage Report</h1>
        <button
          onClick={() => data && downloadCsv(csvFilename(from, to, drilled ? drilledName : null), buildCsv(data, drilled ? drilledName : 'All clients', cmp))}
          disabled={!data}
          title="Export the current view as CSV"
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 6, border: '1px solid #cbd5e1', background: data ? '#fff' : '#f1f5f9', cursor: data ? 'pointer' : 'default', fontSize: 13, color: data ? '#334155' : '#94a3b8' }}
        >
          <Download size={14} /> Export CSV
        </button>
        <button
          onClick={() => refetch()}
          title="Refresh"
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 6, border: '1px solid #cbd5e1', background: '#fff', cursor: 'pointer', fontSize: 13 }}
        >
          <RefreshCw size={14} className={isFetching ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <p style={{ marginTop: 0, color: '#64748b', fontSize: 13 }}>
        Money spent and LLM tokens used across the suite — page/blog generation, research, and
        automation — broken down by type, client, and team member. A spend ledger (all recorded
        cost). Token counts are reported by the LLM page generators (Local SEO, Ecommerce); other
        sources record cost only.
      </p>

      {/* Controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', margin: '14px 0' }}>
        {PRESETS.map((p) => (
          <button key={p.key} onClick={() => setPreset(p.key)} style={rangeBtn(preset === p.key)}>{p.label}</button>
        ))}
        <button onClick={() => setPreset('custom')} style={rangeBtn(preset === 'custom')}>Custom</button>
        {preset === 'custom' && (
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} style={dateInput} />
            <span style={{ color: '#94a3b8' }}>→</span>
            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} style={dateInput} />
          </span>
        )}
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#334155', cursor: 'pointer', marginLeft: 8 }}>
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          Compare to previous period
        </label>
        <select value={clientId} onChange={(e) => setClientId(e.target.value)} title="Drill into one client"
          style={{ marginLeft: 8, padding: '6px 8px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13, background: '#fff', maxWidth: 220 }}>
          <option value="">All clients</option>
          {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {/* Metric toggle — drives what the bars/deltas represent */}
        <div style={{ display: 'inline-flex', marginLeft: 'auto', border: '1px solid #cbd5e1', borderRadius: 8, overflow: 'hidden' }}>
          <button onClick={() => setMetric('cost')} style={segBtn(metric === 'cost')}>Cost</button>
          <button onClick={() => setMetric('tokens')} style={segBtn(metric === 'tokens')}>Tokens</button>
        </div>
      </div>
      {rangeValid && (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>
          {from} → {to}
          {cmp && data?.prev_from && <span> · vs previous period {data.prev_from} → {data.prev_to}</span>}
        </div>
      )}

      {error && (
        <div style={{ padding: 12, background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          Couldn’t load the report. {(error as Error).message}
        </div>
      )}
      {preset === 'custom' && !rangeValid && <div style={{ color: '#64748b', fontSize: 13 }}>Pick a start and end date.</div>}
      {isLoading && rangeValid && <div style={{ color: '#64748b', padding: 20 }}>Loading…</div>}

      {data && (
        <>
          {data.truncated && (
            <div style={{ padding: 10, background: '#fffbeb', color: '#92400e', borderRadius: 8, fontSize: 12.5, marginBottom: 12 }}>
              This range hit the row cap — totals are a lower bound. Narrow the dates for exact figures.
            </div>
          )}

          {drilled && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '6px 10px 6px 12px', background: '#ecfeff', border: '1px solid #a5f3fc', color: '#0e7490', borderRadius: 999, fontSize: 13, marginBottom: 12 }}>
              <span>Drilled into <strong>{drilledName}</strong></span>
              <button onClick={() => setClientId('')} title="Back to all clients" style={{ display: 'inline-flex', alignItems: 'center', border: 'none', background: 'transparent', color: '#0e7490', cursor: 'pointer', padding: 0 }}>
                <X size={15} />
              </button>
            </div>
          )}

          {/* Summary strip — both metrics always shown */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, margin: '4px 0 18px' }}>
            <Stat label="Total cost" value={fmtUsd(data.total.cost)} big
              delta={cmp ? <Delta metric="cost" value={data.total.cost_delta} /> : undefined}
              sub={cmp ? `prev ${fmtUsd(data.total.prev_cost)}` : undefined} />
            <Stat label="Total tokens" value={fmtTok(data.total.tokens)}
              delta={cmp ? <Delta metric="tokens" value={data.total.tokens_delta} /> : undefined}
              sub={`${fmtTok(data.total.input_tokens)} in · ${fmtTok(data.total.output_tokens)} out`} />
            <Stat label="Billable events" value={data.total.events.toLocaleString()} />
            <Stat label="Avg cost / event" value={data.total.events ? fmtUsd(data.total.cost / data.total.events) : '$0.00'} />
          </div>

          {/* Daily volume (selected metric) */}
          <Panel title={metric === 'cost' ? 'Cost per day' : 'Tokens per day'}>
            {data.daily.length === 0 ? <Empty /> : <DailyChart days={data.daily} metric={metric} />}
          </Panel>

          {/* Breakdowns (selected metric) */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginTop: 16 }}>
            <Panel title="By type">
              {data.by_type.length === 0 ? <Empty /> : (
                GROUP_ORDER.filter((g) => byGroup[g]?.length).map((g) => (
                  <div key={g} style={{ marginBottom: 14 }}>
                    <div style={groupHead}>{g}</div>
                    {byGroup[g].map((r) => (
                      <Bar key={r.type} label={r.label} value={rowValue(metric, r)} max={typeMax} color="#7c3aed" metric={metric} delta={cmp ? rowDelta(metric, r) : undefined} />
                    ))}
                  </div>
                ))
              )}
            </Panel>

            {!drilled && (
              <Panel title="By client">
                {data.by_client.length === 0 ? <Empty /> : (
                  data.by_client.map((r) => (
                    <Bar key={r.client_id ?? 'none'} label={r.client_name} value={rowValue(metric, r)} max={clientMax} color="#0891b2" metric={metric}
                      delta={cmp ? rowDelta(metric, r) : undefined} onClick={r.client_id ? () => setClientId(r.client_id as string) : undefined} />
                  ))
                )}
              </Panel>
            )}

            <Panel title="By team member">
              {data.by_member.length === 0 ? <Empty /> : (
                data.by_member.map((r) => (
                  <Bar key={r.member} label={r.member} value={rowValue(metric, r)} max={memberMax} color="#16a34a" metric={metric}
                    muted={r.member === 'Automated / scheduled'} delta={cmp ? rowDelta(metric, r) : undefined} />
                ))
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}

// ── presentational pieces ────────────────────────────────────────────────────
function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', padding: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}
function Empty() { return <div style={{ color: '#94a3b8', fontSize: 13, padding: '8px 0' }}>Nothing in this range.</div> }

function Delta({ metric, value }: { metric: Metric; value: number }) {
  const color = value > 0 ? '#16a34a' : value < 0 ? '#dc2626' : '#94a3b8'
  const mag = metric === 'cost' ? fmtUsd(Math.abs(value)) : fmtTok(Math.abs(value))
  const text = value > 0 ? `+${mag}` : value < 0 ? `−${mag}` : '±0'
  return <span style={{ fontSize: 11, fontWeight: 700, color }}>{text}</span>
}

function Stat({ label, value, big, delta, sub }: { label: string; value: string; big?: boolean; delta?: React.ReactNode; sub?: string }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 16px', minWidth: 140, background: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: big ? 28 : 20, fontWeight: 800, color: '#0f172a' }}>{value}</div>
        {delta}
      </div>
      <div style={{ fontSize: 11, color: '#64748b' }}>{label}{sub ? ` · ${sub}` : ''}</div>
    </div>
  )
}

function Bar({ label, value, max, color, metric, muted, delta, onClick }: { label: string; value: number; max: number; color: string; metric: Metric; muted?: boolean; delta?: number; onClick?: () => void }) {
  const pct = value === 0 ? 0 : Math.max(2, Math.round((value / max) * 100))
  return (
    <div onClick={onClick} title={onClick ? `Drill into ${label}` : label}
      style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '5px 0', cursor: onClick ? 'pointer' : 'default', borderRadius: 4 }}>
      <div style={{ width: 140, flexShrink: 0, fontSize: 12.5, color: muted ? '#94a3b8' : onClick ? '#0e7490' : '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: onClick ? 'underline' : undefined }}>{label}</div>
      <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 16 }}>
        <div style={{ width: `${pct}%`, background: muted ? '#cbd5e1' : color, height: '100%', borderRadius: 4 }} />
      </div>
      {delta !== undefined && <div style={{ width: 52, flexShrink: 0, textAlign: 'right' }}><Delta metric={metric} value={delta} /></div>}
      <div style={{ width: 58, flexShrink: 0, textAlign: 'right', fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>{fmt(metric, value)}</div>
    </div>
  )
}

function DailyChart({ days, metric }: { days: CostDay[]; metric: Metric }) {
  const W = 900, H = 140
  const pad = { t: 8, r: 8, b: 20, l: 8 }
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b
  const val = (d: CostDay) => (metric === 'cost' ? d.cost : d.tokens)
  const max = Math.max(1, ...days.map(val))
  const n = days.length
  const gap = n > 120 ? 0 : 1
  const bw = Math.max(1, iw / n - gap)
  const labelEvery = Math.ceil(n / 8)
  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none" style={{ display: 'block', minWidth: 360 }}>
        {days.map((d, i) => {
          const v = val(d)
          const h = v === 0 ? 0 : Math.max(1, Math.round((v / max) * ih))
          const x = pad.l + i * (iw / n)
          const y = pad.t + ih - h
          return (
            <g key={d.date}>
              <rect x={x} y={y} width={bw} height={h} fill="#7c3aed" rx={bw > 3 ? 1 : 0}>
                <title>{d.date}: {metric === 'cost' ? fmtUsd(d.cost) : fmtTok(d.tokens) + ' tokens'}</title>
              </rect>
              {i % labelEvery === 0 && <text x={x} y={H - 6} fontSize={9} fill="#94a3b8">{d.date.slice(5)}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

// ── styles ───────────────────────────────────────────────────────────────────
const rangeBtn = (active: boolean): CSSProperties => ({
  padding: '6px 12px', borderRadius: 999, fontSize: 13, cursor: 'pointer',
  border: `1px solid ${active ? '#7c3aed' : '#cbd5e1'}`,
  background: active ? '#7c3aed' : '#fff', color: active ? '#fff' : '#334155', fontWeight: active ? 600 : 400,
})
const segBtn = (active: boolean): CSSProperties => ({
  padding: '6px 14px', fontSize: 13, cursor: 'pointer', border: 'none',
  background: active ? '#7c3aed' : '#fff', color: active ? '#fff' : '#334155', fontWeight: active ? 600 : 400,
})
const dateInput: CSSProperties = { padding: '5px 8px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13 }
const groupHead: CSSProperties = { fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', margin: '2px 0 4px' }
