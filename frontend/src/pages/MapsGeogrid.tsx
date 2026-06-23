import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Map, Play, Trash2, MapPin } from 'lucide-react'
import { api } from '../lib/api'
import type {
  Client, MapsConfig, MapsKeyword, MapsRadius, MapsRunResponse, MapsScanDetail,
  MapsScanResultRow, MapsScanSummary,
} from '../lib/types'
import { backLink, card, errorBox, outlineBtn, primaryBtn, relativeTime } from '../components/localseo/shared'

type Tab = 'heatmap' | 'setup' | 'history'

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
  const [recentRunAt, setRecentRunAt] = useState<number | null>(null)

  const { data: scans } = useQuery<MapsScanSummary[]>({
    queryKey: ['maps-scans', clientId],
    queryFn: () => api.get<MapsScanSummary[]>(`/clients/${clientId}/maps/scans`),
    // Poll while a scan is running OR just after a run (to catch the new row).
    refetchInterval: (q) => {
      const inf = (q.state.data ?? []).some(s => s.status === 'polling' || s.status === 'pending')
      const recent = recentRunAt != null && Date.now() - recentRunAt < 90000
      return inf || recent ? 6000 : false
    },
  })

  const inFlight = (scans ?? []).some(s => s.status === 'polling' || s.status === 'pending')
  const scanning = inFlight || (recentRunAt != null && Date.now() - recentRunAt < 90000)

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
        <TabButton active={tab === 'setup'} onClick={() => setTab('setup')} label="Setup" />
        <TabButton active={tab === 'history'} onClick={() => setTab('history')} label="History" />
      </div>

      {tab === 'setup' ? (
        <Setup clientId={clientId} />
      ) : tab === 'history' ? (
        <History clientId={clientId} scans={scans ?? []} onOpen={() => setTab('heatmap')} />
      ) : (
        <Heatmap clientId={clientId} scanning={scanning} onRan={() => setRecentRunAt(Date.now())} />
      )}
    </div>
  )
}

// ── Heatmap (latest completed scan) ─────────────────────────────────────────
function Heatmap({ clientId, scanning, onRan }: { clientId: string; scanning: boolean; onRan: () => void }) {
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

  const runButton = (
    <button style={primaryBtn} onClick={() => runMut.mutate()} disabled={runMut.isPending}>
      <Play size={14} /> {runMut.isPending ? 'Starting…' : 'Run scan now'}
    </button>
  )

  if (isLoading) return <p style={muted}>Loading…</p>
  if (error || !latest) {
    return (
      <div>
        {scanning || runMut.isPending ? <InProgressBanner /> : (
          <div style={card}>
            <p style={{ ...muted, marginTop: 0 }}>
              No completed scans yet. Set the business location &amp; keywords in <strong>Setup</strong>, then run a scan.
            </p>
            {runMut.error && <div style={errorBox}>{(runMut.error as Error).message}</div>}
            {runMut.data?.status === 'failed' && (
              <div style={{ ...errorBox, marginTop: 10 }}>Couldn’t start: {runMut.data.error}. Check Setup is complete (Place ID, center lat/lng, and at least one keyword).</div>
            )}
            {runButton}
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <div style={{ fontSize: 13, color: '#64748b' }}>
          Last scan {latest.completed_at ? relativeTime(latest.completed_at) : ''} · {latest.radius_miles}-mile radius · {latest.grid_size}×{latest.grid_size} grid · {latest.resource_category === 'googleLocalFinder' ? 'Local Finder' : 'Google Maps'}
        </div>
        {runButton}
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
            <ResultView r={r} scan={latest} />
          </div>
        ))
      )}
      <Legend />
    </div>
  )
}

const GMAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined

// Static-map color band for a 1-based rank (0xRRGGBB for Google Static Maps).
function rankBucketColor(rank: number | null): string {
  if (rank == null || rank < 1) return '0x9ca3af'
  if (rank <= 3) return '0x16a34a'
  if (rank <= 7) return '0x65a30d'
  if (rank <= 10) return '0xca8a04'
  if (rank <= 15) return '0xea580c'
  return '0xdc2626'
}

// A Google Static Maps URL with one small color-coded pin per in-circle grid
// point at its real lat/lng (pins spaced 1 mile; row 0 = north). Null when no
// API key is configured (→ fall back to the dependency-free circular heatmap).
function buildStaticMapUrl(grid: Array<Array<number | null>> | null, centerLat: number | null, centerLng: number | null): string | null {
  if (!GMAPS_KEY || !grid || grid.length === 0 || centerLat == null || centerLng == null) return null
  const n = Math.max(...grid.map(r => r.length))
  const center = (n - 1) / 2
  const radiusSq = (n / 2) ** 2
  const degPerMileLng = 1 / (69 * Math.cos((centerLat * Math.PI) / 180))
  const buckets: Record<string, string[]> = {}
  for (let row = 0; row < n; row++) {
    for (let col = 0; col < n; col++) {
      if ((row - center) ** 2 + (col - center) ** 2 > radiusSq) continue
      const lat = centerLat + (center - row) * (1 / 69)   // row 0 = north
      const lng = centerLng + (col - center) * degPerMileLng
      const rank = grid[row] && grid[row][col] != null ? grid[row][col] : null
      const color = rankBucketColor(rank)
      ;(buckets[color] ||= []).push(`${lat.toFixed(6)},${lng.toFixed(6)}`)
    }
  }
  const markers = Object.entries(buckets).map(
    ([color, locs]) => `markers=${encodeURIComponent(`size:tiny|color:${color}|${locs.join('|')}`)}`,
  )
  if (markers.length === 0) return null
  return `https://maps.googleapis.com/maps/api/staticmap?size=480x480&scale=2&maptype=roadmap&${markers.join('&')}&key=${GMAPS_KEY}`
}

