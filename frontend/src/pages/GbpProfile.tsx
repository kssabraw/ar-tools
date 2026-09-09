import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Building2, Sparkles, Save, X, Trash2, RefreshCw, CheckCircle2,
  Clock, Plus, AlertTriangle, Info, Search, ShieldCheck, ShieldAlert,
  Globe, Tag, MapPin, CalendarDays, Power, LayoutGrid, Star, SlidersHorizontal,
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
type Field =
  | 'description' | 'hours' | 'services'
  | 'website' | 'labels' | 'special_hours' | 'more_hours' | 'service_area' | 'open_info'
  | 'categories' | 'attributes'

interface GbpLocationRow { id: string; location_id: string; title: string | null; access_status: string }
interface HoursPeriod { open: string; close: string }
interface HoursRow { day: number; open_24: boolean; periods: HoursPeriod[] }
interface DateInput { year: number; month: number; day: number }
interface SpecialHoursRow { start: DateInput; end?: DateInput | null; closed: boolean; open?: string | null; close?: string | null }
interface HoursValue { regular: HoursRow[]; special?: SpecialHoursRow[] | null }
interface MoreHoursEntry { hours_type_id: string; regular: HoursRow[] }
interface ServiceAreaPlace { name: string; place_id: string }
interface ServiceAreaValue { business_type: string; places: ServiceAreaPlace[]; region_code?: string | null }
interface OpenInfoValue { status: string; opening_date?: DateInput | null }
interface MoreHoursType { hours_type_id: string; display_name: string }
interface MoreHoursTypeCategory { id: string; name: string; more_hours_types: MoreHoursType[] }
interface ResolvedPlace { query: string; name: string; place_id: string; matched: boolean }
interface CategoryRef { id: string; name: string }
interface CategoriesValue { primary: CategoryRef | null; additional: CategoryRef[] }
type AttributeValueType = 'BOOL' | 'ENUM' | 'URL' | 'REPEATED_ENUM'
interface AttributeValue {
  attribute_id: string; value_type: AttributeValueType
  values?: unknown[]; urls?: string[]; set_values?: string[]; unset_values?: string[]
}
interface AttributeValueOption { value: unknown; display_name: string }
interface AttributeMetaItem {
  attribute_id: string; value_type: AttributeValueType; display_name: string
  group_name: string; deprecated: boolean; repeatable: boolean; value_options?: AttributeValueOption[]
}
const OPEN_STATUS_LABELS: Record<string, string> = {
  OPEN: 'Open', CLOSED_TEMPORARILY: 'Temporarily closed', CLOSED_PERMANENTLY: 'Permanently closed',
}
interface ServiceItem {
  kind: 'free_form' | 'structured'; label: string
  description?: string | null; category_id?: string | null
  service_type_id?: string | null; raw?: unknown
}
interface Category { id: string; name: string }
interface ServiceType { service_type_id: string; display_name: string }
interface ServiceTypeCategory { id: string; name: string; service_types: ServiceType[] }
interface ServiceTypesResponse { categories: ServiceTypeCategory[] }
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
  categories: Category[]; metadata: ProfileMetadata
  website: string; labels: string[]; special_hours: SpecialHoursRow[]
  more_hours: MoreHoursEntry[]; service_area: ServiceAreaValue; open_info: OpenInfoValue | null
  categories_value: CategoriesValue
  attributes: AttributeValue[]; attributes_error?: string | null
  edits: ProfileEdit[]
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

// Structured (Google-defined) services come back as raw ids like
// "job_type_id:flex_office_rentals" / "gcid:..."; humanize them for display
// (Flex Office Rentals). The stored value used for the patch is untouched.
// Free-form labels are already plain text and pass through.
function serviceLabel(s: { kind: 'free_form' | 'structured'; label: string }): string {
  if (s.kind !== 'structured') return s.label
  const bare = (s.label || '').replace(/^[^:]*:/, '').replace(/_/g, ' ').trim()
  return bare ? bare.replace(/\b\w/g, (c) => c.toUpperCase()) : s.label
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
  return (
    <div style={{ maxWidth: 920, margin: '0 auto', padding: '0 4px' }}>
      <GbpProfileBody clientId={clientId} />
    </div>
  )
}

// The Profile editor body, reusable standalone (above) and embedded in the
// unified Google Business Profile module. `embedded` hides the back-link, page
// title, and the shared ConnectionBar (the module renders one above all tabs).
export function GbpProfileBody({ clientId, embedded }: { clientId: string; embedded?: boolean }) {
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
    <>
      {!embedded && (
        <>
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
        </>
      )}

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
    </>
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
      <MonitorPanel clientId={clientId} locationRowId={locationRowId} />
      {p.metadata.has_pending_edits && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 12px' }}>
          <Clock size={14} /> Google shows this listing has a pending edit still settling.
        </div>
      )}
      <DescriptionCard clientId={clientId} locationRowId={locationRowId} current={p.description} edit={editFor('description')} onChanged={onChanged} />
      <CategoriesCard clientId={clientId} locationRowId={locationRowId} current={p.categories_value} edit={editFor('categories')} onChanged={onChanged} />
      <ServicesCard clientId={clientId} locationRowId={locationRowId} current={p.services} categories={p.categories} canModify={p.metadata.can_modify_service_list} edit={editFor('services')} onChanged={onChanged} />
      <HoursCard clientId={clientId} locationRowId={locationRowId} current={p.hours} edit={editFor('hours')} onChanged={onChanged} />
      <SpecialHoursCard clientId={clientId} locationRowId={locationRowId} current={p.special_hours} edit={editFor('special_hours')} onChanged={onChanged} />
      <MoreHoursCard clientId={clientId} locationRowId={locationRowId} current={p.more_hours} edit={editFor('more_hours')} onChanged={onChanged} />
      <WebsiteCard clientId={clientId} locationRowId={locationRowId} current={p.website} edit={editFor('website')} onChanged={onChanged} />
      <ServiceAreaCard clientId={clientId} locationRowId={locationRowId} current={p.service_area} edit={editFor('service_area')} onChanged={onChanged} />
      <OpenInfoCard clientId={clientId} locationRowId={locationRowId} current={p.open_info} edit={editFor('open_info')} onChanged={onChanged} />
      <LabelsCard clientId={clientId} locationRowId={locationRowId} current={p.labels} edit={editFor('labels')} onChanged={onChanged} />
      <AttributesCard clientId={clientId} locationRowId={locationRowId} current={p.attributes} currentError={p.attributes_error} edit={editFor('attributes')} onChanged={onChanged} />
    </div>
  )
}

