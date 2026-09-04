import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2, XCircle, Link2, MapPin, Plus, RefreshCw, X,
} from 'lucide-react'
import { api } from '../../lib/api'

// Shared Google Business Profile connection + per-client listing picker, reused
// by the GBP Posts and GBP Profile Editor pages. Both register into the same
// `gbp_locations` table via the same /gbp/match-location + /register-location
// endpoints; the only page-specific bit is which locations-list query key to
// invalidate after a change (passed in as `listQueryKey`).

const DEFAULT_ACCENT = '#6366f1'

export const gbpBtn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: bg === '#fff' ? '1px solid #e2e8f0' : 'none', background: bg, color: fg,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
})

export interface GbpLocation {
  id: string; location_id: string; account_id?: string | null
  title: string | null; access_status: string
}
export interface AvailableLocation {
  location_id: string; account_id: string | null; title: string | null
  address: string | null; phone: string | null; place_id: string | null
  lat?: number | null; lng?: number | null; score?: number | null
  registered_client_id?: string | null; registered_client_name?: string | null
}
export interface MatchResult {
  client_label: string | null
  matched: AvailableLocation | null
  candidates: AvailableLocation[]
  detail: string | null
}

// ── Connect Google Business Profile (agency-account OAuth) ───────────────────
interface OauthStatus { client_configured: boolean; connected: boolean; account_email: string | null; auth_mode: string }

