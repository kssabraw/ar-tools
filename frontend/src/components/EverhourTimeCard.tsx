import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { api } from '../lib/api'
import type { EverhourClientTime, EverhourStatus } from '../lib/types'

// Everhour "Time" card — the client workspace read of hours logged against this
// client over a trailing window (default 30 days), from the time_entries ledger
// the daily Everhour sync maintains (no live Everhour call). Renders nothing
// until Everhour is enabled AND this client has logged time, so the whole
// integration stays dark during a read-first rollout.
export function EverhourTimeCard({ clientId }: { clientId: string }) {
  const { data: status } = useQuery<EverhourStatus>({
    queryKey: ['everhour-status'],
    queryFn: () => api.get<EverhourStatus>('/everhour/status'),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  const { data } = useQuery<EverhourClientTime>({
    queryKey: ['everhour-time', clientId],
    queryFn: () => api.get<EverhourClientTime>(`/clients/${clientId}/everhour/time`),
    enabled: Boolean(clientId) && Boolean(status?.enabled),
    retry: false,
  })

  // Dark unless the integration is on and there's something to show.
  if (!status?.enabled || !data?.available) return null
  if (!data.total_hours) return null

  const members = data.members ?? []
  const split: Array<[string, number | null | undefined, string]> = [
    ['Billable', data.billable_hours, '#16a34a'],
    ['Non-billable', data.non_billable_hours, '#64748b'],
    ['Unclassified', data.unknown_hours, '#cbd5e1'],
  ]
  const hasSplit = split.some(([, v]) => (v ?? 0) > 0 && (v ?? 0) !== data.total_hours)

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Clock size={18} style={{ color: '#2563eb', flexShrink: 0 }} />
        <span style={{ fontWeight: 700, fontSize: 15, color: '#0f172a' }}>Time logged</span>
        <span style={smallMuted}>Last {data.window_days ?? 30} days · Everhour</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: '#0f172a' }}>{data.total_hours}</span>
        <span style={smallMuted}>hours</span>
      </div>

      {hasSplit && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          {split.map(([name, v, color]) =>
            (v ?? 0) > 0 ? (
              <span key={name} style={{ fontSize: 12, color: '#475569' }}>
                <span style={{ ...dot, background: color }} />
                {name}: <strong style={{ color: '#0f172a' }}>{v}h</strong>
              </span>
            ) : null,
          )}
        </div>
      )}

      {members.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {members.map((m) => (
            <div key={m.member_id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: '#334155' }}>{m.name ?? 'Unlinked member'}</span>
              <span style={{ color: '#0f172a', fontWeight: 600 }}>{m.hours}h</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const card: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 16px',
  border: '1px solid #dbeafe', borderRadius: 10, background: '#fff', marginBottom: 20,
}
const smallMuted: React.CSSProperties = { fontSize: 12, color: '#94a3b8' }
const dot: React.CSSProperties = {
  display: 'inline-block', width: 8, height: 8, borderRadius: 999, marginRight: 5,
}