// ── Monitoring (suspension + out-of-band change watch) ────────────────────────
interface MonitorStatus {
  monitored: boolean; enabled: boolean; access_status?: string | null
  checked_at?: string | null; last_change?: { fields?: string[] } | null; last_change_at?: string | null
}
const FIELD_LABELS: Record<string, string> = {
  title: 'business name', description: 'description', categories: 'categories',
  phone: 'phone number', website: 'website', address: 'address',
  hours: 'hours', services: 'services', open_status: 'open/closed status',
}
const fmtWhen = (iso?: string | null) => {
  if (!iso) return null
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

// A compact status strip: is the listing being watched for suspension /
// out-of-band edits, when it was last checked, its access state, and the last
// change Google or an outside source made. "Check now" runs a check immediately.
function MonitorPanel({ clientId, locationRowId }: { clientId: string; locationRowId: string }) {
  const qc = useQueryClient()
  const statusQ = useQuery<MonitorStatus>({
    queryKey: ['gbp-monitor', clientId, locationRowId],
    queryFn: () => api.get<MonitorStatus>(`/clients/${clientId}/gbp/profile/monitor?location_row_id=${locationRowId}`),
    retry: false,
  })
  const { job } = useCardJobs(clientId, locationRowId, 'monitor', () =>
    qc.invalidateQueries({ queryKey: ['gbp-monitor', clientId, locationRowId] }))
  const s = statusQ.data
  if (!s) return null

  const check = () => job.start(
    () => api.post<Job>(`/clients/${clientId}/gbp/profile/monitor/check?location_row_id=${locationRowId}`, {})
      .then((j) => j.job_id), undefined)

  const suspended = s.access_status === 'suspended' || s.access_status === 'no_access'
  const changedFields = (s.last_change?.fields || []).map((f) => FIELD_LABELS[f] || f)
  const checkBtn = s.enabled ? (
    <button onClick={check} disabled={job.running} style={{ ...btn('#fff', '#334155'), marginLeft: 'auto', padding: '5px 10px', fontSize: 12 }}>
      <RefreshCw size={12} /> {job.running ? 'Checking…' : 'Check now'}
    </button>
  ) : null

  if (suspended) {
    return (
      <div style={{ display: 'grid', gap: 6, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#b91c1c', fontWeight: 700, fontSize: 13.5 }}>
          <ShieldAlert size={16} />
          {s.access_status === 'suspended' ? 'This listing appears SUSPENDED' : 'This listing can no longer be read'}
          {checkBtn}
        </div>
        <div style={{ fontSize: 12.5, color: '#7f1d1d', lineHeight: 1.5 }}>
          {s.access_status === 'suspended'
            ? 'Google reports the profile is no longer verified (Voice of Merchant lost). Check the Google Business Profile dashboard and reinstate if needed.'
            : 'Our connected Google account can’t read this listing (removed, unverified, or access revoked). Check the GBP dashboard / connection.'}
          {s.checked_at && <> · last checked {fmtWhen(s.checked_at)}</>}
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 5, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: '#334155' }}>
        <ShieldCheck size={15} color={s.enabled ? '#0d9488' : '#94a3b8'} />
        <span style={{ fontWeight: 600 }}>
          {s.enabled
            ? (s.monitored ? 'Watching for suspensions & outside changes' : 'Monitoring on — first check pending')
            : 'Change & suspension monitoring is off'}
        </span>
        {s.enabled && s.monitored && s.checked_at && (
          <span style={{ color: '#94a3b8' }}>· last checked {fmtWhen(s.checked_at)}</span>
        )}
        {checkBtn}
      </div>
      {changedFields.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#b45309' }}>
          <AlertTriangle size={12} />
          Last outside change: {changedFields.join(', ')}{s.last_change_at ? ` · ${fmtWhen(s.last_change_at)}` : ''}
        </div>
      )}
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
// The structured serviceTypeId of a row (an existing live structured row carries
// it in `label`; a fresh pick carries it in `service_type_id`).
const stId = (r: ServiceItem) => (r.service_type_id || r.label || '')

function ServicesCard({ clientId, locationRowId, current, categories, canModify, edit, onChanged }: {
  clientId: string; locationRowId: string; current: ServiceItem[]; categories: Category[]
  canModify: boolean | null; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [rows, setRows] = useState<ServiceItem[]>([])
  const [query, setQuery] = useState('')
  const { err, setErr, job } = useCardJobs(clientId, locationRowId, 'svc', () => { onChanged(); refresh() })
  const proposed = Array.isArray(edit?.proposed_value) ? (edit!.proposed_value as ServiceItem[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  // The Google-approved service types for this listing's categories (the pick list).
  const typesQ = useQuery<ServiceTypesResponse>({
    queryKey: ['gbp-service-types', clientId, locationRowId],
    queryFn: () => api.get<ServiceTypesResponse>(`/clients/${clientId}/gbp/profile/service-types?location_row_id=${locationRowId}`),
    enabled: editing, retry: false, staleTime: 5 * 60_000,
  })

  const startEdit = () => {
    // Normalize existing structured rows so every one carries service_type_id.
    setRows((proposed ?? current).map((s) =>
      s.kind === 'structured' ? { ...s, service_type_id: stId(s) } : { ...s }))
    setQuery(''); setEditing(true)
  }
  const structured = rows.filter((r) => r.kind === 'structured')
  const freeForm = rows.filter((r) => r.kind !== 'structured')
  const selectedIds = new Set(structured.map(stId))
  const structRowFor = (id: string) => rows.find((r) => r.kind === 'structured' && stId(r) === id)
  const customValid = freeForm.every((r) => r.label.trim() && r.category_id)

  const set = (i: number, patch: Partial<ServiceItem>) => setRows((rs) => rs.map((r, j) => j === i ? { ...r, ...patch } : r))
  const setDescFor = (id: string, description: string) =>
    setRows((rs) => rs.map((r) => r.kind === 'structured' && stId(r) === id ? { ...r, description } : r))

  const draft = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/draft`, { location_row_id: locationRowId, field: 'services' }).then((j) => j.job_id), undefined) }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { services: rows })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'services', services: rows }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  const toggle = (st: ServiceType, catId: string) => {
    setRows((rs) => selectedIds.has(st.service_type_id)
      ? rs.filter((r) => !(r.kind === 'structured' && stId(r) === st.service_type_id))
      : [...rs, { kind: 'structured', service_type_id: st.service_type_id, label: st.display_name, category_id: catId, description: '' }])
  }
  const addCustom = () => setRows((rs) => [...rs, { kind: 'free_form', label: '', category_id: '', description: '' }])

  const q = query.trim().toLowerCase()
  const typeCats = (typesQ.data?.categories ?? []).map((c) => ({
    ...c,
    service_types: q ? c.service_types.filter((t) => t.display_name.toLowerCase().includes(q)) : c.service_types,
  }))
  const hasAnyType = (typesQ.data?.categories ?? []).some((c) => c.service_types.length > 0)

  return (
    <Card title="Services" subtitle="Pick from Google's approved services for this listing's categories, or add your own custom services. Give each an optional short description.">
      {canModify === false && (
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12, color: '#b45309', marginBottom: 8 }}>
          <Info size={13} /> Google reports this listing doesn't allow editing its services list.
        </div>
      )}
      {current.length === 0 ? <CurrentValue empty>No services on the listing yet.</CurrentValue> : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {current.map((s, i) => (
            <span key={i} title={s.description || undefined} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: s.kind === 'free_form' ? '#fef3c7' : '#eef2ff', color: '#334155' }}>
              {serviceLabel(s)}{s.kind === 'free_form' ? ' (custom)' : ''}
            </span>
          ))}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => (
        <span>{proposed?.map(serviceLabel).join(', ')}</span>
      )} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}

      {editing ? (
        <div style={{ display: 'grid', gap: 14, marginTop: 10 }}>
          {/* Custom (free-form) services — name + category + optional description. */}
          <div style={{ display: 'grid', gap: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>Custom services</div>
            {freeForm.map((r) => {
              const i = rows.indexOf(r)
              return (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6, alignItems: 'start' }}>
                  <div style={{ display: 'grid', gap: 4 }}>
                    <input value={r.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="Service name" style={inputStyle} />
                    <input value={r.description ?? ''} onChange={(e) => set(i, { description: e.target.value })} placeholder="Description (optional)" style={{ ...inputStyle, fontSize: 12 }} />
                  </div>
                  <select value={r.category_id ?? ''} onChange={(e) => set(i, { category_id: e.target.value })} style={inputStyle}>
                    <option value="">— pick a category —</option>
                    {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                  <button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} title="Remove" style={btn('#fff', '#b91c1c')}><Trash2 size={13} /></button>
                </div>
              )
            })}
            <button onClick={addCustom} style={{ ...btn('#fff', '#334155'), justifySelf: 'start' }}>
              <Plus size={13} /> Add custom service
            </button>
            {!customValid && freeForm.length > 0 && <div style={{ fontSize: 12, color: '#b45309' }}>Each custom service needs a name and a category.</div>}
          </div>

          {/* Google-approved service picker — each checked service gets an optional description. */}
          <div style={{ display: 'grid', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>Google-approved services</div>
              <span style={{ fontSize: 12, color: '#64748b' }}>{selectedIds.size} selected</span>
            </div>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: 10, color: '#94a3b8' }} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search services…" style={{ ...inputStyle, paddingLeft: 30 }} />
            </div>
            {typesQ.isLoading ? (
              <div style={{ fontSize: 12.5, color: '#64748b' }}>Loading Google's services for this listing…</div>
            ) : typesQ.isError ? (
              <ErrorDetails message={(typesQ.error as Error)?.message} style={{ marginTop: 2 }} />
            ) : !hasAnyType ? (
              <div style={{ fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 10px' }}>
                Google offers no structured services for this listing's categories. Use custom services above instead.
              </div>
            ) : (
              <div style={{ maxHeight: 360, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 8, padding: 4 }}>
                {typeCats.map((cat) => cat.service_types.length > 0 && (
                  <div key={cat.id} style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', padding: '6px 8px 3px' }}>{cat.name}</div>
                    {cat.service_types.map((st) => {
                      const checked = selectedIds.has(st.service_type_id)
                      const row = checked ? structRowFor(st.service_type_id) : undefined
                      return (
                        <div key={st.service_type_id} style={{ borderRadius: 6, background: checked ? '#f0fdfa' : 'transparent' }}>
                          <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', cursor: 'pointer', fontSize: 13 }}>
                            <input type="checkbox" checked={checked} onChange={() => toggle(st, cat.id)} />
                            <span style={{ color: '#0f172a' }}>{st.display_name}</span>
                          </label>
                          {checked && (
                            <div style={{ padding: '0 8px 7px 30px' }}>
                              <input
                                value={row?.description ?? ''}
                                onChange={(e) => setDescFor(st.service_type_id, e.target.value)}
                                placeholder="Description (optional)"
                                style={{ ...inputStyle, fontSize: 12 }}
                              />
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ))}
                {q && !typeCats.some((c) => c.service_types.length > 0) && (
                  <div style={{ fontSize: 12.5, color: '#94a3b8', padding: '8px' }}>No services match “{query}”.</div>
                )}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !customValid} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}>Edit</button>
          <button onClick={draft} disabled={job.running} style={btn('#fff', ACCENT)} title="Suggest which Google-approved services apply">
            <Sparkles size={13} /> {job.running ? 'Drafting…' : 'Suggest with AI'}
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

// ── Website (Phase 3a) ────────────────────────────────────────────────────────
function WebsiteCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: string; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'website', onChanged)
  const proposed = typeof edit?.proposed_value === 'string' ? edit.proposed_value : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { website: text })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'website', website: text }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  return (
    <Card title="Website" subtitle="The website shown on the listing. Leave blank to remove it.">
      <CurrentValue empty={!current}>{current || 'No website on the listing.'}</CurrentValue>
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{proposed || '(cleared)'}</span>} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="https://www.example.com" style={inputStyle} />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={() => { setText(proposed ?? current ?? ''); setEditing(true) }} style={btn('#fff', '#334155')}><Globe size={13} /> Edit website</button>
        </div>
      )}
    </Card>
  )
}

// ── Labels (Phase 3a) ─────────────────────────────────────────────────────────
function LabelsCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: string[]; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [labels, setLabels] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'labels', onChanged)
  const proposed = Array.isArray(edit?.proposed_value) ? (edit!.proposed_value as string[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const add = () => { const v = draft.trim(); if (v && !labels.some((l) => l.toLowerCase() === v.toLowerCase())) setLabels([...labels, v]); setDraft('') }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { labels })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'labels', labels }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  return (
    <Card title="Labels" subtitle="Internal labels to organise listings (not shown to customers). Up to 10.">
      {current.length === 0 ? <CurrentValue empty>No labels.</CurrentValue> : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {current.map((l, i) => <span key={i} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#f1f5f9', color: '#334155' }}>{l}</span>)}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{(proposed ?? []).join(', ') || '(cleared)'}</span>} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {labels.map((l, i) => (
              <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, padding: '3px 6px 3px 9px', borderRadius: 999, background: '#e0f2fe', color: '#334155' }}>
                {l}<button onClick={() => setLabels(labels.filter((_, j) => j !== i))} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748b', display: 'flex' }}><X size={12} /></button>
              </span>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} placeholder="Add a label…" style={inputStyle} />
            <button onClick={add} disabled={!draft.trim() || labels.length >= 10} style={btn('#fff', '#334155')}><Plus size={13} /></button>
          </div>
          {labels.length >= 10 && <div style={{ fontSize: 12, color: '#b45309' }}>10 labels max.</div>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button onClick={() => { setLabels(proposed ?? current ?? []); setDraft(''); setEditing(true) }} style={btn('#fff', '#334155')}><Tag size={13} /> Edit labels</button>
        </div>
      )}
    </Card>
  )
}

// ── Special (holiday) hours (Phase 3a) ────────────────────────────────────────
const toDateStr = (d?: DateInput | null) => d ? `${d.year}-${String(d.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}` : ''
const fromDateStr = (s: string): DateInput | null => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s); return m ? { year: +m[1], month: +m[2], day: +m[3] } : null }

function SpecialHoursCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: SpecialHoursRow[]; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [rows, setRows] = useState<SpecialHoursRow[]>([])
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'special', onChanged)
  const proposed = Array.isArray(edit?.proposed_value) ? (edit!.proposed_value as SpecialHoursRow[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const label = (r: SpecialHoursRow) => `${toDateStr(r.start)}${r.end && toDateStr(r.end) !== toDateStr(r.start) ? `–${toDateStr(r.end)}` : ''}: ${r.closed ? 'Closed' : `${r.open}–${r.close}`}`
  const valid = rows.every((r) => r.start && r.start.year && (r.closed || (r.open && r.close)))
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { special_hours: rows })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'special_hours', special_hours: rows }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  const setRow = (i: number, patch: Partial<SpecialHoursRow>) => setRows((rs) => rs.map((r, j) => j === i ? { ...r, ...patch } : r))
  return (
    <Card title="Holiday & special hours" subtitle="One-off hours for holidays or events. The AI never sets these — enter them by hand.">
      {current.length === 0 ? <CurrentValue empty>No special hours set.</CurrentValue> : (
        <div style={{ display: 'grid', gap: 3, fontSize: 13 }}>{current.map((r, i) => <div key={i}>{label(r)}</div>)}</div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{(proposed ?? []).length} special day(s)</span>} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          {rows.map((r, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <input type="date" value={toDateStr(r.start)} onChange={(e) => { const d = fromDateStr(e.target.value); if (d) setRow(i, { start: d, end: d }) }} style={{ ...inputStyle, width: 160 }} />
              <select value={r.closed ? 'closed' : 'open'} onChange={(e) => setRow(i, e.target.value === 'closed' ? { closed: true } : { closed: false, open: r.open || '09:00', close: r.close || '17:00' })} style={{ ...inputStyle, width: 110 }}>
                <option value="closed">Closed</option><option value="open">Open</option>
              </select>
              {!r.closed && <>
                <input type="time" value={r.open ?? '09:00'} onChange={(e) => setRow(i, { open: e.target.value })} style={{ ...inputStyle, width: 120 }} />
                <span style={{ color: '#94a3b8' }}>–</span>
                <input type="time" value={r.close ?? '17:00'} onChange={(e) => setRow(i, { close: e.target.value })} style={{ ...inputStyle, width: 120 }} />
              </>}
              <button onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} style={btn('#fff', '#b91c1c')}><Trash2 size={13} /></button>
            </div>
          ))}
          <button onClick={() => setRows([...rows, { start: { year: new Date().getFullYear(), month: 1, day: 1 }, closed: true }])} style={{ ...btn('#fff', '#334155'), justifySelf: 'start' }}><Plus size={13} /> Add a special day</button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !valid} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={() => { setRows((proposed ?? current ?? []).map((r) => ({ ...r }))); setEditing(true) }} style={btn('#fff', '#334155')}><CalendarDays size={13} /> Edit special hours</button>
        </div>
      )}
    </Card>
  )
}

// A compact weekly hours editor (reused by More hours). Mirrors the Hours card grid.
function WeeklyHoursEditor({ rows, onChange }: { rows: HoursRow[]; onChange: (rows: HoursRow[]) => void }) {
  const byDay = new Map(rows.map((r) => [r.day, r]))
  const full = DAYS.map((_, d) => byDay.get(d) ?? { day: d, open_24: false, periods: [] })
  const setDay = (d: number, patch: Partial<HoursRow>) => onChange(full.map((r) => r.day === d ? { ...r, ...patch } : r).filter((r) => r.open_24 || r.periods.length > 0))
  return (
    <div style={{ display: 'grid', gap: 6 }}>
      {full.map((r) => (
        <div key={r.day} style={{ display: 'grid', gridTemplateColumns: '90px 110px 1fr', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>{DAYS[r.day]}</span>
          <select value={r.open_24 ? '24' : r.periods.length ? 'open' : 'closed'} onChange={(e) => {
            const v = e.target.value
            if (v === 'closed') setDay(r.day, { open_24: false, periods: [] })
            else if (v === '24') setDay(r.day, { open_24: true, periods: [] })
            else setDay(r.day, { open_24: false, periods: r.periods.length ? r.periods : [{ open: '09:00', close: '17:00' }] })
          }} style={inputStyle}>
            <option value="closed">Closed</option><option value="open">Open</option><option value="24">24h</option>
          </select>
          {!r.open_24 && r.periods.length > 0 && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="time" value={r.periods[0].open} onChange={(e) => setDay(r.day, { periods: [{ ...r.periods[0], open: e.target.value }] })} style={{ ...inputStyle, width: 116 }} />
              <span style={{ color: '#94a3b8' }}>–</span>
              <input type="time" value={r.periods[0].close} onChange={(e) => setDay(r.day, { periods: [{ ...r.periods[0], close: e.target.value }] })} style={{ ...inputStyle, width: 116 }} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── More (additional) hours (Phase 3a) ────────────────────────────────────────
function MoreHoursCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: MoreHoursEntry[]; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [entries, setEntries] = useState<MoreHoursEntry[]>([])
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'morehours', onChanged)
  const proposed = Array.isArray(edit?.proposed_value) ? (edit!.proposed_value as MoreHoursEntry[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const typesQ = useQuery<{ categories: MoreHoursTypeCategory[] }>({
    queryKey: ['gbp-more-hours-types', clientId, locationRowId],
    queryFn: () => api.get(`/clients/${clientId}/gbp/profile/more-hours-types?location_row_id=${locationRowId}`),
    enabled: editing, retry: false, staleTime: 5 * 60_000,
  })
  const allTypes: MoreHoursType[] = (typesQ.data?.categories ?? []).flatMap((c) => c.more_hours_types)
  const typeName = (id: string) => allTypes.find((t) => t.hours_type_id === id)?.display_name || id
  const used = new Set(entries.map((e) => e.hours_type_id))
  const avail = allTypes.filter((t) => !used.has(t.hours_type_id))
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { more_hours: entries })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'more_hours', more_hours: entries }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  const setEntry = (i: number, regular: HoursRow[]) => setEntries((es) => es.map((e, j) => j === i ? { ...e, regular } : e))
  const summary = (e: MoreHoursEntry) => `${typeName(e.hours_type_id)}: ${e.regular.length} day(s)`
  return (
    <Card title="More hours" subtitle="Extra hours for a specific service — e.g. kitchen, delivery, or senior hours. Optional.">
      {current.length === 0 ? <CurrentValue empty>No additional hours set.</CurrentValue> : (
        <div style={{ display: 'grid', gap: 3, fontSize: 13 }}>{current.map((e, i) => <div key={i}>{summary(e)}</div>)}</div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{(proposed ?? []).map((e) => typeName(e.hours_type_id)).join(', ') || '(cleared)'}</span>} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
          {typesQ.isLoading ? <div style={{ fontSize: 12.5, color: '#64748b' }}>Loading additional-hours types…</div>
            : typesQ.isError ? <ErrorDetails message={(typesQ.error as Error)?.message} />
            : allTypes.length === 0 ? <div style={{ fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 10px' }}>This listing's category offers no additional-hours types.</div>
            : <>
              {entries.map((en, i) => (
                <div key={i} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 10, display: 'grid', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 13, fontWeight: 600 }}>{typeName(en.hours_type_id)}</span>
                    <button onClick={() => setEntries((es) => es.filter((_, j) => j !== i))} style={btn('#fff', '#b91c1c')}><Trash2 size={13} /></button>
                  </div>
                  <WeeklyHoursEditor rows={en.regular} onChange={(r) => setEntry(i, r)} />
                </div>
              ))}
              {avail.length > 0 && (
                <select value="" onChange={(e) => { if (e.target.value) setEntries([...entries, { hours_type_id: e.target.value, regular: [{ day: 0, open_24: false, periods: [{ open: '09:00', close: '17:00' }] }] }]) }} style={{ ...inputStyle, justifySelf: 'start', width: 'auto', minWidth: 220 }}>
                  <option value="">+ Add an additional-hours type…</option>
                  {avail.map((t) => <option key={t.hours_type_id} value={t.hours_type_id}>{t.display_name}</option>)}
                </select>
              )}
            </>}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={() => { setEntries((proposed ?? current ?? []).map((e) => ({ ...e, regular: e.regular.map((r) => ({ ...r })) }))); setEditing(true) }} style={btn('#fff', '#334155')}><Clock size={13} /> Edit more hours</button>
        </div>
      )}
    </Card>
  )
}

// ── Service area (Phase 3a) ───────────────────────────────────────────────────
function ServiceAreaCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: ServiceAreaValue; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [businessType, setBusinessType] = useState('CUSTOMER_AND_BUSINESS_LOCATION')
  const [places, setPlaces] = useState<ServiceAreaPlace[]>([])
  const [draft, setDraft] = useState('')
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'servicearea', onChanged)
  const proposed = edit && typeof edit.proposed_value === 'object' && edit.proposed_value ? (edit.proposed_value as ServiceAreaValue) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const startEdit = () => {
    const src = proposed ?? current
    setBusinessType(src?.business_type || 'CUSTOMER_AND_BUSINESS_LOCATION')
    setPlaces((src?.places ?? []).map((p) => ({ ...p })))
    setConfirmed(false); setDraft(''); setEditing(true)
  }
  const resolveMut = useMutation({
    mutationFn: (names: string[]) => api.post<{ places: ResolvedPlace[] }>(`/clients/${clientId}/gbp/profile/resolve-places`, { names }),
  })
  const addPlace = async () => {
    const v = draft.trim(); if (!v) return
    setDraft('')
    try {
      const { places: r } = await resolveMut.mutateAsync([v])
      const hit = r[0]
      setPlaces((ps) => [...ps, { name: hit?.name || v, place_id: hit?.matched ? hit.place_id : '' }])
    } catch { setPlaces((ps) => [...ps, { name: v, place_id: '' }]) }
  }
  const allResolved = places.every((p) => p.place_id)
  const value: ServiceAreaValue = { business_type: businessType, places, region_code: current?.region_code || 'US' }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { service_area: value })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'service_area', service_area: value }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  return (
    <Card title="Service area" subtitle="The areas a service-area business covers. Changing coverage affects where the listing can show — confirm before applying.">
      {(current?.places?.length ?? 0) === 0 ? <CurrentValue empty>No service area set.</CurrentValue> : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {current.places.map((p, i) => <span key={i} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#f1f5f9', color: '#334155' }}>{p.name}</span>)}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{(proposed?.places ?? []).map((p) => p.name).join(', ') || '(cleared)'}</span>} onChanged={onChanged} setErr={setErr} confirmBeforeApply={!confirmed} onNeedConfirm={startEdit} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          <select value={businessType} onChange={(e) => setBusinessType(e.target.value)} style={{ ...inputStyle, width: 'auto', minWidth: 260 }}>
            <option value="CUSTOMER_AND_BUSINESS_LOCATION">Storefront + service area</option>
            <option value="CUSTOMER_LOCATION_ONLY">Service area only (no storefront)</option>
          </select>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {places.map((p, i) => (
              <span key={i} title={p.place_id ? 'Resolved' : 'Not resolved — remove it'} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, padding: '3px 6px 3px 9px', borderRadius: 999, background: p.place_id ? '#f0fdf4' : '#fef2f2', color: p.place_id ? '#15803d' : '#b91c1c' }}>
                {p.place_id ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}{p.name}
                <button onClick={() => setPlaces(places.filter((_, j) => j !== i))} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'inherit', display: 'flex' }}><X size={12} /></button>
              </span>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addPlace() } }} placeholder="Add an area (e.g. Tampa, FL)…" style={inputStyle} />
            <button onClick={addPlace} disabled={!draft.trim() || resolveMut.isPending} style={btn('#fff', '#334155')}><MapPin size={13} /> {resolveMut.isPending ? 'Finding…' : 'Add'}</button>
          </div>
          {!allResolved && <div style={{ fontSize: 12, color: '#b45309' }}>Remove any area that didn’t resolve (⚠) before saving.</div>}
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: '#334155', marginTop: 2 }}>
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            I confirm this service-area change is correct.
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !allResolved || !confirmed} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}><MapPin size={13} /> Edit service area</button>
        </div>
      )}
    </Card>
  )
}

// ── Open / closed status (Phase 3a) ───────────────────────────────────────────
function OpenInfoCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: OpenInfoValue | null; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [status, setStatus] = useState('OPEN')
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'openinfo', onChanged)
  const proposed = edit && typeof edit.proposed_value === 'object' && edit.proposed_value ? (edit.proposed_value as OpenInfoValue) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })
  const curStatus = current?.status || 'OPEN'
  const isClosing = status.startsWith('CLOSED')
  const proposedClosing = (proposed?.status || '').startsWith('CLOSED')
  const startEdit = () => { setStatus(proposed?.status || curStatus); setConfirmed(false); setEditing(true) }
  const saveMut = useMutation({
    mutationFn: () => {
      const value: OpenInfoValue = { status }
      return edit && edit.status !== 'applied' && edit.status !== 'rejected'
        ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { open_info: value })
        : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'open_info', open_info: value })
    },
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })
  return (
    <Card title="Open / closed status" subtitle="Whether the business is open, temporarily closed, or permanently closed. The AI never closes a business.">
      <CurrentValue empty={!current}>{OPEN_STATUS_LABELS[curStatus] || curStatus}</CurrentValue>
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => <span>{OPEN_STATUS_LABELS[proposed?.status || ''] || proposed?.status}</span>} onChanged={onChanged} setErr={setErr} confirmBeforeApply={proposedClosing && !confirmed} onNeedConfirm={startEdit} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}
      {editing ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setConfirmed(false) }} style={{ ...inputStyle, width: 'auto', minWidth: 220 }}>
            {Object.entries(OPEN_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {isClosing && (
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 10px' }}>
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} style={{ marginTop: 2 }} />
              I confirm the business is {OPEN_STATUS_LABELS[status].toLowerCase()} — this removes it from normal search/Maps visibility.
            </label>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || (isClosing && !confirmed)} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}><Power size={13} /> Edit status</button>
        </div>
      )}
    </Card>
  )
}

// ── Categories (Phase 3b) ─────────────────────────────────────────────────────
function CategoriesCard({ clientId, locationRowId, current, edit, onChanged }: {
  clientId: string; locationRowId: string; current: CategoriesValue; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [primary, setPrimary] = useState<CategoryRef | null>(null)
  const [additional, setAdditional] = useState<CategoryRef[]>([])
  const [query, setQuery] = useState('')
  const { err, setErr, job } = useCardJobs(clientId, locationRowId, 'categories', () => { onChanged(); refresh() })
  const proposed = edit && typeof edit.proposed_value === 'object' && edit.proposed_value ? (edit.proposed_value as CategoriesValue) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  // Ask the AI to propose SECONDARY categories (never the primary), max 7. Lands
  // as a draft for review — nothing is applied automatically.
  const draft = () => { setErr(null); job.start(() => api.post<Job>(`/clients/${clientId}/gbp/profile/draft`, { location_row_id: locationRowId, field: 'categories' }).then((j) => j.job_id), undefined) }

  const startEdit = () => {
    const src = proposed ?? current
    setPrimary(src?.primary ?? null)
    setAdditional((src?.additional ?? []).map((c) => ({ ...c })))
    setQuery(''); setConfirmed(false); setEditing(true)
  }
  const searchQ = useQuery<{ categories: CategoryRef[] }>({
    queryKey: ['gbp-category-search', clientId, query.trim()],
    queryFn: () => api.get(`/clients/${clientId}/gbp/profile/categories/search?q=${encodeURIComponent(query.trim())}`),
    enabled: editing && query.trim().length >= 2, retry: false, staleTime: 5 * 60_000,
  })
  const primaryChanged = (primary?.id ?? '') !== (current?.primary?.id ?? '')
  const value: CategoriesValue = { primary, additional }

  const setAsPrimary = (c: CategoryRef) => {
    setAdditional((a) => a.filter((x) => x.id !== c.id).concat(primary && primary.id !== c.id ? [primary] : []))
    setPrimary(c); setConfirmed(false)
  }
  const addAdditional = (c: CategoryRef) => {
    if (c.id === primary?.id || additional.some((x) => x.id === c.id)) return
    setAdditional((a) => [...a, c])
  }
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { categories_value: value })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'categories', categories_value: value }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  return (
    <Card title="Categories" subtitle="The listing's primary + additional business categories. The AI proposes up to 7 secondary categories (never the primary). Changing the PRIMARY category shifts how the listing ranks — confirm before applying.">
      {!current?.primary ? <CurrentValue empty>No categories set.</CurrentValue> : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#eef2ff', color: '#3730a3', fontWeight: 600 }}>
            <Star size={11} /> {current.primary.name}
          </span>
          {current.additional.map((c) => <span key={c.id} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#f1f5f9', color: '#334155' }}>{c.name}</span>)}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => (
        <span>{[proposed?.primary?.name, ...(proposed?.additional ?? []).map((c) => c.name)].filter(Boolean).join(', ')}</span>
      )} onChanged={onChanged} setErr={setErr} confirmBeforeApply={(proposed?.primary?.id ?? '') !== (current?.primary?.id ?? '') && !confirmed} onNeedConfirm={startEdit} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}

      {editing ? (
        <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {primary ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#eef2ff', color: '#3730a3', fontWeight: 600 }}>
                <Star size={11} /> {primary.name} (primary)
              </span>
            ) : <span style={{ fontSize: 12, color: '#b45309' }}>No primary category picked.</span>}
            {additional.map((c) => (
              <span key={c.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, padding: '3px 6px 3px 9px', borderRadius: 999, background: '#f1f5f9', color: '#334155' }}>
                {c.name}
                <button onClick={() => setAdditional((a) => a.filter((x) => x.id !== c.id))} title="Remove" style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748b', display: 'flex' }}><X size={12} /></button>
              </span>
            ))}
          </div>
          <div style={{ position: 'relative' }}>
            <Search size={14} style={{ position: 'absolute', left: 10, top: 10, color: '#94a3b8' }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search Google's categories… (e.g. roofing)" style={{ ...inputStyle, paddingLeft: 30 }} />
          </div>
          {query.trim().length >= 2 && (
            searchQ.isLoading ? <div style={{ fontSize: 12.5, color: '#64748b' }}>Searching…</div>
              : searchQ.isError ? <ErrorDetails message={(searchQ.error as Error)?.message} />
              : (searchQ.data?.categories ?? []).length === 0 ? <div style={{ fontSize: 12.5, color: '#94a3b8' }}>No categories match “{query}”.</div>
              : (
                <div style={{ maxHeight: 240, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 8, padding: 4 }}>
                  {(searchQ.data?.categories ?? []).map((c) => {
                    const isPrimary = c.id === primary?.id
                    const isAdd = additional.some((x) => x.id === c.id)
                    return (
                      <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', fontSize: 13 }}>
                        <span style={{ flex: 1, color: '#0f172a' }}>{c.name}</span>
                        <button onClick={() => setAsPrimary(c)} disabled={isPrimary} style={{ ...btn('#fff', isPrimary ? '#94a3b8' : '#3730a3'), padding: '3px 8px', fontSize: 12 }}><Star size={11} /> {isPrimary ? 'Primary' : 'Set primary'}</button>
                        <button onClick={() => addAdditional(c)} disabled={isPrimary || isAdd} style={{ ...btn('#fff', isPrimary || isAdd ? '#94a3b8' : '#334155'), padding: '3px 8px', fontSize: 12 }}><Plus size={11} /> {isAdd ? 'Added' : 'Add'}</button>
                      </div>
                    )
                  })}
                </div>
              )
          )}
          {primaryChanged && (
            <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, padding: '8px 10px' }}>
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} style={{ marginTop: 2 }} />
              I confirm changing the PRIMARY category to “{primary?.name}” — this changes how the listing ranks.
            </label>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !primary || (primaryChanged && !confirmed)} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}><LayoutGrid size={13} /> Edit categories</button>
          <button onClick={draft} disabled={job.running || !current?.primary} style={btn('#fff', ACCENT)} title="Propose secondary categories (max 7)">
            <Sparkles size={13} /> {job.running ? 'Drafting…' : 'Suggest with AI'}
          </button>
        </div>
      )}
    </Card>
  )
}

// ── Attributes (SEPARATE getAttributes/updateAttributes endpoint pair) ─────────
function humanizeAttr(id: string): string {
  const bare = (id || '').replace(/^attributes\//, '').replace(/^[^:]*:/, '').replace(/_/g, ' ').trim()
  return bare ? bare.replace(/\b\w/g, (c) => c.toUpperCase()) : id
}
function attrHasValue(a?: AttributeValue): boolean {
  if (!a) return false
  if (a.value_type === 'URL') return (a.urls || []).some((u) => (u || '').trim())
  if (a.value_type === 'REPEATED_ENUM') return (a.set_values || []).length > 0
  return (a.values || []).length > 0
}
// A comparable key — a cleared/absent value is '' so "clear" == "not present".
function attrKey(a?: AttributeValue): string {
  if (!a) return ''
  if (a.value_type === 'URL') {
    const u = (a.urls || []).map((s) => (s || '').trim()).filter(Boolean).sort()
    return u.length ? 'URL:' + u.join('|') : ''
  }
  if (a.value_type === 'REPEATED_ENUM') {
    const s = (a.set_values || []).map(String).sort()
    return s.length ? 'RE:' + s.join('|') : ''
  }
  const v = (a.values || []).map(String)
  return v.length ? a.value_type + ':' + v.join('|') : ''
}
function attrSummary(a: AttributeValue, meta?: AttributeMetaItem): string {
  const optLabel = (val: string) =>
    meta?.value_options?.find((o) => String(o.value) === val)?.display_name || val
  if (a.value_type === 'BOOL') return (a.values || []).length ? (a.values![0] ? 'Yes' : 'No') : '—'
  if (a.value_type === 'URL') return (a.urls || []).filter(Boolean).join(', ') || '—'
  if (a.value_type === 'REPEATED_ENUM') return (a.set_values || []).map(optLabel).join(', ') || '—'
  return (a.values || []).map((v) => optLabel(String(v))).join(', ') || '—'
}

function AttributesCard({ clientId, locationRowId, current, currentError, edit, onChanged }: {
  clientId: string; locationRowId: string; current: AttributeValue[]
  currentError?: string | null; edit?: ProfileEdit; onChanged: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [working, setWorking] = useState<Record<string, AttributeValue>>({})
  const [query, setQuery] = useState('')
  const { err, setErr } = useCardJobs(clientId, locationRowId, 'attributes', onChanged)
  const proposed = edit && Array.isArray(edit.proposed_value) ? (edit.proposed_value as AttributeValue[]) : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['gbp-profile', clientId, locationRowId] })

  const availQ = useQuery<{ attributes: AttributeMetaItem[] }>({
    queryKey: ['gbp-attributes-available', clientId, locationRowId],
    queryFn: () => api.get(`/clients/${clientId}/gbp/profile/attributes/available?location_row_id=${locationRowId}`),
    enabled: editing, retry: false, staleTime: 5 * 60_000,
  })
  const metaById = new Map((availQ.data?.attributes ?? []).map((m) => [m.attribute_id, m]))
  const currentById = new Map(current.map((a) => [a.attribute_id, a]))

  const startEdit = () => {
    const base: Record<string, AttributeValue> = {}
    for (const a of current) base[a.attribute_id] = { ...a }
    for (const a of proposed ?? []) base[a.attribute_id] = { ...a }  // draft's changes win
    setWorking(base); setQuery(''); setEditing(true)
  }
  const setWork = (id: string, next: AttributeValue) => setWorking((w) => ({ ...w, [id]: next }))
  const ensure = (m: AttributeMetaItem): AttributeValue =>
    working[m.attribute_id] ?? currentById.get(m.attribute_id) ??
    { attribute_id: m.attribute_id, value_type: m.value_type }

  // The subset of changed attributes (set or clear vs the live current value).
  const subset: AttributeValue[] = Object.values(working).filter(
    (w) => attrKey(w) !== attrKey(currentById.get(w.attribute_id)),
  )
  const saveMut = useMutation({
    mutationFn: () => edit && edit.status !== 'applied' && edit.status !== 'rejected'
      ? api.patch(`/clients/${clientId}/gbp/profile/edits/${edit.id}`, { attributes: subset })
      : api.post(`/clients/${clientId}/gbp/profile/edits`, { location_row_id: locationRowId, field: 'attributes', attributes: subset }),
    onSuccess: () => { setEditing(false); setErr(null); refresh() },
    onError: (e: Error) => setErr(e.message),
  })

  const rows = (availQ.data?.attributes ?? []).filter((m) => !m.deprecated).filter((m) => {
    const q = query.trim().toLowerCase()
    return !q || m.display_name.toLowerCase().includes(q) || m.group_name.toLowerCase().includes(q)
  })

  return (
    <Card title="Attributes" subtitle="Listing attributes (accessibility, amenities, service options, identity, links…). Only the attributes Google offers for this listing’s category can be set.">
      {currentError ? <ErrorDetails message={currentError} /> : current.length === 0 ? (
        <CurrentValue empty>No attributes set.</CurrentValue>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {current.map((a) => (
            <span key={a.attribute_id} style={{ fontSize: 12, padding: '3px 9px', borderRadius: 999, background: '#f1f5f9', color: '#334155' }}>
              {humanizeAttr(a.attribute_id)}: {attrSummary(a, metaById.get(a.attribute_id))}
            </span>
          ))}
        </div>
      )}
      {edit && <ProposedRow edit={edit} clientId={clientId} locationRowId={locationRowId} render={() => (
        <span>{(proposed ?? []).map((a) => `${humanizeAttr(a.attribute_id)}: ${attrHasValue(a) ? attrSummary(a, metaById.get(a.attribute_id)) : '(clear)'}`).join(' · ') || '(no changes)'}</span>
      )} onChanged={onChanged} setErr={setErr} />}
      {err && <ErrorDetails message={err} style={{ marginTop: 4 }} />}

      {editing ? (
        <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
          <div style={{ position: 'relative' }}>
            <Search size={14} style={{ position: 'absolute', left: 10, top: 10, color: '#94a3b8' }} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter attributes… (e.g. wheelchair, appointment)" style={{ ...inputStyle, paddingLeft: 30 }} />
          </div>
          {availQ.isLoading ? <div style={{ fontSize: 12.5, color: '#64748b' }}>Loading available attributes…</div>
            : availQ.isError ? <ErrorDetails message={(availQ.error as Error)?.message} />
            : rows.length === 0 ? <div style={{ fontSize: 12.5, color: '#94a3b8' }}>{query.trim() ? 'No attributes match.' : 'No editable attributes for this listing.'}</div>
            : (
              <div style={{ maxHeight: 340, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 8, padding: 4, display: 'grid', gap: 2 }}>
                {rows.map((m) => (
                  <AttributeRow key={m.attribute_id} meta={m} value={ensure(m)} onChange={(v) => setWork(m.attribute_id, v)} />
                ))}
              </div>
            )}
          <div style={{ fontSize: 12, color: subset.length ? '#0f766e' : '#94a3b8' }}>
            {subset.length ? `${subset.length} change${subset.length === 1 ? '' : 's'} to save.` : 'No changes yet.'}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || subset.length === 0} style={btn(ACCENT)}><Save size={13} /> Save draft</button>
            <button onClick={() => setEditing(false)} style={btn('#fff', '#334155')}><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button onClick={startEdit} style={btn('#fff', '#334155')}><SlidersHorizontal size={13} /> Edit attributes</button>
        </div>
      )}
    </Card>
  )
}

function AttributeRow({ meta, value, onChange }: {
  meta: AttributeMetaItem; value: AttributeValue; onChange: (v: AttributeValue) => void
}) {
  const base: AttributeValue = { attribute_id: meta.attribute_id, value_type: meta.value_type }
  const opts = meta.value_options ?? []
  let control: React.ReactNode = null
  if (meta.value_type === 'BOOL') {
    const state = (value.values ?? []).length ? (value.values![0] ? 'yes' : 'no') : 'unset'
    control = (
      <div style={{ display: 'flex', gap: 4 }}>
        {(['unset', 'yes', 'no'] as const).map((s) => (
          <button key={s} onClick={() => onChange({ ...base, values: s === 'unset' ? [] : [s === 'yes'] })}
            style={{ ...btn(state === s ? ACCENT : '#fff', state === s ? '#fff' : '#334155'), padding: '3px 9px', fontSize: 12 }}>
            {s === 'unset' ? 'Unset' : s === 'yes' ? 'Yes' : 'No'}
          </button>
        ))}
      </div>
    )
  } else if (meta.value_type === 'ENUM') {
    const sel = (value.values ?? [])[0]
    control = (
      <select value={sel != null ? String(sel) : ''} onChange={(e) => onChange({ ...base, values: e.target.value ? [e.target.value] : [] })}
        style={{ ...inputStyle, width: 'auto', minWidth: 160, padding: '6px 8px' }}>
        <option value="">(unset)</option>
        {opts.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.display_name}</option>)}
      </select>
    )
  } else if (meta.value_type === 'REPEATED_ENUM') {
    const set = new Set((value.set_values ?? []).map(String))
    control = (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {opts.map((o) => {
          const v = String(o.value)
          const on = set.has(v)
          return (
            <label key={v} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#334155' }}>
              <input type="checkbox" checked={on} onChange={() => {
                const next = new Set(set); on ? next.delete(v) : next.add(v)
                onChange({ ...base, set_values: [...next] })
              }} />
              {o.display_name}
            </label>
          )
        })}
      </div>
    )
  } else {  // URL
    control = (
      <input value={(value.urls ?? [])[0] ?? ''} onChange={(e) => onChange({ ...base, urls: e.target.value.trim() ? [e.target.value.trim()] : [] })}
        placeholder="https://…" style={{ ...inputStyle, width: 'auto', minWidth: 220, padding: '6px 8px' }} />
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', fontSize: 13 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: '#0f172a' }}>{meta.display_name}</div>
        {meta.group_name && <div style={{ fontSize: 11, color: '#94a3b8' }}>{meta.group_name}</div>}
      </div>
      {control}
    </div>
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
