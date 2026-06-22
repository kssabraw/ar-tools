import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Clock, Copy, Globe, History, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { api } from '../../lib/api'
import type {
  GscProperty, IngestResponse, SyncRun, VerifyAccessResponse,
} from '../../lib/types'
import { Spinner } from '../localseo/Spinner'
import { card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime } from '../localseo/shared'

interface ServiceAccountInfo { email: string }

// M1/M2 connection management: service-account email, property CRUD, verify
// access, and last-sync status / manual sync.
export function RankSettings({ clientId, isAdmin }: { clientId: string; isAdmin: boolean }) {
  const queryClient = useQueryClient()

  const { data: sa, error: saError } = useQuery<ServiceAccountInfo>({
    queryKey: ['gsc-service-account'],
    queryFn: () => api.get<ServiceAccountInfo>('/gsc/service-account-email'),
    retry: false,
  })

  const { data: properties, isLoading } = useQuery<GscProperty[]>({
    queryKey: ['gsc-properties', clientId],
    queryFn: () => api.get<GscProperty[]>(`/clients/${clientId}/gsc-properties`),
  })

  const [siteUrl, setSiteUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [copied, setCopied] = useState(false)
  const [verifyResult, setVerifyResult] = useState<Record<string, VerifyAccessResponse>>({})

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['gsc-properties', clientId] })

  const addMut = useMutation({
    mutationFn: (site_url: string) =>
      api.post<GscProperty>(`/clients/${clientId}/gsc-properties`, { site_url }),
    onSuccess: () => { invalidate(); setSiteUrl(''); setAdding(false) },
  })
  const verifyMut = useMutation({
    mutationFn: (propertyId: string) =>
      api.post<VerifyAccessResponse>(`/gsc-properties/${propertyId}/verify`, {}),
    onSuccess: (res) => {
      setVerifyResult((prev) => ({ ...prev, [res.property_id]: res }))
      invalidate()
    },
  })
  const deleteMut = useMutation({
    mutationFn: (propertyId: string) => api.delete<void>(`/gsc-properties/${propertyId}`),
    onSuccess: invalidate,
  })

  const copyEmail = () => {
    if (!sa?.email) return
    navigator.clipboard.writeText(sa.email).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <>
      <div style={{ ...card, marginBottom: 20 }}>
        <h2 style={sectionTitle}>1 · Grant the service account access</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px', lineHeight: 1.6 }}>
          In the client’s Search Console, open <strong>Settings → Users and permissions</strong>,
          add the email below as a user (<strong>Restricted</strong> is enough), then verify below.
        </p>
        {saError ? (
          <div style={errorBox}>
            Service account not configured yet. An admin needs to set
            <code style={code}>GOOGLE_SERVICE_ACCOUNT_KEY</code> on the platform API before
            properties can be verified.
          </div>
        ) : sa?.email ? (
          <div style={emailRow}>
            <Globe size={15} color="#6366f1" />
            <code style={{ ...code, flex: 1 }}>{sa.email}</code>
            <button style={outlineBtn} onClick={copyEmail}>
              {copied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
            </button>
          </div>
        ) : (
          <Spinner />
        )}
      </div>

      <div style={card}>
        <h2 style={sectionTitle}>2 · Properties</h2>
        {isLoading ? (
          <Spinner />
        ) : properties && properties.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
            {properties.map((p) => (
              <PropertyRow
                key={p.id}
                property={p}
                isAdmin={isAdmin}
                verifying={verifyMut.isPending && verifyMut.variables === p.id}
                detail={verifyResult[p.id]?.detail ?? null}
                onVerify={() => verifyMut.mutate(p.id)}
                onDelete={() => deleteMut.mutate(p.id)}
              >
                {p.access_status === 'ok' && <SyncStatus propertyId={p.id} isAdmin={isAdmin} />}
              </PropertyRow>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 16px' }}>No property connected yet.</p>
        )}

        {!isAdmin ? null : adding ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={label} htmlFor="site_url">Property URL</label>
            <input
              id="site_url" style={input} autoFocus
              placeholder="https://acmehvac.com/  or  sc-domain:acmehvac.com"
              value={siteUrl} onChange={(e) => setSiteUrl(e.target.value)}
            />
            <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>
              URL-prefix properties need the full https:// URL with a trailing slash; domain
              properties use the <code style={code}>sc-domain:</code> prefix.
            </p>
            {addMut.error && <div style={errorBox}>{(addMut.error as Error).message}</div>}
            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button style={primaryBtn} disabled={!siteUrl.trim() || addMut.isPending}
                onClick={() => addMut.mutate(siteUrl.trim())}>
                {addMut.isPending ? 'Adding…' : 'Add property'}
              </button>
              <button style={outlineBtn} onClick={() => { setAdding(false); setSiteUrl('') }}>Cancel</button>
            </div>
          </div>
        ) : (
          <button style={outlineBtn} onClick={() => setAdding(true)}>
            <Plus size={14} /> Add property
          </button>
        )}
      </div>
    </>
  )
}

function PropertyRow({
  property, isAdmin, verifying, detail, onVerify, onDelete, children,
}: {
  property: GscProperty; isAdmin: boolean; verifying: boolean; detail: string | null
  onVerify: () => void; onDelete: () => void; children?: React.ReactNode
}) {
  const badge = statusBadge(property.access_status)
  return (
    <div style={propRow}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <code style={{ ...code, fontSize: 13 }}>{property.site_url}</code>
            <span style={{ fontSize: 11, color: '#94a3b8' }}>
              {property.property_type === 'domain' ? 'domain' : 'url-prefix'}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
            <span style={badge.style}>{badge.icon} {badge.text}</span>
            {property.last_verified_at && (
              <span style={{ fontSize: 11, color: '#94a3b8' }}>checked {relativeTime(property.last_verified_at)}</span>
            )}
          </div>
          {property.access_status === 'no_access' && (
            <p style={{ fontSize: 12, color: '#b45309', margin: '6px 0 0' }}>
              The service account can’t read this property yet — confirm the email was added as a
              user, then verify again.{detail ? ` (${detail})` : ''}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button style={outlineBtn} onClick={onVerify} disabled={verifying}>
            <RefreshCw size={14} /> {verifying ? 'Verifying…' : 'Verify access'}
          </button>
          {isAdmin && (
            <button style={{ ...outlineBtn, color: '#dc2626' }} onClick={onDelete} title="Remove">
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>
      {children}
    </div>
  )
}

function SyncStatus({ propertyId, isAdmin }: { propertyId: string; isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const { data: runs } = useQuery<SyncRun[]>({
    queryKey: ['gsc-sync-runs', propertyId],
    queryFn: () => api.get<SyncRun[]>(`/gsc-properties/${propertyId}/sync-runs`),
  })
  const ingestMut = useMutation({
    mutationFn: () => api.post<IngestResponse>(`/gsc-properties/${propertyId}/ingest`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gsc-sync-runs', propertyId] }),
  })
  const backfillMut = useMutation({
    mutationFn: () => api.post(`/gsc-properties/${propertyId}/backfill`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gsc-sync-runs', propertyId] }),
  })
  const latest = runs?.[0]
  return (
    <div style={syncStrip}>
      <div style={{ fontSize: 12, color: '#64748b', display: 'flex', alignItems: 'center', gap: 6 }}>
        <Clock size={12} color="#94a3b8" />
        {latest ? (
          latest.status === 'ok' ? (
            <span>Last sync {relativeTime(latest.run_at)} · {latest.rows.toLocaleString()} rows</span>
          ) : (
            <span style={{ color: '#b45309' }}>
              Last sync failed {relativeTime(latest.run_at)}{latest.error ? ` · ${latest.error}` : ''}
            </span>
          )
        ) : (
          <span>Not synced yet — the daily job runs automatically, or sync now.</span>
        )}
      </div>
      {isAdmin && (
        <div style={{ display: 'flex', gap: 6 }}>
          <button style={{ ...outlineBtn, padding: '5px 10px', fontSize: 12 }}
            onClick={() => ingestMut.mutate()} disabled={ingestMut.isPending}>
            <RefreshCw size={13} /> {ingestMut.isPending ? 'Syncing…' : 'Sync now'}
          </button>
          <button style={{ ...outlineBtn, padding: '5px 10px', fontSize: 12 }}
            title="Pull ~16 months of history in the background"
            onClick={() => {
              if (confirm('Backfill ~16 months of Search Console history? This runs in the background and may take a few minutes.'))
                backfillMut.mutate()
            }}
            disabled={backfillMut.isPending || backfillMut.isSuccess}>
            <History size={13} /> {backfillMut.isSuccess ? 'Backfill queued' : 'Backfill history'}
          </button>
        </div>
      )}
    </div>
  )
}

function statusBadge(status: GscProperty['access_status']) {
  switch (status) {
    case 'ok': return { text: 'Connected', icon: <Check size={12} />, style: pill('#dcfce7', '#166534') }
    case 'no_access': return { text: 'No access', icon: <X size={12} />, style: pill('#fee2e2', '#991b1b') }
    default: return { text: 'Pending', icon: <Clock size={12} />, style: pill('#f1f5f9', '#64748b') }
  }
}

function pill(bg: string, color: string): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    background: bg, color, borderRadius: 999, padding: '2px 9px', fontSize: 11, fontWeight: 600,
  }
}

const sectionTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: '#0f172a', margin: '0 0 8px',
  textTransform: 'uppercase', letterSpacing: '0.04em',
}
const code: React.CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 12, background: '#f1f5f9', borderRadius: 5, padding: '2px 6px', color: '#334155',
}
const emailRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10,
  background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px',
}
const propRow: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 12,
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 14,
}
const syncStrip: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
  borderTop: '1px solid #f1f5f9', paddingTop: 10,
}
