import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Building2, Sparkles, Save, X, Trash2, RefreshCw, CheckCircle2,
  Clock, Plus, AlertTriangle, Info,
} from 'lucide-react'
import { api } from '../lib/api'
import { useResumableJob, type JobPoll } from '../lib/useResumableJob'
import { ConnectionBar, RegisterLocations } from '../components/gbp/GbpConnection'
import { ErrorDetails } from '../components/ErrorDetails'
import type { Client } from '../lib/types'

// GBP Profile Editor — read + edit a client's Google Business Profile
// description / services / hours via the v1 Business Information API. Every edit
// is drafted (manual or AI) then applied on an EXPLICIT Apply click — nothing is
// auto-applied (ADR 0004). Backend gated on gbp_api_enabled + gbp_profile_enabled;
// when off every endpoint 503s and we render an enablement notice.

const ACCENT = '#0d9488'
const DESC_MAX = 750
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

type EditStatus =
  | 'draft' | 'applying' | 'applied' | 'pending_review' | 'rejected' | 'live_changed' | 'failed'
type Field = 'description' | 'hours' | 'services'

interface GbpLocationRow { id: string; location_id: string; title: string | null; access_status: string }
interface HoursPeriod { open: string; close: string }
interface HoursRow { day: number; open_24: boolean; periods: HoursPeriod[] }
interface HoursValue { regular: HoursRow[]; special?: unknown[] | null }
interface ServiceItem {
  kind: 'free_form' | 'structured'; label: string
  description?: string | null; category_id?: string | null; raw?: unknown
}
interface Category { id: string; name: string }
interface ProfileMetadata {
  has_pending_edits: boolean; can_modify_service_list: boolean | null
  can_operate_local_post: boolean | null; place_id: string | null; maps_uri: string | null
}
interface ProfileEdit {
  id: string; client_id: string; location_row_id: string; field: Field; source: string
  current_value: unknown; proposed_value: unknown; status: EditStatus
  google_pending: boolean; sync_attempts: number; next_sync_at: string | null
  error: string | null; applied_at: string | null; created_at: string | null; updated_at: string | null
}
interface ProfileResponse {
  location_row_id: string; location_id: string; title: string | null
  description: string; hours: HoursValue; services: ServiceItem[]
  categories: Category[]; metadata: ProfileMetadata; edits: ProfileEdit[]
}
interface Job { job_id: string }
interface JobStatus { job_id: string; status: string; edit_id: string | null; error: string | null }

const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: bg === '#fff' ? '1px solid #e2e8f0' : 'none', background: bg, color: fg,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
})
const inputStyle: React.CSSProperties = {
  width: '100%', padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13,
  fontFamily: 'inherit', boxSizing: 'border-box',
}

const STATUS_META: Record<EditStatus, { label: string; color: string; bg: string }> = {
  draft: { label: 'Draft', color: '#475569', bg: '#f1f5f9' },
  applying: { label: 'Applying…', color: '#b45309', bg: '#fffbeb' },
  applied: { label: 'Live', color: '#15803d', bg: '#f0fdf4' },
  pending_review: { label: 'Pending Google review', color: '#b45309', bg: '#fffbeb' },
  rejected: { label: 'Rejected by Google', color: '#b91c1c', bg: '#fef2f2' },
  live_changed: { label: 'Live value changed — re-review', color: '#b45309', bg: '#fffbeb' },
  failed: { label: 'Failed', color: '#b91c1c', bg: '#fef2f2' },
}

