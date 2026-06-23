import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDownRight, CheckCheck, EyeOff, FileX, TrendingDown } from 'lucide-react'
import { api } from '../../lib/api'
import type { RankAlert, RankAlertType, RankAlertsResponse } from '../../lib/types'
import { card, errorBox, outlineBtn, relativeTime } from '../localseo/shared'

const TYPE_META: Record<RankAlertType, { label: string; icon: React.ReactNode; color: string }> = {
  weekly_drop: { label: 'Weekly drop', icon: <ArrowDownRight size={15} />, color: '#dc2626' },
  page_one_exit: { label: 'Off page 1', icon: <TrendingDown size={15} />, color: '#ea580c' },
  thirty_day_drop: { label: '30-day drop', icon: <ArrowDownRight size={15} />, color: '#d97706' },
  deindexed: { label: 'Deindexed', icon: <FileX size={15} />, color: '#b91c1c' },
}

// Per-client Rankings "Alerts" tab. Surfaces the in-app rank-drop alerts the
// daily materialize job opens (weekly_drop / page_one_exit / thirty_day_drop /
// deindexed). Email delivery stays deferred to the notifications service.
export function RankAlerts({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery<RankAlertsResponse>({
    queryKey: ['rank-alerts', clientId],
    queryFn: () => api.get<RankAlertsResponse>(`/clients/${clientId}/rank/alerts`),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['rank-alerts', clientId] })
    queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
  }
  const readMut = useMutation({
    mutationFn: (id: string) => api.post<RankAlert>(`/rank-alerts/${id}/read`, {}),
    onSuccess: invalidate,
  })
  const dismissMut = useMutation({
    mutationFn: (id: string) => api.post<RankAlert>(`/rank-alerts/${id}/dismiss`, {}),
    onSuccess: invalidate,
  })
  const readAllMut = useMutation({
    mutationFn: () => api.post<RankAlertsResponse>(`/clients/${clientId}/rank/alerts/read-all`, {}),
    onSuccess: invalidate,
  })

  const alerts = data?.alerts ?? []

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={sectionTitle}>
          Alerts{data && data.unread_count > 0 ? <span style={countPill}>{data.unread_count} new</span> : null}
        </h2>
        {data && data.unread_count > 0 && (
          <button style={outlineBtn} onClick={() => readAllMut.mutate()} disabled={readAllMut.isPending}>
            <CheckCheck size={14} /> Mark all read
          </button>
        )}
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px', lineHeight: 1.6 }}>
        We flag a keyword when it <strong>drops 6+ spots in a week</strong> from a top-15 position,
        <strong> falls off page 1</strong>, <strong>drops 6+ spots over 30 days</strong> from ~top 20, or
        <strong> falls out of Google's index</strong>. Each alert clears automatically once the keyword recovers.
      </p>

      {error && <div style={errorBox}>{(error as Error).message}</div>}

      {isLoading ? (
        <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>Loading…</p>
      ) : alerts.length === 0 ? (
        <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>
          No alerts. Keywords are holding their positions.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {alerts.map((a, i) => {
            const meta = TYPE_META[a.alert_type]
            const resolved = Boolean(a.resolved_at)
            const unread = a.status === 'unread'
            return (
              <div
                key={a.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, padding: '11px 2px',
                  borderTop: i ? '1px solid #f1f5f9' : 'none', opacity: resolved ? 0.6 : 1,
                }}
              >
                <span style={{ color: meta.color, display: 'flex', flexShrink: 0 }}>{meta.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
                    {unread && <span style={unreadDot} title="Unread" />}
                    <span style={{ fontSize: 13.5, fontWeight: unread ? 700 : 500, color: '#0f172a' }}>{a.message}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3 }}>
                    <span style={{ ...typeTag, color: meta.color, background: `${meta.color}14` }}>{meta.label}</span>
                    {a.source && <span style={sourceTag}>{a.source === 'gsc' ? 'Search Console' : 'DataForSEO'}</span>}
                    {resolved && <span style={recoveredTag}>Recovered</span>}
                    <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{relativeTime(a.created_at)}</span>
                  </div>
                </div>
                {unread && (
                  <button style={{ ...outlineBtn, padding: '4px 9px', fontSize: 12 }}
                    onClick={() => readMut.mutate(a.id)}
                    disabled={readMut.isPending && readMut.variables === a.id}
                    title="Mark read">
                    Read
                  </button>
                )}
                <button style={{ ...outlineBtn, padding: '4px 7px', color: '#94a3b8' }}
                  onClick={() => dismissMut.mutate(a.id)}
                  disabled={dismissMut.isPending && dismissMut.variables === a.id}
                  title="Dismiss"><EyeOff size={13} /></button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const sectionTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: '#0f172a', margin: 0,
  textTransform: 'uppercase', letterSpacing: '0.04em',
  display: 'flex', alignItems: 'center', gap: 8,
}
const countPill: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#b91c1c', background: '#fee2e2',
  borderRadius: 999, padding: '2px 8px', textTransform: 'none', letterSpacing: 0,
}
const unreadDot: React.CSSProperties = {
  width: 7, height: 7, borderRadius: 999, background: '#6366f1', flexShrink: 0,
}
const typeTag: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, borderRadius: 5, padding: '2px 7px',
}
const sourceTag: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#475569', background: '#f1f5f9', borderRadius: 5, padding: '2px 7px',
}
const recoveredTag: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#166534', background: '#dcfce7', borderRadius: 5, padding: '2px 7px',
}
