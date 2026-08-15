import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw, PlugZap, CheckCircle2, AlertTriangle, History, Users } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type {
  Client, GbpDashboard, GbpLocation, GbpMetricGrowth, GbpResolvedLocation, GbpSeriesPoint,
} from '../lib/types'

const WINDOWS: [number, string][] = [
  [30, 'Last 30 days'],
  [90, 'Last 90 days'],
  [180, 'Last 6 months'],
  [365, 'Last 12 months'],
]

// GBP Insights — the Google Business Profile performance dashboard. Reads the
// dormant-until-enabled GBP metrics pipeline (gbp_metric_daily, populated by the
// daily ingest) and shows period-over-period growth per metric plus a daily
// trend. When no location is verified yet, it surfaces the connect flow
// (resolve → register → verify → backfill) that starts ingest.
export function GbpMetrics() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  // Not `window` — that shadows the global and would break any window.* call.
  const [windowDays, setWindowDays] = useState(30)
  const [mode, setMode] = useState<'preset' | 'custom'>('preset')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')

  const today = new Date().toISOString().slice(0, 10)
  const customReady = mode === 'custom' && Boolean(customStart && customEnd)
  // Preset window OR an explicit start/end range; the backend compares either
  // against the equal-length window immediately before it.
  const qs = customReady ? `start=${customStart}&end=${customEnd}` : `window=${windowDays}`

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data, isLoading, error } = useQuery<GbpDashboard>({
    queryKey: ['gbp-dashboard', clientId, qs],
    queryFn: () => api.get<GbpDashboard>(`/clients/${clientId}/gbp-metrics/dashboard?${qs}`),
    enabled: Boolean(clientId) && (mode === 'preset' || customReady),
  })

  function onPeriodChange(value: string) {
    if (value === 'custom') {
      setMode('custom')
      // Seed a 30-day range so the view loads immediately; the user adjusts from there.
      if (!customStart || !customEnd) {
        const startD = new Date()
        startD.setDate(startD.getDate() - 29)
        setCustomStart(startD.toISOString().slice(0, 10))
        setCustomEnd(today)
      }
    } else {
      setMode('preset')
      setWindowDays(Number(value))
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 1080 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 18, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>GBP Insights</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0', maxWidth: 640 }}>
            Google Business Profile performance for {client?.name ?? 'this client'} — profile views, calls,
            website clicks, direction requests &amp; messages over time, from the Business Profile Performance API.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <select
            style={select}
            value={mode === 'custom' ? 'custom' : String(windowDays)}
            onChange={(e) => onPeriodChange(e.target.value)}
          >
            {WINDOWS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            <option value="custom">Custom range…</option>
          </select>
          {mode === 'custom' && (
            <>
              <input
                type="date" style={select} max={customEnd || today}
                value={customStart} onChange={(e) => setCustomStart(e.target.value)}
              />
              <span style={{ color: '#94a3b8', fontSize: 13 }}>→</span>
              <input
                type="date" style={select} max={today} min={customStart || undefined}
                value={customEnd} onChange={(e) => setCustomEnd(e.target.value)}
              />
            </>
          )}
        </div>
      </div>

      {error ? (
        <div style={{ ...emptyBox, color: '#b91c1c' }}>Couldn't load GBP data: {(error as Error).message}</div>
      ) : isLoading || !data ? (
        <div style={emptyBox}>Loading…</div>
      ) : !data.enabled ? (
        <NotEnabled />
      ) : !data.connected ? (
        <ConnectPanel clientId={clientId!} locations={data.locations} />
      ) : (
        <Dashboard clientId={clientId!} data={data} />
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

// ── Not-enabled notice ───────────────────────────────────────────────────────
function NotEnabled() {
  return (
    <div style={{ ...noticeCard, borderColor: '#fed7aa', background: '#fffbeb' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <AlertTriangle size={16} color="#b45309" />
        <strong style={{ fontSize: 13.5, color: '#92400e' }}>GBP metrics aren't enabled on the server yet</strong>
      </div>
      <p style={{ fontSize: 13, color: '#78350f', margin: 0 }}>
        The Business Profile Performance API pipeline is built but gated off (<code>GBP_METRICS_ENABLED</code>).
        An admin can confirm live API access with <code>GET /gbp/diagnose-performance</code>, then turn the flag on.
        Once enabled, connect a location here and the daily ingest starts populating this dashboard.
      </p>
    </div>
  )
}

// Admin-only agency-wide action: bulk-onboard every client that has a captured
// GBP but no registered location (resolve once → auto-match → register + backfill).
function OnboardAllButton() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()

  const { data: status } = useQuery<{ status: string; result?: { onboarded: unknown[]; skipped: unknown[] } }>({
    queryKey: ['gbp-onboard-status'],
    queryFn: () => api.get('/gbp/onboard/status'),
    enabled: isAdmin,
    refetchInterval: (q) => {
      const s = (q.state.data as { status?: string } | undefined)?.status
      return s === 'pending' || s === 'running' ? 2500 : false
    },
  })

  const start = useMutation({
    mutationFn: () => api.post<{ status: string; job_id: string }>('/gbp/onboard', {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['gbp-onboard-status'] }),
  })

  // When a run completes, refresh this client's dashboard (it may have just been onboarded).
  useEffect(() => {
    if (status?.status === 'complete') void queryClient.invalidateQueries({ queryKey: ['gbp-dashboard'] })
  }, [status?.status, queryClient])

  if (!isAdmin) return null
  const running = start.isPending || status?.status === 'pending' || status?.status === 'running'
  const result = status?.status === 'complete' ? status.result : undefined

  return (
    <div style={{ ...noticeCard, marginBottom: 12, background: '#f8fafc' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Users size={16} color="#6366f1" />
          <div>
            <strong style={{ fontSize: 13, color: '#0f172a' }}>Onboard all clients</strong>
            <div style={{ fontSize: 12, color: '#94a3b8' }}>
              Auto-match every client's Google Business Profile and start an 18-month backfill.
            </div>
          </div>
        </div>
        <button style={primaryBtn} onClick={() => start.mutate()} disabled={running}>
          <RefreshCw size={14} style={running ? spinStyle : undefined} />
          {running ? 'Onboarding…' : 'Auto-onboard all'}
        </button>
      </div>
      {start.isError && <div style={errText}>{(start.error as Error).message}</div>}
      {result && (
        <div style={{ fontSize: 12.5, color: '#334155', marginTop: 10 }}>
          Onboarded <strong>{result.onboarded.length}</strong>, skipped <strong>{result.skipped.length}</strong>.
          {result.onboarded.length > 0 && ' Backfills are running — data appears in a few minutes.'}
        </div>
      )}
    </div>
  )
}

// ── Connect flow (resolve → register → verify → backfill) ────────────────────
function ConnectPanel({ clientId, locations }: { clientId: string; locations: GbpLocation[] }) {
  const queryClient = useQueryClient()
  const [resolved, setResolved] = useState<GbpResolvedLocation[] | null>(null)
  const [resolveNote, setResolveNote] = useState<string | null>(null)

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['gbp-dashboard', clientId] })

  const resolve = useMutation({
    mutationFn: () => api.get<{ locations: GbpResolvedLocation[]; detail: string | null }>('/gbp/resolve-locations'),
    onSuccess: (r) => { setResolved(r.locations); setResolveNote(r.detail) },
  })

  const register = useMutation({
    mutationFn: (loc: GbpResolvedLocation) => api.post<GbpLocation>(`/clients/${clientId}/gbp-locations`, {
      location_id: loc.location_id, account_id: loc.account_id, place_id: loc.place_id, title: loc.title,
    }),
    onSuccess: invalidate,
  })

  const registeredIds = new Set(locations.map((l) => l.location_id))

  return (
    <div>
      <OnboardAllButton />
      <div style={noticeCard}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <PlugZap size={16} color="#6366f1" />
          <strong style={{ fontSize: 13.5, color: '#0f172a' }}>Connect this client's Business Profile</strong>
        </div>
        <p style={{ fontSize: 13, color: '#475569', margin: '0 0 12px' }}>
          Find the Google Business Profile locations the connected agency account manages, then register this
          client's location. Verifying runs a live 1-day fetch; a backfill pulls ~18 months of history so the
          dashboard has trend right away.
        </p>
        <button style={primaryBtn} onClick={() => resolve.mutate()} disabled={resolve.isPending}>
          <RefreshCw size={14} style={resolve.isPending ? spinStyle : undefined} />
          {resolve.isPending ? 'Finding…' : 'Find locations'}
        </button>
        {resolve.isError && <div style={errText}>{(resolve.error as Error).message}</div>}
        {resolveNote && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>{resolveNote}</div>}

        {resolved && resolved.length > 0 && (
          <div style={{ marginTop: 14, display: 'grid', gap: 8 }}>
            {resolved.map((loc) => (
              <div key={loc.location_id} style={resolvedRow}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {loc.title || loc.location_id}
                  </div>
                  {loc.address && <div style={{ fontSize: 12, color: '#94a3b8' }}>{loc.address}</div>}
                </div>
                {registeredIds.has(loc.location_id) ? (
                  <span style={{ fontSize: 12, color: '#15803d', flexShrink: 0 }}>✓ registered</span>
                ) : (
                  <button style={linkBtn} onClick={() => register.mutate(loc)} disabled={register.isPending}>
                    Connect
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {resolved && resolved.length === 0 && (
          <div style={{ fontSize: 12.5, color: '#94a3b8', marginTop: 10 }}>
            No locations visible to the connected account. Make sure the agency Google account (OAuth) — or the
            service account, if using that path — manages this client's Business Profile.
          </div>
        )}
      </div>

      {locations.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={sectionLabel}>Registered locations</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {locations.map((loc) => (
              <LocationRow key={loc.id} clientId={clientId} loc={loc} onChange={invalidate} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function LocationRow({ clientId, loc, onChange }: { clientId: string; loc: GbpLocation; onChange: () => void }) {
  const queryClient = useQueryClient()
  const done = () => { onChange(); queryClient.invalidateQueries({ queryKey: ['gbp-dashboard', clientId] }) }

  const verify = useMutation({
    mutationFn: () => api.post<{ access_status: string; detail: string | null }>(`/gbp-locations/${loc.id}/verify`, {}),
    onSuccess: done,
  })
  const backfill = useMutation({
    mutationFn: () => api.post<{ status: string }>(`/gbp-locations/${loc.id}/backfill`, {}),
    onSuccess: done,
  })

  return (
    <div style={resolvedRow}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{loc.title || loc.location_id}</div>
        <div style={{ fontSize: 12 }}>
          <AccessBadge status={loc.access_status} />
          {loc.last_synced_at && <span style={{ color: '#94a3b8' }}> · synced {new Date(loc.last_synced_at).toLocaleDateString()}</span>}
        </div>
        {verify.data?.detail && <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 2 }}>{verify.data.detail}</div>}
      </div>
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        <button style={linkBtn} onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? 'Verifying…' : 'Verify'}
        </button>
        {loc.access_status === 'ok' && (
          <button style={linkBtn} onClick={() => backfill.mutate()} disabled={backfill.isPending}>
            <History size={13} /> {backfill.isPending ? 'Queued' : backfill.isSuccess ? 'Queued ✓' : 'Backfill'}
          </button>
        )}
      </div>
    </div>
  )
}

// ── The dashboard itself ─────────────────────────────────────────────────────
function Dashboard({ clientId, data }: { clientId: string; data: GbpDashboard }) {
  const queryClient = useQueryClient()
  const okLocations = data.locations.filter((l) => l.access_status === 'ok')

  const sync = useMutation({
    // Trigger an ingest for each verified location, then refresh the view.
    mutationFn: () => Promise.all(
      okLocations.map((l) => api.post<{ status: string }>(`/gbp-locations/${l.id}/ingest`, {})),
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gbp-dashboard', clientId] }),
  })

  const hasData = data.metrics.length > 0

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12.5, color: '#64748b', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <CheckCircle2 size={14} color="#15803d" />
          {okLocations.length} location{okLocations.length === 1 ? '' : 's'} connected
          {data.last_synced_at && <span>· last synced {new Date(data.last_synced_at).toLocaleString()}</span>}
        </div>
        <button style={secondaryBtn} onClick={() => sync.mutate()} disabled={sync.isPending}>
          <RefreshCw size={13} style={sync.isPending ? spinStyle : undefined} />
          {sync.isPending ? 'Syncing…' : 'Sync now'}
        </button>
      </div>

      {!hasData ? (
        <div style={emptyBox}>
          No performance data in this window yet. Data lands ~3–5 days after the fact — if you just connected,
          run a <strong>Backfill</strong> (from the connect step) or <strong>Sync now</strong>, then check back.
        </div>
      ) : (
        <>
          <div style={tileGrid}>
            {data.metrics.map((m) => (
              <MetricTile key={m.metric} metric={m} series={data.series} />
            ))}
          </div>
          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 14 }}>
            {data.date_start} – {data.date_end} ({data.window_days} days) vs. the prior period
            ({data.compare_start} – {data.compare_end}). GBP reports performance data with a 3–5 day lag,
            so the most recent days may still be filling in.
          </div>
        </>
      )}
    </div>
  )
}

function MetricTile({ metric, series }: { metric: GbpMetricGrowth; series: GbpSeriesPoint[] }) {
  const daily = useMemo(() => series.map((p) => p.values[metric.metric] ?? 0), [series, metric.metric])
  const pct = metric.pct
  const dir = pct == null ? 'new' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  const badge = { up: '#15803d', down: '#b91c1c', flat: '#64748b', new: '#6366f1' }[dir]
  const badgeBg = { up: '#f0fdf4', down: '#fef2f2', flat: '#f1f5f9', new: '#eef2ff' }[dir]
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : dir === 'flat' ? '▬' : '＋'
  const changeText = pct == null ? 'new' : `${arrow} ${Math.abs(pct)}%`

  return (
    <div style={tile}>
      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>{metric.label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '4px 0 2px' }}>
        <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', letterSpacing: '-0.02em' }}>
          {metric.current.toLocaleString()}
        </div>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: badge, background: badgeBg, borderRadius: 999, padding: '2px 8px' }}>
          {changeText}
        </span>
      </div>
      <div style={{ fontSize: 11.5, color: '#94a3b8' }}>
        was {metric.previous.toLocaleString()} · {metric.delta >= 0 ? '+' : ''}{metric.delta.toLocaleString()}
      </div>
      <div style={{ marginTop: 8 }}>
        <MiniSpark values={daily} color={dir === 'down' ? '#f87171' : '#6366f1'} />
      </div>
    </div>
  )
}

// Self-scaling upward sparkline (higher = better) with a soft area fill.
function MiniSpark({ values, color, width = 200, height = 40 }: { values: number[]; color: string; width?: number; height?: number }) {
  if (values.length === 0) {
    return <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" />
  }
  const max = Math.max(1, ...values)
  const n = values.length
  const pad = 2
  const x = (i: number) => (n > 1 ? (i / (n - 1)) * width : width / 2)
  const y = (v: number) => pad + (1 - v / max) * (height - pad * 2)
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${x(n - 1).toFixed(1)},${height} L${x(0).toFixed(1)},${height} Z`
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <path d={area} fill={color} opacity={0.1} />
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function AccessBadge({ status }: { status: GbpLocation['access_status'] }) {
  const c = {
    ok: { fg: '#166534', label: 'verified' },
    no_access: { fg: '#b91c1c', label: 'no access — reconnect' },
    pending: { fg: '#b45309', label: 'not verified' },
    error: { fg: '#b45309', label: 'error' },
  }[status]
  return <span style={{ color: c.fg, fontWeight: 600 }}>{c.label}</span>
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none',
  color: '#6366f1', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0,
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '9px 16px', cursor: 'pointer',
}
const secondaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600, color: '#475569',
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 12px', cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#6366f1',
  background: '#eef2ff', border: 'none', borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
}
const select: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', fontSize: 13,
  color: '#0f172a', background: '#fff', outline: 'none', flexShrink: 0,
}
const noticeCard: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, background: '#fff',
}
const emptyBox: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center',
}
const resolvedRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', background: '#fff',
}
const tileGrid: React.CSSProperties = {
  display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
}
const tile: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff',
}
const sectionLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#94a3b8', marginBottom: 8,
}
const errText: React.CSSProperties = { fontSize: 12, color: '#b91c1c', marginTop: 8 }
const spinStyle: React.CSSProperties = { animation: 'spin 1s linear infinite' }
