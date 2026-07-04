import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { OctagonAlert, ShieldOff } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'

interface FreezeRow {
  id: string
  reason: 'manual_action' | 'deindexing' | 'manual'
  source: string
  note?: string | null
  created_at: string
}

const REASON_LABELS: Record<string, string> = {
  manual_action: 'Manual action',
  deindexing: 'Site deindexed',
  manual: 'Manual freeze',
}

// Freeze Protocol banner (Link Building SOP §Risk Monitoring & Freeze
// Protocol). Renders a red banner when the client is under an active freeze —
// all link building and content creation are paused server-side. Admins can
// freeze/lift from here; everyone else sees the state.
export function FreezeBanner({ clientId }: { clientId: string }) {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [showFreezeForm, setShowFreezeForm] = useState(false)
  const [note, setNote] = useState('')
  const [reason, setReason] = useState<'manual_action' | 'deindexing' | 'manual'>('manual')

  const { data } = useQuery<{ active: FreezeRow | null }>({
    queryKey: ['freeze', clientId],
    queryFn: () => api.get<{ active: FreezeRow | null }>(`/clients/${clientId}/freeze`),
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['freeze', clientId] })
  const freezeMut = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/freeze`, { reason, note: note || null }),
    onSuccess: () => {
      setShowFreezeForm(false)
      setNote('')
      invalidate()
    },
  })
  const liftMut = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/freeze/lift`, {}),
    onSuccess: invalidate,
  })

  const active = data?.active

  if (active) {
    return (
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
          background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10,
          marginBottom: 20,
        }}
      >
        <OctagonAlert size={20} color="#dc2626" style={{ flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#991b1b' }}>
            FROZEN — {REASON_LABELS[active.reason] ?? active.reason}
          </div>
          <div style={{ fontSize: 13, color: '#b91c1c' }}>
            All link building and content creation are paused for this client
            {active.note ? ` — ${active.note}` : ''}. Recovery is owned by the Admins.
          </div>
        </div>
        {isAdmin && (
          <button
            onClick={() => liftMut.mutate()}
            disabled={liftMut.isPending}
            style={{
              padding: '7px 14px', borderRadius: 8, border: '1px solid #dc2626',
              background: '#fff', color: '#dc2626', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {liftMut.isPending ? 'Lifting…' : 'Lift freeze'}
          </button>
        )}
      </div>
    )
  }

  if (!isAdmin) return null

  // No active freeze: a quiet admin affordance to open one (confirmed manual
  // action / deindexing found in GSC's UI — there is no manual-actions API).
  return (
    <div style={{ marginBottom: 16 }}>
      {showFreezeForm ? (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px',
            background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 10, flexWrap: 'wrap',
          }}
        >
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value as typeof reason)}
            style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 13 }}
          >
            <option value="manual_action">Manual action (confirmed in GSC)</option>
            <option value="deindexing">Deindexing (confirmed)</option>
            <option value="manual">Other / manual</option>
          </select>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Note (optional)"
            style={{ flex: 1, minWidth: 180, padding: '6px 8px', borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 13 }}
          />
          <button
            onClick={() => freezeMut.mutate()}
            disabled={freezeMut.isPending}
            style={{
              padding: '7px 14px', borderRadius: 8, border: 'none',
              background: '#dc2626', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {freezeMut.isPending ? 'Freezing…' : 'Freeze client'}
          </button>
          <button
            onClick={() => setShowFreezeForm(false)}
            style={{
              padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0',
              background: '#fff', color: '#64748b', fontSize: 13, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowFreezeForm(true)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px',
            borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff',
            color: '#94a3b8', fontSize: 12, cursor: 'pointer',
          }}
          title="Freeze Protocol: pause all link building & content creation for this client (confirmed manual action / deindexing)"
        >
          <ShieldOff size={13} /> Freeze Protocol
        </button>
      )}
    </div>
  )
}
