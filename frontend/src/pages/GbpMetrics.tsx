import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw, PlugZap, CheckCircle2, AlertTriangle, History, Users, Lightbulb, Star, Download, Search, ArrowUpDown } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type {
  Client, GbpDashboard, GbpLocation, GbpMetricGrowth, GbpResolvedLocation, GbpSeriesPoint,
  GbpBreakdownItem, GbpActionsSummary, GbpReviewsSummary, GbpSearchKeywords, GbpPeriodReviews,
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
        <Dashboard clientId={clientId!} data={data} periodQs={qs} />
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
function Dashboard({ clientId, data, periodQs }: { clientId: string; data: GbpDashboard; periodQs: string }) {
  const queryClient = useQueryClient()
  const okLocations = data.locations.filter((l) => l.access_status === 'ok')
  const [exporting, setExporting] = useState(false)

  const sync = useMutation({
    // Trigger an ingest for each verified location, then refresh the view.
    mutationFn: () => Promise.all(
      okLocations.map((l) => api.post<{ status: string }>(`/gbp-locations/${l.id}/ingest`, {})),
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gbp-dashboard', clientId] }),
  })

  async function exportCsv() {
    setExporting(true)
    try {
      await api.download(
        `/clients/${clientId}/gbp-metrics/export?${periodQs}`,
        `gbp-metrics-${data.date_start}-to-${data.date_end}.csv`,
      )
    } finally {
      setExporting(false)
    }
  }

  const hasData = data.metrics.length > 0
  // Tolerate a backend that predates these fields (e.g. during a deploy where the
  // frontend ships before the API) — degrade, never white-screen.
  const insights = data.insights ?? []
  const breakdown = data.breakdown ?? { surface: [], device: [] }
  const isVisibility = (m: GbpMetricGrowth) => (m.group ? m.group === 'visibility' : m.metric === 'profile_views')
  const visibility = data.metrics.filter(isVisibility)
  const actions = data.metrics.filter((m) => !isVisibility(m))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12.5, color: '#64748b', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <CheckCircle2 size={14} color="#15803d" />
          {okLocations.length} location{okLocations.length === 1 ? '' : 's'} connected
          {data.last_synced_at && <span>· last synced {new Date(data.last_synced_at).toLocaleString()}</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {hasData && (
            <button style={secondaryBtn} onClick={exportCsv} disabled={exporting}>
              <Download size={13} /> {exporting ? 'Exporting…' : 'Export CSV'}
            </button>
          )}
          <button style={secondaryBtn} onClick={() => sync.mutate()} disabled={sync.isPending}>
            <RefreshCw size={13} style={sync.isPending ? spinStyle : undefined} />
            {sync.isPending ? 'Syncing…' : 'Sync now'}
          </button>
        </div>
      </div>

      {!hasData ? (
        <div style={emptyBox}>
          No performance data in this window yet. Data lands ~3–5 days after the fact — if you just connected,
          run a <strong>Backfill</strong> (from the connect step) or <strong>Sync now</strong>, then check back.
        </div>
      ) : (
        <>
          {insights.length > 0 && <InsightsPanel lines={insights} />}

          {data.reviews && (data.reviews.rating != null || data.reviews.review_count > 0) && (
            <ReviewsPanel reviews={data.reviews} />
          )}

          <PeriodReviewsPanel clientId={clientId} start={data.date_start} end={data.date_end} />

          <TrendChart data={data} />

          <SectionHeading>Visibility — how many people saw this business</SectionHeading>
          <div style={tileGrid}>
            {visibility.map((m) => <MetricTile key={m.metric} metric={m} series={data.series} />)}
          </div>
          {(breakdown.surface.length > 0 || breakdown.device.length > 0) && (
            <div style={breakdownGrid}>
              <BreakdownCard title="Where views came from" items={breakdown.surface} />
              <BreakdownCard title="By device" items={breakdown.device} />
            </div>
          )}

          <SectionHeading>Customer actions — what they did next</SectionHeading>
          {data.actions && <ActionsHeadline actions={data.actions} />}
          <div style={tileGrid}>
            {actions.map((m) => <MetricTile key={m.metric} metric={m} series={data.series} />)}
          </div>

          <SearchKeywordsPanel clientId={clientId} />

          <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 16 }}>
            {data.date_start} – {data.date_end} ({data.window_days} days) vs. the prior period
            ({data.compare_start} – {data.compare_end}). GBP reports performance data with a 3–5 day lag,
            so the most recent days may still be filling in.
          </div>
        </>
      )}
    </div>
  )
}