// Advisory client-side linter (mirrors the server; warnings only, never a gate).
function lintDescription(text: string): { code: string; message: string }[] {
  const v = (text || '').trim()
  const out: { code: string; message: string }[] = []
  if (v.length > DESC_MAX) out.push({ code: 'too_long', message: `Over ${DESC_MAX} characters (${v.length}).` })
  if (/(https?:\/\/|www\.)\S+/i.test(v)) out.push({ code: 'url', message: 'Contains a URL — Google removes/rejects links in the description.' })
  if (/(?<!\d)(?:\+?\d[\s().-]{0,2}){7,}\d(?!\d)/.test(v)) out.push({ code: 'phone', message: 'Contains a phone number — not allowed in the description.' })
  const letters = v.replace(/[^a-zA-Z]/g, '')
  if (v.length >= 40 && letters.length && [...letters].filter((c) => c === c.toUpperCase()).length / letters.length > 0.3)
    out.push({ code: 'all_caps', message: 'Heavy use of ALL-CAPS reads as promotional.' })
  if (/\b(best|#1|number one|guaranteed?|cheapest|lowest price|world[- ]?class|unbeatable|top[- ]?rated|award[- ]?winning)\b/i.test(v))
    out.push({ code: 'promotional', message: 'Promotional superlatives (best / #1 / guaranteed) can trip review.' })
  if ((v.match(/!/g) || []).length >= 3) out.push({ code: 'punctuation', message: 'Excessive exclamation marks read as spammy.' })
  return out
}

// ── page shell ───────────────────────────────────────────────────────────────
export function GbpProfile() {
  const { id: clientId = '' } = useParams()
  const qc = useQueryClient()
  const [manageOpen, setManageOpen] = useState(false)
  const [selectedLoc, setSelectedLoc] = useState<string | null>(null)

  const clientQ = useQuery<Client>({
    queryKey: ['client', clientId], queryFn: () => api.get<Client>(`/clients/${clientId}`),
  })
  const locationsQ = useQuery<GbpLocationRow[]>({
    queryKey: ['gbp-profile-locations', clientId],
    queryFn: () => api.get<GbpLocationRow[]>(`/clients/${clientId}/gbp/profile-locations`),
    enabled: Boolean(clientId), retry: false,
  })
  const disabled = (locationsQ.error as Error | null)?.message === 'gbp_profile_not_enabled'
  const locations = locationsQ.data ?? []
  const okLocations = locations.filter((l) => l.access_status === 'ok')

  useEffect(() => {
    if (!selectedLoc && okLocations.length) setSelectedLoc(okLocations[0].id)
  }, [okLocations, selectedLoc])

  return (
    <div style={{ maxWidth: 920, margin: '0 auto', padding: '0 4px' }}>
      <Link to={`/clients/${clientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 14 }}>
        <ArrowLeft size={14} /> Back to {clientQ.data?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Building2 size={22} color={ACCENT} />
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: '#0f172a' }}>Business Profile</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 18px', lineHeight: 1.6 }}>
        Edit the client's Google Business Profile <strong>description</strong>, <strong>services</strong>, and
        <strong> hours</strong>. Every edit is drafted, then <em>you</em> click Apply — nothing is applied automatically.
      </p>

      <ConnectionBar accent={ACCENT} />

      {disabled ? (
        <EnablementNotice />
      ) : locationsQ.isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : okLocations.length === 0 ? (
        <RegisterLocations clientId={clientId} registered={locations} listQueryKey={['gbp-profile-locations', clientId]} accent={ACCENT} />
      ) : manageOpen ? (
        <RegisterLocations clientId={clientId} registered={locations} listQueryKey={['gbp-profile-locations', clientId]} accent={ACCENT} onClose={() => setManageOpen(false)} />
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
            {okLocations.length > 1 && (
              <select value={selectedLoc ?? ''} onChange={(e) => setSelectedLoc(e.target.value)} style={{ ...inputStyle, width: 'auto', minWidth: 220 }}>
                {okLocations.map((l) => <option key={l.id} value={l.id}>{l.title || l.location_id}</option>)}
              </select>
            )}
            <button onClick={() => setManageOpen(true)} style={{ marginLeft: 'auto', ...btn('#fff', '#334155') }}>
              Manage listing
            </button>
          </div>
          {selectedLoc && <ProfileEditor key={selectedLoc} clientId={clientId} locationRowId={selectedLoc} onChanged={() => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, selectedLoc] })} />}
        </>
      )}
    </div>
  )
}

function EnablementNotice() {
  return (
    <div style={{ padding: 20, borderRadius: 12, background: '#fffbeb', border: '1px solid #fde68a', fontSize: 13, color: '#92400e', lineHeight: 1.6 }}>
      <strong>The GBP Profile Editor isn't turned on yet.</strong>
      <p style={{ margin: '8px 0 0' }}>
        This tool is built but gated off. To activate it: connect the agency Google account (the Connect button above),
        prove the write path with <code>verify_gbp_api_access.py --edit-test</code> on the agency's own listing, then set
        <code> GBP_API_ENABLED</code> and <code>GBP_PROFILE_ENABLED</code> on the platform service.
      </p>
    </div>
  )
}

// ── the three-field editor ────────────────────────────────────────────────────
function ProfileEditor({ clientId, locationRowId, onChanged }: { clientId: string; locationRowId: string; onChanged: () => void }) {
  const profileQ = useQuery<ProfileResponse>({
    queryKey: ['gbp-profile', clientId, locationRowId],
    queryFn: () => api.get<ProfileResponse>(`/clients/${clientId}/gbp/profile?location_row_id=${locationRowId}`),
    retry: false,
  })

  if (profileQ.isLoading) return <div style={{ color: '#64748b', fontSize: 13 }}>Reading the live profile from Google…</div>
  if (profileQ.isError) {
    return <ErrorDetails message={(profileQ.error as Error)?.message} style={{ marginTop: 8 }} />
  }
  const p = profileQ.data!
  const editFor = (f: Field) => p.edits.find((e) => e.field === f && e.status !== 'applied' && e.status !== 'rejected')
    ?? p.edits.filter((e) => e.field === f)[0]

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {p.metadata.has_pending_edits && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 12px' }}>
          <Clock size={14} /> Google shows this listing has a pending edit still settling.
        </div>
      )}
      <DescriptionCard clientId={clientId} locationRowId={locationRowId} current={p.description} edit={editFor('description')} onChanged={onChanged} />
      <ServicesCard clientId={clientId} locationRowId={locationRowId} current={p.services} categories={p.categories} canModify={p.metadata.can_modify_service_list} edit={editFor('services')} onChanged={onChanged} />
      <HoursCard clientId={clientId} locationRowId={locationRowId} current={p.hours} edit={editFor('hours')} onChanged={onChanged} />
    </div>
  )
}

// Shared job orchestration for a card's draft/apply/refresh actions.
function useCardJobs(clientId: string, locationRowId: string, scope: string, onDone: () => void) {
  const [err, setErr] = useState<string | null>(null)
  const poll = (jobId: string) =>
    api.post<JobStatus[]>(`/clients/${clientId}/gbp/profile/jobs/status`, { job_ids: [jobId] })
      .then((rows): JobPoll<JobStatus> => {
        const r = rows[0]
        return { status: r?.status ?? 'pending', result: r, error: r?.error ?? null }
      })
  const job = useResumableJob<JobStatus, undefined>({
    storageKey: `gbp-profile-${scope}-${clientId}-${locationRowId}`,
    poll,
    onComplete: (r) => { if (r?.error) setErr(r.error); onDone() },
    onError: (e) => setErr(e),
  })
  return { err, setErr, job }
}

// ── Description ───────────────────────────────────────────────────────────────
function DescriptionCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: string; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const { err, setErr, job } = useCardJobs(clientId, locationRowId, 'desc', () => { onChanged(); refresh() })
  const proposed = typeof edit?.proposed_value === 'string' ? edit.proposed_value : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  const draft = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/draft`, { location_row_id: locationRowId, field: 'description' }).then((j) => j.job_id), undefined) }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { description: text })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'description', description: text }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  const warnings = editing ? lintDescription(text) : []
  return (
    <Card title="Business description" subtitle="What the business does, who it serves, and where. Max 750 characters — no links or phone numbers.">
      <CurrentValue empty={!current}>{current || 'No description on the listing yet.'}</CurrentValue>
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span style={{ whiteSpace: 'pre-wrap' }}>{proposed}</span>} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} style={{ ...inputStyle, resize: 'vertical' }} placeholder="Write the business description…" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: text.length > DESC_MAX ? '#b91c1c' : '#94a3b8' }}>
            <span>{text.length} / {DESC_MAX}</span>
          </div>
          {warnings.length > 0 && (
            <div style={{ display: 'grid', gap: 4, fontSize: 12, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 10px' }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontWeight: 600 }}><AlertTriangle size={13} /> Advisory (not blocking):</div>
              {warnings.map((w) => <div key={w.code}>• {w.message}</div>)}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !text.trim() || text.length > DESC_MAX} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={() => { setText(proposed ?? current ?? ''); setEditing(true) }} style={btn('#fff', '#334155')}>Edit</button>
          <button onClick={draft} disabled={job.running} style={btn('#fff', ACCENT)}>
            <Sparkles size={13} /> {job.running ? 'Drafting…' : 'Draft with AI'}
          </button>
        </div>
      )}
    </Card>
  )
}

