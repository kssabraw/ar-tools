import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sparkles, Trash2, RotateCcw, Upload, Eye, ExternalLink } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { Spinner } from '../components/localseo/Spinner'
import { backLink, card, errorBox, input, label, outlineBtn, primaryBtn } from '../components/localseo/shared'

// ── types (mirror the backend models) ────────────────────────────────────────
type FieldSpec = {
  name: string; type: 'text' | 'textarea' | 'wysiwyg'; section: string
  focus: string; min_words: number; max_words: number; guidance?: string
  is_link?: boolean; default?: string
}
type Section = { section: string; fields: FieldSpec[] }
type Warning = { field: string; issue: 'short' | 'long' | 'empty'; words: number; min_words: number; max_words: number }
type Page = {
  id: string; page_type?: 'city' | 'service'; state: string; city: string; service: string; title: string
  slug_path: string; acf: Record<string, string>; field_sources: Record<string, string>
  validation_warnings: Warning[]; status: 'draft' | 'published'; wp_status?: string | null
  wp_page_id?: number | null; published_url?: string | null; edit_link?: string | null
  generation_failed?: boolean
}
type JobStatus = { job_id: string; status: string; page_id?: string | null; error?: string | null }
type Tab = 'mass' | 'oneoff' | 'saved' | 'drafts'

const wrap = { maxWidth: 1000, margin: '0 auto', padding: '24px 20px 80px' }
const tabBtn = (active: boolean) => ({
  ...outlineBtn, borderRadius: 999, padding: '7px 16px',
  background: active ? '#6366f1' : '#fff', color: active ? '#fff' : '#0f172a',
  borderColor: active ? '#6366f1' : '#e2e8f0',
})