// Search terms that drove impressions (monthly). Fetched separately from the
// daily dashboard — the data is monthly and independent of the window. Loads up
// to 500 terms, shown in a scrollable viewport with client-side search + sort.
// Range options → number of most-recent calendar months to aggregate (GBP
// keyword data is monthly, so a "last N days" view sums the recent month(s)).
const KEYWORD_RANGES: [string, string, number][] = [
  ['30d', 'Last 30 days', 1],
  ['60d', 'Last 60 days', 2],
  ['90d', 'Last 90 days', 3],
  ['6mo', 'Last 6 months', 6],
  ['12mo', 'Last 12 months', 12],
]

function SearchKeywordsPanel({ clientId }: { clientId: string }) {
  // '' = default (latest month); a range token ('30d'…) or a month ('YYYY-MM-01').
  const [selection, setSelection] = useState('')
  const [q, setQ] = useState('')
  const [sortAlpha, setSortAlpha] = useState(false)
  const rangeMonths = KEYWORD_RANGES.find(([tok]) => tok === selection)?.[2]
  const { data, isLoading, isError } = useQuery<GbpSearchKeywords>({
    queryKey: ['gbp-search-keywords', clientId, selection || 'latest'],
    queryFn: () => {
      const qs = rangeMonths ? `&months=${rangeMonths}` : selection ? `&month=${selection}` : ''
      return api.get<GbpSearchKeywords>(
        `/clients/${clientId}/gbp-metrics/search-keywords?limit=500${qs}`,
      )
    },
    enabled: Boolean(clientId),
  })
  const muted: React.CSSProperties = { fontSize: 12.5, color: '#94a3b8', padding: '6px 0' }

  // Filter by substring, then sort A–Z or keep the backend's volume-desc order.
  const shown = useMemo(() => {
    const all = data?.keywords ?? []
    const needle = q.trim().toLowerCase()
    const filtered = needle ? all.filter((k) => k.keyword.toLowerCase().includes(needle)) : all
    return sortAlpha ? [...filtered].sort((a, b) => a.keyword.localeCompare(b.keyword)) : filtered
  }, [data, q, sortAlpha])

  const hasData = Boolean(data && data.keywords.length > 0)

  return (
    <>
      <SectionHeading>Search keywords — what people searched to find this business</SectionHeading>
      <div style={tile}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#64748b' }}>
            <Search size={14} color="#6366f1" />
            {data?.total ? (
              <span>
                <strong style={{ color: '#0f172a' }}>{data.total.toLocaleString()}</strong> impressions from search terms
                {rangeMonths && data.range_months > 1 && <span style={{ color: '#94a3b8' }}> · {data.range_months} months</span>}
              </span>
            ) : 'Top search terms'}
          </div>
          {data && data.months.length > 0 && (
            <select style={{ ...select, padding: '6px 8px' }} value={selection || (data.month ?? '')} onChange={(e) => setSelection(e.target.value)}>
              <optgroup label="Ranges">
                {KEYWORD_RANGES.map(([tok, label]) => <option key={tok} value={tok}>{label}</option>)}
              </optgroup>
              <optgroup label="By month">
                {data.months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
              </optgroup>
            </select>
          )}
        </div>
        {isLoading ? (
          <div style={muted}>Loading search keywords…</div>
        ) : isError ? (
          <div style={muted}>Couldn't load search keywords right now — try refreshing.</div>
        ) : !hasData ? (
          <div style={muted}>
            No search-keyword data yet. GBP reports these monthly (about a month behind) — it fills in after the next monthly sync.
          </div>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search keywords…"
                style={{ flex: '1 1 200px', minWidth: 140, fontSize: 12.5, padding: '6px 9px', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none', color: '#334155' }}
              />
              <button
                style={{ ...secondaryBtn, padding: '6px 10px' }}
                onClick={() => setSortAlpha((s) => !s)}
                title={sortAlpha ? 'Sorted A–Z — click for volume' : 'Sorted by volume — click for A–Z'}
              >
                <ArrowUpDown size={13} /> {sortAlpha ? 'A–Z' : 'Volume'}
              </button>
            </div>
            {shown.length === 0 ? (
              <div style={muted}>No keywords match “{q.trim()}”.</div>
            ) : (
              <div style={{ maxHeight: 'min(1000px, 72vh)', overflowY: 'auto', display: 'grid', gap: 2, paddingRight: 4 }}>
                {shown.map((k) => (
                  <div key={k.keyword} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 12.5, padding: '3px 0', borderBottom: '1px solid #f8fafc' }}>
                    <span style={{ color: '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.keyword}</span>
                    <span style={{ color: '#64748b', flexShrink: 0 }}>{k.is_threshold ? `<${k.value.toLocaleString()}` : k.value.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ fontSize: 10.5, color: '#cbd5e1', marginTop: 6 }}>
              Showing {shown.length.toLocaleString()} of {data!.keywords.length.toLocaleString()} keyword{data!.keywords.length === 1 ? '' : 's'} · “&lt;N” = Google's privacy floor for low-volume terms.
            </div>
          </>
        )}
      </div>
    </>
  )
}

function InsightsPanel({ lines }: { lines: string[] }) {
  return (
    <div style={{ ...noticeCard, background: '#eef2ff', borderColor: '#c7d2fe', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <Lightbulb size={15} color="#4f46e5" />
        <strong style={{ fontSize: 12.5, color: '#3730a3' }}>At a glance</strong>
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>
        {lines.map((l, i) => <li key={i} style={{ fontSize: 13, color: '#312e81' }}>{l}</li>)}
      </ul>
    </div>
  )
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 12.5, fontWeight: 700, color: '#0f172a', margin: '20px 0 10px', letterSpacing: '-0.01em' }}>
      {children}
    </div>
  )
}

function ReviewsPanel({ reviews }: { reviews: GbpReviewsSummary }) {
  const rating = reviews.rating
  const full = rating != null ? Math.round(rating) : 0
  return (
    <div style={{ ...tile, marginBottom: 16, display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <div style={{ flexShrink: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 3 }}>Google reviews</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a' }}>{rating != null ? rating.toFixed(1) : '—'}</div>
          <div style={{ display: 'flex', gap: 1 }}>
            {[0, 1, 2, 3, 4].map((i) => (
              <Star key={i} size={14} fill={i < full ? '#f59e0b' : 'none'} color={i < full ? '#f59e0b' : '#cbd5e1'} />
            ))}
          </div>
        </div>
        <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 2 }}>{reviews.review_count.toLocaleString()} reviews</div>
      </div>
      {reviews.items.length > 0 && (
        <div style={{ flex: '1 1 320px', minWidth: 0, display: 'grid', gap: 6 }}>
          {reviews.items.slice(0, 3).map((r, i) => (
            <div key={i} style={{ fontSize: 12.5, color: '#475569' }}>
              {r.rating != null && <span style={{ color: '#f59e0b' }}>{'★'.repeat(Math.round(r.rating))} </span>}
              <span style={{ fontStyle: 'italic' }}>"{r.text}"</span>
              {r.reviewer && <span style={{ color: '#94a3b8' }}> — {r.reviewer}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Reviews actually posted during the reporting window (first-party v4), fetched
// separately with the dashboard's resolved date range so it matches the period.
function PeriodReviewsPanel({ clientId, start, end }: { clientId: string; start: string; end: string }) {
  const { data, isLoading, isError } = useQuery<GbpPeriodReviews>({
    queryKey: ['gbp-period-reviews', clientId, start, end],
    queryFn: () => api.get<GbpPeriodReviews>(
      `/clients/${clientId}/gbp-metrics/reviews?start=${start}&end=${end}`,
    ),
    enabled: Boolean(clientId && start && end),
  })
  const muted: React.CSSProperties = { fontSize: 12.5, color: '#94a3b8', padding: '6px 0' }
  const stars = (n: number | null) => (n != null ? '★'.repeat(Math.round(n)) + '☆'.repeat(Math.max(0, 5 - Math.round(n))) : '')

  return (
    <>
      <SectionHeading>Reviews posted this period</SectionHeading>
      <div style={tile}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#64748b' }}>
            <Star size={14} color="#f59e0b" fill="#f59e0b" />
            {data ? (
              <span>
                <strong style={{ color: '#0f172a' }}>{data.count.toLocaleString()}</strong> new review{data.count === 1 ? '' : 's'}
                {data.average_rating != null && <> · avg <strong style={{ color: '#0f172a' }}>{data.average_rating.toFixed(1)}</strong>
                  <span style={{ color: '#f59e0b' }}> {stars(data.average_rating)}</span></>}
              </span>
            ) : 'New reviews'}
          </div>
          {data && data.overall_rating != null && (
            <div style={{ fontSize: 11.5, color: '#94a3b8' }}>
              all-time {Number(data.overall_rating).toFixed(1)}★ · {data.overall_count.toLocaleString()} reviews
            </div>
          )}
        </div>
        {isLoading ? (
          <div style={muted}>Loading reviews…</div>
        ) : isError ? (
          <div style={muted}>Couldn't load reviews right now — try refreshing.</div>
        ) : !data || data.items.length === 0 ? (
          <div style={muted}>
            No new reviews posted in this period.{data && data.count === 0 && data.overall_count === 0 ? ' Reviews sync daily once connected.' : ''}
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {data.items.map((r, i) => (
              <div key={i} style={{ borderBottom: i < data.items.length - 1 ? '1px solid #f1f5f9' : 'none', paddingBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 3 }}>
                  <span style={{ color: '#f59e0b', fontSize: 12.5 }}>{stars(r.rating)}</span>
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: '#334155' }}>{r.reviewer || 'Anonymous'}</span>
                  <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{r.date}</span>
                  {r.has_reply && <span style={{ fontSize: 10.5, color: '#0369a1', background: '#e0f2fe', borderRadius: 4, padding: '1px 6px' }}>replied</span>}
                </div>
                {r.text && <div style={{ fontSize: 12.5, color: '#475569', lineHeight: 1.45 }}>{r.text}</div>}
              </div>
            ))}
            {data.count > data.items.length && (
              <div style={{ fontSize: 11, color: '#cbd5e1' }}>Showing {data.items.length} of {data.count.toLocaleString()} this period.</div>
            )}
          </div>
        )}
      </div>
    </>
  )
}

// Large interactive trend chart: this period (solid) vs the prior period (dashed),
// aligned by day-of-period, with a metric selector and a hover tooltip.
function TrendChart({ data }: { data: GbpDashboard }) {
  const options = data.metrics.map((m) => ({ key: m.metric, label: m.label }))
  const [metric, setMetric] = useState(options[0]?.key ?? 'profile_views')
  const [hover, setHover] = useState<number | null>(null)

  const cur = useMemo(() => (data.series ?? []).map((p) => p.values[metric] ?? 0), [data.series, metric])
  const prev = useMemo(() => (data.compare_series ?? []).map((p) => p.values[metric] ?? 0), [data.compare_series, metric])
  const dates = (data.series ?? []).map((p) => p.date)
  const label = options.find((o) => o.key === metric)?.label ?? metric

  const width = 900, height = 260
  const padL = 44, padR = 16, padT = 16, padB = 26
  const span = Math.max(cur.length, prev.length, 2)
  const maxV = Math.max(1, ...cur, ...prev)
  const x = (i: number) => padL + (i / (span - 1)) * (width - padL - padR)
  const y = (v: number) => padT + (1 - v / maxV) * (height - padT - padB)
  const line = (vals: number[]) => vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const curArea = cur.length
    ? `${line(cur)} L${x(cur.length - 1).toFixed(1)},${height - padB} L${x(0).toFixed(1)},${height - padB} Z`
    : ''

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const f = (e.clientX - rect.left) / rect.width
    const plotFrac = (f - padL / width) / ((width - padL - padR) / width)
    setHover(Math.round(Math.max(0, Math.min(1, plotFrac)) * (cur.length - 1)))
  }
  const gridY = [0, 0.5, 1].map((f) => ({ v: Math.round(maxV * (1 - f)), yy: padT + f * (height - padT - padB) }))
  const hi = hover != null && hover >= 0 && hover < cur.length ? hover : null

  return (
    <div style={{ ...tile, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <select style={{ ...select, padding: '6px 8px' }} value={metric} onChange={(e) => setMetric(e.target.value)}>
          {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
        <div style={{ display: 'flex', gap: 14, fontSize: 11.5, color: '#64748b' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 14, height: 2, background: '#6366f1', display: 'inline-block' }} /> This period
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 14, height: 0, borderTop: '2px dashed #94a3b8', display: 'inline-block' }} /> Previous
          </span>
        </div>
      </div>
      <div style={{ position: 'relative' }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block', height: 260 }}>
          {gridY.map((g, i) => (
            <g key={i}>
              <line x1={padL} y1={g.yy} x2={width - padR} y2={g.yy} stroke="#f1f5f9" strokeWidth={1} />
              <text x={padL - 6} y={g.yy + 3} textAnchor="end" fontSize={10} fill="#94a3b8">{g.v.toLocaleString()}</text>
            </g>
          ))}
          {curArea && <path d={curArea} fill="#6366f1" opacity={0.08} />}
          {prev.length > 1 && <path d={line(prev)} fill="none" stroke="#94a3b8" strokeWidth={1.5} strokeDasharray="4 3" strokeLinejoin="round" />}
          {cur.length > 1 && <path d={line(cur)} fill="none" stroke="#6366f1" strokeWidth={2} strokeLinejoin="round" />}
          {hi != null && (
            <g>
              <line x1={x(hi)} y1={padT} x2={x(hi)} y2={height - padB} stroke="#cbd5e1" strokeWidth={1} />
              <circle cx={x(hi)} cy={y(cur[hi])} r={3} fill="#6366f1" />
            </g>
          )}
          <text x={padL} y={height - 8} fontSize={10} fill="#94a3b8">{dates[0]}</text>
          <text x={width - padR} y={height - 8} textAnchor="end" fontSize={10} fill="#94a3b8">{dates[dates.length - 1]}</text>
        </svg>
        {hi != null && (
          <div style={{
            position: 'absolute', left: `${(x(hi) / width) * 100}%`, top: 0, transform: 'translateX(-50%)',
            background: '#0f172a', color: '#fff', fontSize: 11, borderRadius: 6, padding: '5px 8px',
            pointerEvents: 'none', whiteSpace: 'nowrap',
          }}>
            <div style={{ opacity: 0.7 }}>{dates[hi]}</div>
            <div><strong>{cur[hi].toLocaleString()}</strong> {label.toLowerCase()}</div>
            {prev[hi] != null && <div style={{ opacity: 0.7 }}>prev: {prev[hi].toLocaleString()}</div>}
          </div>
        )}
      </div>
    </div>
  )
}

function BreakdownCard({ title, items }: { title: string; items: GbpBreakdownItem[] }) {
  const colors = ['#6366f1', '#0ea5e9', '#14b8a6', '#f59e0b']
  return (
    <div style={tile}>
      <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 10 }}>{title}</div>
      <div style={{ display: 'grid', gap: 10 }}>
        {items.map((it, i) => (
          <div key={it.label}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 3 }}>
              <span style={{ color: '#334155', fontWeight: 600 }}>{it.label}</span>
              <span style={{ color: '#64748b' }}>{it.current.toLocaleString()} · {it.share}%</span>
            </div>
            <div style={{ height: 7, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(100, it.share)}%`, height: '100%', background: colors[i % colors.length], borderRadius: 999 }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ActionsHeadline({ actions }: { actions: GbpActionsSummary }) {
  const pct = actions.pct
  const dir = pct == null ? 'new' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  const c = { up: '#15803d', down: '#b91c1c', flat: '#64748b', new: '#6366f1' }[dir]
  const cbg = { up: '#f0fdf4', down: '#fef2f2', flat: '#f1f5f9', new: '#eef2ff' }[dir]
  const arrow = dir === 'up' ? '▲' : dir === 'down' ? '▼' : dir === 'flat' ? '▬' : '＋'
  return (
    <div style={{ ...tile, display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', marginBottom: 12 }}>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>Total customer actions</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a' }}>{actions.current.toLocaleString()}</div>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: c, background: cbg, borderRadius: 999, padding: '2px 8px' }}>
            {pct == null ? 'new' : `${arrow} ${Math.abs(pct)}%`}
          </span>
        </div>
      </div>
      {actions.engagement_current != null && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>Engagement rate</div>
          <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a', marginTop: 2 }}>{actions.engagement_current}%</div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>of viewers took an action</div>
        </div>
      )}
    </div>
  )
}

function MetricTile({ metric, series }: { metric: GbpMetricGrowth; series: GbpSeriesPoint[] }) {
  const daily = useMemo(() => series.map((p) => p.values[metric.metric] ?? 0), [series, metric.metric])
  const busiest = useMemo(() => {
    let bi = -1, bv = -1
    daily.forEach((v, i) => { if (v > bv) { bv = v; bi = i } })
    return bi >= 0 && bv > 0 ? { date: series[bi]?.date, value: bv } : null
  }, [daily, series])
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
      {busiest && (
        <div style={{ fontSize: 10.5, color: '#94a3b8', marginTop: 5 }}>
          Busiest: {new Date(busiest.date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ({busiest.value.toLocaleString()})
        </div>
      )}
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

// "2026-07-01" → "Jul 2026". Parsed as local time-of-day to avoid a UTC
// off-by-one shoving the 1st into the prior month.
function monthLabel(m: string): string {
  const d = new Date(m + 'T00:00:00')
  return isNaN(d.getTime()) ? m : d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
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
const breakdownGrid: React.CSSProperties = {
  display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', marginTop: 12,
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
