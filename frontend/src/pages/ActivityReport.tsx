import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, RefreshCw, Download, X } from 'lucide-react'
import { api } from '../lib/api'
import type { ActivityReport, ActivityReportDay, OverdueReport, OverdueBucketRow } from '../lib/types'

interface ClientListItem { id: string; name: string }

// Admin Activity Report — agency-wide count of PRODUCED deliverables (completed
// pages, live GBP posts, completed task work, reports, scans) broken down by
// type, by client, and by team member over a date range. Backed by
// GET /admin/activity-report (services/deliverables_analytics.py) reading the
// deliverable_events view. Admin-only (matches the /activity-report AdminRoute).

// ── date-range presets ───────────────────────────────────────────────────────
function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10)
}
function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return isoDay(d)
}
type Preset = { key: string; label: string; from: () => string; to: () => string }
const PRESETS: Preset[] = [
  { key: '30d', label: 'Last 30 days', from: () => daysAgo(29), to: () => isoDay(new Date()) },
  { key: '60d', label: 'Last 60 days', from: () => daysAgo(59), to: () => isoDay(new Date()) },
  { key: '90d', label: 'Last 90 days', from: () => daysAgo(89), to: () => isoDay(new Date()) },
]

const GROUP_ORDER = ['Content pages', 'GBP posts', 'Tasks', 'Reports', 'Research & scans', 'Other']