// ── Services ──────────────────────────────────────────────────────────────────
function ServicesCard({ clientId, locationRowId, current, categories, canModify, edit, onChanged }: {
  clientId: string; locationRowId: string; current: ServiceItem[]; categories: Category[]
  canModify: boolean | null; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [rows, setRows] = useState<ServiceItem[]>([])
  const { err, setErr, job } = useCardJobs(clientId, locationRowId, 'svc', () => { onChanged(); refresh() })
  const proposed = Array.isArray(edit?.proposed_value) ? (edit!.proposed_value as ServiceItem[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  const startEdit = () => {
    setRows((proposed ?? current).map((s) => ({ ...s })))
    setEditing(true)
  }
  const freeForm = rows.filter((r) => r.kind !== 'structured')
  const structuredCount = rows.filter((r) => r.kind === 'structured').length
  const allHaveCategory = freeForm.every((r) => r.label.trim() && r.category_id)

  const draft = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/draft`, { location_row_id: locationRowId, field: 'services' }).then((j) => j.job_id), undefined) }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { services: rows })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'services', services: rows }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  const set = (i: number, patch: Partial<ServiceItem>) => setRows((rs) => rs.map((r, j) => j === i ? { ...r, ...patch } : r))
  const catOptions = categories

  return (
    <Card title="Services" subtitle="Free-form services, each attached to one of the listing's categories.">
      {canModify === false && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, color: '#b45309', marginBottom: 8 }}>
          <Info size={13} /> Google reports this listing doesn't allow editing its services list.
        </div>
      )}
      {current.length === 0 ? <CurrentValue empty>No services on the listing yet.</CurrentValue> : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {current.map((s, i) => (
            <span key={i} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: s.kind === 'structured' ? '#eef2ff' : '#f1f5f9', color: '#334155' }}>
              {s.label}{s.kind === 'structured' ? ' (structured)' : ''}
            </span>
          ))}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => (
        <span>{proposed?.map((s) => s.label).join(', ')}</span>
      )} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}

      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
          {structuredCount > 0 && <div style={{ fontSize: 12, color: '#64748b' }}>{structuredCount} structured service(s) will be kept as-is.</div>}
          {freeForm.map((r) => {
            const i = rows.indexOf(r)
            return (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6, alignItems: 'center' }}>
                <input value={r.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="Service name" style={inputStyle} />
                <select value={r.category_id ?? ''} onChange={(e) => set(i, { category_id: e.target.value })} style={inputStyle}>
                  <option value="">— pick a category —</option>
                  {catOptions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} style={btn('#fff', '#b91c1c')}><Trash2 size={13} /></button>
              </div>
            )
          })}
          <button onClick={() => setRows((rs) => [...rs, { kind: 'free_form', label: '', category_id: '' }])} style={{ ...btn('#fff', '#334155'), justifySelf: 'start' }}>
            <Plus size={13} /> Add service
          </button>
          {!allHaveCategory && freeForm.length > 0 && <div style={{ fontSize: 12, color: '#b45309' }}>Every service needs a name and a category before you can save.</div>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !allHaveCategory} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}>Edit</button>
          <button onClick={draft} disabled={job.running} style={btn('#fff', ACCENT)}>
            <Sparkles size={13} /> {job.running ? 'Drafting…' : 'Draft with AI'}
          </button>
        </div>
      )}
    </Card>
  )
}

// ── Hours ─────────────────────────────────────────────────────────────────────
function HoursCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: HoursValue; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [rows, setRows] = useState<HoursRow[]>([])
  const [err, setErr] = useState<string | null>(null)
  const proposed = edit && typeof edit.proposed_value === 'object' && edit.proposed_value
    ? (edit.proposed_value as HoursValue) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  const startEdit = () => {
    const src = (proposed ?? current)?.regular ?? []
    const byDay = new Map(src.map((r) => [r.day, r]))
    setRows(DAYS.map((_, d) => byDay.get(d) ?? { day: d, open_24: false, periods: [] }))
    setConfirmed(false); setEditing(true)
  }
  const saveMut = useMutation({
    mutationFn: () => {
      const regular = rows.filter((r) => r.open_24 || r.periods.length > 0)
      const value: HoursValue = { regular }
      return edit && edit.status !== 'applied' && edit.status !== 'rejected'
        ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { hours: value })
        : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'hours', hours: value })
    },
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  const setDay = (d: number, patch: Partial<HoursRow>) => setRows((rs) => rs.map((r) => r.day === d ? { ...r, ...patch } : r))

  return (
    <Card title="Operating hours" subtitle="The AI never drafts hours — enter them by hand and confirm they're correct.">
      <div style={{ display: 'grid', gap: 3, fontSize: 13 }}>
        {DAYS.map((name, d) => {
          const row = current.regular.find((r) => r.day === d)
          const label = !row ? 'Closed' : row.open_24 ? 'Open 24 hours' : row.periods.map((p) => `${p.open}–${p.close}`).join(', ')
          return (
            <div key={d} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', color: row ? '#0f172a' : '#94a3b8' }}>
              <span style={{ fontWeight: 600 }}>{name}</span><span>{label}</span>
            </div>
          )
        })}
      </div>
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => (
        <span>{(proposed?.regular ?? []).length} day(s) set</span>
      )} onChanged={onChanged} setErr={setErr} confirmBeforeApply={!confirmed} onNeedConfirm={() => { startEdit() }} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}

      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          {rows.map((r) => (
            <div key={r.day} style={{ display: 'grid', gridTemplateColumns: '100px 120px 1fr', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{DAYS[r.day]}</span>
              <select
                value={r.open_24 ? '24' : r.periods.length ? 'open' : 'closed'}
                onChange={(e) => {
                  const v = e.target.value
                  if (v === 'closed') setDay(r.day, { open_24: false, periods: [] })
                  else if (v === '24') setDay(r.day, { open_24: true, periods: [] })
                  else setDay(r.day, { open_24: false, periods: r.periods.length ? r.periods : [{ open: '09:00', close: '17:00' }] })
                }}
                style={inputStyle}
              >
                <option value="closed">Closed</option>
                <option value="open">Open</option>
                <option value="24">Open 24h</option>
              </select>
              {!r.open_24 && r.periods.length > 0 && (
                <div style={{ display: 'grid', gap: 4 }}>
                  {r.periods.map((per, pi) => (
                    <div key={pi} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <input type="time" value={per.open} onChange={(e) => setDay(r.day, { periods: r.periods.map((x, j) => j === pi ? { ...x, open: e.target.value } : x) })} style={{ ...inputStyle, width: 120 }} />
                      <span style={{ color: '#94a3b8' }}>–</span>
                      <input type="time" value={per.close} onChange={(e) => setDay(r.day, { periods: r.periods.map((x, j) => j === pi ? { ...x, close: e.target.value } : x) })} style={{ ...inputStyle, width: 120 }} />
                      {r.periods.length > 1 && <button onClick={() => setDay(r.day, { periods: r.periods.filter((_, j) => j !== pi) })} style={btn('#fff', '#b91c1c')}><X size={12} /></button>}
                    </div>
                  ))}
                  <button onClick={() => setDay(r.day, { periods: [...r.periods, { open: '09:00', close: '17:00' }] })} style={{ ...btn('#fff', '#334155'), justifySelf: 'start', padding: '4px 10px' }}>
                    <Plus size={12} /> Add hours
                  </button>
                </div>
              )}
            </div>
          ))}
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: '#334155', marginTop: 4 }}>
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            I confirm these hours are correct (wrong hours can trip a GBP suspension).
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !confirmed} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}><Clock size={13} /> Edit hours</button>
        </div>
      )}
    </Card>
  )
}

// ── shared bits ────────────────────────────────────────────────────────────────
function Card({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, background: '#fff' }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{title}</div>
      <div style={{ fontSize: 12.5, color: '#94a3b8', margin: '2px 0 12px', lineHeight: 1.5 }}>{subtitle}</div>
      {children}
    </div>
  )
}

function CurrentValue({ empty, children }: { empty?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, color: empty ? '#94a3b8' : '#0f172a', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
      <span style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.4 }}>Current on Google</span>
      {children}
    </div>
  )
}

// The current proposed/recent edit row with its status + Apply / Discard / Refresh.
function ProposedRow({ edit, clientId, locationRowId, render, onChanged, setErr, confirmBeforeApply, onNeedConfirm }: {
  edit: ProfileEdit; clientId: string; locationRowId: string; render: () => React.ReactNode
  onChanged: () => void; setErr: (e: string | null) => void
  confirmBeforeApply?: boolean; onNeedConfirm?: () => void
}) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const { job } = useCardJobs(clientId, locationRowId, `apply-${edit.field}`, () => { onChanged(); refresh() })
  const meta = STATUS_META[edit.status]
  const isOpen = edit.status === 'draft' || edit.status === 'live_changed' || edit.status === 'failed'

  const apply = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/edits/${edit.id}/apply`, {}).then((j) => j.job_id), undefined) }
  const kickRefresh = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/edits/${edit.id}/refresh`, {}).then((j) => j.job_id), undefined) }
  const discardMut = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/gbp/profile/edits/${edit.id}/discard`, {}),
    onSuccess: () => { setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  return (
    <div style={{ marginTop: 12, borderTop: '1px dashed #e2e8f0', paddingTop: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>Proposed{edit.source === 'ai' ? ' (AI)' : edit.source === 'strategist' ? ' (strategist)' : ''}</span>
        <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999, color: meta.color, background: meta.bg }}>{meta.label}</span>
      </div>
      <div style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.6 }}>{render()}</div>
      {edit.error && <ErrorDetails message={edit.error} style={{ marginTop: 6 }} />}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        {isOpen && (
          <button
            onClick={() => { if (confirmBeforeApply && onNeedConfirm) { onNeedConfirm() } else { apply() } }}
            disabled={job.running}
            style={btn(ACCENT)}
          >
            <CheckCircle2 size={13} /> {job.running ? 'Applying…' : edit.status === 'live_changed' ? 'Re-review & Apply' : 'Apply to Google'}
          </button>
        )}
        {edit.status === 'pending_review' && (
          <button onClick={kickRefresh} disabled={job.running} style={btn('#fff', '#334155')}>
            <RefreshCw size={13} /> Refresh status
          </button>
        )}
        {(isOpen || edit.status === 'pending_review') && (
          <button onClick={() => discardMut.mutate()} disabled={discardMut.isPending || edit.status === 'pending_review'} title={edit.status === 'pending_review' ? 'Can’t discard while Google is reviewing' : ''} style={btn('#fff', '#b91c1c')}>
            <Trash2 size={13} /> Discard
          </button>
        )}
      </div>
    </div>
  )
}
