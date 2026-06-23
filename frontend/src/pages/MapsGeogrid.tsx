import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Map, Play, Trash2, MapPin } from 'lucide-react'
import { api } from '../lib/api'
import type {
  Client, MapsConfig, MapsKeyword, MapsRadius, MapsRunResponse, MapsScanDetail, MapsScanSummary,
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
  const { data: scans } = useQuery<MapsScanSummary[]>({
    queryKey: ['maps-scans', clientId],
    queryFn: () => api.get<MapsScanSummary[]>(`/clients/${clientId}/maps/scans`),
    // Poll while a scan is in flight so the heatmap appears when it lands.
    refetchInterval: (q) => ((q.state.data ?? []).some(s => s.status === 'polling' || s.status === 'pending') ? 15000 : false),
  })

  const inFlight = (scans ?? []).some(s => s.status === 'polling' || s.status === 'pending')

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Map size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Maps Geo-Grid Ranker</h1>
        {inFlight && <span style={scanningPill}>Scanning…</span>}
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
        <Heatmap clientId={clientId} />
      )}
    </div>
  )
}

// ── Heatmap (latest completed scan) ─────────────────────────────────────────
function Heatmap({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const { data: latest, error, isLoading } = useQuery<MapsScanDetail>({
    queryKey: ['maps-latest', clientId],
    queryFn: () => api.get<MapsScanDetail>(`/clients/${clientId}/maps/latest`),
    retry: false,
  })
  const runMut = useMutation({
    mutationFn: () => api.post<MapsRunResponse>(`/clients/${clientId}/maps/scan`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['maps-scans', clientId] }),
  })

  const runButton = (
    <button style={primaryBtn} onClick={() => runMut.mutate()} disabled={runMut.isPending}>
      <Play size={14} /> {runMut.isPending ? 'Starting…' : 'Run scan now'}
    </button>
  )

  if (isLoading) return <p style={muted}>Loading…</p>
  if (error || !latest) {
    return (
      <div style={card}>
        <p style={{ ...muted, marginTop: 0 }}>
          No completed scans yet. Set the business location &amp; keywords in <strong>Setup</strong>, then run a scan.
        </p>
        {runMut.error && <div style={errorBox}>{(runMut.error as Error).message}</div>}
        {runButton}
        {runMut.data?.status === 'failed' && (
          <div style={{ ...errorBox, marginTop: 10 }}>Couldn’t start: {runMut.data.error}. Check Setup is complete.</div>
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
      {runMut.data?.status === 'enqueued' && <div style={{ ...okBox, marginBottom: 12 }}>New scan started — results will appear here when it finishes.</div>}

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
            <div style={{ marginTop: 12 }}><Grid grid={r.rank_grid} /></div>
          </div>
        ))
      )}
      <Legend />
    </div>
  )
}

function Grid({ grid }: { grid: Array<Array<number | null>> | null }) {
  if (!grid || grid.length === 0) return <p style={muted}>No grid data.</p>
  const cols = Math.max(...grid.map(r => r.length))
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 3, maxWidth: cols * 30 }}>
      {grid.flatMap((row, ri) =>
        row.map((cell, ci) => (
          <div key={`${ri}-${ci}`} title={cell == null ? 'Not in top 20' : `Rank ${cell}`}
            style={{
              aspectRatio: '1', display: 'flex', alignItems: 'center', justifyContent: 'center',
              borderRadius: 4, fontSize: 11, fontWeight: 700,
              background: rankColor(cell), color: cell == null ? '#9ca3af' : '#fff',
            }}>
            {cell == null ? '·' : cell}
          </div>
        )),
      )}
    </div>
  )
}

function Legend() {
  const items: Array<[string, string]> = [
    ['1–3', rankColor(2)], ['4–7', rankColor(5)], ['8–10', rankColor(9)],
    ['11–15', rankColor(13)], ['16–20', rankColor(18)], ['20+', rankColor(null)],
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
      shape: form.shape ?? 'square',
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
          <Field label="Shape">
            <select style={input} value={form.shape ?? 'square'} onChange={e => set({ shape: e.target.value as 'square' | 'circle' })}>
              <option value="square">Square</option>
              <option value="circle">Circle</option>
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
  if (rank == null) return '#e5e7eb'
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
const okBox: React.CSSProperties = { fontSize: 13, color: '#166534', background: '#dcfce7', borderRadius: 6, padding: '8px 12px' }