function qs(params: Record<string, string>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v)
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ── CSV export (client-side; the real app allows <a download>) ────────────────
function csvCell(v: string | number): string {
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function buildCsv(data: ActivityReport, clientLabel: string, cmp: boolean): string {
  const lines: string[] = []
  lines.push(['Activity Report'].map(csvCell).join(','))
  lines.push(['Range', data.from, data.to].map(csvCell).join(','))
  if (cmp && data.prev_from) lines.push(['Previous period', data.prev_from, data.prev_to ?? ''].map(csvCell).join(','))
  lines.push(['Client', clientLabel].map(csvCell).join(','))
  lines.push(['Total', data.total, ...(cmp ? ['Prev', data.prev_total, 'Delta', data.total_delta] : [])].map(csvCell).join(','))
  lines.push('')
  const header = ['Breakdown', 'Name', 'Group', 'Count', ...(cmp ? ['Previous', 'Delta'] : [])]
  lines.push(header.map(csvCell).join(','))
  for (const r of data.by_type) {
    lines.push(['Type', r.label, r.group, r.count, ...(cmp ? [r.prev_count, r.delta] : [])].map(csvCell).join(','))
  }
  for (const r of data.by_client) {
    lines.push(['Client', r.client_name, '', r.count, ...(cmp ? [r.prev_count, r.delta] : [])].map(csvCell).join(','))
  }
  for (const r of data.by_member) {
    lines.push(['Member', r.member, '', r.count, ...(cmp ? [r.prev_count, r.delta] : [])].map(csvCell).join(','))
  }
  return lines.join('\n')
}

function csvFilename(from: string, to: string, clientLabel: string | null): string {
  const c = clientLabel ? '_' + clientLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') : ''
  return `activity-report_${from}_${to}${c}.csv`
}

function downloadCsv(filename: string, text: string): void {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function ActivityReport() {
  const [preset, setPreset] = useState('30d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [compare, setCompare] = useState(true)
  const [clientId, setClientId] = useState('')  // '' = all clients; else drilled into one

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

  const { data, isLoading, isFetching, refetch, error } = useQuery<ActivityReport>({
    queryKey: ['activity-report', from, to, compare, clientId],
    queryFn: () => api.get<ActivityReport>(`/admin/activity-report${qs({ date_from: from, date_to: to, compare: String(compare), client_id: clientId })}`),
    enabled: rangeValid,
  })
  const cmp = !!data?.compare
  const drilled = !!clientId
  const drilledName = clientName[clientId] || data?.by_client?.[0]?.client_name || 'Client'

  // Overdue tasks — a live "as of today" snapshot (independent of the date range
  // / comparison), scoped to the drilled client when one is selected.
  const { data: overdue } = useQuery<OverdueReport>({
    queryKey: ['overdue-tasks', clientId],
    queryFn: () => api.get<OverdueReport>(`/admin/overdue-tasks${qs({ client_id: clientId })}`),
  })

  const byGroup = useMemo(() => {
    const groups: Record<string, { label: string; count: number; delta: number }[]> = {}
    for (const r of data?.by_type ?? []) {
      ;(groups[r.group] ||= []).push({ label: r.label, count: r.count, delta: r.delta })
    }
    return groups
  }, [data])

  const typeMax = Math.max(1, ...(data?.by_type ?? []).map((r) => r.count))
  const clientMax = Math.max(1, ...(data?.by_client ?? []).map((r) => r.count))
  const memberMax = Math.max(1, ...(data?.by_member ?? []).map((r) => r.count))

  return (
    <div style={{ padding: 32, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <BarChart3 size={22} />
        <h1 style={{ margin: 0, fontSize: 22 }}>Activity Report</h1>
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
        Deliverables produced across the agency — completed pages, live GBP posts, completed task
        work, reports and scans — broken down by type, client, and team member. Counts finished work
        only (excludes drafts, in-progress, and failed).
      </p>

      {/* Range selector */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', margin: '14px 0' }}>
        {PRESETS.map((p) => (
          <button
            key={p.key}
            onClick={() => setPreset(p.key)}
            style={rangeBtn(preset === p.key)}
          >
            {p.label}
          </button>
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
        <select
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          title="Drill into one client"
          style={{ marginLeft: 8, padding: '6px 8px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13, background: '#fff', maxWidth: 220 }}
        >
          <option value="">All clients</option>
          {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      {rangeValid && (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>
          {from} → {to}
          {cmp && data?.prev_from && (
            <span> · vs previous period {data.prev_from} → {data.prev_to}</span>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: 12, background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 12 }}>
          Couldn’t load the report. {(error as Error).message}
        </div>
      )}
      {preset === 'custom' && !rangeValid && (
        <div style={{ color: '#64748b', fontSize: 13 }}>Pick a start and end date.</div>
      )}

      {isLoading && rangeValid && <div style={{ color: '#64748b', padding: 20 }}>Loading…</div>}

      {data && (
        <>
          {data.truncated && (
            <div style={{ padding: 10, background: '#fffbeb', color: '#92400e', borderRadius: 8, fontSize: 12.5, marginBottom: 12 }}>
              This range hit the row cap — counts are a lower bound. Narrow the dates for exact totals.
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

          {/* Summary strip */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, margin: '4px 0 18px' }}>
            <Stat label="Total deliverables" value={data.total} big delta={cmp ? data.total_delta : undefined} prev={cmp ? data.prev_total : undefined} />
            <Stat label="Types" value={data.by_type.filter((t) => t.count > 0).length} />
            <Stat label="Clients" value={data.by_client.filter((c) => c.client_id && c.count > 0).length} />
            <Stat label="Contributors" value={data.by_member.filter((m) => m.count > 0).length} />
          </div>

          {/* Daily volume */}
          <Panel title="Deliverables per day">
            {data.daily.length === 0 ? (
              <Empty />
            ) : (
              <DailyChart days={data.daily} />
            )}
          </Panel>

          {/* Breakdowns */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginTop: 16 }}>
            <Panel title="By type">
              {data.by_type.length === 0 ? <Empty /> : (
                GROUP_ORDER.filter((g) => byGroup[g]?.length).map((g) => (
                  <div key={g} style={{ marginBottom: 14 }}>
                    <div style={groupHead}>{g}</div>
                    {byGroup[g].map((r) => <Bar key={r.label} label={r.label} count={r.count} max={typeMax} color="#6366f1" delta={cmp ? r.delta : undefined} />)}
                  </div>
                ))
              )}
            </Panel>

            {!drilled && (
              <Panel title="By client">
                {data.by_client.length === 0 ? <Empty /> : (
                  data.by_client.map((r) => (
                    <Bar
                      key={r.client_id ?? 'none'}
                      label={r.client_name}
                      count={r.count}
                      max={clientMax}
                      color="#0891b2"
                      delta={cmp ? r.delta : undefined}
                      onClick={r.client_id ? () => setClientId(r.client_id as string) : undefined}
                    />
                  ))
                )}
              </Panel>
            )}

            <Panel title="By team member">
              {data.by_member.length === 0 ? <Empty /> : (
                data.by_member.map((r) => (
                  <Bar key={r.member} label={r.member} count={r.count} max={memberMax} color="#16a34a" muted={r.member === 'Automated / scheduled'} delta={cmp ? r.delta : undefined} />
                ))
              )}
            </Panel>
          </div>
        </>
      )}

      {/* Overdue tasks — live snapshot (as of today), respects the client drill-down */}
      {overdue && (
        <div style={{ marginTop: 28 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 2 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>Overdue tasks</h2>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>open, past due · as of {overdue.as_of}</span>
          </div>
          <p style={{ marginTop: 2, marginBottom: 12, color: '#64748b', fontSize: 12.5 }}>
            Split by how far past due, and by cause — internal (the team owns the next step) vs
            external (waiting on the client: {overdue.external_status_keys.join(', ') || 'none'}).
          </p>

          {overdue.total === 0 ? (
            <Panel title="Overdue"><div style={{ color: '#16a34a', fontSize: 13 }}>Nothing overdue 🎉</div></Panel>
          ) : (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
                <Stat label="Total overdue" value={overdue.total} big />
                <Stat label="Internal (team)" value={overdue.internal} />
                <Stat label="External (waiting on client)" value={overdue.external} />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
                <Panel title="By age (internal vs external)">
                  <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 11, color: '#64748b' }}>
                    <span><span style={legendDot('#6366f1')} /> Internal</span>
                    <span><span style={legendDot('#d97706')} /> External</span>
                  </div>
                  {overdue.by_bucket.map((b) => (
                    <StackedBar key={b.bucket} row={b} max={Math.max(1, ...overdue.by_bucket.map((x) => x.total))} />
                  ))}
                </Panel>

                {!drilled && (
                  <Panel title="By client">
                    {overdue.by_client.length === 0 ? <Empty /> : (
                      overdue.by_client.map((r) => (
                        <Bar key={r.client_id ?? 'none'} label={r.client_name} count={r.count}
                          max={Math.max(1, ...overdue.by_client.map((x) => x.count))} color="#dc2626"
                          onClick={r.client_id ? () => setClientId(r.client_id as string) : undefined} />
                      ))
                    )}
                  </Panel>
                )}

                <Panel title="By assignee">
                  {overdue.by_member.length === 0 ? <Empty /> : (
                    overdue.by_member.map((r) => (
                      <Bar key={r.member} label={r.member} count={r.count}
                        max={Math.max(1, ...overdue.by_member.map((x) => x.count))} color="#dc2626"
                        muted={r.member === 'Unassigned'} />
                    ))
                  )}
                </Panel>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// Horizontal stacked bar for one overdue age bucket: internal + external segments.
function StackedBar({ row, max }: { row: OverdueBucketRow; max: number }) {
  const iPct = Math.round((row.internal / max) * 100)
  const ePct = Math.round((row.external / max) * 100)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '5px 0' }}>
      <div style={{ width: 90, flexShrink: 0, fontSize: 12.5, color: '#334155' }}>{row.bucket}</div>
      <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 16, display: 'flex', overflow: 'hidden' }}>
        <div style={{ width: `${iPct}%`, background: '#6366f1', height: '100%' }} title={`Internal: ${row.internal}`} />
        <div style={{ width: `${ePct}%`, background: '#d97706', height: '100%' }} title={`External: ${row.external}`} />
      </div>
      <div style={{ width: 78, flexShrink: 0, textAlign: 'right', fontSize: 12, color: '#334155' }}>
        <span style={{ fontWeight: 700, color: '#0f172a' }}>{row.total}</span>
        {row.external > 0 && <span style={{ color: '#d97706' }}> · {row.external} ext</span>}
      </div>
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

function Empty() {
  return <div style={{ color: '#94a3b8', fontSize: 13, padding: '8px 0' }}>Nothing in this range.</div>
}

// A colored +N / −N / no-change delta chip (rendered only when comparing).
function Delta({ value, style }: { value: number; style?: CSSProperties }) {
  const color = value > 0 ? '#16a34a' : value < 0 ? '#dc2626' : '#94a3b8'
  const text = value > 0 ? `+${value.toLocaleString()}` : value < 0 ? `−${Math.abs(value).toLocaleString()}` : '±0'
  return <span style={{ fontSize: 11, fontWeight: 700, color, ...style }}>{text}</span>
}

function Stat({ label, value, big, delta, prev }: { label: string; value: number; big?: boolean; delta?: number; prev?: number }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 16px', minWidth: 120, background: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <div style={{ fontSize: big ? 28 : 20, fontWeight: 800, color: '#0f172a' }}>{value.toLocaleString()}</div>
        {delta !== undefined && <Delta value={delta} />}
      </div>
      <div style={{ fontSize: 11, color: '#64748b' }}>
        {label}
        {prev !== undefined && <span> · prev {prev.toLocaleString()}</span>}
      </div>
    </div>
  )
}

function Bar({ label, count, max, color, muted, delta, onClick }: { label: string; count: number; max: number; color: string; muted?: boolean; delta?: number; onClick?: () => void }) {
  const pct = count === 0 ? 0 : Math.max(2, Math.round((count / max) * 100))
  return (
    <div
      onClick={onClick}
      title={onClick ? `Drill into ${label}` : label}
      style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '5px 0', cursor: onClick ? 'pointer' : 'default', borderRadius: 4 }}
    >
      <div style={{ width: 150, flexShrink: 0, fontSize: 12.5, color: muted ? '#94a3b8' : onClick ? '#0e7490' : '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: onClick ? 'underline' : undefined }}>{label}</div>
      <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 16, position: 'relative' }}>
        <div style={{ width: `${pct}%`, background: muted ? '#cbd5e1' : color, height: '100%', borderRadius: 4 }} />
      </div>
      {delta !== undefined && <div style={{ width: 40, flexShrink: 0, textAlign: 'right' }}><Delta value={delta} /></div>}
      <div style={{ width: 44, flexShrink: 0, textAlign: 'right', fontSize: 12.5, fontWeight: 600, color: '#0f172a' }}>{count.toLocaleString()}</div>
    </div>
  )
}

// Dependency-free SVG daily bar chart (matches the suite's inline-SVG convention).
function DailyChart({ days }: { days: ActivityReportDay[] }) {
  const W = 900
  const H = 140
  const pad = { t: 8, r: 8, b: 20, l: 8 }
  const iw = W - pad.l - pad.r
  const ih = H - pad.t - pad.b
  const max = Math.max(1, ...days.map((d) => d.count))
  const n = days.length
  const gap = n > 120 ? 0 : 1
  const bw = Math.max(1, iw / n - gap)
  const labelEvery = Math.ceil(n / 8)
  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none" style={{ display: 'block', minWidth: 360 }}>
        {days.map((d, i) => {
          const h = d.count === 0 ? 0 : Math.max(1, Math.round((d.count / max) * ih))
          const x = pad.l + i * (iw / n)
          const y = pad.t + ih - h
          return (
            <g key={d.date}>
              <rect x={x} y={y} width={bw} height={h} fill="#6366f1" rx={bw > 3 ? 1 : 0}>
                <title>{d.date}: {d.count}</title>
              </rect>
              {i % labelEvery === 0 && (
                <text x={x} y={H - 6} fontSize={9} fill="#94a3b8">{d.date.slice(5)}</text>
              )}
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
  border: `1px solid ${active ? '#6366f1' : '#cbd5e1'}`,
  background: active ? '#6366f1' : '#fff', color: active ? '#fff' : '#334155',
  fontWeight: active ? 600 : 400,
})
const dateInput: CSSProperties = { padding: '5px 8px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13 }
const groupHead: CSSProperties = { fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', margin: '2px 0 4px' }
const legendDot = (color: string): CSSProperties => ({ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: color, marginRight: 4 })
