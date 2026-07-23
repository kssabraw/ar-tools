import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Megaphone, Trash2, RotateCcw, ExternalLink, RefreshCw, Sparkles,
  CalendarClock, Send, Save, X, Upload, ImageIcon, CheckCircle2, XCircle, Clock, Link2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Google Business Profile Posts — compose (manual + AI-drafted) and publish
// GBP posts (Updates / Offers / Events / Products) to a client's listing via
// the v4 localPosts API. Backend gated on gbp_api_enabled + gbp_posts_enabled;
// when off, every endpoint 503s and we render an enablement notice.

const ACCENT = '#6366f1'

type TopicType = 'standard' | 'offer' | 'event' | 'product'
type CtaType = 'book' | 'order' | 'shop' | 'learn_more' | 'sign_up' | 'call'
type PostStatus = 'draft' | 'scheduled' | 'publishing' | 'live' | 'rejected' | 'failed' | 'deleted'

interface GbpLocation { id: string; location_id: string; title: string | null; access_status: string }
interface ReusableImage { url: string; source: string; label: string | null }
interface GbpPost {
  id: string; location_row_id: string; source: string; topic_type: TopicType
  summary: string; cta_type: CtaType | null; cta_url: string | null
  event: Record<string, unknown> | null; offer: Record<string, unknown> | null
  media: { sourceUrl?: string }[] | null; status: PostStatus
  scheduled_at: string | null; published_at: string | null
  search_url: string | null; error: string | null; created_at: string | null
}
interface JobStatus { job_id: string; status: string; post_id: string | null; error: string | null }
interface GbpSchedule {
  location_row_id: string | null; cadence: string; day_of_week: number | null
  day_of_month: number | null; hour_local: number; topic_type: TopicType
  theme_notes: string | null; cta_type: CtaType | null; cta_url: string | null
  auto_publish: boolean; is_active: boolean; next_run_at: string | null; last_run_at: string | null
  timezone: string | null
}

// The client's local timezone GBP scheduling is expressed in (derived from the
// GBP location server-side). null → fall back to the viewer's browser timezone.
function useClientTz(clientId: string): string | null {
  const { data } = useQuery<{ timezone: string | null }>({
    queryKey: ['gbp-tz', clientId],
    queryFn: () => api.get<{ timezone: string | null }>(`/clients/${clientId}/gbp/timezone`),
  })
  return data?.timezone ?? null
}

// Format a UTC ISO instant in the client's timezone (or the browser's if unknown).
function fmtInTz(iso: string, tz: string | null): string {
  const d = new Date(iso)
  return tz
    ? d.toLocaleString('en-US', { timeZone: tz, dateStyle: 'medium', timeStyle: 'short' })
    : d.toLocaleString()
}

// Short label for a timezone (e.g. "America/Los_Angeles" → "client local time
// · America/Los_Angeles"); a plain UTC note when unknown.
function tzLabel(tz: string | null): string {
  return tz ? `client local time · ${tz}` : 'UTC'
}

const TYPE_OPTIONS: { value: TopicType; label: string; hint: string }[] = [
  { value: 'standard', label: 'Update', hint: "A general update or 'What's New' post." },
  { value: 'offer', label: 'Offer', hint: 'A promotion with an optional coupon code, terms & validity window.' },
  { value: 'event', label: 'Event', hint: 'An event with a title and start/end date & time.' },
  { value: 'product', label: 'Product', hint: 'Spotlights a product. Publishes as an Update — Google has no product-post API.' },
]
const CTA_OPTIONS: { value: CtaType; label: string }[] = [
  { value: 'learn_more', label: 'Learn more' }, { value: 'book', label: 'Book' },
  { value: 'order', label: 'Order online' }, { value: 'shop', label: 'Shop' },
  { value: 'sign_up', label: 'Sign up' }, { value: 'call', label: 'Call' },
]
const STATUS_META: Record<PostStatus, { label: string; color: string; bg: string }> = {
  draft: { label: 'Draft', color: '#475569', bg: '#f1f5f9' },
  scheduled: { label: 'Scheduled', color: '#7c3aed', bg: '#f5f3ff' },
  publishing: { label: 'Publishing…', color: '#b45309', bg: '#fffbeb' },
  live: { label: 'Live', color: '#15803d', bg: '#f0fdf4' },
  rejected: { label: 'Rejected', color: '#b91c1c', bg: '#fef2f2' },
  failed: { label: 'Failed', color: '#b91c1c', bg: '#fef2f2' },
  deleted: { label: 'Deleted', color: '#64748b', bg: '#f8fafc' },
}
const MAX_CHARS = 1500

// google.type.Date / TimeOfDay builders from HTML date/time input values.
function dateToGoogle(v: string) {
  if (!v) return undefined
  const [y, m, d] = v.split('-').map(Number)
  return { year: y, month: m, day: d }
}
function timeToGoogle(v: string) {
  if (!v) return undefined
  const [h, min] = v.split(':').map(Number)
  return { hours: h, minutes: min }
}

