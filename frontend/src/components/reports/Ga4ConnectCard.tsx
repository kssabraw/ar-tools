import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, Check, Copy, Plus, Trash2 } from 'lucide-react'
import { api } from '../../lib/api'
import type { Ga4Property, Ga4PropertySummary, Ga4VerifyResponse } from '../../lib/types'
import { Spinner } from '../localseo/Spinner'
import { card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime } from '../localseo/shared'

interface ServiceAccountInfo { email: string }

// GA4 connection management (Client Reporting Phase 2): surface the service-
// account email to add as a Viewer, discover visible properties via the Admin
// API, connect one, verify access. Mirrors the GSC connection panel.
export function Ga4ConnectCard({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()

  const { data: sa, error: saError } = useQuery<ServiceAccountInfo>({
    queryKey: ['ga4-service-account'],
    queryFn: () => api.get<ServiceAccountInfo>('/ga4/service-account-email'),
    retry: false,
  })

  const { data: properties, isLoading } = useQuery<Ga4Property[]>({
    queryKey: ['ga4-properties', clientId],
    queryFn: () => api.get<Ga4Property[]>(`/clients/${clientId}/ga4-properties`),
  })

  const [adding, setAdding] = useState(false)
  const [manualId, setManualId] = useState('')
  const [copied, setCopied] = useState(false)
  const [verifyResult, setVerifyResult] = useState<Record<string, Ga4VerifyResponse>>({})

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['ga4-properties', clientId] })

  const addMut = useMutation({
    mutationFn: (body: { property_id: string; display_name?: string }) =>
      api.post<Ga4Property>(`/clients/${clientId}/ga4-properties`, body),
    onSuccess: () => { invalidate(); setManualId(''); setAdding(false) },
  })
  const verifyMut = useMutation({
    mutationFn: (propertyId: string) =>
      api.post<Ga4VerifyResponse>(`/ga4-properties/${propertyId}/verify`, {}),
    onSuccess: (res) => {
      setVerifyResult((prev) => ({ ...prev, [res.property_id]: res }))
      invalidate()
    },
  })
  const deleteMut = useMutation({
    mutationFn: (propertyId: string) => api.delete<void>(`/ga4-properties/${propertyId}`),
    onSuccess: invalidate,
  })

  const copyEmail = () => {
    if (!sa?.email) return
    navigator.clipboard.writeText(sa.email).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const connectedIds = new Set((properties ?? []).map((p) => p.property_id))

  return (
    <div style={{ ...card, marginBottom: 20 }}>
      <h2 style={sectionTitle}><BarChart3 size={16} color="#6366f1" /> Google Analytics (GA4)</h2>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px', lineHeight: 1.6 }}>
        Connect the client’s GA4 property to add website-traffic (visits, visitors,
        conversions, channels) to their reports. In GA4, open <strong>Admin → Property
        Access Management</strong> and add the email below as a <strong>Viewer</strong>, then
        connect the property.
      </p>

      {saError ? (
        <div style={errorBox}>
          Service account not configured. An admin needs
          <code style={code}> GOOGLE_SERVICE_ACCOUNT_KEY </code> set on the platform API.
        </div>
      ) : sa?.email ? (
        <div style={emailRow}>
          <code style={{ ...code, flex: 1 }}>{sa.email}</code>
          <button style={outlineBtn} onClick={copyEmail}>
            {copied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
          </button>
        </div>
      ) : (
        <Spinner />
      )}

      <div style={{ marginTop: 16 }}>
        {isLoading ? (
          <Spinner />
        ) : properties && properties.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 14 }}>
            {properties.map((p) => (
              <Ga4PropertyRow
                key={p.id}
                property={p}
                verifying={verifyMut.isPending && verifyMut.variables === p.id}
                detail={verifyResult[p.id]?.detail ?? null}
                onVerify={() => verifyMut.mutate(p.id)}
                onDelete={() => deleteMut.mutate(p.id)}
              />
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 14px' }}>No GA4 property connected yet.</p>
        )}

        {adding ? (
          <AddProperty
            connectedIds={connectedIds}
            pending={addMut.isPending}
            error={(addMut.error as Error) ?? null}
            manualId={manualId}
            setManualId={setManualId}
            onAdd={(property_id, display_name) => addMut.mutate({ property_id, display_name })}
            onCancel={() => { setAdding(false); setManualId('') }}
          />
        ) : (
          <button style={outlineBtn} onClick={() => setAdding(true)}>
            <Plus size={14} /> Connect a property
          </button>
        )}
      </div>
    </div>
  )
}

// A property picker sourced from the Admin API (what the service account can
// see), with a manual numeric-id fallback for when discovery is empty.
function AddProperty({
  connectedIds, pending, error, manualId, setManualId, onAdd, onCancel,
}: {
  connectedIds: Set<string>
  pending: boolean
  error: Error | null
  manualId: string
  setManualId: (v: string) => void
  onAdd: (propertyId: string, displayName?: string) => void
  onCancel: () => void
}) {
  const { data: summaries, isLoading, error: discoverError } = useQuery<Ga4PropertySummary[]>({
    queryKey: ['ga4-property-summaries'],
    queryFn: () => api.get<Ga4PropertySummary[]>('/ga4/property-summaries'),
    retry: false,
  })

  const available = (summaries ?? []).filter((s) => !connectedIds.has(s.property_id))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {isLoading ? (
        <Spinner />
      ) : available.length > 0 ? (
        <>
          <label style={label}>Properties this service account can see</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {available.map((s) => (
              <div key={s.property_id} style={pickRow}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{s.display_name || s.property_id}</div>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>
                    {s.account_name ? `${s.account_name} · ` : ''}<code style={code}>{s.property_id}</code>
                  </div>
                </div>
                <button style={primaryBtn} disabled={pending}
                  onClick={() => onAdd(s.property_id, s.display_name || undefined)}>
                  {pending ? 'Connecting…' : 'Connect'}
                </button>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>Not listed? Enter the numeric property id manually:</div>
        </>
      ) : (
        <div style={{ fontSize: 12, color: '#94a3b8' }}>
          {discoverError
            ? 'Property discovery is unavailable (the Admin API may not be enabled, or the service account isn’t added to any property yet). Enter the numeric property id manually:'
            : 'No new properties visible to the service account. Enter the numeric property id manually:'}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <input
          style={{ ...input, flex: 1 }} autoFocus
          placeholder="properties/123456789  or  123456789"
          value={manualId} onChange={(e) => setManualId(e.target.value)}
        />
        <button style={primaryBtn} disabled={!manualId.trim() || pending}
          onClick={() => onAdd(manualId.trim())}>
          {pending ? 'Connecting…' : 'Connect'}
        </button>
        <button style={outlineBtn} onClick={onCancel}>Cancel</button>
      </div>
      {error && <div style={errorBox}>{error.message}</div>}
    </div>
  )
}

function Ga4PropertyRow({
  property, verifying, detail, onVerify, onDelete,
}: {
  property: Ga4Property
  verifying: boolean
  detail: string | null
  onVerify: () => void
  onDelete: () => void
}) {
  const badge = statusBadge(property.access_status)
  return (
    <div style={propRow}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
            {property.display_name || property.property_id}
          </span>
          <span style={badge.style}>{badge.text}</span>
          {property.last_verified_at && (
            <span style={{ fontSize: 11, color: '#94a3b8' }}>checked {relativeTime(property.last_verified_at)}</span>
          )}
        </div>
        <code style={{ ...code, fontSize: 12 }}>{property.property_id}</code>
        {property.access_status === 'no_access' && (
          <div style={{ fontSize: 11, color: '#b45309', marginTop: 4 }}>
            The service account can’t read this property yet — confirm the email was added as a Viewer.
          </div>
        )}
        {detail && property.access_status !== 'ok' && (
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{detail}</div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button style={outlineBtn} onClick={onVerify} disabled={verifying}>
          {verifying ? 'Verifying…' : 'Verify'}
        </button>
        <button style={{ ...outlineBtn, color: '#dc2626', borderColor: '#fecaca' }} onClick={onDelete} title="Remove">
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}

function statusBadge(status: Ga4Property['access_status']) {
  if (status === 'ok') return { text: 'connected', style: { ...badgeBase, background: '#dcfce7', color: '#166534' } }
  if (status === 'no_access') return { text: 'no access', style: { ...badgeBase, background: '#fee2e2', color: '#b91c1c' } }
  return { text: 'pending', style: { ...badgeBase, background: '#f1f5f9', color: '#64748b' } }
}

const sectionTitle: React.CSSProperties = {
  fontSize: 15, fontWeight: 700, color: '#0f172a', margin: '0 0 4px',
  display: 'flex', alignItems: 'center', gap: 8,
}
const code: React.CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12,
  background: '#f1f5f9', padding: '2px 6px', borderRadius: 5, color: '#334155',
}
const emailRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10,
  background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px',
}
const propRow: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12,
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px',
}
const pickRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10,
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px',
}
const badgeBase: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em',
  padding: '2px 7px', borderRadius: 9,
}
