import { useEffect, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Map, Play, Trash2, MapPin, Download, Printer, Square, ToggleLeft, ToggleRight, Bell, Check, X } from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type {
  Client, MapsAlert, MapsAlertsResponse, MapsChangesResponse, MapsCompetitorTrendsResponse,
  MapsConfig, MapsKeyword, MapsKeywordChange, MapsPeriodMetric, MapsPeriodScope,
  MapsPeriodsResponse, MapsRadius, MapsRunResponse,
  MapsScanDetail, MapsScanResultRow, MapsScanSummary, MapsTrendsResponse,
} from '../lib/types'
import { GeoGridMap, TrendChart } from '../components/maps/visuals'
import { Markdown } from '../components/Markdown'
import { rankColor, TREND_METRICS } from '../components/maps/rank'
import type { TrendMetric } from '../components/maps/rank'
import { backLink, card, errorBox, outlineBtn, primaryBtn, relativeTime } from '../components/localseo/shared'

type Tab = 'heatmap' | 'changes' | 'setup' | 'history'

// Maps / local-pack geo-grid ranker (Module #5). A separate per-client module:
// configure a 3/5/7-mile grid around the business, track keywords, and see the
// business's Maps rank per pin as a heatmap (via Local Dominator).
export function MapsGeogrid() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('heatmap')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })
  // Track a just-clicked run so the progress UI shows immediately, before the
  // scan row exists (the create job runs async, a few seconds behind the click).
  // recentlyRan holds a ~90s grace window after a run; runSeq bumps on each run so
  // the timer effect restarts. Holding the window in a timeout (rather than a
  // Date.now() comparison in render) keeps render pure and avoids setState-in-effect.
  const [recentlyRan, setRecentlyRan] = useState(false)
  const [runSeq, setRunSeq] = useState(0)
  useEffect(() => {
    if (!recentlyRan) return
    const t = setTimeout(() => setRecentlyRan(false), 90000)
    return () => clearTimeout(t)
  }, [recentlyRan, runSeq])
  const markRun = () => { setRecentlyRan(true); setRunSeq(s => s + 1) }
  // Stopping a scan clears the grace window so the in-progress UI drops away
  // immediately rather than lingering for the rest of the 90s.
  const stopRun = () => setRecentlyRan(false)

  const { data: scans } = useQuery<MapsScanSummary[]>({
    queryKey: ['maps-scans', clientId],
    queryFn: () => api.get<MapsScanSummary[]>(`/clients/${clientId}/maps/scans`),
    // Poll while a scan is running OR just after a run (to catch the new row).
    refetchInterval: (q) => {
      const inf = (q.state.data ?? []).some(s => s.status === 'polling' || s.status === 'pending')
      return inf || recentlyRan ? 6000 : false
    },
  })

  const inFlight = (scans ?? []).some(s => s.status === 'polling' || s.status === 'pending')
  const scanning = inFlight || recentlyRan

  // Badge the "What changed" tab with the unread geo-grid alert count.
  const { data: alerts } = useQuery<MapsAlertsResponse>({
    queryKey: ['maps-alerts', clientId],
    queryFn: () => api.get<MapsAlertsResponse>(`/clients/${clientId}/maps/alerts`),
    enabled: Boolean(clientId),
  })
  const alertsUnread = alerts?.unread_count ?? 0

  // While scanning, drive Local Dominator polling from the client so results
  // land in seconds instead of waiting for the 5-minute scheduler tick.
  useQuery({
    queryKey: ['maps-poll', clientId],
    queryFn: () => api.post(`/clients/${clientId}/maps/poll`, {}),
    enabled: scanning,
    refetchInterval: scanning ? 10000 : false,
  })

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Map size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Maps Geo-Grid Ranker</h1>
        {scanning && <span style={scanningPill}>Scanning…</span>}
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px' }}>
        {client?.name ?? 'This client'} · local-pack &amp; Maps rank across a grid of points around the business.
      </p>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 24 }}>
        <TabButton active={tab === 'heatmap'} onClick={() => setTab('heatmap')} label="Heatmap" />
        <TabButton active={tab === 'changes'} onClick={() => setTab('changes')} label="What changed" badge={alertsUnread} />
        <TabButton active={tab === 'setup'} onClick={() => setTab('setup')} label="Setup" />
        <TabButton active={tab === 'history'} onClick={() => setTab('history')} label="History" />
      </div>

      {tab === 'setup' ? (
        <Setup clientId={clientId} />
      ) : tab === 'history' ? (
        <History clientId={clientId} scans={scans ?? []} onOpen={() => setTab('heatmap')} />
      ) : tab === 'changes' ? (
        <WhatChanged clientId={clientId} />
      ) : (
        <Heatmap clientId={clientId} scanning={scanning} onRan={markRun} onStopped={stopRun} />
      )}
    </div>
  )
}

