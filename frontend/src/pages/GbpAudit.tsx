import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, ClipboardCheck, CheckCircle2, XCircle, ShieldAlert,
  Pencil, Globe2, Star, ExternalLink, History,
} from 'lucide-react'
import { api } from '../lib/api'
import { ConnectionBar, RegisterLocations } from '../components/gbp/GbpConnection'
import { ErrorDetails } from '../components/ErrorDetails'
import type { Client } from '../lib/types'

// GBP Audit — a profile-health score + prioritized recommendations (grounded in
// the LIVE listing read + captured competitor context) AND a change-audit trail
// (the team's own applied edits merged with the outside/Google changes the
// monitor detected). Read-only. Backend gated on gbp_api_enabled +
// gbp_profile_enabled; off → the shared enablement notice.

const ACCENT = '#0d9488'

interface GbpLocationRow { id: string; location_id: string; title: string | null; access_status: string }
interface AuditCheck { key: string; label: string; ok: boolean; detail: string }
interface AuditRec { key: string; severity: 'critical' | 'high' | 'medium' | 'low'; title: string; detail: string; target: string | null }
interface ReviewGap { client: number; competitor_median: number; deficit: number }
interface AuditResponse {
  access_status: string | null; score: number | null; band: string | null
  checks: AuditCheck[]; recommendations: AuditRec[]; category_gaps: string[]
  review_gap: ReviewGap | null; competitor_count: number
}
interface ChangeEvent {
  at: string | null; source: 'team' | 'external'; kind: string; field: string | null
  detail: string; who: string | null; edit_source: string | null; status: string | null
}

const SEV: Record<AuditRec['severity'], { label: string; color: string; bg: string }> = {
  critical: { label: 'Critical', color: '#b91c1c', bg: '#fef2f2' },
  high: { label: 'High', color: '#b45309', bg: '#fffbeb' },
  medium: { label: 'Medium', color: '#475569', bg: '#f1f5f9' },
  low: { label: 'Low', color: '#64748b', bg: '#f8fafc' },
}
const BAND: Record<string, { label: string; color: string }> = {
  strong: { label: 'Strong', color: '#15803d' },
  fair: { label: 'Fair', color: '#b45309' },
  needs_work: { label: 'Needs work', color: '#b91c1c' },
}
const fmtWhen = (iso?: string | null) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

export function GbpAudit() {
  const { id: clientId = '' } = useParams()
  return (
    <div style={{ maxWidth: 920, margin: '0 auto', padding: '0 4px' }}>
      <GbpAuditBody clientId={clientId} />
    </div>
  )
}