export function ConnectionBar({ accent = DEFAULT_ACCENT }: { accent?: string }) {
  const qc = useQueryClient()
  const [notice, setNotice] = useState<{ ok: boolean; msg: string } | null>(null)
  const { data } = useQuery<OauthStatus>({
    queryKey: ['gbp-oauth-status'], queryFn: () => api.get<OauthStatus>('/gbp/oauth/status'),
  })
  // Handle the redirect back from Google (?gbp_connected / ?gbp_error), then
  // strip the params so a refresh doesn't re-show the banner.
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
  const invitationsQ = useQuery<{ invitations: { business: string | null }[] }>({
    queryKey: ['gbp-invitations'],
    queryFn: () => api.get<{ invitations: { business: string | null }[] }>('/gbp/oauth/invitations'),
    enabled: Boolean(data?.connected), staleTime: 60_000, retry: false, refetchOnWindowFocus: true,
  })
  const pendingCount = invitationsQ.data?.invitations.length ?? 0
  const acceptMut = useMutation({
    mutationFn: () => api.post<{ accepted: number; pending: number }>('/gbp/oauth/accept-invitations', {}),
    onSuccess: (r) => {
      setNotice({ ok: true, msg: r.accepted > 0 ? `Accepted ${r.accepted} access invitation${r.accepted === 1 ? '' : 's'}.` : 'No pending access invitations.' })
      qc.invalidateQueries({ queryKey: ['gbp-invitations'] })
    },
    onError: (e: Error) => setNotice({ ok: false, msg: e.message === 'forbidden' ? 'Only an admin/staff user can do this.' : e.message }),
  })

  useEffect(() => {
    if (!notice?.ok) return
    const t = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(t)
  }, [notice])

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
          {pendingCount > 0 && (
            <button onClick={() => acceptMut.mutate()} disabled={acceptMut.isPending} title="Clients have added this account as a Manager — accept to manage their listings" style={{ ...gbpBtn(accent), marginLeft: 'auto' }}>
              {acceptMut.isPending ? 'Accepting…' : `Accept ${pendingCount} access invitation${pendingCount === 1 ? '' : 's'}`}
            </button>
          )}
          <button onClick={() => disconnectMut.mutate()} disabled={disconnectMut.isPending}
            style={{ marginLeft: pendingCount > 0 ? 8 : 'auto', border: 'none', background: 'none', color: '#15803d', fontSize: 12, cursor: 'pointer', textDecoration: 'underline', opacity: 0.75 }}>
            {disconnectMut.isPending ? 'Disconnecting…' : 'Disconnect'}
          </button>
        </div>
      ) : data.client_configured ? (
        <div style={{ ...bar, background: '#eef2ff', border: '1px solid #c7d2fe', color: '#3730a3' }}>
          <Link2 size={15} />
          <span>Connect the agency Google account that manages these listings — one click, no per-client setup.</span>
          <button onClick={connect} style={{ ...gbpBtn(accent), marginLeft: 'auto' }}>Connect Google Business Profile</button>
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

// ── This client's Business Profile (auto-matched to one GBP) ─────────────────
export function RegisterLocations({
  clientId, registered, listQueryKey, onClose, accent = DEFAULT_ACCENT,
}: {
  clientId: string; registered: GbpLocation[]; listQueryKey: unknown[]
  onClose?: () => void; accent?: string
}) {
  const qc = useQueryClient()
  const [showAll, setShowAll] = useState(false)
  const [changing, setChanging] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const hasRegistered = registered.length > 0

  const matchQ = useQuery<MatchResult>({
    queryKey: ['gbp-match-location', clientId],
    queryFn: () => api.get<MatchResult>(`/clients/${clientId}/gbp/match-location`),
    enabled: !hasRegistered || changing, retry: false,
  })
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: listQueryKey })
    qc.invalidateQueries({ queryKey: ['gbp-match-location', clientId] })
  }
  const registerMut = useMutation({
    mutationFn: (l: AvailableLocation) => api.post(`/clients/${clientId}/gbp/register-location`, {
      location_id: l.location_id, account_id: l.account_id, place_id: l.place_id, title: l.title,
    }),
    onSuccess: () => { setChanging(false); setShowAll(false); invalidate() },
    onError: (e: Error) => setErr(e.message === 'forbidden' ? 'Only an admin/staff user can set the listing.' : e.message),
  })
  const unregisterMut = useMutation({
    mutationFn: (rowId: string) => api.delete(`/clients/${clientId}/gbp/locations/${rowId}`),
    onSuccess: invalidate,
    onError: (e: Error) => setErr(e.message),
  })

  const detailMsg = (d: string | null): string => {
    if (d === 'gbp_not_connected') return 'Connect the agency Google account first (the Connect button above).'
    if (d === 'no_locations_visible') return "The connected account doesn't manage any listings yet — accept access invitations above, or add it as a Manager on the client's Business Profile."
    if (d === 'service_account_not_a_manager_or_insufficient_permission') return 'The connected account has no access to any listings yet. Accept access invitations above, or have the client add it as a Manager.'
    if (d === 'quota_exceeded_or_not_granted') return 'Google returned a quota error — try again shortly.'
    return d ? `Could not load listings: ${d}` : 'No matching Business Profile found for this client.'
  }
  const m = matchQ.data
  const registeredLocIds = new Set(registered.map((r) => r.location_id))

  const LocationCard = ({ l, suggested }: { l: AvailableLocation; suggested?: boolean }) => {
    const here = registeredLocIds.has(l.location_id)
    const elsewhere = !here && l.registered_client_id
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, border: `1px solid ${suggested ? '#c7d2fe' : '#e2e8f0'}`, background: suggested ? '#f5f3ff' : '#fff', borderRadius: 10, padding: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{l.title || l.location_id}</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>{[l.address, l.phone].filter(Boolean).join(' · ') || l.location_id}</div>
          {elsewhere && <div style={{ fontSize: 11, color: '#b45309', marginTop: 2 }}>Currently assigned to {l.registered_client_name || 'another client'}</div>}
        </div>
        {here ? (
          <span style={{ fontSize: 12, color: '#15803d', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}><CheckCircle2 size={14} /> In use</span>
        ) : (
          <button onClick={() => { setErr(null); registerMut.mutate(l) }} disabled={registerMut.isPending}
            style={gbpBtn(elsewhere ? '#fff' : accent, elsewhere ? '#334155' : '#fff')}>
            <Plus size={13} /> {elsewhere ? 'Use here instead' : 'Use this profile'}
          </button>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 640 }}>
      <div style={{ padding: 16, borderRadius: 12, background: '#f8fafc', border: '1px solid #e2e8f0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <MapPin size={16} color={accent} />
          <strong style={{ fontSize: 14, color: '#0f172a' }}>This client's Business Profile</strong>
          {onClose && <button onClick={onClose} style={{ marginLeft: 'auto', ...gbpBtn('#fff', '#334155') }}>Done</button>}
        </div>
        <p style={{ fontSize: 13, color: '#64748b', margin: 0, lineHeight: 1.6 }}>
          Edits apply to this client's Google Business Profile. We match it automatically from the client's known listing.
        </p>
      </div>

      {err && <div style={{ color: '#b91c1c', fontSize: 13, background: '#fef2f2', border: '1px solid #fecaca', padding: 10, borderRadius: 8 }}>{err}</div>}

      {hasRegistered && registered.map((r) => (
        <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 10, border: '1px solid #bbf7d0', background: '#f0fdf4', borderRadius: 10, padding: 12 }}>
          <CheckCircle2 size={15} color="#15803d" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{r.title || r.location_id}</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{r.location_id}{r.access_status !== 'ok' ? ` · ${r.access_status}` : ''}</div>
          </div>
          <button onClick={() => { setErr(null); setChanging((c) => !c) }} style={gbpBtn('#fff', '#334155')}>
            <RefreshCw size={12} /> Change
          </button>
          <button onClick={() => { if (confirm('Remove this Business Profile from the client?')) unregisterMut.mutate(r.id) }}
            disabled={unregisterMut.isPending} style={gbpBtn('#fff', '#b91c1c')}>
            <X size={12} /> Remove
          </button>
        </div>
      ))}

      {(!hasRegistered || changing) && (
        matchQ.isLoading ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>Finding this client's Business Profile…</div>
        ) : matchQ.isError ? (
          <div style={{ color: '#b91c1c', fontSize: 13 }}>Couldn't reach Google. {(matchQ.error as Error)?.message}</div>
        ) : (m?.candidates.length ?? 0) === 0 ? (
          <div style={{ fontSize: 13, color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a', padding: 12, borderRadius: 8, lineHeight: 1.6 }}>
            {detailMsg(m?.detail ?? null)}
          </div>
        ) : m?.matched && !showAll ? (
          <div style={{ display: 'grid', gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#475569' }}>
              Matched{m.client_label ? ` for ${m.client_label}` : ''}
            </span>
            <LocationCard l={m.matched} suggested />
            <button onClick={() => setShowAll(true)} style={{ justifySelf: 'start', border: 'none', background: 'none', color: accent, fontSize: 12, fontWeight: 600, cursor: 'pointer', padding: 0 }}>
              Not the right listing? Show all
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              {m?.matched ? 'All listings managed by the connected account — best match first.' : "We couldn't confidently match this client — pick its listing:"}
            </span>
            {(m?.candidates ?? []).map((l) => <LocationCard key={l.location_id} l={l} suggested={l.location_id === m?.matched?.location_id} />)}
          </div>
        )
      )}
    </div>
  )
}