export function Wheelhouse() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('mass')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })
  const { data: fieldData } = useQuery<{ sections: Section[] }>({
    queryKey: ['wheelhouse-fields', clientId],
    queryFn: () => api.get(`/clients/${clientId}/wheelhouse/fields`),
    enabled: Boolean(clientId),
  })
  const { data: pagesData, isLoading: loadingPages } = useQuery<{ pages: Page[] }>({
    queryKey: ['wheelhouse-pages', clientId],
    queryFn: () => api.get(`/clients/${clientId}/wheelhouse/pages`),
    enabled: Boolean(clientId),
  })
  const { data: draftsData } = useQuery<{ pages: Page[] }>({
    queryKey: ['wheelhouse-drafts', clientId],
    queryFn: () => api.get(`/clients/${clientId}/wheelhouse/pages?deleted=true`),
    enabled: Boolean(clientId),
  })

  const sections = fieldData?.sections ?? []
  const pages = pagesData?.pages ?? []
  const drafts = draftsData?.pages ?? []
  const [openPageId, setOpenPageId] = useState<string | null>(null)
  const openPage = pages.find((p) => p.id === openPageId) ?? null

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['wheelhouse-pages', clientId] })
    qc.invalidateQueries({ queryKey: ['wheelhouse-drafts', clientId] })
  }

  const wpConfigured = Boolean(client?.wordpress_site_url && client?.wordpress_username && client?.wordpress_app_password_set)

  return (
    <div style={wrap}>
      <Link to={`/clients/${clientId}`} style={{ ...backLink, textDecoration: 'none' }}>
        <ArrowLeft size={14} /> Back to workspace
      </Link>
      <h1 style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', margin: '4px 0 2px' }}>Wheelhouse Pages</h1>
      <p style={{ color: '#64748b', fontSize: 14, margin: '0 0 16px' }}>
        Local SEO pages published to WordPress as ACF-driven Pages — city pages
        (/florida/miami/) and the service pages nested beneath them.
      </p>

      {!wpConfigured && (
        <div style={{ ...errorBox, marginBottom: 16, background: '#fffbeb', borderColor: '#fde68a', color: '#92400e' }}>
          WordPress isn't connected for this client yet. Set the site URL, username, and application password on the
          client's Setup page before publishing. You can still generate and save drafts.
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        <button style={tabBtn(tab === 'mass')} onClick={() => { setTab('mass'); setOpenPageId(null) }}>Mass Create</button>
        <button style={tabBtn(tab === 'oneoff')} onClick={() => { setTab('oneoff'); setOpenPageId(null) }}>One-Off</button>
        <button style={tabBtn(tab === 'saved')} onClick={() => { setTab('saved'); setOpenPageId(null) }}>Saved ({pages.length})</button>
        <button style={tabBtn(tab === 'drafts')} onClick={() => { setTab('drafts'); setOpenPageId(null) }}>Drafts ({drafts.length})</button>
      </div>

      {openPage ? (
        <PageDetail clientId={clientId} page={openPage} sections={sections} wpConfigured={wpConfigured}
          onClose={() => setOpenPageId(null)} onChange={refresh} />
      ) : tab === 'mass' ? (
        <MassCreate clientId={clientId} onDone={refresh} />
      ) : tab === 'oneoff' ? (
        <OneOff clientId={clientId} sections={sections} onSaved={(pid) => { refresh(); setTab('saved'); setOpenPageId(pid) }} />
      ) : tab === 'saved' ? (
        <PageList pages={pages} loading={loadingPages} onOpen={setOpenPageId} emptyLabel="No pages yet — generate some from Mass Create or One-Off." />
      ) : (
        <DraftsList clientId={clientId} drafts={drafts} onChange={refresh} />
      )}
    </div>
  )
}

// ── page-type toggle (shared) ────────────────────────────────────────────────
type PageType = 'city' | 'service'
function PageTypeToggle({ value, onChange }: { value: PageType; onChange: (v: PageType) => void }) {
  const opt = (v: PageType, text: string) => (
    <button style={{ ...outlineBtn, borderRadius: 8, padding: '7px 14px',
      background: value === v ? '#6366f1' : '#fff', color: value === v ? '#fff' : '#0f172a',
      borderColor: value === v ? '#6366f1' : '#e2e8f0' }} onClick={() => onChange(v)}>{text}</button>
  )
  return (
    <div>
      <label style={label}>Page type</label>
      <div style={{ display: 'flex', gap: 8 }}>{opt('city', 'City pages')}{opt('service', 'Service pages')}</div>
    </div>
  )
}

// ── Mass Create ──────────────────────────────────────────────────────────────
function MassCreate({ clientId, onDone }: { clientId: string; onDone: () => void }) {
  const [pageType, setPageType] = useState<PageType>('city')
  const [state, setState] = useState('')
  const [city, setCity] = useState('')
  const [citiesText, setCitiesText] = useState('Miami\nFort Lauderdale\nBoca Raton\nWest Palm Beach')
  const [servicesText, setServicesText] = useState('Managed IT\nCo-Managed IT\nCybersecurity\nIT Consulting')
  const [jobIds, setJobIds] = useState<string[]>([])
  const [jobs, setJobs] = useState<JobStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const isCity = pageType === 'city'
  const items = (isCity ? citiesText : servicesText).split('\n').map((s) => s.trim()).filter(Boolean)
  const combos = isCity
    ? items.map((c) => `${c} IT Support Company`)
    : (city && items.length ? items.map((s) => `${s} in ${city}`) : [])
  const ready = Boolean(state) && items.length > 0 && (isCity || Boolean(city))

  useEffect(() => () => { if (timer.current) clearInterval(timer.current) }, [])

  const poll = (ids: string[]) => {
    if (timer.current) clearInterval(timer.current)
    timer.current = setInterval(async () => {
      try {
        const res = await api.post<{ jobs: JobStatus[] }>(`/clients/${clientId}/wheelhouse/jobs/status`, { job_ids: ids })
        setJobs(res.jobs)
        // Done when every job we can still see is terminal. A deleted job simply
        // drops out of the response (so a missing row can't wedge the poll), while
        // in-flight jobs are always present as non-terminal.
        const done = res.jobs.length > 0 && res.jobs.every((j) => ['complete', 'failed', 'cancelled'].includes(j.status))
        if (done) { if (timer.current) clearInterval(timer.current); onDone() }
      } catch { /* keep polling */ }
    }, 3000)
  }

  const submit = async () => {
    setError(null); setSubmitting(true); setJobs([])
    try {
      const res = await api.post<{ job_ids: string[] }>(
        `/clients/${clientId}/wheelhouse/generate-mass`,
        { page_type: pageType, state, city: isCity ? '' : city, items })
      setJobIds(res.job_ids); poll(res.job_ids)
    } catch (e) { setError(e instanceof Error ? e.message : 'Failed to start') } finally { setSubmitting(false) }
  }

  const doneCount = jobs.filter((j) => j.status === 'complete').length

  return (
    <div style={card}>
      <div style={{ display: 'grid', gap: 14 }}>
        <PageTypeToggle value={pageType} onChange={setPageType} />
        <div style={{ display: 'grid', gridTemplateColumns: isCity ? '1fr' : '1fr 1fr', gap: 12 }}>
          <div><label style={label}>State</label><input style={input} value={state} onChange={(e) => setState(e.target.value)} placeholder="Florida" /></div>
          {!isCity && <div><label style={label}>City</label><input style={input} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Miami" /></div>}
        </div>
        {isCity ? (
          <div>
            <label style={label}>Cities (one per line)</label>
            <textarea style={{ ...input, minHeight: 110, fontFamily: 'inherit' }} value={citiesText} onChange={(e) => setCitiesText(e.target.value)} />
          </div>
        ) : (
          <div>
            <label style={label}>Services (one per line)</label>
            <textarea style={{ ...input, minHeight: 110, fontFamily: 'inherit' }} value={servicesText} onChange={(e) => setServicesText(e.target.value)} />
          </div>
        )}
        {combos.length > 0 && (
          <div style={{ fontSize: 13, color: '#475569' }}>
            Will create <strong>{combos.length}</strong> {isCity ? 'city' : 'service'} page{combos.length === 1 ? '' : 's'}: {combos.join(' · ')}
          </div>
        )}
        {error && <div style={errorBox}>{error}</div>}
        <div>
          <button style={{ ...primaryBtn, opacity: submitting || !ready ? 0.6 : 1 }}
            disabled={submitting || !ready} onClick={submit}>
            <Sparkles size={16} /> {submitting ? 'Starting…' : `Generate ${combos.length || ''} page${combos.length === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>

      {jobIds.length > 0 && (
        <div style={{ marginTop: 20, borderTop: '1px solid #e2e8f0', paddingTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
            Generating {doneCount}/{jobIds.length} — you can leave this page; jobs finish in the background.
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {jobs.map((j) => (
              <div key={j.job_id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <StatusDot status={j.status} />
                <span style={{ color: '#475569' }}>{j.status}{j.error ? ` — ${j.error}` : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusDot({ status }: { status: string }) {
  const color = status === 'complete' ? '#16a34a' : status === 'failed' ? '#dc2626' : status === 'cancelled' ? '#94a3b8' : '#f59e0b'
  if (!['complete', 'failed', 'cancelled'].includes(status)) return <Spinner />
  return <span style={{ width: 9, height: 9, borderRadius: 999, background: color, display: 'inline-block' }} />
}

// ── One-Off ──────────────────────────────────────────────────────────────────
function OneOff({ clientId, sections, onSaved }: { clientId: string; sections: Section[]; onSaved: (id: string) => void }) {
  const [pageType, setPageType] = useState<PageType>('city')
  const [state, setState] = useState('')
  const [city, setCity] = useState('')
  const [service, setService] = useState('')
  const [acf, setAcf] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isCity = pageType === 'city'
  const hasLocation = Boolean(state && city && (isCity || service))
  const body = () => ({ page_type: pageType, state, city, service: isCity ? '' : service })

  const setField = (name: string, value: string) => setAcf((a) => ({ ...a, [name]: value }))

  const generateAll = async () => {
    setBusy('all'); setError(null)
    try {
      const supplied = Object.fromEntries(Object.entries(acf).filter(([, v]) => v && v.trim()))
      // persist:false → live preview, no Saved row until the user clicks Save.
      const res = await api.post<{ acf: Record<string, string>; generation_failed?: boolean }>(
        `/clients/${clientId}/wheelhouse/generate-one`, { ...body(), supplied, persist: false })
      setAcf(res.acf)
      if (res.generation_failed) setError('The AI writer returned nothing (it may be temporarily unavailable). Try again, or fill fields manually.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Generation failed') } finally { setBusy(null) }
  }
  const draftField = async (name: string) => {
    setBusy(name); setError(null)
    try {
      const res = await api.post<{ value: string }>(`/clients/${clientId}/wheelhouse/draft-field`, { ...body(), field_name: name })
      if (res.value) setField(name, res.value)
    } catch (e) { setError(e instanceof Error ? e.message : 'Draft failed') } finally { setBusy(null) }
  }
  const save = async () => {
    setBusy('save'); setError(null)
    try {
      const page = await api.post<Page>(`/clients/${clientId}/wheelhouse/one-off`, { ...body(), acf })
      onSaved(page.id)
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed') } finally { setBusy(null) }
  }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={card}>
        <div style={{ marginBottom: 12 }}><PageTypeToggle value={pageType} onChange={setPageType} /></div>
        <div style={{ display: 'grid', gridTemplateColumns: isCity ? '1fr 1fr' : '1fr 1fr 1fr', gap: 12 }}>
          <div><label style={label}>State</label><input style={input} value={state} onChange={(e) => setState(e.target.value)} placeholder="Florida" /></div>
          <div><label style={label}>City</label><input style={input} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Miami" /></div>
          {!isCity && <div><label style={label}>Service</label><input style={input} value={service} onChange={(e) => setService(e.target.value)} placeholder="Managed IT" /></div>}
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
          <button style={{ ...outlineBtn, opacity: hasLocation && !busy ? 1 : 0.6 }} disabled={!hasLocation || Boolean(busy)} onClick={generateAll}>
            {busy === 'all' ? <Spinner /> : <Sparkles size={15} />} Draft all fields with AI
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Fills empty fields; keeps anything you've typed.</span>
        </div>
        {error && <div style={{ ...errorBox, marginTop: 12 }}>{error}</div>}
      </div>

      <FieldGrid sections={sections} acf={acf} onField={setField} onDraft={draftField} busyField={busy} canDraft={hasLocation} />

      <div style={{ display: 'flex', gap: 10 }}>
        <button style={{ ...primaryBtn, opacity: hasLocation && !busy ? 1 : 0.6 }} disabled={!hasLocation || Boolean(busy)} onClick={save}>
          {busy === 'save' ? <Spinner /> : null} Save draft
        </button>
      </div>
    </div>
  )
}

// ── shared field editor ──────────────────────────────────────────────────────
function FieldGrid({ sections, acf, onField, onDraft, busyField, canDraft }: {
  sections: Section[]; acf: Record<string, string>; onField: (n: string, v: string) => void
  onDraft?: (n: string) => void; busyField?: string | null; canDraft?: boolean
}) {
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {sections.map((sec) => (
        <div key={sec.section} style={card}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>{sec.section}</div>
          <div style={{ display: 'grid', gap: 14 }}>
            {sec.fields.map((f) => (
              <div key={f.name}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <label style={label}>
                    {f.name}
                    <span style={{ fontWeight: 400, color: '#94a3b8', marginLeft: 8, fontSize: 11 }}>
                      {f.type} · {f.min_words}–{f.max_words}w · {f.focus}{f.is_link ? ' · fixed nav' : ''}
                    </span>
                  </label>
                  {onDraft && !f.is_link && (
                    <button style={{ ...outlineBtn, padding: '3px 9px', fontSize: 11, opacity: canDraft && busyField !== f.name ? 1 : 0.5 }}
                      disabled={!canDraft || Boolean(busyField)} onClick={() => onDraft(f.name)}>
                      {busyField === f.name ? <Spinner /> : <Sparkles size={12} />} Draft
                    </button>
                  )}
                </div>
                {f.type === 'text' ? (
                  <input style={input} value={acf[f.name] ?? ''} onChange={(e) => onField(f.name, e.target.value)} placeholder={f.default ?? ''} />
                ) : (
                  <textarea style={{ ...input, minHeight: f.type === 'wysiwyg' ? 90 : 60, fontFamily: 'inherit' }}
                    value={acf[f.name] ?? ''} onChange={(e) => onField(f.name, e.target.value)}
                    placeholder={f.type === 'wysiwyg' ? '<p>…</p> HTML' : ''} />
                )}
                {f.guidance && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{f.guidance}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── saved list ───────────────────────────────────────────────────────────────
function PageList({ pages, loading, onOpen, emptyLabel }: {
  pages: Page[]; loading?: boolean; onOpen: (id: string) => void; emptyLabel: string
}) {
  if (loading) return <div style={card}><Spinner /> Loading…</div>
  if (!pages.length) return <div style={{ ...card, color: '#64748b' }}>{emptyLabel}</div>
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {pages.map((p) => (
        <button key={p.id} style={{ ...card, textAlign: 'left', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }} onClick={() => onOpen(p.id)}>
          <div>
            <div style={{ fontWeight: 600, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 8 }}>
              <TypeBadge page={p} />{p.title || (p.page_type === 'city' ? `${p.city} IT Support Company` : `${p.service} · ${p.city}`)}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{p.slug_path}</div>
          </div>
          <StatusPill page={p} />
        </button>
      ))}
    </div>
  )
}

function TypeBadge({ page }: { page: Page }) {
  const city = page.page_type === 'city'
  return <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase',
    background: city ? '#e0e7ff' : '#f1f5f9', color: city ? '#3730a3' : '#475569',
    borderRadius: 5, padding: '2px 6px' }}>{city ? 'City' : 'Service'}</span>
}

function StatusPill({ page }: { page: Page }) {
  const published = page.status === 'published'
  const wpPublished = page.wp_status === 'publish'
  const modified = !published && Boolean(page.wp_page_id)  // posted to WP, then edited
  let bg = '#f1f5f9', fg = '#475569', text = 'Not posted'
  if (published) {
    bg = wpPublished ? '#dcfce7' : '#e0e7ff'
    fg = wpPublished ? '#166534' : '#3730a3'
    text = wpPublished ? 'Published' : 'On WP (draft)'
  } else if (modified) {
    bg = '#fef3c7'; fg = '#92400e'; text = 'Modified — needs republish'
  }
  return <span style={{ background: bg, color: fg, fontSize: 12, fontWeight: 600, borderRadius: 999, padding: '4px 10px' }}>{text}</span>
}

// ── drafts (soft-deleted) ────────────────────────────────────────────────────
function DraftsList({ clientId, drafts, onChange }: { clientId: string; drafts: Page[]; onChange: () => void }) {
  const restore = async (pid: string) => { await api.post(`/clients/${clientId}/wheelhouse/pages/${pid}/restore`, {}); onChange() }
  const purge = async (pid: string) => { await api.delete(`/clients/${clientId}/wheelhouse/pages/${pid}/permanent`); onChange() }
  if (!drafts.length) return <div style={{ ...card, color: '#64748b' }}>No deleted drafts.</div>
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {drafts.map((p) => (
        <div key={p.id} style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 600, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 8 }}>
              <TypeBadge page={p} />{p.title || (p.page_type === 'city' ? `${p.city} IT Support Company` : `${p.service} · ${p.city}`)}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8' }}>{p.slug_path}</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={{ ...outlineBtn, padding: '6px 12px' }} onClick={() => restore(p.id)}><RotateCcw size={13} /> Restore</button>
            <button style={{ ...outlineBtn, padding: '6px 12px', color: '#b91c1c', borderColor: '#fecaca' }} onClick={() => purge(p.id)}><Trash2 size={13} /> Delete</button>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── page detail (edit + publish + dry-run + report) ──────────────────────────
function PageDetail({ clientId, page, sections, wpConfigured, onClose, onChange }: {
  clientId: string; page: Page; sections: Section[]; wpConfigured: boolean; onClose: () => void; onChange: () => void
}) {
  const [acf, setAcf] = useState<Record<string, string>>(page.acf)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dryRun, setDryRun] = useState<unknown | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const dirty = useMemo(() => JSON.stringify(acf) !== JSON.stringify(page.acf), [acf, page.acf])

  const setField = (name: string, value: string) => setAcf((a) => ({ ...a, [name]: value }))
  const saveBody = () => ({ page_type: page.page_type ?? 'service', state: page.state, city: page.city, service: page.service, acf })

  const saveEdits = async () => {
    setBusy('save'); setError(null); setMsg(null)
    try {
      await api.post(`/clients/${clientId}/wheelhouse/one-off`, saveBody())
      setMsg('Saved.'); onChange()
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed') } finally { setBusy(null) }
  }
  const publish = async (status: 'draft' | 'publish') => {
    setBusy(status); setError(null); setMsg(null)
    try {
      if (dirty) await api.post(`/clients/${clientId}/wheelhouse/one-off`, saveBody())
      const res = await api.post<{ link?: string; slug_path: string; acf_written?: boolean; hubs_promoted?: boolean; city_page_unpublished?: boolean }>(
        `/clients/${clientId}/wheelhouse/pages/${page.id}/publish`, { status })
      if (res.acf_written === false) {
        setError(`Page posted to ${res.slug_path}, but WordPress ignored the ACF fields — the field group isn't exposed to REST / assigned to Pages. Check the ACF prerequisites, then republish.`)
      } else if (res.city_page_unpublished) {
        const cityPath = res.slug_path.replace(/[^/]+\/$/, '')  // strip the service segment
        setMsg(`Published (${status}) → ${res.slug_path}. Note: the parent city page ${cityPath} isn't published yet, so it renders empty until you publish the City page for ${page.city}.`)
      } else {
        setMsg(`Published (${status}) → ${res.slug_path}${res.hubs_promoted ? ' (parent pages promoted to live)' : ''}`)
      }
      onChange()
    } catch (e) { setError(e instanceof Error ? e.message : 'Publish failed') } finally { setBusy(null) }
  }
  const doDryRun = async () => {
    setBusy('dry'); setError(null); setDryRun(null)
    try {
      if (dirty) await api.post(`/clients/${clientId}/wheelhouse/one-off`, saveBody())
      const res = await api.post(`/clients/${clientId}/wheelhouse/pages/${page.id}/dry-run`, { status: 'draft' })
      setDryRun(res)
    } catch (e) { setError(e instanceof Error ? e.message : 'Dry-run failed') } finally { setBusy(null) }
  }
  const del = async () => { await api.delete(`/clients/${clientId}/wheelhouse/pages/${page.id}`); onChange(); onClose() }

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={card}>
        <button style={backLink} onClick={onClose}><ArrowLeft size={14} /> Back to list</button>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{page.title}</div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>
              {page.state} → {page.city}{page.page_type !== 'city' && page.service ? ` → ${page.service}` : ''} · <code>{page.slug_path}</code>
            </div>
          </div>
          <StatusPill page={page} />
        </div>
        {page.published_url && (
          <a href={page.published_url} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: '#6366f1', display: 'inline-flex', gap: 5, alignItems: 'center', marginTop: 8 }}>
            <ExternalLink size={13} /> View on site
          </a>
        )}
        {page.edit_link && (
          <a href={page.edit_link} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: '#6366f1', display: 'inline-flex', gap: 5, alignItems: 'center', marginTop: 8, marginLeft: 14 }}>
            <ExternalLink size={13} /> Edit in wp-admin
          </a>
        )}
        {page.validation_warnings.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 12, color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 12px' }}>
            {page.validation_warnings.length} field length warning{page.validation_warnings.length === 1 ? '' : 's'} (advisory): {page.validation_warnings.map((w) => `${w.field} (${w.issue})`).join(', ')}
          </div>
        )}
        {error && <div style={{ ...errorBox, marginTop: 12 }}>{error}</div>}
        {msg && <div style={{ marginTop: 12, fontSize: 13, color: '#166534', background: '#dcfce7', borderRadius: 8, padding: '8px 12px' }}>{msg}</div>}
        <div style={{ display: 'flex', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
          <button style={{ ...outlineBtn, opacity: busy ? 0.6 : 1 }} disabled={Boolean(busy)} onClick={saveEdits}>{busy === 'save' ? <Spinner /> : null} Save edits</button>
          <button style={{ ...outlineBtn, opacity: busy ? 0.6 : 1 }} disabled={Boolean(busy)} onClick={doDryRun}><Eye size={14} /> Dry-run</button>
          <button style={{ ...outlineBtn, opacity: wpConfigured && !busy ? 1 : 0.5 }} disabled={!wpConfigured || Boolean(busy)} onClick={() => publish('draft')}>
            {busy === 'draft' ? <Spinner /> : <Upload size={14} />} Publish as WP draft
          </button>
          <button style={{ ...primaryBtn, opacity: wpConfigured && !busy ? 1 : 0.5 }} disabled={!wpConfigured || Boolean(busy)} onClick={() => publish('publish')}>
            {busy === 'publish' ? <Spinner /> : <Upload size={14} />} Publish live
          </button>
          <button style={{ ...outlineBtn, marginLeft: 'auto', color: '#b91c1c', borderColor: '#fecaca' }} onClick={del}><Trash2 size={13} /> Delete</button>
        </div>
        {dryRun != null && (
          <pre style={{ marginTop: 14, background: '#0f172a', color: '#e2e8f0', borderRadius: 8, padding: 14, fontSize: 12, overflowX: 'auto', maxHeight: 360 }}>
            {JSON.stringify(dryRun, null, 2)}
          </pre>
        )}
      </div>

      <FieldGrid sections={sections} acf={acf} onField={setField} />
    </div>
  )
}