// One keyword's result: color-coded pins at their real lat/lng on a Google Static
// Map when a Maps API key is configured; otherwise a dependency-free circular pin
// heatmap. (Local Dominator's own image URL isn't embeddable outside their app.)
function ResultView({ r, scan }: { r: MapsScanResultRow; scan: MapsScanDetail }) {
  const [imgError, setImgError] = useState(false)
  const mapUrl = buildStaticMapUrl(r.rank_grid, scan.center_lat, scan.center_lng)
  return (
    <div style={{ marginTop: 12 }}>
      {mapUrl && !imgError ? (
        <img src={mapUrl} alt={`Geo-grid heatmap for ${r.keyword}`} onError={() => setImgError(true)}
          style={{ width: '100%', maxWidth: 480, borderRadius: 8, border: '1px solid #e2e8f0', display: 'block' }} />
      ) : (
        <CircleHeatmap grid={r.rank_grid} />
      )}
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
    </div>
  )
}

// Circular pin heatmap: small color-coded dots laid out in a circle (cells
// outside the scan circle are omitted so the shape reads as a circle).
function CircleHeatmap({ grid }: { grid: Array<Array<number | null>> | null }) {
  if (!grid || grid.length === 0) return <p style={muted}>No grid data.</p>
  const n = Math.max(...grid.map(r => r.length))
  const center = (n - 1) / 2
  const radiusSq = (n / 2) ** 2
  const inCircle = (r: number, c: number) => (r - center) ** 2 + (c - center) ** 2 <= radiusSq
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${n}, 1fr)`, gap: 3, maxWidth: n * 28 }}>
      {Array.from({ length: n }).flatMap((_, ri) =>
        Array.from({ length: n }).map((__, ci) => {
          if (!inCircle(ri, ci)) return <div key={`${ri}-${ci}`} />
          const cell = (grid[ri] && grid[ri][ci] != null) ? grid[ri][ci] : null
          const ranked = typeof cell === 'number' && cell >= 1
          return (
            <div key={`${ri}-${ci}`} title={ranked ? `Rank ${cell}` : 'Not ranked here'}
              style={{
                aspectRatio: '1', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 9, fontWeight: 700, background: rankColor(cell), color: ranked ? '#fff' : '#cbd5e1',
              }}>
              {ranked ? cell : ''}
            </div>
          )
        }),
      )}
    </div>
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

  const [form, setForm] = useState<Partial<MapsConfig>>({})
  useEffect(() => { if (config) setForm(config) }, [config])
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

// ── History ─────────────────────────────────────────────────────────────────
function History({ scans }: { clientId: string; scans: MapsScanSummary[]; onOpen: () => void }) {
  if (scans.length === 0) return <div style={card}><p style={muted}>No scans yet.</p></div>
  return (
    <div style={card}>
      <h2 style={sectionTitle}>Scan history</h2>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {scans.map((s, i) => (
          <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 2px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
            <span style={statusDot(s.status)} />
            <span style={{ flex: 1, fontSize: 14, color: '#0f172a' }}>
              {s.radius_miles}-mile · {s.grid_size}×{s.grid_size}
              <span style={{ color: '#94a3b8', marginLeft: 8, fontSize: 12 }}>{s.trigger}</span>
            </span>
            <span style={{ fontSize: 12, color: '#64748b' }}>{cap(s.status)}</span>
            <span style={{ fontSize: 12, color: '#94a3b8', minWidth: 90, textAlign: 'right' }}>
              {relativeTime(s.completed_at || s.requested_at || '')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── helpers / styles ────────────────────────────────────────────────────────
function rankColor(rank: number | null): string {
  if (rank == null || rank < 1) return '#e5e7eb'  // not ranked (-1 / 0 / null)
  if (rank <= 3) return '#16a34a'
  if (rank <= 7) return '#65a30d'
  if (rank <= 10) return '#ca8a04'
  if (rank <= 15) return '#ea580c'
  return '#dc2626'
}
function pct(n: number, d: number): string { return d ? `${Math.round((n / d) * 100)}%` : '—' }
function cap(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1) }
function statusDot(status: string): React.CSSProperties {
  const color = status === 'complete' ? '#16a34a' : status === 'failed' ? '#dc2626' : '#d97706'
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
function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} style={{
      background: 'none', border: 'none', cursor: 'pointer', padding: '10px 14px', fontSize: 14, fontWeight: 600,
      color: active ? '#6366f1' : '#64748b', borderBottom: active ? '2px solid #6366f1' : '2px solid transparent', marginBottom: -1,
    }}>{label}</button>
  )
}

const sectionTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: '#0f172a', margin: '0 0 8px', textTransform: 'uppercase', letterSpacing: '0.04em' }
const muted: React.CSSProperties = { fontSize: 13, color: '#94a3b8' }
const input: React.CSSProperties = { fontSize: 14, padding: '8px 10px', borderRadius: 6, border: '1px solid #cbd5e1', width: '100%', boxSizing: 'border-box' }
const scanningPill: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#92400e', background: '#fef3c7', borderRadius: 999, padding: '3px 10px' }