export function GbpAuditBody({ clientId, embedded }: { clientId: string; embedded?: boolean }) {
  const [manageOpen, setManageOpen] = useState(false)
  const [selectedLoc, setSelectedLoc] = useState<string | null>(null)

  const clientQ = useQuery<Client>({ queryKey: ['client', clientId], queryFn: () => api.get<Client>(`/clients/${clientId}`) })
  const locationsQ = useQuery<GbpLocationRow[]>({
    queryKey: ['gbp-profile-locations', clientId],
    queryFn: () => api.get<GbpLocationRow[]>(`/clients/${clientId}/gbp/profile-locations`),
    enabled: Boolean(clientId), retry: false,
  })
  const disabled = (locationsQ.error as Error | null)?.message === 'gbp_profile_not_enabled'
  const locations = locationsQ.data ?? []
  const okLocations = locations.filter((l) => l.access_status === 'ok')
  useEffect(() => { if (!selectedLoc && okLocations.length) setSelectedLoc(okLocations[0].id) }, [okLocations, selectedLoc])

  return (
    <>
      {!embedded && (
        <>
          <Link to={`/clients/${clientId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 14 }}>
            <ArrowLeft size={14} /> Back to {clientQ.data?.name ?? 'client'}
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <ClipboardCheck size={22} color={ACCENT} />
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: '#0f172a' }}>Profile Audit</h1>
          </div>
          <ConnectionBar accent={ACCENT} />
        </>
      )}

      {disabled ? (
        <div style={{ padding: 20, borderRadius: 12, background: '#fffbeb', border: '1px solid #fde68a', fontSize: 13, color: '#92400e' }}>
          The GBP module isn't enabled yet.
        </div>
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
              <select value={selectedLoc ?? ''} onChange={(e) => setSelectedLoc(e.target.value)} style={{ padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, minWidth: 220 }}>
                {okLocations.map((l) => <option key={l.id} value={l.id}>{l.title || l.location_id}</option>)}
              </select>
            )}
            <button onClick={() => setManageOpen(true)} style={{ marginLeft: 'auto', padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              Manage listing
            </button>
          </div>
          {selectedLoc && <AuditView key={selectedLoc} clientId={clientId} locationRowId={selectedLoc} />}
        </>
      )}
    </>
  )
}

function AuditView({ clientId, locationRowId }: { clientId: string; locationRowId: string }) {
  const auditQ = useQuery<AuditResponse>({
    queryKey: ['gbp-audit', clientId, locationRowId],
    queryFn: () => api.get<AuditResponse>(`/clients/${clientId}/gbp/profile/audit?location_row_id=${locationRowId}`),
    retry: false,
  })
  const historyQ = useQuery<ChangeEvent[]>({
    queryKey: ['gbp-audit-history', clientId, locationRowId],
    queryFn: () => api.get<ChangeEvent[]>(`/clients/${clientId}/gbp/profile/audit/history?location_row_id=${locationRowId}`),
    retry: false,
  })

  if (auditQ.isLoading) return <div style={{ color: '#64748b', fontSize: 13 }}>Auditing the live profile…</div>
  if (auditQ.isError) return <ErrorDetails message={(auditQ.error as Error)?.message} style={{ marginTop: 8 }} />
  const d = auditQ.data!
  const band = d.band ? BAND[d.band] : null
  const passing = d.checks.filter((c) => c.ok).length

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {/* Score card */}
      <div style={{ display: 'flex', gap: 18, alignItems: 'center', border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, background: '#fff' }}>
        <div style={{ textAlign: 'center', minWidth: 92 }}>
          <div style={{ fontSize: 40, fontWeight: 800, lineHeight: 1, color: band?.color ?? '#94a3b8' }}>
            {d.score ?? '—'}
          </div>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>/ 100</div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: band?.color ?? '#0f172a' }}>
            {band?.label ?? 'Profile health'}
          </div>
          <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 3 }}>
            {d.checks.length > 0 ? `${passing} of ${d.checks.length} checks passing` : 'Live profile audit'}
            {d.competitor_count > 0 && ` · vs ${d.competitor_count} local competitor${d.competitor_count === 1 ? '' : 's'}`}
          </div>
          {d.access_status && d.access_status !== 'ok' && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12, fontWeight: 700, color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '4px 10px' }}>
              <ShieldAlert size={13} /> {d.access_status === 'suspended' ? 'Listing appears suspended' : 'Listing unreadable'}
            </div>
          )}
        </div>
      </div>

      {/* Recommendations */}
      {d.recommendations.length > 0 && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, background: '#fff' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>Recommendations</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {d.recommendations.map((r) => {
              const s = SEV[r.severity]
              return (
                <div key={r.key} style={{ display: 'grid', gap: 4, padding: '10px 12px', borderRadius: 8, background: s.bg, border: `1px solid ${s.color}22` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4, color: s.color }}>{s.label}</span>
                    <span style={{ fontSize: 13.5, fontWeight: 600, color: '#0f172a' }}>{r.title}</span>
                    <RecAction target={r.target} clientId={clientId} />
                  </div>
                  <div style={{ fontSize: 12.5, color: '#475569', lineHeight: 1.5 }}>{r.detail}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Checks */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, background: '#fff' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>Profile checks</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 8 }}>
          {d.checks.map((c) => (
            <div key={c.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              {c.ok ? <CheckCircle2 size={15} color="#15803d" /> : <XCircle size={15} color="#b91c1c" />}
              <span style={{ color: '#334155' }}>{c.label}</span>
              {c.detail && <span style={{ color: '#94a3b8', fontSize: 11.5 }}>· {c.detail}</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Change trail */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, padding: 18, background: '#fff' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 15, fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>
          <History size={16} /> Change history
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>Your team's applied edits and the outside / Google changes the monitor caught.</div>
        {historyQ.isLoading ? (
          <div style={{ fontSize: 12.5, color: '#64748b' }}>Loading…</div>
        ) : (historyQ.data ?? []).length === 0 ? (
          <div style={{ fontSize: 12.5, color: '#94a3b8' }}>No recorded changes yet.</div>
        ) : (
          <div style={{ display: 'grid', gap: 2 }}>
            {(historyQ.data ?? []).map((e, i) => <HistoryRow key={i} e={e} />)}
          </div>
        )}
      </div>
    </div>
  )
}

function RecAction({ target, clientId }: { target: string | null; clientId: string }) {
  if (target === 'profile') {
    return (
      <Link to={`/clients/${clientId}/gbp?tab=profile`} style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: ACCENT, textDecoration: 'none' }}>
        <Pencil size={12} /> Fix in editor
      </Link>
    )
  }
  if (target === 'reviews') {
    return <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b' }}><Star size={12} /> Reviews</span>
  }
  if (target === 'dashboard') {
    return <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b' }}><ExternalLink size={12} /> GBP dashboard</span>
  }
  return null
}

function HistoryRow({ e }: { e: ChangeEvent }) {
  const external = e.source === 'external'
  const critical = e.kind === 'suspended' || e.kind === 'access_lost'
  const icon = critical ? <ShieldAlert size={14} color="#b91c1c" />
    : external ? <Globe2 size={14} color="#b45309" />
    : <Pencil size={14} color={ACCENT} />
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '20px 1fr auto', gap: 8, alignItems: 'center', padding: '6px 0', borderBottom: '1px solid #f1f5f9', fontSize: 12.5 }}>
      <span>{icon}</span>
      <span style={{ color: critical ? '#b91c1c' : '#334155' }}>
        {e.detail}{e.who ? ` · ${e.who}` : ''}
      </span>
      <span style={{ color: '#94a3b8', fontSize: 11.5, whiteSpace: 'nowrap' }}>{fmtWhen(e.at)}</span>
    </div>
  )
}