// ── Heatmap (latest completed scan) ─────────────────────────────────────────
function Heatmap({ clientId, scanning, onRan, onStopped }: { clientId: string; scanning: boolean; onRan: () => void; onStopped: () => void }) {
  const queryClient = useQueryClient()
  const { data: latest, error, isLoading } = useQuery<MapsScanDetail>({
    queryKey: ['maps-latest', clientId],
    queryFn: () => api.get<MapsScanDetail>(`/clients/${clientId}/maps/latest`),
    retry: false,
    // Refresh while a scan runs so the heatmap appears as soon as it completes.
    refetchInterval: scanning ? 8000 : false,
  })
  const runMut = useMutation({
    mutationFn: () => api.post<MapsRunResponse>(`/clients/${clientId}/maps/scan`, {}),
    onSuccess: () => {
      onRan()
      queryClient.invalidateQueries({ queryKey: ['maps-scans', clientId] })
    },
  })
  const cancelMut = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/maps/scan/cancel`, {}),
    onSuccess: () => {
      onStopped()
      queryClient.invalidateQueries({ queryKey: ['maps-scans', clientId] })
    },
  })

  const busy = scanning || runMut.isPending
  // One-off run + a stop control (while a scan is in flight) + the quick weekly
  // schedule toggle, grouped so they sit together above the heatmap.
  const controls = (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
      <ScheduleToggle clientId={clientId} />
      {busy && (
        <button style={{ ...outlineBtn, color: '#dc2626', borderColor: '#fecaca' }} onClick={() => cancelMut.mutate()} disabled={cancelMut.isPending}>
          <Square size={13} /> {cancelMut.isPending ? 'Stopping…' : 'Stop scan'}
        </button>
      )}
      <button style={primaryBtn} onClick={() => runMut.mutate()} disabled={runMut.isPending}>
        <Play size={14} /> {runMut.isPending ? 'Starting…' : 'Run scan now'}
      </button>
    </div>
  )

  if (isLoading) return <p style={muted}>Loading…</p>
  if (error || !latest) {
    return (
      <div>
        {busy && <InProgressBanner />}
        <div style={card}>
          {!busy && (
            <p style={{ ...muted, marginTop: 0 }}>
              No completed scans yet. Set the business location &amp; keywords in <strong>Setup</strong>, then run a scan.
            </p>
          )}
          {runMut.error && <div style={errorBox}>{(runMut.error as Error).message}</div>}
          {runMut.data?.status === 'failed' && (
            <div style={{ ...errorBox, marginTop: 10 }}>Couldn’t start: {runMut.data.error}. Check Setup is complete (Place ID, center lat/lng, and at least one keyword).</div>
          )}
          {cancelMut.error && <div style={{ ...errorBox, marginTop: 10 }}>{(cancelMut.error as Error).message}</div>}
          <div style={{ marginTop: busy ? 0 : 4 }}>{controls}</div>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ fontSize: 13, color: '#64748b' }}>
          Last scan {latest.completed_at ? relativeTime(latest.completed_at) : ''} · {latest.radius_miles}-mile radius · {latest.grid_size}×{latest.grid_size} grid · {latest.resource_category === 'googleLocalFinder' ? 'Local Finder' : 'Google Maps'}
        </div>
        {controls}
      </div>
      {(scanning || runMut.isPending) && <InProgressBanner />}

      {latest.results.length === 0 ? (
        <div style={card}><p style={muted}>This scan returned no keyword results.</p></div>
      ) : (
        latest.results.map(r => (
          <div key={r.keyword} style={{ ...card, marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }}>{r.keyword}</h3>
              <div style={{ display: 'flex', gap: 14, fontSize: 13, color: '#475569' }}>
                <span><strong>Avg rank</strong> {r.average_rank ?? '—'}</span>
                <span><strong>Top 3</strong> {pct(r.top3_pins, r.total_pins)}</span>
                <span><strong>Found</strong> {r.found_pins}/{r.total_pins} pins</span>
              </div>
            </div>
            <ResultView r={r} scan={latest} clientId={clientId} />
          </div>
        ))
      )}
      <Legend />
    </div>
  )
}

// One keyword's result: the geo-grid map (numbered rank pins) plus the LD
// interactive-map link and the full numeric grid.
function ResultView({ r, scan, clientId }: { r: MapsScanResultRow; scan: MapsScanDetail; clientId: string }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', gap: 18, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 360px', maxWidth: 480 }}>
          <GeoGridMap grid={r.rank_grid} centerLat={scan.center_lat} centerLng={scan.center_lng} />
        </div>
        <AtAGlance r={r} />
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 10 }}>
        {r.dynamic_url && (
          <a href={r.dynamic_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#6366f1', textDecoration: 'none' }}>
            Open interactive map ↗
          </a>
        )}
        <details>
          <summary style={{ fontSize: 12, color: '#64748b', cursor: 'pointer' }}>Show full grid</summary>
          <div style={{ marginTop: 10 }}><Grid grid={r.rank_grid} /></div>
        </details>
      </div>
      <LocalRankAnalysis r={r} clientId={clientId} scanId={scan.id} />
    </div>
  )
}

// At-a-glance panel beside the map — fills the whitespace with the headline
// coverage metrics plus the strongest/weakest directions and performance
// horizon (from the report analytics, when available).
function GlanceRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '5px 0', borderTop: '1px solid #f1f5f9' }}>
      <span style={{ fontSize: 12, color: '#64748b' }}>{label}</span>
      <span style={{ fontSize: 12, color: '#0f172a', fontWeight: 600, textAlign: 'right' }}>{value}</span>
    </div>
  )
}

function AtAGlance({ r }: { r: MapsScanResultRow }) {
  const a = r.report_analytics
  const dirs = (list?: { sector: string }[]) => (list ?? []).map(d => d.sector).join(' · ') || '—'
  const horizon = a?.performance_horizon
  const topThreat = r.report_top_competitors?.[0] ?? r.competitors?.[0]?.name ?? null
  return (
    <div style={{ flex: '1 1 240px', minWidth: 220, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}>At a glance</div>
      <GlanceRow label="Average rank" value={r.average_rank ?? '—'} />
      <GlanceRow label="Top-3 coverage" value={pct(r.top3_pins, r.total_pins)} />
      <GlanceRow label="Top-10 coverage" value={pct(r.top10_pins, r.total_pins)} />
      <GlanceRow label="Found" value={`${r.found_pins}/${r.total_pins} pins`} />
      {horizon && <GlanceRow label="Visibility horizon" value={`~${horizon.radius_mi} mi`} />}
      <GlanceRow label="Strongest" value={<span style={{ color: '#16a34a' }}>{dirs(a?.best_directions)}</span>} />
      <GlanceRow label="Weakest" value={<span style={{ color: '#dc2626' }}>{dirs(a?.weakest_directions)}</span>} />
      {topThreat && <GlanceRow label="Top competitor" value={topThreat} />}
    </div>
  )
}

// Local Rank Analysis: the auto-generated client-facing report (Markdown) plus
// suggested hyper-local pins for the weak zones, with a Regenerate control.
function LocalRankAnalysis({ r, clientId, scanId }: { r: MapsScanResultRow; clientId: string; scanId: string }) {
  const queryClient = useQueryClient()
  const regenMut = useMutation({
    // Target the scan being viewed (not just the client's latest).
    mutationFn: () => api.post(`/clients/${clientId}/maps/report?scan_id=${scanId}`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['maps-latest', clientId] }),
  })

  // Prefer the geocoded octant pins (they carry the nearest-city label); fall
  // back to the raw pin generator output for pre-geocoding scans.
  const loc = r.report_weak_locations
  const pins = (loc?.octant_pins?.length ? loc.octant_pins : r.report_octant_pins?.points) ?? []
  const weakAreas = loc?.weak_areas ?? []
  const gmapsLink = (lat: number, lng: number) => `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`
  const TIER_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
    critical: { bg: '#fee2e2', fg: '#b91c1c', label: 'Critical' },
    weak: { bg: '#fef3c7', fg: '#b45309', label: 'Weak' },
    watch: { bg: '#f1f5f9', fg: '#64748b', label: 'Watch' },
  }
  const tierBadge = (tier?: string) => {
    const t = TIER_STYLE[tier ?? ''] ?? TIER_STYLE.watch
    return <span style={{ display: 'inline-block', padding: '1px 7px', borderRadius: 10, fontSize: 10.5, fontWeight: 700, background: t.bg, color: t.fg }}>{t.label}</span>
  }

  return (
    <div style={{ marginTop: 16, borderTop: '1px solid #f1f5f9', paddingTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <h4 style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', margin: 0 }}>Local Rank Analysis</h4>
        <div style={{ display: 'flex', gap: 8 }}>
          {r.report_status === 'complete' && r.report_md && (
            <Link
              to={`/clients/${clientId}/maps/report?keyword=${encodeURIComponent(r.keyword)}&print=1`}
              target="_blank"
              rel="noreferrer"
              style={{ ...outlineBtn, padding: '6px 10px', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 5 }}
            >
              <Download size={13} /> Download report
            </Link>
          )}
          <button
            style={{ ...outlineBtn, padding: '6px 10px', fontSize: 12 }}
            onClick={() => regenMut.mutate()}
            disabled={regenMut.isPending}
          >
            {regenMut.isPending ? 'Queuing…' : 'Regenerate report'}
          </button>
        </div>
      </div>

      {r.report_status === 'complete' && r.report_md ? (
        <div>
          <Markdown>{r.report_md}</Markdown>
          {weakAreas.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#475569', marginBottom: 2 }}>Weak coverage areas (nearby cities)</div>
              <p style={{ fontSize: 11.5, color: '#94a3b8', margin: '0 0 6px' }}>
                The towns/cities the grid is weakest in — where {r.keyword ? `“${r.keyword}”` : 'this keyword'} ranks poorly or not at all, ordered by <strong>priority</strong> (severity × proximity × beatability) so the top rows are where to work first. <em>Watch</em> = ranks 5–9 (lowest priority); <em>Weak</em> = 10+; <em>Critical</em> = unranked. Open a point on Google Maps to scope local SEO work there.
              </p>
              <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12.5 }}>
                <thead>
                  <tr>
                    {['Priority', 'City', 'Tier', 'Weak pins', 'Directions', 'Worst rank', 'Map'].map((h, hi) => (
                      <th key={h} style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: hi === 1 || hi === 4 ? 'left' : hi === 2 || hi === 6 ? 'center' : 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', background: '#f8fafc' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {weakAreas.map((a, ai) => (
                    <tr key={ai}>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', fontWeight: 700, color: '#0f172a' }}>{a.priority}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }}>
                        {a.city ?? '—'}{a.admin_area ? <span style={{ color: '#94a3b8' }}>, {a.admin_area}</span> : null}
                      </td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'center' }}>{tierBadge(a.tier)}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', color: '#334155' }}>
                        {a.pins}{a.not_ranked > 0 ? <span style={{ color: '#dc2626' }}> ({a.not_ranked} unranked)</span> : null}
                      </td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }}>{a.octants.join(' · ') || '—'}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', color: '#334155' }}>{a.worst_rank ?? 'Not ranked'}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'center' }}>
                        <a href={gmapsLink(a.lat, a.lng)} target="_blank" rel="noreferrer" style={{ color: '#6366f1', textDecoration: 'none' }}>Open ↗</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {pins.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Suggested hyper-local pins (weak zones)</div>
              <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12.5 }}>
                <thead>
                  <tr>
                    {['Octant', 'Nearby city', 'Ring (mi)', 'Strength', 'Lat', 'Lng', 'Map'].map((h, hi) => (
                      <th key={h} style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: hi === 0 || hi === 1 || hi === 3 ? 'left' : hi === 6 ? 'center' : 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', background: '#f8fafc' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {pins.map((p, pi) => (
                    <tr key={pi}>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }}>{p.octant}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }}>{p.city ?? '—'}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', color: '#334155' }}>{p.radius_mi.toFixed(1)}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }}>{p.strength}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', color: '#334155', fontVariantNumeric: 'tabular-nums' }}>{p.lat.toFixed(5)}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'right', color: '#334155', fontVariantNumeric: 'tabular-nums' }}>{p.lng.toFixed(5)}</td>
                      <td style={{ border: '1px solid #e2e8f0', padding: '6px 10px', textAlign: 'center' }}>
                        <a href={gmapsLink(p.lat, p.lng)} target="_blank" rel="noreferrer" style={{ color: '#6366f1', textDecoration: 'none' }}>Open ↗</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {loc && !loc.geocoded && (
                <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
                  City names unavailable — set a Google Geocoding API key to label these weak zones with their nearest town.
                </p>
              )}
            </div>
          )}
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginTop: 10 }}>
            {r.report_doc_url && (
              <a href={r.report_doc_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#6366f1', textDecoration: 'none' }}>
                View Google Doc ↗
              </a>
            )}
            {r.report_generated_at && (
              <span style={{ fontSize: 12, color: '#94a3b8' }}>Generated {relativeTime(r.report_generated_at)}</span>
            )}
          </div>
        </div>
      ) : r.report_status === 'pending' ? (
        <p style={muted}>Generating report…</p>
      ) : r.report_status === 'failed' ? (
        <p style={muted}>Report generation failed.</p>
      ) : (
        <p style={muted}>No report yet.</p>
      )}

      {regenMut.error && <div style={{ ...errorBox, marginTop: 10 }}>{(regenMut.error as Error).message}</div>}
    </div>
  )
}

// Quick on/off for the weekly recurring scan, without going to Setup. Shares the
// ['maps-config'] cache with Setup so both views stay in sync.
function ScheduleToggle({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const { data: config } = useQuery<MapsConfig>({
    queryKey: ['maps-config', clientId],
    queryFn: () => api.get<MapsConfig>(`/clients/${clientId}/maps/config`),
  })
  const on = config?.cadence === 'weekly'
  const toggleMut = useMutation({
    mutationFn: () => api.put<MapsConfig>(`/clients/${clientId}/maps/config`, { cadence: on ? 'off' : 'weekly' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['maps-config', clientId] }),
  })
  if (!config) return null
  return (
    <button
      style={{ ...outlineBtn, color: on ? '#16a34a' : '#64748b' }}
      onClick={() => toggleMut.mutate()}
      disabled={toggleMut.isPending}
      title={on ? 'Weekly auto-scan is on — click to pause' : 'Weekly auto-scan is off — click to resume'}
    >
      {on ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
      {toggleMut.isPending ? 'Saving…' : on ? 'Weekly: On' : 'Weekly: Off'}
    </button>
  )
}

function InProgressBanner() {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const mm = Math.floor(secs / 60)
  const ss = String(secs % 60).padStart(2, '0')
  return (
    <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 14, background: '#fffbeb', border: '1px solid #fde68a', marginBottom: 16 }}>
      <span className="ld-spin" style={{ width: 24, height: 24, borderRadius: 999, border: '3px solid #fcd34d', borderTopColor: '#d97706', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#92400e', display: 'flex', justifyContent: 'space-between' }}>
          <span>Scan in progress…</span>
          <span style={{ fontVariantNumeric: 'tabular-nums', color: '#b45309' }}>{mm}:{ss}</span>
        </div>
        <div style={{ fontSize: 13, color: '#b45309', margin: '2px 0 8px' }}>
          Scanning the grid across Google Maps — usually a couple of minutes. The heatmap appears here automatically when it’s done; you can leave this page.
        </div>
        <div style={{ height: 6, borderRadius: 999, background: '#fde68a', overflow: 'hidden' }}>
          <div className="ld-bar" style={{ height: '100%', width: '35%', borderRadius: 999, background: '#d97706' }} />
        </div>
      </div>
      <style>{'@keyframes ld-spin{to{transform:rotate(360deg)}}.ld-spin{animation:ld-spin .9s linear infinite}@keyframes ld-bar{0%{margin-left:-35%}100%{margin-left:100%}}.ld-bar{animation:ld-bar 1.4s ease-in-out infinite}'}</style>
    </div>
  )
}

function Grid({ grid }: { grid: Array<Array<number | null>> | null }) {
  if (!grid || grid.length === 0) return <p style={muted}>No grid data.</p>
  const cols = Math.max(...grid.map(r => r.length))
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 2, maxWidth: cols * 22 }}>
      {grid.flatMap((row, ri) =>
        row.map((cell, ci) => {
          // Grid is 1-based; not-ranked pins are null.
          const ranked = typeof cell === 'number' && cell >= 1
          return (
            <div key={`${ri}-${ci}`} title={ranked ? `Rank ${cell}` : 'Not ranked here'}
              style={{
                aspectRatio: '1', display: 'flex', alignItems: 'center', justifyContent: 'center',
                borderRadius: 3, fontSize: 9, fontWeight: 700,
                background: rankColor(cell), color: ranked ? '#fff' : '#9ca3af',
              }}>
              {ranked ? cell : '·'}
            </div>
          )
        }),
      )}
    </div>
  )
}

function Legend() {
  const items: Array<[string, string]> = [
    ['1–3', rankColor(2)], ['4–7', rankColor(5)], ['8–10', rankColor(9)],
    ['11–15', rankColor(13)], ['16–20', rankColor(18)], ['Not ranked', rankColor(null)],
  ]
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 12, color: '#64748b', marginTop: 4 }}>
      <span>Rank:</span>
      {items.map(([label, color]) => (
        <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 12, height: 12, borderRadius: 3, background: color, display: 'inline-block' }} />{label}
        </span>
      ))}
    </div>
  )
}

// ── Setup (config + keywords) ───────────────────────────────────────────────
function Setup({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const { data: config } = useQuery<MapsConfig>({
    queryKey: ['maps-config', clientId],
    queryFn: () => api.get<MapsConfig>(`/clients/${clientId}/maps/config`),
  })
  const { data: keywords } = useQuery<MapsKeyword[]>({
    queryKey: ['maps-keywords', clientId],
    queryFn: () => api.get<MapsKeyword[]>(`/clients/${clientId}/maps/keywords`),
  })

  // Seed the editable form from the fetched config once it arrives (and re-seed if
  // the config object reference changes), via the "adjust state during render"
  // pattern — no setState-in-effect.
  const [form, setForm] = useState<Partial<MapsConfig>>({})
  const [seededFrom, setSeededFrom] = useState<MapsConfig | null>(null)
  if (config && config !== seededFrom) {
    setSeededFrom(config)
    setForm(config)
  }
  const set = (patch: Partial<MapsConfig>) => setForm(f => ({ ...f, ...patch }))

  const saveMut = useMutation({
    mutationFn: () => api.put<MapsConfig>(`/clients/${clientId}/maps/config`, {
      google_place_id: form.google_place_id ?? null,
      business_name: form.business_name ?? null,
      center_lat: form.center_lat ?? null,
      center_lng: form.center_lng ?? null,
      radius_miles: form.radius_miles ?? 5,
      resource_category: form.resource_category ?? 'googleMaps',
      serp_device: form.serp_device ?? 'desktop',
      cadence: form.cadence ?? 'weekly',
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['maps-config', clientId] }),
  })

  const [newKw, setNewKw] = useState('')
  const addMut = useMutation({
    mutationFn: () => api.post<MapsKeyword[]>(`/clients/${clientId}/maps/keywords`, {
      keywords: newKw.split(/[\n,]/).map(s => s.trim()).filter(Boolean),
    }),
    onSuccess: () => { setNewKw(''); queryClient.invalidateQueries({ queryKey: ['maps-keywords', clientId] }) },
  })
  const delMut = useMutation({
    mutationFn: (kid: string) => api.delete<void>(`/maps-keywords/${kid}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['maps-keywords', clientId] }),
  })

  const pins = ({ 3: 49, 5: 121, 7: 225 } as Record<number, number>)[form.radius_miles ?? 5]

  return (
    <div>
      <div style={{ ...card, marginBottom: 16 }}>
        <h2 style={sectionTitle}>Business &amp; grid</h2>
        <p style={{ ...muted, marginTop: 0 }}>
          The scan centers on the business and reads its Maps rank at a pin every mile out to the chosen radius.
        </p>
        <Field label="Google Place ID">
          <input style={input} value={form.google_place_id ?? ''} onChange={e => set({ google_place_id: e.target.value })} placeholder="ChIJ…" />
        </Field>
        <Field label="Business name">
          <input style={input} value={form.business_name ?? ''} onChange={e => set({ business_name: e.target.value })} />
        </Field>
        <div style={{ display: 'flex', gap: 12 }}>
          <Field label="Center latitude">
            <input style={input} type="number" value={form.center_lat ?? ''} onChange={e => set({ center_lat: e.target.value === '' ? null : Number(e.target.value) })} />
          </Field>
          <Field label="Center longitude">
            <input style={input} type="number" value={form.center_lng ?? ''} onChange={e => set({ center_lng: e.target.value === '' ? null : Number(e.target.value) })} />
          </Field>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <Field label={`Radius (≈${pins} pins)`}>
            <select style={input} value={form.radius_miles ?? 5} onChange={e => set({ radius_miles: Number(e.target.value) as MapsRadius })}>
              {[3, 5, 7].map(r => <option key={r} value={r}>{r} miles</option>)}
            </select>
          </Field>
          <Field label="Surface">
            <select style={input} value={form.resource_category ?? 'googleMaps'} onChange={e => set({ resource_category: e.target.value as MapsConfig['resource_category'] })}>
              <option value="googleMaps">Google Maps</option>
              <option value="googleLocalFinder">Local Finder (local pack)</option>
            </select>
          </Field>
          <Field label="Schedule">
            <select style={input} value={form.cadence ?? 'weekly'} onChange={e => set({ cadence: e.target.value as 'off' | 'weekly' })}>
              <option value="weekly">Weekly</option>
              <option value="off">Manual only</option>
            </select>
          </Field>
        </div>
        <button style={primaryBtn} onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
          {saveMut.isPending ? 'Saving…' : 'Save setup'}
        </button>
        {saveMut.error && <div style={{ ...errorBox, marginTop: 10 }}>{(saveMut.error as Error).message}</div>}
        {(form.center_lat == null || form.center_lng == null || !form.google_place_id) && (
          <p style={{ fontSize: 12, color: '#b45309', margin: '10px 0 0', display: 'flex', alignItems: 'center', gap: 6 }}>
            <MapPin size={13} /> A Place ID and center lat/lng are required before a scan can run.
          </p>
        )}
      </div>

      <div style={card}>
        <h2 style={sectionTitle}>Keywords</h2>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <textarea style={{ ...input, minHeight: 38, flex: 1 }} value={newKw} onChange={e => setNewKw(e.target.value)}
            placeholder="One keyword per line (e.g. emergency plumber)" />
          <button style={outlineBtn} onClick={() => addMut.mutate()} disabled={addMut.isPending || !newKw.trim()}>Add</button>
        </div>
        {(keywords ?? []).length === 0 ? (
          <p style={muted}>No keywords yet. Each keyword is scanned across the whole grid.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {keywords!.map((k, i) => (
              <div key={k.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 2px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
                <span style={{ flex: 1, fontSize: 14, color: '#0f172a' }}>{k.keyword}</span>
                <button style={{ ...outlineBtn, padding: '4px 7px', color: '#dc2626' }} onClick={() => delMut.mutate(k.id)} title="Remove"><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── History (trend over time + scan list) ───────────────────────────────────
function History({ clientId, scans }: { clientId: string; scans: MapsScanSummary[]; onOpen: () => void }) {
  const queryClient = useQueryClient()
  const { data: trends } = useQuery<MapsTrendsResponse>({
    queryKey: ['maps-trends', clientId],
    queryFn: () => api.get<MapsTrendsResponse>(`/clients/${clientId}/maps/trends`),
  })
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['maps-scans', clientId] })
    queryClient.invalidateQueries({ queryKey: ['maps-trends', clientId] })
  }
  const stopMut = useMutation({
    mutationFn: (id: string) => api.post(`/maps-scans/${id}/cancel`, {}),
    onSuccess: invalidate,
  })
  const delMut = useMutation({
    mutationFn: (id: string) => api.delete(`/maps-scans/${id}`),
    onSuccess: invalidate,
  })
  const clearMut = useMutation({
    mutationFn: () => api.delete(`/clients/${clientId}/maps/scans`),
    onSuccess: () => { invalidate(); queryClient.invalidateQueries({ queryKey: ['maps-latest', clientId] }) },
  })
  const [queued, setQueued] = useState<string | null>(null)
  const genMut = useMutation({
    mutationFn: (id: string) => api.post(`/clients/${clientId}/maps/report?scan_id=${id}`, {}),
    onSuccess: (_d, id) => setQueued(id),
  })
  const fmtScanDate = (s: MapsScanSummary) => {
    const iso = s.completed_at || s.requested_at
    return iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'
  }
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Link to={`/clients/${clientId}/maps/report`} style={{ ...outlineBtn, textDecoration: 'none' }}>
          <Printer size={14} /> Printable report
        </Link>
      </div>
      <TrendPanel trends={trends} />
      <CompetitorMomentum clientId={clientId} />
      {scans.length === 0 ? (
        <div style={card}><p style={muted}>No scans yet.</p></div>
      ) : (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
            <h2 style={{ ...sectionTitle, margin: 0 }}>Scan history</h2>
            <button
              style={{ ...outlineBtn, padding: '5px 9px', fontSize: 12, color: '#dc2626', borderColor: '#fecaca' }}
              onClick={() => { if (confirm('Delete all finished scans for this client? This removes their heatmaps and results and can’t be undone.')) clearMut.mutate() }}
              disabled={clearMut.isPending}
              title="Delete all finished scans (keeps any in-flight scan)"
            >
              <Trash2 size={13} /> {clearMut.isPending ? 'Clearing…' : 'Clear all'}
            </button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {scans.map((s, i) => {
              const inFlight = s.status === 'polling' || s.status === 'pending'
              const keywords = (s.search_terms ?? []).join(', ') || '—'
              const triggerLabel = s.trigger === 'scheduled' ? 'Scheduled' : 'One-off'
              const generating = genMut.isPending && genMut.variables === s.id
              return (
                <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 2px', borderTop: i ? '1px solid #f1f5f9' : 'none', flexWrap: 'wrap' }}>
                  <span style={{ ...statusDot(s.status), alignSelf: 'flex-start', marginTop: 5 }} />
                  <div style={{ flex: '1 1 200px', minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{keywords}</div>
                    <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 1 }}>
                      {fmtScanDate(s)} · {s.radius_miles}-mile · {triggerLabel}
                    </div>
                  </div>
                  <span style={{ fontSize: 12, color: '#64748b', minWidth: 70 }}>{cap(s.status)}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {s.status === 'complete' && (
                      <>
                        <button style={{ ...outlineBtn, padding: '4px 9px', fontSize: 12 }}
                          onClick={() => genMut.mutate(s.id)} disabled={generating} title="Generate the Local Rank Analysis report for this scan">
                          {generating ? 'Queuing…' : queued === s.id ? 'Report queued ✓' : 'Generate report'}
                        </button>
                        <Link to={`/clients/${clientId}/maps/report?scan_id=${s.id}`} target="_blank" rel="noreferrer"
                          style={{ ...outlineBtn, padding: '4px 9px', fontSize: 12, textDecoration: 'none' }} title="Open this scan's report">
                          Open ↗
                        </Link>
                      </>
                    )}
                    {inFlight ? (
                      <button style={{ ...outlineBtn, padding: '4px 7px', fontSize: 12, color: '#dc2626' }}
                        onClick={() => stopMut.mutate(s.id)} disabled={stopMut.isPending} title="Stop this scan">
                        <Square size={12} /> Stop
                      </button>
                    ) : (
                      <button style={{ ...outlineBtn, padding: '4px 7px', color: '#dc2626' }}
                        onClick={() => { if (confirm('Delete this scan and its results?')) delMut.mutate(s.id) }}
                        disabled={delMut.isPending} title="Delete this scan">
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {(stopMut.error || delMut.error || clearMut.error || genMut.error) && (
            <div style={{ ...errorBox, marginTop: 10 }}>{((stopMut.error || delMut.error || clearMut.error || genMut.error) as Error).message}</div>
          )}
        </div>
      )}
    </div>
  )
}

// Coverage/rank trend over time, one line per keyword, with a metric switch.
// Top-3 % and Top-10 % are the headline measures of local-pack visibility.
function TrendPanel({ trends }: { trends?: MapsTrendsResponse }) {
  const [metric, setMetric] = useState<TrendMetric>('top3_pct')
  const keywords = trends?.keywords ?? []
  const hasData = keywords.some(k => k.points.length > 0)

  // Export the full per-keyword, per-scan history (all metrics) — one row per
  // (keyword, scan), oldest → newest, for spreadsheets / client reporting.
  const exportCsv = () => {
    const headers = ['Date', 'Keyword', 'Total pins', 'Found pins', 'Found %',
      'Top 3 pins', 'Top 3 %', 'Top 10 pins', 'Top 10 %', 'Avg rank', 'Trigger']
    const rows = keywords.flatMap(k => k.points.map(p => [
      p.completed_at ? p.completed_at.slice(0, 10) : '',
      k.keyword, p.total_pins, p.found_pins, p.found_pct ?? '',
      p.top3_pins, p.top3_pct ?? '', p.top10_pins, p.top10_pct ?? '',
      p.average_rank ?? '', p.trigger,
    ] as (string | number | null)[]))
    downloadCsv(`maps-trends-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, rows))
  }

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <h2 style={{ ...sectionTitle, margin: 0 }}>Trend over time</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 3 }}>
            {TREND_METRICS.map(m => (
              <button key={m.key} onClick={() => setMetric(m.key)} style={{
                border: 'none', cursor: 'pointer', borderRadius: 6, padding: '5px 10px', fontSize: 12, fontWeight: 600,
                background: metric === m.key ? '#fff' : 'transparent', color: metric === m.key ? '#6366f1' : '#64748b',
                boxShadow: metric === m.key ? '0 1px 2px rgba(0,0,0,.08)' : 'none',
              }}>{m.label}</button>
            ))}
          </div>
          {hasData && (
            <button style={outlineBtn} onClick={exportCsv} title="Export the full trend history to CSV">
              <Download size={14} /> Export CSV
            </button>
          )}
        </div>
      </div>
      {!hasData ? (
        <p style={muted}>Run at least one scan to start building a trend. Each scan adds a point per keyword.</p>
      ) : (
        <TrendChart keywords={keywords} metric={TREND_METRICS.find(m => m.key === metric)!} />
      )}
    </div>
  )
}

// ── Competitor momentum (are they gaining on us?) ───────────────────────────
function CompetitorMomentum({ clientId }: { clientId: string }) {
  const { data } = useQuery<MapsCompetitorTrendsResponse>({
    queryKey: ['maps-competitor-trends', clientId],
    queryFn: () => api.get<MapsCompetitorTrendsResponse>(`/clients/${clientId}/maps/competitor-trends`),
  })
  const comps = data?.competitors ?? []
  const enough = (data?.scan_count ?? 0) >= 2 && comps.length > 0
  const th: React.CSSProperties = { padding: '6px 8px', textAlign: 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', borderBottom: '1px solid #e2e8f0' }
  const td: React.CSSProperties = { padding: '6px 8px', textAlign: 'right', fontSize: 13, color: '#334155' }

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <h2 style={{ ...sectionTitle, margin: '0 0 4px' }}>Competitor momentum</h2>
      <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 12px' }}>
        Who’s gaining on you — % of pins each competitor outranks you, over time. <span style={{ color: '#dc2626', fontWeight: 600 }}>▲ gaining</span> (more threat) · <span style={{ color: '#16a34a', fontWeight: 600 }}>▼ losing ground</span>.
      </p>
      {!enough ? (
        <p style={muted}>Need at least 2 scans with competitor data to show momentum — run another scan and check back.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={{ ...th, textAlign: 'left' }}>Competitor</th><th style={th}>Beats you now</th><th style={th}>Change</th><th style={th}>Trend</th>
          </tr></thead>
          <tbody>
            {comps.map(c => {
              const up = c.delta_pct != null && c.delta_pct > 0
              const down = c.delta_pct != null && c.delta_pct < 0
              const color = up ? '#dc2626' : down ? '#16a34a' : '#94a3b8'
              return (
                <tr key={c.place_id} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={{ ...td, textAlign: 'left' }}>{c.name ?? '—'}</td>
                  <td style={td}>{c.latest_pct != null ? `${Math.round(c.latest_pct)}%` : '—'}</td>
                  <td style={{ ...td, color, fontWeight: 600 }}>{c.delta_pct != null ? `${up ? '▲' : down ? '▼' : '–'} ${Math.abs(c.delta_pct)} pts` : '—'}</td>
                  <td style={{ ...td, width: 100 }}><PctSparkline values={c.points.map(p => p.beats_pct)} color={color} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

// Up-is-more sparkline (rising line = increasing threat), gaps for missing pts.
function PctSparkline({ values, color, width = 90, height = 24 }: { values: (number | null)[]; color: string; width?: number; height?: number }) {
  const present = values.filter((v): v is number => v != null)
  if (present.length < 2) return <svg width={width} height={height} />
  const min = Math.min(...present), max = Math.max(...present)
  const span = (max - min) || 1
  const pad = 2
  const dx = values.length > 1 ? width / (values.length - 1) : 0
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - pad * 2)  // higher % → top
  const pts = values.map((v, i) => (v == null ? null : `${i * dx},${y(v)}`)).filter(Boolean).join(' ')
  return (
    <svg width={width} height={height} role="img" aria-label="competitor pressure trend" style={{ display: 'block', marginLeft: 'auto' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

// ── What changed (scan-over-scan analyzer + alerts) ─────────────────────────
const ALERT_LABEL: Record<string, string> = {
  grid_rank_drop: 'Avg rank drop',
  coverage_drop: 'Coverage drop',
  lost_pack: 'Lost the pack',
  area_decline: 'Area decline',
  competitor_surge: 'Competitor surge',
}

function WhatChanged({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  // null = view the latest scan (default); otherwise a specific past scan.
  const [scanId, setScanId] = useState<string | null>(null)

  const { data: periods } = useQuery<MapsPeriodsResponse>({
    queryKey: ['maps-periods', clientId],
    queryFn: () => api.get<MapsPeriodsResponse>(`/clients/${clientId}/maps/periods`),
  })
  const { data: scans } = useQuery<MapsScanSummary[]>({
    queryKey: ['maps-scans', clientId],
    queryFn: () => api.get<MapsScanSummary[]>(`/clients/${clientId}/maps/scans`),
  })
  const { data: changes, isLoading } = useQuery<MapsChangesResponse>({
    queryKey: ['maps-changes', clientId, scanId ?? 'latest'],
    queryFn: () => api.get<MapsChangesResponse>(
      `/clients/${clientId}/maps/changes${scanId ? `?scan_id=${scanId}` : ''}`,
    ),
  })
  const { data: alerts } = useQuery<MapsAlertsResponse>({
    queryKey: ['maps-alerts', clientId],
    queryFn: () => api.get<MapsAlertsResponse>(`/clients/${clientId}/maps/alerts`),
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['maps-alerts', clientId] })
  const readMut = useMutation({ mutationFn: (id: string) => api.post(`/maps-alerts/${id}/read`, {}), onSuccess: invalidate })
  const dismissMut = useMutation({ mutationFn: (id: string) => api.post(`/maps-alerts/${id}/dismiss`, {}), onSuccess: invalidate })
  const readAllMut = useMutation({ mutationFn: () => api.post(`/clients/${clientId}/maps/alerts/read-all`, {}), onSuccess: invalidate })

  const openAlerts = (alerts?.alerts ?? []).filter(a => a.status !== 'dismissed')
  const completed = (scans ?? []).filter(s => s.status === 'complete')

  return (
    <div>
      <PeriodSummary periods={periods} />
      <AlertsPanel
        alerts={openAlerts}
        unread={alerts?.unread_count ?? 0}
        onRead={(id) => readMut.mutate(id)}
        onDismiss={(id) => dismissMut.mutate(id)}
        onReadAll={() => readAllMut.mutate()}
        busy={readMut.isPending || dismissMut.isPending || readAllMut.isPending}
      />
      <ChangeBrowser
        clientId={clientId}
        completed={completed}
        scanId={scanId}
        onSelect={setScanId}
        changes={changes}
        isLoading={isLoading}
      />
    </div>
  )
}

// Period summary: 7/30/90-day + since-start deltas for the visibility metrics,
// switchable between the overall client rollup and any single keyword.
function fmtMetric(metric: string, v: number | null): string {
  if (v == null) return '—'
  return metric.endsWith('_pct') ? `${Math.round(v)}%` : v.toFixed(1)
}

function DeltaCell({ metric, d }: { metric: string; d?: { delta: number | null } }) {
  if (!d || d.delta == null || d.delta === 0) return <span style={{ color: '#cbd5e1' }}>—</span>
  // Avg rank is lower-is-better; percentages are higher-is-better.
  const higherBetter = metric !== 'average_rank'
  const improved = higherBetter ? d.delta > 0 : d.delta < 0
  const color = improved ? '#16a34a' : '#dc2626'
  const mag = Math.abs(d.delta)
  const txt = metric.endsWith('_pct') ? `${Math.round(mag)} pts` : mag.toFixed(1)
  return <span style={{ color, fontWeight: 600 }}>{improved ? '▲' : '▼'} {txt}</span>
}

function PeriodSummary({ periods }: { periods?: MapsPeriodsResponse }) {
  const scopes: MapsPeriodScope[] = periods
    ? [...(periods.overall ? [periods.overall] : []), ...periods.keywords]
    : []
  const [sel, setSel] = useState<string>('__overall__')
  const current = scopes.find(s => (s.keyword ?? '__overall__') === sel) ?? scopes[0]

  const th: React.CSSProperties = { padding: '6px 8px', textAlign: 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', borderBottom: '1px solid #e2e8f0' }
  const td: React.CSSProperties = { padding: '7px 8px', textAlign: 'right', fontSize: 13, color: '#334155', borderTop: '1px solid #f1f5f9' }
  const WINDOWS: Array<[string, string]> = [['7d', '7 days'], ['30d', '30 days'], ['90d', '90 days'], ['start', 'Since start']]

  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 8 }}>
        <h2 style={{ ...sectionTitle, margin: 0 }}>Performance over time</h2>
        {current && (
          <select style={{ ...input, width: 'auto', padding: '6px 8px', fontSize: 13 }} value={sel} onChange={e => setSel(e.target.value)}>
            {periods?.overall && <option value="__overall__">Overall (all keywords)</option>}
            {(periods?.keywords ?? []).map(k => <option key={k.keyword} value={k.keyword!}>{k.keyword}</option>)}
          </select>
        )}
      </div>
      {!current ? (
        <p style={muted}>Run at least one scan to see period comparisons. With two or more scans, the 7/30/90-day and since-start columns fill in.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={{ ...th, textAlign: 'left' }}>Metric</th>
            <th style={th}>Now</th>
            {WINDOWS.map(([, label]) => <th key={label} style={th}>{label}</th>)}
          </tr></thead>
          <tbody>
            {current.metrics.map((m: MapsPeriodMetric) => (
              <tr key={m.metric}>
                <td style={{ ...td, textAlign: 'left', fontWeight: 600, color: '#0f172a' }}>{m.label}</td>
                <td style={{ ...td, fontWeight: 700 }}>{fmtMetric(m.metric, m.now)}</td>
                {WINDOWS.map(([wk]) => <td key={wk} style={td}><DeltaCell metric={m.metric} d={m.windows[wk]} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// Browse any past week's scan-over-scan change (default: latest).
function ChangeBrowser({ clientId, completed, scanId, onSelect, changes, isLoading }: {
  clientId: string; completed: MapsScanSummary[]; scanId: string | null
  onSelect: (id: string | null) => void; changes?: MapsChangesResponse; isLoading: boolean
}) {
  const fmt = (s: MapsScanSummary) => {
    const iso = s.completed_at || s.requested_at
    return iso ? new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'
  }
  // The scan whose report to link to (selected, or the latest completed).
  const viewing = scanId ?? completed[0]?.id ?? null
  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10, marginBottom: 4 }}>
        <h2 style={{ ...sectionTitle, margin: 0 }}>Week-over-week change</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {completed.length > 0 && (
            <select style={{ ...input, width: 'auto', padding: '6px 8px', fontSize: 13 }} value={scanId ?? ''} onChange={e => onSelect(e.target.value || null)}>
              <option value="">Latest scan</option>
              {completed.map(s => <option key={s.id} value={s.id}>{fmt(s)}</option>)}
            </select>
          )}
          {viewing && (
            <Link to={`/clients/${clientId}/maps/report?scan_id=${viewing}`} target="_blank" rel="noreferrer"
              style={{ ...outlineBtn, padding: '6px 10px', fontSize: 12, textDecoration: 'none' }}>
              <Printer size={13} /> Open report ↗
            </Link>
          )}
        </div>
      </div>
      {isLoading ? <p style={muted}>Loading…</p> : <ChangeTable changes={changes} />}
    </div>
  )
}

function AlertsPanel({ alerts, unread, onRead, onDismiss, onReadAll, busy }: {
  alerts: MapsAlert[]; unread: number; onRead: (id: string) => void; onDismiss: (id: string) => void; onReadAll: () => void; busy: boolean
}) {
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <h2 style={{ ...sectionTitle, margin: 0, display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <Bell size={14} color="#6366f1" /> Alerts {unread > 0 && <span style={{ color: '#dc2626' }}>({unread} new)</span>}
        </h2>
        {unread > 0 && (
          <button style={{ ...outlineBtn, padding: '5px 9px', fontSize: 12 }} onClick={onReadAll} disabled={busy}>
            <Check size={13} /> Mark all read
          </button>
        )}
      </div>
      {alerts.length === 0 ? (
        <p style={muted}>No active alerts. Declines detected between scans show up here (and in the client's notifications feed + Slack).</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {alerts.map((a, i) => {
            const critical = a.severity === 'critical'
            const unreadRow = a.status === 'unread'
            return (
              <div key={a.id} style={{
                display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 2px',
                borderTop: i ? '1px solid #f1f5f9' : 'none',
              }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, marginTop: 6, flexShrink: 0, background: critical ? '#dc2626' : '#d97706' }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.03em',
                      padding: '1px 7px', borderRadius: 10,
                      background: critical ? '#fee2e2' : '#fef3c7', color: critical ? '#b91c1c' : '#b45309',
                    }}>{ALERT_LABEL[a.alert_type] ?? a.alert_type}</span>
                    {unreadRow && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#6366f1' }}>NEW</span>}
                  </div>
                  <div style={{ fontSize: 13.5, color: '#334155', marginTop: 3 }}>{a.message}</div>
                  {a.triggered_on && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{a.triggered_on}</div>}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {unreadRow && (
                    <button style={{ ...outlineBtn, padding: '4px 7px', fontSize: 12 }} onClick={() => onRead(a.id)} disabled={busy} title="Mark read"><Check size={13} /></button>
                  )}
                  <button style={{ ...outlineBtn, padding: '4px 7px', fontSize: 12, color: '#dc2626' }} onClick={() => onDismiss(a.id)} disabled={busy} title="Dismiss"><X size={13} /></button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ChangeTable({ changes }: { changes?: MapsChangesResponse }) {
  if (!changes || !changes.current_scan_id) {
    return <p style={muted}>No completed scans yet. Run a scan to start tracking changes.</p>
  }
  if (!changes.has_previous) {
    return <p style={muted}>No earlier scan to compare against — this is the first one in range. The next scan will populate the comparison.</p>
  }
  const th: React.CSSProperties = { padding: '6px 8px', textAlign: 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', borderBottom: '1px solid #e2e8f0' }
  const td: React.CSSProperties = { padding: '7px 8px', textAlign: 'right', fontSize: 13, color: '#334155', borderTop: '1px solid #f1f5f9' }
  return (
    <div>
      <p style={{ fontSize: 12, color: '#64748b', margin: '2px 0 12px' }}>
        This scan vs the one before it. <span style={{ color: '#dc2626', fontWeight: 600 }}>▲ worse</span> · <span style={{ color: '#16a34a', fontWeight: 600 }}>▼ better</span>.
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          <th style={{ ...th, textAlign: 'left' }}>Keyword</th>
          <th style={th}>Avg rank</th>
          <th style={th}>Top-3 %</th>
          <th style={th}>Found %</th>
          <th style={{ ...th, textAlign: 'left' }}>Weakened areas</th>
          <th style={{ ...th, textAlign: 'left' }}>Alerts</th>
        </tr></thead>
        <tbody>
          {changes.keywords.map(k => <ChangeRow key={k.keyword} k={k} td={td} />)}
        </tbody>
      </table>
    </div>
  )
}

function ChangeRow({ k, td }: { k: MapsKeywordChange; td: React.CSSProperties }) {
  // Avg rank: lower is better, so a positive delta (now > prev) is worse.
  const d = k.average_rank_delta
  const worse = d != null && d > 0
  const better = d != null && d < 0
  const arrow = worse ? '▲' : better ? '▼' : ''
  const color = worse ? '#dc2626' : better ? '#16a34a' : '#94a3b8'
  const fmtPct = (now: number | null, prev: number | null) =>
    now == null ? '—' : <span>{Math.round(now)}%{prev != null && <span style={{ color: '#94a3b8' }}> (was {Math.round(prev)}%)</span>}</span>
  const octants = k.octants.map(o => o.sector).join(' · ')
  return (
    <tr>
      <td style={{ ...td, textAlign: 'left', fontWeight: 600, color: '#0f172a' }}>{k.keyword}</td>
      <td style={td}>
        {k.average_rank_now ?? '—'}
        {d != null && d !== 0 && (
          <span style={{ color, fontWeight: 600 }}> {arrow}{Math.abs(d)}</span>
        )}
      </td>
      <td style={td}>{fmtPct(k.top3_pct_now, k.top3_pct_prev)}</td>
      <td style={td}>{fmtPct(k.found_pct_now, k.found_pct_prev)}</td>
      <td style={{ ...td, textAlign: 'left', color: octants ? '#b45309' : '#94a3b8' }}>{octants || '—'}</td>
      <td style={{ ...td, textAlign: 'left' }}>
        {k.alert_types.length === 0 ? <span style={{ color: '#16a34a' }}>—</span> : (
          <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
            {k.alert_types.map(t => (
              <span key={t} style={{ fontSize: 10.5, fontWeight: 700, padding: '1px 6px', borderRadius: 10, background: t === 'lost_pack' ? '#fee2e2' : '#fef3c7', color: t === 'lost_pack' ? '#b91c1c' : '#b45309' }}>
                {ALERT_LABEL[t] ?? t}
              </span>
            ))}
          </span>
        )}
      </td>
    </tr>
  )
}

// ── helpers / styles ────────────────────────────────────────────────────────
function pct(n: number, d: number): string { return d ? `${Math.round((n / d) * 100)}%` : '—' }
function cap(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1) }
function statusDot(status: string): React.CSSProperties {
  const color = status === 'complete' ? '#16a34a'
    : status === 'failed' ? '#dc2626'
    : status === 'cancelled' ? '#94a3b8'
    : '#d97706'
  return { width: 8, height: 8, borderRadius: 999, background: color, flexShrink: 0 }
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10, flex: 1 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: '#475569' }}>{label}</span>
      {children}
    </label>
  )
}
function TabButton({ active, onClick, label, badge }: { active: boolean; onClick: () => void; label: string; badge?: number }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none', cursor: 'pointer', padding: '10px 14px', fontSize: 14, fontWeight: 600,
      color: active ? '#6366f1' : '#64748b', borderBottom: active ? '2px solid #6366f1' : '2px solid transparent', marginBottom: -1,
      display: 'inline-flex', alignItems: 'center', gap: 6,
    }}>
      {label}
      {badge ? (
        <span style={{ fontSize: 11, fontWeight: 700, color: '#fff', background: '#dc2626', borderRadius: 999, padding: '1px 7px', minWidth: 18, textAlign: 'center' }}>{badge}</span>
      ) : null}
    </button>
  )
}

const sectionTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: '#0f172a', margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }
const muted: React.CSSProperties = { fontSize: 13, color: '#94a3b8' }
const input: React.CSSProperties = { fontSize: 14, padding: '8px 10px', borderRadius: 6, border: '1px solid #cbd5e1', width: '100%', boxSizing: 'border-box' }
const scanningPill: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#92400e', background: '#fef3c7', borderRadius: 999, padding: '3px 10px' }
