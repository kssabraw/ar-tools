import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Map, Play, Trash2, MapPin, Download } from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type {
  Client, MapsConfig, MapsKeyword, MapsKeywordTrend, MapsRadius, MapsRunResponse, MapsScanDetail,
  MapsScanResultRow, MapsScanSummary, MapsTrendPoint, MapsTrendsResponse,
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
const MAP_SIZE = 480 // logical px of the square static map (requested at scale=2 for sharpness)

// Lat/lng of an in-circle grid cell: pins are spaced 1 mile, row 0 = north.
function cellLatLng(row: number, col: number, n: number, centerLat: number, centerLng: number) {
  const c = (n - 1) / 2
  const lat = centerLat + (c - row) * (1 / 69)
  const lng = centerLng + (col - c) * (1 / (69 * Math.cos((centerLat * Math.PI) / 180)))
  return { lat, lng }
}

// Largest integer Google zoom that fits the ~n-mile-wide grid into ~90% of the
// image (floored so edge pins never spill outside the map and get clipped).
function fitZoom(centerLat: number, n: number): number {
  const target = (n * 1609.34) / (MAP_SIZE * 0.9) // meters per logical px wanted
  const z = Math.log2((156543.03392 * Math.cos((centerLat * Math.PI) / 180)) / target)
  return Math.max(1, Math.min(16, Math.floor(z)))
}

// Web-Mercator projection of a lat/lng to a pixel within a MAP_SIZE square map
// centered on (centerLat, centerLng) at the given zoom.
function projectToPixel(lat: number, lng: number, centerLat: number, centerLng: number, zoom: number) {
  const worldSize = 256 * 2 ** zoom
  const px = (lo: number) => ((lo + 180) / 360) * worldSize
  const py = (la: number) => {
    const s = Math.max(-0.9999, Math.min(0.9999, Math.sin((la * Math.PI) / 180)))
    return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * worldSize
  }
  return { x: px(lng) - px(centerLng) + MAP_SIZE / 2, y: py(lat) - py(centerLat) + MAP_SIZE / 2 }
}

// The base (marker-less) Google Static Map centered on the scan, at a zoom that
// frames the grid. Null when no API key is configured (→ fall back to the
// dependency-free circular heatmap).
function buildBaseMapUrl(centerLat: number | null, centerLng: number | null, zoom: number): string | null {
  if (!GMAPS_KEY || centerLat == null || centerLng == null) return null
  return `https://maps.googleapis.com/maps/api/staticmap?center=${centerLat},${centerLng}&zoom=${zoom}` +
    `&size=${MAP_SIZE}x${MAP_SIZE}&scale=2&maptype=roadmap&key=${GMAPS_KEY}`
}

// One keyword's result: the business's Maps rank per pin shown as numbered,
// color-coded badges projected onto a Google Static Map at their real lat/lng
// (ranked pins show the rank number; not-ranked pins are small grey dots). Falls
// back to the dependency-free circular heatmap when no Maps key is configured.
function ResultView({ r, scan }: { r: MapsScanResultRow; scan: MapsScanDetail }) {
  const [imgError, setImgError] = useState(false)
  const grid = r.rank_grid
  const { center_lat: centerLat, center_lng: centerLng } = scan
  const n = grid && grid.length ? Math.max(...grid.map(row => row.length)) : 0
  const zoom = centerLat != null && n ? fitZoom(centerLat, n) : 12
  const mapUrl = n ? buildBaseMapUrl(centerLat, centerLng, zoom) : null

  // Project each in-circle pin onto the map and tag it with its rank.
  const pins: Array<{ x: number; y: number; rank: number | null; ranked: boolean }> = []
  if (mapUrl && grid && centerLat != null && centerLng != null) {
    const c = (n - 1) / 2
    const radiusSq = (n / 2) ** 2
    for (let row = 0; row < n; row++) {
      for (let col = 0; col < n; col++) {
        if ((row - c) ** 2 + (col - c) ** 2 > radiusSq) continue
        const { lat, lng } = cellLatLng(row, col, n, centerLat, centerLng)
        const { x, y } = projectToPixel(lat, lng, centerLat, centerLng, zoom)
        const cell = grid[row] && grid[row][col] != null ? grid[row][col] : null
        pins.push({ x, y, rank: cell, ranked: typeof cell === 'number' && cell >= 1 })
      }
    }
  }

  return (
    <div style={{ marginTop: 12 }}>
      {mapUrl && !imgError ? (
        <div style={{ position: 'relative', width: '100%', maxWidth: MAP_SIZE, aspectRatio: '1 / 1', borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
          <img src={mapUrl} alt={`Geo-grid map for ${r.keyword}`} onError={() => setImgError(true)}
            style={{ width: '100%', height: '100%', display: 'block' }} />
          {pins.map((p, i) => (
            <div key={i} title={p.ranked ? `Rank ${p.rank}` : 'Not ranked here'}
              style={{
                position: 'absolute', left: `${(p.x / MAP_SIZE) * 100}%`, top: `${(p.y / MAP_SIZE) * 100}%`,
                transform: 'translate(-50%, -50%)',
                width: p.ranked ? 22 : 12, height: p.ranked ? 22 : 12, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: rankColor(p.rank), color: '#fff', fontSize: 11, fontWeight: 700, lineHeight: 1,
                border: '1.5px solid #fff', boxShadow: '0 1px 2px rgba(0,0,0,.35)', boxSizing: 'border-box',
              }}>
              {p.ranked ? p.rank : ''}
            </div>
          ))}
        </div>
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

// ── History (trend over time + scan list) ───────────────────────────────────
function History({ clientId, scans }: { clientId: string; scans: MapsScanSummary[]; onOpen: () => void }) {
  const { data: trends } = useQuery<MapsTrendsResponse>({
    queryKey: ['maps-trends', clientId],
    queryFn: () => api.get<MapsTrendsResponse>(`/clients/${clientId}/maps/trends`),
  })
  return (
    <div>
      <TrendPanel trends={trends} />
      {scans.length === 0 ? (
        <div style={card}><p style={muted}>No scans yet.</p></div>
      ) : (
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
      )}
    </div>
  )
}

type TrendMetric = 'top3_pct' | 'top10_pct' | 'found_pct' | 'average_rank'
const TREND_METRICS: Array<{ key: TrendMetric; label: string; unit: string; lowerIsBetter: boolean; fixedMax?: number }> = [
  { key: 'top3_pct', label: 'Top 3 %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'top10_pct', label: 'Top 10 %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'found_pct', label: 'Found %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'average_rank', label: 'Avg rank', unit: '', lowerIsBetter: true },
]
const SERIES_COLORS = ['#6366f1', '#16a34a', '#ea580c', '#0ea5e9', '#db2777', '#ca8a04', '#7c3aed', '#0d9488']

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

function TrendChart({ keywords, metric }: { keywords: MapsKeywordTrend[]; metric: typeof TREND_METRICS[number] }) {
  const W = 600, H = 240, padL = 38, padR = 12, padT = 12, padB = 26
  const plotW = W - padL - padR, plotH = H - padT - padB

  const val = (p: MapsTrendPoint): number | null => p[metric.key] as number | null
  // X domain over all points' completed_at; fall back to index when timestamps tie.
  const times = keywords.flatMap(k => k.points.map(p => Date.parse(p.completed_at || '') || 0))
  const tMin = Math.min(...times), tMax = Math.max(...times)
  // Y domain: 0–100 for percentages; for avg rank, 1..max(observed) padded a little.
  const vals = keywords.flatMap(k => k.points.map(val).filter((v): v is number => v != null))
  const yLo = metric.lowerIsBetter ? 1 : 0
  const yHi = metric.fixedMax ?? Math.max(yLo + 1, Math.ceil((Math.max(...vals, yLo) + 1)))

  const x = (t: number) => padL + (tMax === tMin ? plotW / 2 : ((t - tMin) / (tMax - tMin)) * plotW)
  const y = (v: number) => {
    const frac = (v - yLo) / (yHi - yLo || 1)
    return padT + (metric.lowerIsBetter ? frac : 1 - frac) * plotH
  }
  const ticks = Array.from({ length: 5 }, (_, i) => yLo + ((yHi - yLo) * i) / 4)
  const fmt = (v: number | null) => (v == null ? '—' : `${metric.lowerIsBetter ? (Math.round(v * 10) / 10) : Math.round(v)}${metric.unit}`)

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, display: 'block' }} role="img" aria-label={`${metric.label} trend`}>
        {ticks.map((tk, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(tk)} y2={y(tk)} stroke="#eef2f7" strokeWidth={1} />
            <text x={padL - 6} y={y(tk) + 3} textAnchor="end" fontSize={9} fill="#94a3b8">{Math.round(tk)}{metric.unit}</text>
          </g>
        ))}
        {keywords.map((k, ki) => {
          const color = SERIES_COLORS[ki % SERIES_COLORS.length]
          const pts = k.points.filter(p => val(p) != null)
          const line = pts.map(p => `${x(Date.parse(p.completed_at || '') || 0)},${y(val(p) as number)}`).join(' ')
          return (
            <g key={k.keyword}>
              {pts.length > 1 && <polyline points={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
              {pts.map((p, i) => (
                <circle key={i} cx={x(Date.parse(p.completed_at || '') || 0)} cy={y(val(p) as number)} r={2.8} fill={color}>
                  <title>{`${k.keyword} · ${fmt(val(p))} · ${p.completed_at ? new Date(p.completed_at).toLocaleDateString() : ''}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 8 }}>
        {keywords.map((k, ki) => {
          const last = [...k.points].reverse().find(p => val(p) != null)
          return (
            <span key={k.keyword} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569' }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: SERIES_COLORS[ki % SERIES_COLORS.length] }} />
              {k.keyword}<strong style={{ color: '#0f172a' }}>{fmt(last ? val(last) : null)}</strong>
            </span>
          )
        })}
      </div>
      {metric.lowerIsBetter && <p style={{ ...muted, marginBottom: 0, marginTop: 8 }}>Lower is better — the line is drawn so up = improving.</p>}
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
