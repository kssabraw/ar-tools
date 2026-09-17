import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, HelpCircle, Link2, Check, X, Trash2, ExternalLink, AlertTriangle,
  FileText, Download, RefreshCw, ShieldCheck, FileSpreadsheet,
  Radar, Search, Layers, Play, RotateCcw,
} from 'lucide-react'
import { api } from '../lib/api'
import { supabase } from '../lib/supabase'
import type {
  Client, PaaSet, PaaCandidate, PaaPullResponse, PaaPreflight, PaaItem, PaaGate,
  PaaManifest, PaaManifestAsset, PaaCampaignView, PaaDrillPreview,
} from '../lib/types'

const API_BASE = import.meta.env.VITE_PLATFORM_API_URL as string

// The export endpoint returns raw CSV / JSON (not the api client's parsed JSON),
// so fetch it directly with the auth header and save it as a file.
async function downloadManifest(manifestId: string, fmt: 'csv' | 'json') {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  const res = await fetch(`${API_BASE}/paa-manifests/${manifestId}/export?format=${fmt}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error('Export failed')
  const blob = fmt === 'csv'
    ? await res.blob()
    : new Blob([JSON.stringify(await res.json(), null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `paa-prep-sheet.${fmt}`
  a.click()
  URL.revokeObjectURL(url)
}

// The three PAA writing rules + the cannibalization discipline, tagged with the
// methodology's own confidence markers (PRD §9 — surface, never present as
// settled Google guidance).
const RULES: { text: string; tag: string }[] = [
  { text: 'One question → one post (never blend two PAAs into one page).', tag: 'PROVEN' },
  { text: 'Exact-match everywhere — the exact question is the post title AND an H2, and seeds the GBP post.', tag: 'BELIEF' },
  { text: 'Link HIGH to the service page (the money page) from the first section — not the homepage.', tag: 'BELIEF' },
]

const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', padding: 18,
}
const label: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: '#334155', display: 'block', marginBottom: 6 }
const input: React.CSSProperties = {
  width: '100%', padding: '9px 11px', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 14, boxSizing: 'border-box',
}
const btn: React.CSSProperties = {
  padding: '9px 16px', borderRadius: 8, border: 'none', background: '#0ea5e9', color: '#fff',
  fontSize: 14, fontWeight: 600, cursor: 'pointer',
}
const btnGhost: React.CSSProperties = { ...btn, background: '#f1f5f9', color: '#0f172a' }
const tagStyle = (t: string): React.CSSProperties => ({
  fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 4, marginLeft: 6,
  background: t === 'PROVEN' ? '#dcfce7' : '#fef9c3', color: t === 'PROVEN' ? '#166534' : '#854d0e',
})

export function PaaSets() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  // ── new-set builder state ──
  const [service, setService] = useState('')
  const [geoMode, setGeoMode] = useState<'geo' | 'naked'>('geo')
  const [locationOverride, setLocationOverride] = useState('')
  const [pull, setPull] = useState<PaaPullResponse | null>(null)
  const [pulling, setPulling] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [servicePageUrl, setServicePageUrl] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // ── set-detail / create state ──
  const [openSetId, setOpenSetId] = useState<string | null>(null)
  const [preflight, setPreflight] = useState<PaaPreflight | null>(null)
  const [busy, setBusy] = useState(false)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id], queryFn: () => api.get<Client>(`/clients/${id}`), enabled: Boolean(id),
  })
  const { data: setsData } = useQuery<{ sets: PaaSet[] }>({
    queryKey: ['paa-sets', id], queryFn: () => api.get(`/clients/${id}/paa-sets`), enabled: Boolean(id),
  })
  const { data: openSet } = useQuery<PaaSet>({
    queryKey: ['paa-set', openSetId], queryFn: () => api.get(`/paa-sets/${openSetId}`), enabled: Boolean(openSetId),
  })

  const sets = setsData?.sets ?? []

  async function runPull() {
    setError(''); setPull(null); setSelected(new Set()); setServicePageUrl(''); setPulling(true)
    try {
      const r = await api.post<PaaPullResponse>(`/clients/${id}/paa-sets/pull`, {
        service_keyword: service, geo_mode: geoMode, location: locationOverride || null,
      })
      setPull(r)
      setServicePageUrl(r.auto_service_page_url ?? '')
      // Preselect the top ~4 by volume (the methodology's ~4-per-service default).
      const top = [...r.candidates]
        .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0)).slice(0, 4)
        .map((c) => c.question)
      setSelected(new Set(top))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PAA pull failed')
    } finally { setPulling(false) }
  }

  function toggle(q: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(q)) next.delete(q); else next.add(q)
      return next
    })
  }

  async function saveSet() {
    if (!pull) return
    setSaving(true); setError('')
    try {
      const items = pull.candidates.filter((c) => selected.has(c.question))
      const created = await api.post<PaaSet>(`/clients/${id}/paa-sets`, {
        service_keyword: pull.service_keyword,
        items,
        geo_mode: pull.geo_mode,
        location: pull.location || null,
        location_code: pull.location_code,
        service_page_url: servicePageUrl || null,
        auto_service_page_url: pull.auto_service_page_url,
      })
      setPull(null); setSelected(new Set()); setService('')
      await queryClient.invalidateQueries({ queryKey: ['paa-sets', id] })
      setOpenSetId(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save set')
    } finally { setSaving(false) }
  }

  async function openCreate(setId: string, acknowledge: boolean) {
    setBusy(true); setError('')
    try {
      const pf = await api.get<PaaPreflight>(`/paa-sets/${setId}/preflight?acknowledge=${acknowledge}`)
      const blocking = pf.gates.filter((g) => g.blocking)
      if (blocking.length && !acknowledge) { setPreflight(pf); return }
      const res = await api.post<{ blocked: boolean; created: number; gbp_created: number; gates?: PaaPreflight['gates'] }>(
        `/paa-sets/${setId}/create-posts`, { acknowledge })
      if (res.blocked) { setPreflight({ ...pf, gates: res.gates ?? pf.gates }); return }
      setPreflight(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['paa-set', setId] }),
        queryClient.invalidateQueries({ queryKey: ['paa-sets', id] }),
      ])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create posts')
    } finally { setBusy(false) }
  }

  async function verify(setId: string) {
    setBusy(true); setError('')
    try {
      await api.post(`/paa-sets/${setId}/verify`, {})
      await queryClient.invalidateQueries({ queryKey: ['paa-set', setId] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Verify failed')
    } finally { setBusy(false) }
  }

  async function del(setId: string) {
    if (!confirm('Delete this PAA set? (Created posts/runs are not deleted.)')) return
    await api.delete(`/paa-sets/${setId}`)
    if (openSetId === setId) setOpenSetId(null)
    await queryClient.invalidateQueries({ queryKey: ['paa-sets', id] })
  }

  const selectedCount = selected.size

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '24px 16px' }}>
      <Link to={id ? `/clients/${id}` : '/'} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none' }}>
        <ArrowLeft size={14} /> Back to workspace
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <HelpCircle size={22} color="#0ea5e9" />
        <h1 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>PAA Content</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 6 }}>
        Answer the exact questions buyers ask about one service in one place — one page per question, linking high to the
        service page. {client?.name ? `Client: ${client.name}.` : ''}
      </p>

      {/* the three rules (confidence-tagged) */}
      <div style={{ ...card, background: '#f8fafc', marginTop: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 6 }}>How PAA posts are written</div>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#475569', lineHeight: 1.7 }}>
          {RULES.map((r) => (
            <li key={r.text}>{r.text}<span style={tagStyle(r.tag)}>{r.tag}</span></li>
          ))}
        </ul>
        <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 6 }}>
          These are one local-SEO group's working model, not confirmed Google guidance — strong defaults, surfaced with
          their confidence tags, not laws.
        </div>
      </div>

      {error && (
        <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#b91c1c', fontSize: 13 }}>{error}</div>
      )}

      {/* ── new set builder ── */}
      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12 }}>New PAA set</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 160px 1fr', gap: 12 }}>
          <div>
            <label style={label}>Service keyword</label>
            <input style={input} placeholder="e.g. metal roof repair" value={service}
              onChange={(e) => setService(e.target.value)} />
          </div>
          <div>
            <label style={label}>Query mode</label>
            <select style={input} value={geoMode} onChange={(e) => setGeoMode(e.target.value as 'geo' | 'naked')}>
              <option value="geo">Geo-modified</option>
              <option value="naked">Naked (no city)</option>
            </select>
          </div>
          <div>
            <label style={label}>Location (optional — defaults to client)</label>
            <input style={input} placeholder={client?.business_location || 'City'} value={locationOverride}
              onChange={(e) => setLocationOverride(e.target.value)} />
          </div>
        </div>
        <button style={{ ...btn, marginTop: 12, opacity: service.trim() && !pulling ? 1 : 0.6 }}
          disabled={!service.trim() || pulling} onClick={runPull}>
          {pulling ? 'Pulling…' : 'Pull PAA questions'}
        </button>

        {pull && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>
              {pull.candidates.length === 0
                ? `No People-Also-Ask questions returned for "${pull.geo_query}". Try a different service or query mode.`
                : <>Searched <code>{pull.geo_query}</code> — pick the buyer questions to build (≈4). Selected: <strong>{selectedCount}</strong></>}
            </div>
            {pull.candidates.map((c: PaaCandidate) => {
              const on = selected.has(c.question)
              return (
                <label key={c.question} style={{
                  display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', marginBottom: 6,
                  border: `1px solid ${on ? '#0ea5e9' : '#e2e8f0'}`, borderRadius: 8,
                  background: on ? '#f0f9ff' : '#fff', cursor: 'pointer',
                }}>
                  <input type="checkbox" checked={on} onChange={() => toggle(c.question)} />
                  <span style={{ flex: 1, fontSize: 14 }}>{c.question}</span>
                  <span style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>
                    {c.volume != null ? `${c.volume.toLocaleString()} vol` : '— vol'}
                    {c.competition ? ` · ${c.competition.toLowerCase()}` : ''}
                  </span>
                </label>
              )
            })}

            {pull.candidates.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <label style={label}>
                  <Link2 size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
                  Service page URL (the "link high" target)
                </label>
                <input style={input} placeholder="https://client.com/metal-roof-repair/" value={servicePageUrl}
                  onChange={(e) => setServicePageUrl(e.target.value)} />
                <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>
                  {pull.auto_service_page_url
                    ? 'Auto-matched from the client’s live site — edit if it’s not the money page.'
                    : 'No live page auto-matched — paste the service page so each post can link high to it.'}
                </div>
                <button style={{ ...btn, marginTop: 12, opacity: selectedCount && !saving ? 1 : 0.6 }}
                  disabled={!selectedCount || saving} onClick={saveSet}>
                  {saving ? 'Saving…' : `Save set (${selectedCount})`}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── saved sets ── */}
      <div style={{ marginTop: 24 }}>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 10 }}>Saved PAA sets</div>
        {sets.length === 0 && <div style={{ color: '#94a3b8', fontSize: 14 }}>No PAA sets yet.</div>}
        {sets.map((s) => (
          <div key={s.id} style={{ ...card, marginBottom: 10, padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button onClick={() => setOpenSetId(openSetId === s.id ? null : s.id)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', flex: 1, textAlign: 'left', padding: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{s.service_keyword}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {s.geo_mode === 'geo' ? (s.location || 'geo') : 'naked'} · {s.chosen_count ?? 0} questions · {s.post_count ?? 0} posts · {s.status}
                </div>
              </button>
              <button style={{ ...btnGhost, padding: '6px 10px' }} onClick={() => del(s.id)} title="Delete set">
                <Trash2 size={14} />
              </button>
            </div>

            {openSetId === s.id && openSet && (
              <div style={{ marginTop: 12, borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
                {openSet.service_page_url && (
                  <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
                    Links high to <a href={openSet.service_page_url} target="_blank" rel="noreferrer" style={{ color: '#0ea5e9' }}>{openSet.service_page_url}</a>
                  </div>
                )}
                {(openSet.items ?? []).map((it: PaaItem) => (
                  <div key={it.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: '1px solid #f8fafc' }}>
                    <span style={{ flex: 1, fontSize: 13.5 }}>{it.question}</span>
                    {it.run_id
                      ? <Link to={`/runs/${it.run_id}`} style={{ fontSize: 12, color: '#0ea5e9', display: 'inline-flex', alignItems: 'center', gap: 3 }}>run <ExternalLink size={11} /></Link>
                      : <span style={{ fontSize: 12, color: '#cbd5e1' }}>no post</span>}
                    {it.checks && <CheckBadges checks={it.checks} />}
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button style={{ ...btn, opacity: busy ? 0.6 : 1 }} disabled={busy}
                    onClick={() => openCreate(s.id, false)}>Create PAA posts</button>
                  <button style={{ ...btnGhost, opacity: busy ? 0.6 : 1 }} disabled={busy}
                    onClick={() => verify(s.id)}>Verify posts</button>
                </div>

                <CampaignPanel setId={s.id} />

                <PrepSheet setId={s.id} />

                {preflight && preflight.gates.some((g) => g.blocking) && (
                  <div style={{ marginTop: 12, padding: 12, border: '1px solid #fed7aa', background: '#fff7ed', borderRadius: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: 13, color: '#9a3412' }}>
                      <AlertTriangle size={15} /> Cannibalization check
                    </div>
                    <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 13, color: '#7c2d12' }}>
                      {preflight.gates.filter((g) => g.blocking).map((g) => <li key={g.kind}>{g.message}</li>)}
                    </ul>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      {preflight.gates.filter((g) => g.blocking).every((g) => g.acknowledgeable) ? (
                        <button style={{ ...btn, background: '#ea580c' }} disabled={busy}
                          onClick={() => openCreate(s.id, true)}>Acknowledge &amp; create anyway</button>
                      ) : (
                        <span style={{ fontSize: 12.5, color: '#9a3412' }}>Reduce the batch or split it — this limit can’t be overridden.</span>
                      )}
                      <button style={btnGhost} onClick={() => setPreflight(null)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function CheckBadges({ checks }: { checks: NonNullable<PaaItem['checks']> }) {
  const em = checks.exact_match
  const sl = checks.service_link
  const pill = (ok: boolean | null | undefined, text: string) => (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '1px 6px', borderRadius: 5, display: 'inline-flex', alignItems: 'center', gap: 3,
      background: ok == null ? '#f1f5f9' : ok ? '#dcfce7' : '#fee2e2',
      color: ok == null ? '#64748b' : ok ? '#166534' : '#b91c1c',
    }}>
      {ok == null ? null : ok ? <Check size={11} /> : <X size={11} />}{text}
    </span>
  )
  return (
    <span style={{ display: 'inline-flex', gap: 4 }}>
      {em && pill(em.ok, `exact-match${em.match === 'contains' ? '*' : ''}`)}
      {sl && pill(sl.ok, sl.ok == null ? 'no link target' : 'links high')}
    </span>
  )
}

// ── Phase 2 — the prep-sheet manifest (track / cost / QA / hand-off) ──────────

const CATEGORY_ORDER: PaaManifestAsset['category'][] = [
  'paa_post', 'gbp_post', 'syndication', 'image', 'authority', 'media',
]
const CATEGORY_LABELS: Record<string, string> = {
  paa_post: 'PAA posts', gbp_post: 'GBP posts', syndication: 'Syndication copies',
  image: 'Hosted images',
  authority: 'Authority layer — tracked, NEVER executed by the suite',
  media: 'Audio / video / influencer — manual, never generated',
}
const AUTHORITY_STATUSES = ['planned', 'handed_off', 'done']

function verdictStyle(v: string | null | undefined): React.CSSProperties {
  const red = v === 'fail' || v === 'needs_human'
  const amber = v === 'revisions' || v === 'minor_revisions' || v === 'major_revisions' || v === 'advisory'
  const green = v === 'pass'
  return {
    fontSize: 11, fontWeight: 600, padding: '1px 6px', borderRadius: 5,
    background: red ? '#fee2e2' : amber ? '#fef9c3' : green ? '#dcfce7' : '#f1f5f9',
    color: red ? '#b91c1c' : amber ? '#854d0e' : green ? '#166534' : '#64748b',
  }
}

function PrepSheet({ setId }: { setId: string }) {
  const qc = useQueryClient()
  const { data: m, refetch, isFetching } = useQuery<PaaManifest>({
    queryKey: ['paa-manifest', setId],
    queryFn: () => api.get(`/paa-sets/${setId}/manifest`),
    enabled: Boolean(setId),
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')

  async function run(fn: () => Promise<void>) {
    setBusy(true); setErr(''); setNote('')
    try { await fn() } catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(false) }
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ['paa-manifest', setId] })

  const build = () => run(async () => {
    await api.post(`/paa-sets/${setId}/manifest/build`, {})
    await invalidate()
  })

  const runQa = (manifestId: string) => run(async () => {
    await api.post(`/paa-manifests/${manifestId}/qa`, {})
    setNote('QA started — reviewing the live content URLs. Refresh in ~1 minute.')
    // Best-effort auto-refresh a couple of times; the Refresh button covers the rest.
    setTimeout(invalidate, 20000)
    setTimeout(invalidate, 50000)
  })

  const exportSheet = (manifestId: string) => run(async () => {
    const r = await api.post<{ sheet_url: string | null }>(
      `/paa-manifests/${manifestId}/export/sheet`, {})
    setNote(r.sheet_url ? `Exported to Google Sheet: ${r.sheet_url}` : 'Exported to Drive.')
    await invalidate()
  })

  const editStatus = (assetId: string, status: string) => run(async () => {
    await api.patch(`/paa-manifest-assets/${assetId}`, { status })
    await invalidate()
  })

  if (!m) return null

  const box: React.CSSProperties = {
    marginTop: 14, borderTop: '1px solid #f1f5f9', paddingTop: 14,
  }
  const header = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <FileText size={16} color="#7c3aed" />
      <span style={{ fontWeight: 700, fontSize: 14 }}>Prep Sheet</span>
      <span style={{ fontSize: 11.5, color: '#94a3b8' }}>
        the hand-off manifest — track / cost / QA the campaign's assets, export for the link operator
      </span>
    </div>
  )

  if (!m.exists) {
    return (
      <div style={box}>
        {header}
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>
          Auto-collect every asset URL this campaign has produced (PAA posts, GBP posts, syndication),
          seed the standard authority bundle as tracked rows, cost it, and export a prep sheet.
        </div>
        <button style={{ ...btn, background: '#7c3aed', opacity: busy ? 0.6 : 1 }} disabled={busy}
          onClick={build}>{busy ? 'Building…' : 'Build prep sheet'}</button>
        {err && <div style={{ color: '#b91c1c', fontSize: 12.5, marginTop: 6 }}>{err}</div>}
      </div>
    )
  }

  const manifest = m.manifest!
  const assets = m.assets ?? []
  const cost = m.cost_summary
  const qa = m.qa_summary
  const grouped = CATEGORY_ORDER
    .map((cat) => ({ cat, rows: assets.filter((a) => a.category === cat) }))
    .filter((g) => g.rows.length > 0)

  return (
    <div style={box}>
      {header}

      {/* action bar */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        <span style={{ ...verdictStyle(null), background: '#ede9fe', color: '#6d28d9' }}>{manifest.status}</span>
        <button style={{ ...btnGhost, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy || isFetching} onClick={build} title="Refresh auto-collected assets">
          <RefreshCw size={13} /> Rebuild
        </button>
        <button style={{ ...btnGhost, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy} onClick={() => refetch()}>Refresh</button>
        <button style={{ ...btn, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy} onClick={() => runQa(manifest.id)} title="QA the content the authority layer will amplify">
          <ShieldCheck size={13} /> Run QA
        </button>
        <span style={{ flex: 1 }} />
        <button style={{ ...btnGhost, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy} onClick={() => run(() => downloadManifest(manifest.id, 'csv'))}>
          <Download size={13} /> CSV
        </button>
        <button style={{ ...btnGhost, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy} onClick={() => run(() => downloadManifest(manifest.id, 'json'))}>
          <Download size={13} /> JSON
        </button>
        <button style={{ ...btnGhost, padding: '6px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
          disabled={busy} onClick={() => exportSheet(manifest.id)} title="Export to a Google Sheet in the client's Drive">
          <FileSpreadsheet size={13} /> Sheet
        </button>
      </div>

      {/* cost + QA summary */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, fontSize: 12.5, color: '#475569', marginBottom: 10 }}>
        <span>
          <strong>Authority cost (est.):</strong>{' '}
          {cost?.estimated_total != null ? `$${cost.estimated_total.toFixed(2)}` : 'not estimated'}
          {cost?.not_estimated?.length ? ` · ${cost.not_estimated.length} not estimated (incl. off-menu RD 100)` : ''}
        </span>
        <span>
          <strong>Content QA:</strong>{' '}
          {qa ? <>{qa.reviewed}/{qa.content_assets} reviewed · {qa.pending} pending{qa.worst ? <> · worst <span style={verdictStyle(qa.worst)}>{qa.worst}</span></> : ''}</> : '—'}
        </span>
      </div>

      {manifest.sheet_url && (
        <div style={{ fontSize: 12, marginBottom: 8 }}>
          Last export: <a href={manifest.sheet_url} target="_blank" rel="noreferrer" style={{ color: '#7c3aed' }}>Google Sheet</a>
        </div>
      )}
      {note && <div style={{ fontSize: 12, color: '#166534', marginBottom: 8 }}>{note}</div>}
      {err && <div style={{ color: '#b91c1c', fontSize: 12.5, marginBottom: 8 }}>{err}</div>}

      {/* asset table grouped by category */}
      {grouped.map(({ cat, rows }) => (
        <div key={cat} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, color: cat === 'authority' || cat === 'media' ? '#9a3412' : '#475569', marginBottom: 4 }}>
            {CATEGORY_LABELS[cat] || cat}
          </div>
          {rows.map((a) => {
            const authorityLike = a.category === 'authority' || a.category === 'media'
            return (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid #f8fafc' }}>
                <span style={{ flex: 1, fontSize: 13 }}>
                  {a.label}
                  {a.confidence_tag && <span style={tagStyle(a.confidence_tag)}>{a.confidence_tag}</span>}
                </span>
                {a.url && (
                  <a href={a.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#0ea5e9', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                    open <ExternalLink size={11} />
                  </a>
                )}
                {a.qa_verdict && <span style={verdictStyle(a.qa_verdict)}>{a.qa_verdict}</span>}
                {authorityLike ? (
                  <select value={a.status} disabled={busy}
                    onChange={(e) => editStatus(a.id, e.target.value)}
                    style={{ fontSize: 11.5, padding: '2px 4px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
                    {AUTHORITY_STATUSES.map((st) => <option key={st} value={st}>{st}</option>)}
                  </select>
                ) : (
                  <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{a.status}</span>
                )}
              </div>
            )
          })}
        </div>
      ))}

      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
        Authority-layer items are off-platform vendor work — tracked here, <strong>never executed by the suite</strong>.
        Confidence tags are the methodology's own working model, not Google guidance.
      </div>
    </div>
  )
}

// ── Phase 3 — the Service PAA Campaign + the automated single-variable gate ───

const STATE_LABELS: Record<string, string> = {
  draft: 'Draft', content: 'Writing posts', settling: 'Settling',
  scan_ready: 'Ready to scan', scanning: 'Scanning', evaluating: 'Reading the gate',
  moved: 'Moved', drill_ready: 'Drill deeper?', halted: 'Halted', maintenance: 'Maintenance',
}
function stateStyle(state: string): React.CSSProperties {
  const good = state === 'moved' || state === 'maintenance'
  const warn = state === 'drill_ready'
  const bad = state === 'halted'
  return {
    fontSize: 11.5, fontWeight: 700, padding: '2px 8px', borderRadius: 6,
    background: bad ? '#fee2e2' : warn ? '#fef9c3' : good ? '#dcfce7' : '#e0e7ff',
    color: bad ? '#b91c1c' : warn ? '#854d0e' : good ? '#166534' : '#3730a3',
  }
}
function whenText(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString()
}

function CampaignPanel({ setId }: { setId: string }) {
  const qc = useQueryClient()
  const { data: c, refetch, isFetching } = useQuery<PaaCampaignView>({
    queryKey: ['paa-campaign', setId],
    queryFn: () => api.get(`/paa-sets/${setId}/campaign`),
    enabled: Boolean(setId),
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const [drill, setDrill] = useState<PaaDrillPreview | null>(null)
  const [picked, setPicked] = useState<Record<string, boolean>>({})

  async function run(fn: () => Promise<void>) {
    setBusy(true); setErr(''); setNote('')
    try { await fn() } catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
    finally { setBusy(false) }
  }
  const invalidate = () => qc.invalidateQueries({ queryKey: ['paa-campaign', setId] })

  // Feature off → render nothing (keeps the set detail clean when Phase 3 is dark).
  if (!c || c.enabled === false) return null

  const box: React.CSSProperties = { marginTop: 14, borderTop: '1px solid #f1f5f9', paddingTop: 14 }
  const header = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <Radar size={16} color="#4f46e5" />
      <span style={{ fontWeight: 700, fontSize: 14 }}>Campaign</span>
      <span style={{ fontSize: 11.5, color: '#94a3b8' }}>
        the single-variable loop — content → settle → scan → moved / drill / HALT → rinse
      </span>
    </div>
  )

  if (!c.exists) {
    return (
      <div style={box}>
        {header}
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>
          Run this set as a campaign: create the PAA posts, let them settle ~1 week, then
          measure with a single-variable Maps scan and read the gate. The paid scan + any drill
          round are confirmed by you (never auto-run).
        </div>
        <button style={{ ...btn, background: '#4f46e5', display: 'inline-flex', alignItems: 'center', gap: 6, opacity: busy ? 0.6 : 1 }}
          disabled={busy}
          onClick={() => run(async () => {
            const created = await api.post<PaaCampaignView>(`/paa-sets/${setId}/campaign`, {})
            const started = await api.post<{ blocked: boolean; created?: number; gates?: PaaGate[] }>(
              `/paa-campaigns/${created.campaign!.id}/start`, {})
            setNote(started.blocked
              ? 'Cannibalization sign-off needed — use the set’s Create PAA posts button to review it first.'
              : `Campaign started — ${started.created ?? 0} PAA post(s) writing.`)
            await invalidate()
          })}>
          <Play size={13} /> {busy ? 'Starting…' : 'Start campaign'}
        </button>
        {note && <div style={{ fontSize: 12, color: '#166534', marginTop: 6 }}>{note}</div>}
        {err && <div style={{ color: '#b91c1c', fontSize: 12.5, marginTop: 6 }}>{err}</div>}
      </div>
    )
  }

  const camp = c.campaign!
  const na = c.next_action
  const cid = camp.id

  const confirmScan = () => run(async () => { await api.post(`/paa-campaigns/${cid}/confirm-scan`, {}); await invalidate() })
  const reset = () => run(async () => { await api.post(`/paa-campaigns/${cid}/reset`, {}); await invalidate() })
  const openDrill = () => run(async () => {
    const p = await api.get<PaaDrillPreview>(`/paa-campaigns/${cid}/drill-preview`)
    setDrill(p); setPicked(Object.fromEntries((p.candidates ?? []).slice(0, 4).map((x) => [x.question, true])))
  })
  const confirmDrill = () => run(async () => {
    const items = (drill?.candidates ?? []).filter((x) => picked[x.question])
    const res = await api.post<{ blocked: boolean; gates?: PaaGate[] }>(`/paa-campaigns/${cid}/drill`, { items })
    setDrill(null)
    setNote(res.blocked ? 'Cannibalization sign-off needed before drilling.' : 'Drill round started.')
    await invalidate()
  })

  return (
    <div style={box}>
      {header}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 8 }}>
        <span style={stateStyle(camp.state)}>{STATE_LABELS[camp.state] || camp.state}</span>
        {camp.drill_level > 0 && <span style={{ fontSize: 11.5, color: '#64748b' }}>drill level {camp.drill_level}</span>}
        {(camp.baseline_rank != null || camp.current_rank != null) && (
          <span style={{ fontSize: 12, color: '#475569' }}>
            avg rank {camp.baseline_rank ?? '—'} → {camp.current_rank ?? '—'}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button style={{ ...btnGhost, padding: '5px 9px' }} disabled={busy || isFetching} onClick={() => refetch()}>Refresh</button>
      </div>

      {na && (
        <div style={{ fontSize: 13, color: '#334155', marginBottom: 8 }}>
          <strong>Next:</strong> {na.label}
          {na.when && <span style={{ color: '#94a3b8' }}> — {whenText(na.when)}</span>}
        </div>
      )}

      {/* the two human-confirmed steps (hybrid propose-confirm) */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {na?.action === 'confirm_scan' && (
          <button style={{ ...btn, background: '#4f46e5', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            disabled={busy} onClick={confirmScan}><Search size={13} /> Run single-variable scan</button>
        )}
        {na?.action === 'confirm_drill' && !drill && (
          <button style={{ ...btn, background: '#ca8a04', display: 'inline-flex', alignItems: 'center', gap: 6 }}
            disabled={busy} onClick={openDrill}><Layers size={13} /> Drill deeper — pull sub-PAAs</button>
        )}
        {camp.state === 'halted' && (
          <button style={{ ...btnGhost, display: 'inline-flex', alignItems: 'center', gap: 6 }}
            disabled={busy} onClick={reset}><RotateCcw size={13} /> Reset (on-page/entity re-checked)</button>
        )}
      </div>

      {camp.state === 'halted' && camp.halted_reason && (
        <div style={{ marginTop: 8, padding: 10, border: '1px solid #fecaca', background: '#fef2f2', borderRadius: 8, fontSize: 12.5, color: '#991b1b' }}>
          <strong>HALT.</strong> {camp.halted_reason} <em style={{ color: '#b91c1c' }}>[PROVEN model — one local-SEO group’s working model, not Google guidance]</em>
        </div>
      )}

      {/* drill preview — pick the sub-PAAs to add + create posts for */}
      {drill && (
        <div style={{ marginTop: 10, padding: 12, border: '1px solid #fde68a', background: '#fffbeb', borderRadius: 8 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: '#854d0e', marginBottom: 6 }}>
            Sub-PAAs for drill level {drill.drill_level} (from: {drill.seeds.join(', ') || '—'})
          </div>
          {(drill.candidates ?? []).length === 0 && (
            <div style={{ fontSize: 12.5, color: '#92400e' }}>No sub-questions found — the topic may be exhausted; consider HALT and an on-page/entity re-check.</div>
          )}
          {(drill.candidates ?? []).map((x) => (
            <label key={x.question} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', fontSize: 13 }}>
              <input type="checkbox" checked={Boolean(picked[x.question])}
                onChange={(e) => setPicked((p) => ({ ...p, [x.question]: e.target.checked }))} />
              <span style={{ flex: 1 }}>{x.question}</span>
              {x.volume != null && <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{x.volume}/mo</span>}
            </label>
          ))}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button style={{ ...btn, background: '#ca8a04', opacity: busy ? 0.6 : 1 }} disabled={busy || !Object.values(picked).some(Boolean)}
              onClick={confirmDrill}>Add {Object.values(picked).filter(Boolean).length} &amp; create posts</button>
            <button style={{ ...btnGhost }} disabled={busy} onClick={() => setDrill(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* timeline */}
      {(camp.history ?? []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 3 }}>Timeline</div>
          {[...camp.history].slice(-6).reverse().map((h, i) => (
            <div key={i} style={{ fontSize: 11.5, color: '#64748b' }}>
              {whenText(h.at)} · {h.from} → {h.to}{h.note ? ` — ${h.note}` : ''}
            </div>
          ))}
        </div>
      )}

      {note && <div style={{ fontSize: 12, color: '#166534', marginTop: 8 }}>{note}</div>}
      {err && <div style={{ color: '#b91c1c', fontSize: 12.5, marginTop: 8 }}>{err}</div>}
    </div>
  )
}

export default PaaSets