async function pollJob(clientId: string, jobId: string): Promise<JobStatus> {
  const started = Date.now()
  for (;;) {
    const rows = await api.post<JobStatus[]>(`/clients/${clientId}/gbp/posts/jobs/status`, { job_ids: [jobId] })
    const row = rows[0]
    if (row && ['complete', 'failed', 'cancelled'].includes(row.status)) return row
    if (Date.now() - started > 150000) return { job_id: jobId, status: 'timeout', post_id: null, error: 'timed_out' }
    await new Promise((r) => setTimeout(r, 2500))
  }
}

const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: bg === '#fff' ? '1px solid #e2e8f0' : 'none', background: bg, color: fg,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
})
const input: React.CSSProperties = {
  width: '100%', padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13,
  fontFamily: 'inherit', boxSizing: 'border-box',
}
const label: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4, display: 'block' }

export function GbpPosts() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'compose' | 'posts' | 'schedule' | 'trash'>('compose')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id], queryFn: () => api.get<Client>(`/clients/${id}`), enabled: Boolean(id),
  })
  const locationsQ = useQuery<GbpLocation[]>({
    queryKey: ['gbp-post-locations', id],
    queryFn: () => api.get<GbpLocation[]>(`/clients/${id}/gbp/post-locations`),
    enabled: Boolean(id), retry: false,
  })

  const disabled = (locationsQ.error as Error | null)?.message === 'gbp_posts_not_enabled'

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <Link to={`/clients/${id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: ACCENT, textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Megaphone size={22} color={ACCENT} />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>GBP Posts</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 20 }}>
        Compose and publish Google Business Profile posts — Updates, Offers, Events & Products — to this client's listing.
      </p>

      <ConnectionBar />

      {disabled ? (
        <EnablementNotice />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #e2e8f0' }}>
            {(['compose', 'posts', 'schedule', 'trash'] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                style={{ padding: '9px 16px', border: 'none', borderBottom: tab === t ? `2px solid ${ACCENT}` : '2px solid transparent', background: 'none', color: tab === t ? ACCENT : '#64748b', fontSize: 13, fontWeight: 600, cursor: 'pointer', textTransform: 'capitalize' }}>
                {t === 'posts' ? 'Posts' : t}
              </button>
            ))}
          </div>

          {locationsQ.isLoading ? (
            <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
          ) : (locationsQ.data ?? []).length === 0 ? (
            <NoLocations />
          ) : tab === 'compose' ? (
            <ComposeTab clientId={id!} locations={locationsQ.data!} onDone={() => { setTab('posts'); qc.invalidateQueries({ queryKey: ['gbp-posts', id] }) }} />
          ) : tab === 'posts' ? (
            <PostsTab clientId={id!} />
          ) : tab === 'schedule' ? (
            <ScheduleTab clientId={id!} locations={locationsQ.data!} />
          ) : (
            <TrashTab clientId={id!} />
          )}
        </>
      )}
    </div>
  )
}

// ── Connect Google Business Profile (agency-account OAuth) ───────────────────
interface OauthStatus { client_configured: boolean; connected: boolean; account_email: string | null; auth_mode: string }
function ConnectionBar() {
  const qc = useQueryClient()
  const [notice, setNotice] = useState<{ ok: boolean; msg: string } | null>(null)
  const { data } = useQuery<OauthStatus>({
    queryKey: ['gbp-oauth-status'], queryFn: () => api.get<OauthStatus>('/gbp/oauth/status'),
  })
  // Handle the redirect back from Google (?gbp_connected / ?gbp_error), then
  // strip the params from the URL so a refresh doesn't re-show the banner.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search)
    if (p.get('gbp_connected')) { setNotice({ ok: true, msg: 'Connected to Google Business Profile.' }); qc.invalidateQueries({ queryKey: ['gbp-oauth-status'] }) }
    else if (p.get('gbp_error')) setNotice({ ok: false, msg: `Connection failed: ${p.get('gbp_error')}` })
    if (p.get('gbp_connected') || p.get('gbp_error')) {
      p.delete('gbp_connected'); p.delete('gbp_error')
      window.history.replaceState({}, '', window.location.pathname + (p.toString() ? `?${p}` : ''))
    }
  }, [qc])

  const connect = async () => {
    try {
      const r = await api.get<{ auth_url?: string; error?: string }>(`/gbp/oauth/start?return_to=${encodeURIComponent(window.location.href)}`)
      if (r.auth_url) window.location.href = r.auth_url
      else setNotice({ ok: false, msg: r.error === 'oauth_client_not_configured' ? 'The Google OAuth client isn’t configured on the server yet.' : (r.error || 'Could not start Connect.') })
    } catch (e) { setNotice({ ok: false, msg: (e as Error).message === 'forbidden' ? 'Only an admin/staff user can connect.' : (e as Error).message }) }
  }
  const disconnectMut = useMutation({
    mutationFn: () => api.post('/gbp/oauth/disconnect', {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['gbp-oauth-status'] }),
    onError: (e: Error) => setNotice({ ok: false, msg: e.message === 'forbidden' ? 'Only an admin/staff user can disconnect.' : e.message }),
  })
  const acceptMut = useMutation({
    mutationFn: () => api.post<{ accepted: number; pending: number }>('/gbp/oauth/accept-invitations', {}),
    onSuccess: (r) => setNotice({ ok: true, msg: r.accepted > 0 ? `Accepted ${r.accepted} access invitation${r.accepted === 1 ? '' : 's'}.` : 'No pending access invitations.' }),
    onError: (e: Error) => setNotice({ ok: false, msg: e.message === 'forbidden' ? 'Only an admin/staff user can do this.' : e.message }),
  })

  if (!data) return null
  const bar: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderRadius: 10, fontSize: 13, marginBottom: 16 }
  return (
    <div>
      {notice && (
        <div style={{ ...bar, background: notice.ok ? '#f0fdf4' : '#fef2f2', border: `1px solid ${notice.ok ? '#bbf7d0' : '#fecaca'}`, color: notice.ok ? '#15803d' : '#b91c1c' }}>
          {notice.ok ? <CheckCircle2 size={15} /> : <XCircle size={15} />} {notice.msg}
        </div>
      )}
      {data.connected ? (
        <div style={{ ...bar, background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#15803d' }}>
          <CheckCircle2 size={15} />
          <span>Connected to Google Business Profile{data.account_email ? ` as ${data.account_email}` : ''}.</span>
          <button onClick={() => acceptMut.mutate()} disabled={acceptMut.isPending} title="Accept manager invitations clients have sent to the connected account" style={{ ...btn('#fff', '#334155'), marginLeft: 'auto' }}>
            {acceptMut.isPending ? 'Checking…' : 'Accept access invitations'}
          </button>
          <button onClick={() => disconnectMut.mutate()} disabled={disconnectMut.isPending} style={btn('#fff', '#334155')}>
            {disconnectMut.isPending ? 'Disconnecting…' : 'Disconnect'}
          </button>
        </div>
      ) : data.client_configured ? (
        <div style={{ ...bar, background: '#eef2ff', border: '1px solid #c7d2fe', color: '#3730a3' }}>
          <Link2 size={15} />
          <span>Connect the agency Google account that manages these listings — one click, no per-client setup.</span>
          <button onClick={connect} style={{ ...btn(ACCENT), marginLeft: 'auto' }}>Connect Google Business Profile</button>
        </div>
      ) : (
        <div style={{ ...bar, background: '#f8fafc', border: '1px solid #e2e8f0', color: '#64748b' }}>
          <Link2 size={15} />
          <span>One-click Connect isn't available yet — an admin needs to configure the Google OAuth client (server env: client id / secret / redirect URI).</span>
        </div>
      )}
    </div>
  )
}

function EnablementNotice() {
  return (
    <div style={{ padding: 20, borderRadius: 12, background: '#fffbeb', border: '1px solid #fde68a', fontSize: 13, color: '#92400e', lineHeight: 1.6 }}>
      <strong>GBP Posts isn't turned on yet.</strong>
      <p style={{ margin: '8px 0 0' }}>
        This tool is built but gated off. To activate it: connect the agency Google account (the Connect button above),
        then set <code>GBP_API_ENABLED</code> and <code>GBP_POSTS_ENABLED</code> on the platform service.
      </p>
    </div>
  )
}
function NoLocations() {
  return (
    <div style={{ padding: 20, borderRadius: 12, background: '#f8fafc', border: '1px solid #e2e8f0', fontSize: 13, color: '#475569', lineHeight: 1.6 }}>
      No Business Profile location is registered for this client yet. Add the service account as a Manager on the
      client's Google Business Profile and register the location (GBP connection) before posting.
    </div>
  )
}

// ── Image field (upload + reuse existing) ────────────────────────────────────
function ImageField({ clientId, value, onChange }: { clientId: string; value: string | null; onChange: (url: string | null) => void }) {
  const [showReuse, setShowReuse] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const reuseQ = useQuery<ReusableImage[]>({
    queryKey: ['gbp-reusable-images', clientId],
    queryFn: () => api.get<ReusableImage[]>(`/clients/${clientId}/gbp/posts/reusable-images`),
    enabled: showReuse,
  })
  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData(); form.append('file', file)
      return api.upload<{ url: string }>(`/clients/${clientId}/gbp/posts/image`, form)
    },
    onSuccess: (r) => { setErr(null); onChange(r.url) },
    onError: (e: Error) => setErr(e.message),
  })

  return (
    <div>
      <label style={label}>Image <span style={{ color: '#94a3b8', fontWeight: 400 }}>(JPG/PNG, ≥250×250px — recommended)</span></label>
      {value ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <img src={value} alt="" style={{ width: 96, height: 96, objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0' }} />
          <button onClick={() => onChange(null)} style={btn('#fff', '#334155')}><X size={13} /> Remove</button>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <label style={{ ...btn('#fff', '#334155'), cursor: uploadMut.isPending ? 'wait' : 'pointer' }}>
            <Upload size={13} /> {uploadMut.isPending ? 'Uploading…' : 'Upload'}
            <input type="file" accept="image/jpeg,image/png" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadMut.mutate(f) }} />
          </label>
          <button onClick={() => setShowReuse((s) => !s)} style={btn('#fff', '#334155')}><ImageIcon size={13} /> Reuse existing</button>
        </div>
      )}
      {err && <div style={{ color: '#b91c1c', fontSize: 12, marginTop: 6 }}>{err === 'image_dimensions_too_small' ? 'Image must be at least 250×250px.' : err === 'unsupported_image_type' ? 'Use a JPG or PNG image.' : err}</div>}
      {showReuse && !value && (
        <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(84px,1fr))', gap: 8, maxHeight: 200, overflowY: 'auto', padding: 8, border: '1px solid #e2e8f0', borderRadius: 8 }}>
          {reuseQ.isLoading ? <span style={{ fontSize: 12, color: '#94a3b8' }}>Loading…</span>
            : (reuseQ.data ?? []).length === 0 ? <span style={{ fontSize: 12, color: '#94a3b8' }}>No existing images for this client.</span>
            : reuseQ.data!.map((im) => (
              <img key={im.url} src={im.url} alt={im.label ?? ''} title={im.label ?? im.source}
                onClick={() => { onChange(im.url); setShowReuse(false) }}
                style={{ width: '100%', height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0', cursor: 'pointer' }} />
            ))}
        </div>
      )}
    </div>
  )
}

// ── Compose ──────────────────────────────────────────────────────────────────
function ComposeTab({ clientId, locations, onDone }: { clientId: string; locations: GbpLocation[]; onDone: () => void }) {
  const okLocations = locations.filter((l) => l.access_status === 'ok')
  const [locationId, setLocationId] = useState(okLocations[0]?.id ?? locations[0]?.id ?? '')
  const [type, setType] = useState<TopicType>('standard')
  const [summary, setSummary] = useState('')
  const [ctaType, setCtaType] = useState<CtaType | ''>('')
  const [ctaUrl, setCtaUrl] = useState('')
  const [image, setImage] = useState<string | null>(null)
  // offer/event fields
  const [eventTitle, setEventTitle] = useState('')
  const [startDate, setStartDate] = useState(''); const [startTime, setStartTime] = useState('')
  const [endDate, setEndDate] = useState(''); const [endTime, setEndTime] = useState('')
  const [couponCode, setCouponCode] = useState(''); const [redeemUrl, setRedeemUrl] = useState(''); const [terms, setTerms] = useState('')
  // ai draft + scheduling
  const [theme, setTheme] = useState(''); const [sourceUrl, setSourceUrl] = useState('')
  const [scheduleAt, setScheduleAt] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const tz = useClientTz(clientId)

  const needsEvent = type === 'offer' || type === 'event'

  function buildBody() {
    const body: Record<string, unknown> = {
      location_row_id: locationId, topic_type: type, summary: summary.trim(),
      cta_type: ctaType || null, cta_url: ctaType && ctaType !== 'call' ? ctaUrl.trim() || null : null,
      media: image ? [{ sourceUrl: image }] : null,
    }
    if (needsEvent) {
      const schedule: Record<string, unknown> = {}
      if (startDate) schedule.startDate = dateToGoogle(startDate)
      if (type === 'event' && startTime) schedule.startTime = timeToGoogle(startTime)
      if (endDate) schedule.endDate = dateToGoogle(endDate)
      if (type === 'event' && endTime) schedule.endTime = timeToGoogle(endTime)
      body.event = { title: eventTitle.trim(), schedule }
    }
    if (type === 'offer') {
      const offer: Record<string, unknown> = {}
      if (couponCode.trim()) offer.couponCode = couponCode.trim()
      if (redeemUrl.trim()) offer.redeemOnlineUrl = redeemUrl.trim()
      if (terms.trim()) offer.termsConditions = terms.trim()
      body.offer = Object.keys(offer).length ? offer : null
    }
    return body
  }

  const valid = locationId && summary.trim() && (!needsEvent || (eventTitle.trim() && startDate)) && (!ctaType || ctaType === 'call' || ctaUrl.trim())

  async function submit(action: 'draft' | 'publish' | 'schedule') {
    setError(null); setBusy(action)
    try {
      const post = await api.post<GbpPost>(`/clients/${clientId}/gbp/posts`, buildBody())
      if (action === 'publish') {
        const { job_id } = await api.post<{ job_id: string }>(`/clients/${clientId}/gbp/posts/${post.id}/publish`, {})
        await pollJob(clientId, job_id)
      } else if (action === 'schedule') {
        // tz known → send the raw wall-clock; the backend interprets it in the
        // client's timezone. tz unknown → resolve in the browser tz to a UTC ISO
        // (graceful fallback, matches the backend's naive-as-UTC path).
        const scheduled_at = tz ? scheduleAt : new Date(scheduleAt).toISOString()
        await api.post(`/clients/${clientId}/gbp/posts/${post.id}/schedule`, { scheduled_at })
      }
      onDone()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const aiDraft = useMutation({
    mutationFn: async () => {
      const { job_id } = await api.post<{ job_id: string }>(`/clients/${clientId}/gbp/posts/generate`, {
        location_row_id: locationId, topic_type: type, theme: theme.trim() || null,
        source_url: sourceUrl.trim() || null, cta_type: ctaType || null, cta_url: ctaUrl.trim() || null,
      })
      const done = await pollJob(clientId, job_id)
      if (done.status !== 'complete' || !done.post_id) throw new Error(done.error || 'draft_failed')
      return api.get<GbpPost>(`/gbp/posts/${done.post_id}`)
    },
    onSuccess: (p) => { setSummary(p.summary); setError(null) },
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 640 }}>
      {okLocations.length === 0 && (
        <div style={{ fontSize: 12, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', padding: 10, borderRadius: 8 }}>
          No verified location — posts can't publish until the service account is a Manager and the location shows “ok”.
        </div>
      )}
      {locations.length > 1 && (
        <div>
          <label style={label}>Location</label>
          <select value={locationId} onChange={(e) => setLocationId(e.target.value)} style={input}>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.title || l.location_id}{l.access_status !== 'ok' ? ` (${l.access_status})` : ''}</option>)}
          </select>
        </div>
      )}

      <div>
        <label style={label}>Post type</label>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {TYPE_OPTIONS.map((t) => (
            <button key={t.value} onClick={() => setType(t.value)}
              style={{ padding: '7px 14px', borderRadius: 8, border: `1px solid ${type === t.value ? ACCENT : '#e2e8f0'}`, background: type === t.value ? '#eef2ff' : '#fff', color: type === t.value ? ACCENT : '#475569', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              {t.label}
            </button>
          ))}
        </div>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>{TYPE_OPTIONS.find((t) => t.value === type)!.hint}</p>
      </div>

      {needsEvent && (
        <div style={{ display: 'grid', gap: 12, padding: 12, border: '1px solid #e2e8f0', borderRadius: 10, background: '#fafafa' }}>
          <div>
            <label style={label}>{type === 'offer' ? 'Offer title' : 'Event title'}</label>
            <input value={eventTitle} onChange={(e) => setEventTitle(e.target.value)} style={input} placeholder={type === 'offer' ? 'e.g. 15% off spring roof inspections' : 'e.g. Fall community open house'} />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={label}>Start date</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={input} />
            </div>
            {type === 'event' && <div style={{ flex: 1 }}><label style={label}>Start time</label><input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} style={input} /></div>}
            <div style={{ flex: 1 }}>
              <label style={label}>End date</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={input} />
            </div>
            {type === 'event' && <div style={{ flex: 1 }}><label style={label}>End time</label><input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} style={input} /></div>}
          </div>
          {type === 'offer' && (
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}><label style={label}>Coupon code</label><input value={couponCode} onChange={(e) => setCouponCode(e.target.value)} style={input} placeholder="optional" /></div>
              <div style={{ flex: 1 }}><label style={label}>Redeem URL</label><input value={redeemUrl} onChange={(e) => setRedeemUrl(e.target.value)} style={input} placeholder="optional" /></div>
            </div>
          )}
          {type === 'offer' && <div><label style={label}>Terms</label><input value={terms} onChange={(e) => setTerms(e.target.value)} style={input} placeholder="optional" /></div>}
        </div>
      )}

      {/* AI draft */}
      <div style={{ padding: 12, border: '1px dashed #c7d2fe', borderRadius: 10, background: '#f5f3ff' }}>
        <label style={{ ...label, color: ACCENT }}><Sparkles size={12} style={{ verticalAlign: -1 }} /> AI draft</label>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <input value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="Topic / angle (optional)" style={{ ...input, flex: 2, minWidth: 160 }} />
          <input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="Announce a page URL (optional)" style={{ ...input, flex: 2, minWidth: 160 }} />
          <button onClick={() => aiDraft.mutate()} disabled={!locationId || aiDraft.isPending} style={btn(ACCENT)}>
            {aiDraft.isPending ? 'Drafting…' : 'Draft with AI'}
          </button>
        </div>
      </div>

      <div>
        <label style={label}>Post text</label>
        <textarea value={summary} onChange={(e) => setSummary(e.target.value.slice(0, MAX_CHARS))} rows={5}
          placeholder="Write your post…" style={{ ...input, resize: 'vertical' }} />
        <div style={{ fontSize: 11, color: summary.length > MAX_CHARS - 100 ? '#b45309' : '#94a3b8', textAlign: 'right', marginTop: 2 }}>{summary.length}/{MAX_CHARS}</div>
      </div>

      <ImageField clientId={clientId} value={image} onChange={setImage} />

      <div>
        <label style={label}>Call to action <span style={{ color: '#94a3b8', fontWeight: 400 }}>(optional)</span></label>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={ctaType} onChange={(e) => setCtaType(e.target.value as CtaType | '')} style={{ ...input, flex: 1 }}>
            <option value="">No button</option>
            {CTA_OPTIONS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          {ctaType && ctaType !== 'call' && (
            <input value={ctaUrl} onChange={(e) => setCtaUrl(e.target.value)} placeholder="https://…" style={{ ...input, flex: 2 }} />
          )}
        </div>
      </div>

      {error && <div style={{ color: '#b91c1c', fontSize: 13, background: '#fef2f2', border: '1px solid #fecaca', padding: 10, borderRadius: 8 }}>{error}</div>}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', borderTop: '1px solid #f1f5f9', paddingTop: 14 }}>
        <button onClick={() => submit('draft')} disabled={!valid || busy !== null} style={{ ...btn('#fff', '#334155'), opacity: valid ? 1 : 0.5 }}>
          <Save size={13} /> {busy === 'draft' ? 'Saving…' : 'Save draft'}
        </button>
        <button onClick={() => submit('publish')} disabled={!valid || busy !== null || okLocations.length === 0} style={{ ...btn('#16a34a'), opacity: valid && okLocations.length ? 1 : 0.5 }}>
          <Send size={13} /> {busy === 'publish' ? 'Publishing…' : 'Publish now'}
        </button>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginLeft: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <input type="datetime-local" value={scheduleAt} onChange={(e) => setScheduleAt(e.target.value)} style={{ ...input, width: 200 }} title={`Publish time — ${tzLabel(tz)}`} />
            <span style={{ fontSize: 10, color: '#94a3b8' }}>{tzLabel(tz)}</span>
          </div>
          <button onClick={() => submit('schedule')} disabled={!valid || !scheduleAt || busy !== null} style={{ ...btn(ACCENT), opacity: valid && scheduleAt ? 1 : 0.5 }}>
            <CalendarClock size={13} /> {busy === 'schedule' ? 'Scheduling…' : 'Schedule'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Posts list ───────────────────────────────────────────────────────────────
function PostsTab({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<GbpPost[]>({
    queryKey: ['gbp-posts', clientId], queryFn: () => api.get<GbpPost[]>(`/clients/${clientId}/gbp/posts`),
  })
  const invalidate = () => qc.invalidateQueries({ queryKey: ['gbp-posts', clientId] })
  const [pending, setPending] = useState<string | null>(null)
  const tz = useClientTz(clientId)

  async function run(fn: () => Promise<unknown>, key: string) {
    setPending(key)
    try { await fn() } finally { setPending(null); invalidate() }
  }
  const syncMut = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${clientId}/gbp/posts/sync`, {}),
    onSuccess: async (r) => { await pollJob(clientId, r.job_id); invalidate() },
  })

  const posts = data ?? []
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending} style={btn('#fff', '#334155')}>
          <RefreshCw size={13} /> {syncMut.isPending ? 'Syncing…' : 'Sync from Google'}
        </button>
      </div>
      {isLoading ? <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
        : posts.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13, padding: '24px 0' }}>No posts yet — compose one to get started.</div>
        : (
          <div style={{ display: 'grid', gap: 10 }}>
            {posts.map((p) => {
              const meta = STATUS_META[p.status]
              const busy = pending?.startsWith(p.id)
              return (
                <div key={p.id} style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ padding: '3px 9px', borderRadius: 999, background: meta.bg, color: meta.color, fontSize: 11, fontWeight: 700 }}>{meta.label}</span>
                    <span style={{ fontSize: 11, color: '#94a3b8', textTransform: 'capitalize' }}>{p.topic_type === 'standard' ? 'update' : p.topic_type}</span>
                    {p.scheduled_at && p.status === 'scheduled' && (
                      <span style={{ fontSize: 11, color: '#7c3aed', display: 'inline-flex', alignItems: 'center', gap: 3 }} title={tzLabel(tz)}><Clock size={11} /> {fmtInTz(p.scheduled_at, tz)}</span>
                    )}
                    {p.search_url && (
                      <a href={p.search_url} target="_blank" rel="noreferrer" style={{ marginLeft: 'auto', fontSize: 12, color: ACCENT, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        View on Google <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 12 }}>
                    {p.media?.[0]?.sourceUrl && <img src={p.media[0].sourceUrl} alt="" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6, flexShrink: 0 }} />}
                    <p style={{ margin: 0, fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap', flex: 1 }}>{p.summary}</p>
                  </div>
                  {p.error && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>Error: {p.error}</div>}
                  <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
                    {(p.status === 'draft' || p.status === 'failed') && (
                      <button disabled={busy} onClick={() => run(async () => { const r = await api.post<{ job_id: string }>(`/clients/${clientId}/gbp/posts/${p.id}/publish`, {}); await pollJob(clientId, r.job_id) }, `${p.id}:pub`)} style={btn('#16a34a')}>
                        <Send size={12} /> {pending === `${p.id}:pub` ? 'Publishing…' : 'Publish'}
                      </button>
                    )}
                    {p.status === 'scheduled' && (
                      <button disabled={busy} onClick={() => run(() => api.post(`/clients/${clientId}/gbp/posts/${p.id}/unschedule`, {}), `${p.id}:unsch`)} style={btn('#fff', '#334155')}>
                        <X size={12} /> Unschedule
                      </button>
                    )}
                    {p.status === 'live' && p.search_url && (
                      <button disabled={busy} onClick={() => run(() => api.post(`/gbp/posts/${p.id}/remove-from-google`, {}), `${p.id}:rmg`)} style={btn('#fff', '#b91c1c')}>
                        <XCircle size={12} /> {pending === `${p.id}:rmg` ? 'Removing…' : 'Remove from Google'}
                      </button>
                    )}
                    <button disabled={busy} onClick={() => run(() => api.delete(`/gbp/posts/${p.id}`), `${p.id}:del`)} style={btn('#fff', '#64748b')}>
                      <Trash2 size={12} /> Trash
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
    </div>
  )
}

// ── Trash ────────────────────────────────────────────────────────────────────
function TrashTab({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<GbpPost[]>({
    queryKey: ['gbp-trash', clientId], queryFn: () => api.get<GbpPost[]>(`/clients/${clientId}/gbp/posts?deleted=true`),
  })
  const invalidate = () => { qc.invalidateQueries({ queryKey: ['gbp-trash', clientId] }); qc.invalidateQueries({ queryKey: ['gbp-posts', clientId] }) }
  const restoreMut = useMutation({ mutationFn: (pid: string) => api.post(`/gbp/posts/${pid}/restore`, {}), onSuccess: invalidate })
  const purgeMut = useMutation({ mutationFn: (pid: string) => api.delete(`/gbp/posts/${pid}/permanent`), onSuccess: invalidate })
  const emptyMut = useMutation({ mutationFn: () => api.delete<{ purged: number; skipped_live: number }>(`/clients/${clientId}/gbp/posts/trash`), onSuccess: invalidate })

  const posts = data ?? []
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>{posts.length} in trash</span>
        <button onClick={() => emptyMut.mutate()} disabled={emptyMut.isPending || posts.length === 0} style={btn('#fff', '#b91c1c')}>
          <Trash2 size={13} /> {emptyMut.isPending ? 'Emptying…' : 'Empty trash'}
        </button>
      </div>
      {emptyMut.data && emptyMut.data.skipped_live > 0 && (
        <div style={{ fontSize: 12, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', padding: 10, borderRadius: 8, marginBottom: 12 }}>
          Purged {emptyMut.data.purged}. {emptyMut.data.skipped_live} kept because they're still live on Google — remove them from Google first.
        </div>
      )}
      {isLoading ? <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
        : posts.length === 0 ? <div style={{ color: '#94a3b8', fontSize: 13, padding: '24px 0' }}>Trash is empty.</div>
        : (
          <div style={{ display: 'grid', gap: 8 }}>
            {posts.map((p) => (
              <div key={p.id} style={{ border: '1px solid #f1f5f9', borderRadius: 8, padding: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ padding: '2px 8px', borderRadius: 999, background: STATUS_META[p.status].bg, color: STATUS_META[p.status].color, fontSize: 11, fontWeight: 700 }}>{STATUS_META[p.status].label}</span>
                <p style={{ margin: 0, fontSize: 13, color: '#475569', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.summary || '(empty)'}</p>
                {p.status === 'live' && <span style={{ fontSize: 11, color: '#b45309' }}>still live</span>}
                <button onClick={() => restoreMut.mutate(p.id)} title="Restore" style={btn('#fff', '#334155')}><RotateCcw size={12} /> Restore</button>
                <button onClick={() => purgeMut.mutate(p.id)} title="Delete permanently" style={{ border: 'none', background: 'none', color: '#cbd5e1', cursor: 'pointer' }}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

// ── Recurring schedule ───────────────────────────────────────────────────────
const DOW = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
function ScheduleTab({ clientId, locations }: { clientId: string; locations: GbpLocation[] }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<GbpSchedule>({
    queryKey: ['gbp-schedule', clientId], queryFn: () => api.get<GbpSchedule>(`/clients/${clientId}/gbp/post-schedule`),
  })
  const [form, setForm] = useState<GbpSchedule | null>(null)
  const s = form ?? data
  const set = (patch: Partial<GbpSchedule>) => setForm({ ...(s as GbpSchedule), ...patch })
  const saveMut = useMutation({
    mutationFn: () => api.put<GbpSchedule>(`/clients/${clientId}/gbp/post-schedule`, {
      location_row_id: s!.location_row_id ?? locations.find((l) => l.access_status === 'ok')?.id ?? locations[0]?.id,
      cadence: s!.cadence, day_of_week: s!.day_of_week, day_of_month: s!.day_of_month, hour_local: s!.hour_local,
      topic_type: s!.topic_type, theme_notes: s!.theme_notes, cta_type: s!.cta_type, cta_url: s!.cta_url,
      auto_publish: s!.auto_publish, is_active: s!.is_active,
    }),
    onSuccess: (r) => { setForm(null); qc.setQueryData(['gbp-schedule', clientId], r) },
  })

  const okId = useMemo(() => locations.find((l) => l.access_status === 'ok')?.id ?? locations[0]?.id, [locations])
  if (isLoading || !s) return <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>

  return (
    <div style={{ maxWidth: 560, display: 'grid', gap: 16 }}>
      <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
        Auto-draft a GBP post on a recurring cadence. Drafts land for review by default; turn on auto-publish to post them live automatically.
      </p>
      <div>
        <label style={label}>Cadence</label>
        <select value={s.cadence} onChange={(e) => set({ cadence: e.target.value, is_active: e.target.value !== 'disabled' })} style={input}>
          <option value="disabled">Off</option><option value="weekly">Weekly</option>
          <option value="biweekly">Every 2 weeks</option><option value="monthly">Monthly</option>
        </select>
      </div>
      {(s.cadence === 'weekly' || s.cadence === 'biweekly') && (
        <div><label style={label}>Day of week</label>
          <select value={s.day_of_week ?? 0} onChange={(e) => set({ day_of_week: Number(e.target.value) })} style={input}>
            {DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        </div>
      )}
      {s.cadence === 'monthly' && (
        <div><label style={label}>Day of month</label>
          <input type="number" min={1} max={28} value={s.day_of_month ?? 1} onChange={(e) => set({ day_of_month: Number(e.target.value) })} style={input} />
        </div>
      )}
      {s.cadence !== 'disabled' && (
        <>
          <div><label style={label}>Hour of day <span style={{ color: '#94a3b8', fontWeight: 400 }}>({tzLabel(s.timezone)})</span></label>
            <input type="number" min={0} max={23} value={s.hour_local} onChange={(e) => set({ hour_local: Number(e.target.value) })} style={input} />
          </div>
          <div><label style={label}>Post type</label>
            <select value={s.topic_type} onChange={(e) => set({ topic_type: e.target.value as TopicType })} style={input}>
              {TYPE_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div><label style={label}>Theme / rotation notes <span style={{ color: '#94a3b8', fontWeight: 400 }}>(guides the AI draft)</span></label>
            <textarea value={s.theme_notes ?? ''} onChange={(e) => set({ theme_notes: e.target.value })} rows={2} style={{ ...input, resize: 'vertical' }} placeholder="e.g. rotate between service highlights, seasonal tips, and reviews" />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155', cursor: 'pointer' }}>
            <input type="checkbox" checked={s.auto_publish} onChange={(e) => set({ auto_publish: e.target.checked })} />
            Auto-publish (skip review — posts go live automatically)
          </label>
          {s.auto_publish && <div style={{ fontSize: 12, color: '#b45309', marginTop: -8 }}>⚠ Posts will publish live with no human review.</div>}
        </>
      )}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || (!s.location_row_id && !okId)} style={btn(ACCENT)}>
          {saveMut.isPending ? 'Saving…' : 'Save schedule'}
        </button>
        {form && <button onClick={() => setForm(null)} style={btn('#fff', '#334155')}>Cancel</button>}
        {data?.next_run_at && data.is_active && <span style={{ fontSize: 12, color: '#15803d', display: 'inline-flex', alignItems: 'center', gap: 4 }} title={tzLabel(data.timezone)}><CheckCircle2 size={12} /> Next: {fmtInTz(data.next_run_at, data.timezone)}</span>}
      </div>
    </div>
  )
}
