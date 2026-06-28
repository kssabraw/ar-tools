import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell, Check, X } from 'lucide-react'
import { api } from '../lib/api'
import type { Notification } from '../lib/types'

// Per-client notifications panel (the in-app channel of the notifications
// service). Shows recent alerts — rank drops now, the reoptimization planner
// next — with mark-read / dismiss. Renders nothing when there are none.
export function ClientNotifications({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: notifications = [] } = useQuery<Notification[]>({
    queryKey: ['notifications', clientId],
    queryFn: () => api.get<Notification[]>(`/clients/${clientId}/notifications`),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['notifications', clientId] })
    queryClient.invalidateQueries({ queryKey: ['notification-unread-counts'] })
  }
  const readMut = useMutation({ mutationFn: (id: string) => api.post(`/notifications/${id}/read`, {}), onSuccess: invalidate })
  const dismissMut = useMutation({ mutationFn: (id: string) => api.post(`/notifications/${id}/dismiss`, {}), onSuccess: invalidate })
  const readAllMut = useMutation({ mutationFn: () => api.post(`/clients/${clientId}/notifications/read-all`, {}), onSuccess: invalidate })

  // Hide dismissed; show unread first.
  const visible = useMemo(
    () => notifications
      .filter(n => n.status !== 'dismissed')
      .sort((a, b) => (a.status === 'unread' ? 0 : 1) - (b.status === 'unread' ? 0 : 1)),
    [notifications],
  )
  const unread = visible.filter(n => n.status === 'unread').length

  if (visible.length === 0) return null

  return (
    <section style={{ marginBottom: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Bell size={15} color="#dc2626" />
        <h2 style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', margin: 0, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Alerts{unread ? ` · ${unread} new` : ''}
        </h2>
        {unread > 0 && (
          <button style={linkBtn} onClick={() => readAllMut.mutate()} disabled={readAllMut.isPending}>
            Mark all read
          </button>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {visible.map(n => {
          const c = sev(n.severity)
          const link = typeof n.payload?.link === 'string' ? (n.payload.link as string) : null
          return (
            <div key={n.id} style={{ ...row, borderLeft: `3px solid ${c.bar}`, background: n.status === 'unread' ? '#fff' : '#f8fafc' }}>
              <div
                style={{ flex: 1, minWidth: 0, cursor: link ? 'pointer' : 'default' }}
                onClick={() => { if (link) { if (n.status === 'unread') readMut.mutate(n.id); navigate('/' + link.replace(/^\//, '')) } }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ ...pill, color: c.fg, background: c.bg }}>{n.severity}</span>
                  <span style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{n.title}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>{new Date(n.created_at).toLocaleDateString()}</span>
                </div>
                {n.summary && <div style={{ fontSize: 12, color: '#64748b', marginTop: 2, lineHeight: 1.5 }}>{n.summary}</div>}
              </div>
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                {n.status === 'unread' && (
                  <button style={iconBtn} title="Mark read" onClick={() => readMut.mutate(n.id)}><Check size={14} /></button>
                )}
                <button style={iconBtn} title="Dismiss" onClick={() => dismissMut.mutate(n.id)}><X size={14} /></button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function sev(severity: string): { bar: string; fg: string; bg: string } {
  switch (severity) {
    case 'critical': return { bar: '#dc2626', fg: '#b91c1c', bg: '#fef2f2' }
    case 'warning': return { bar: '#f59e0b', fg: '#b45309', bg: '#fffbeb' }
    default: return { bar: '#6366f1', fg: '#4338ca', bg: '#eef2ff' }
  }
}

const row: React.CSSProperties = { display: 'flex', alignItems: 'flex-start', gap: 10, padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: 8 }
const pill: React.CSSProperties = { fontSize: 9, fontWeight: 700, borderRadius: 999, padding: '1px 7px', textTransform: 'uppercase', letterSpacing: '0.03em' }
const iconBtn: React.CSSProperties = { background: 'none', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', color: '#64748b', padding: '4px 6px', display: 'inline-flex' }
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', color: '#6366f1', fontSize: 12, fontWeight: 600, cursor: 'pointer', marginLeft: 'auto' }
