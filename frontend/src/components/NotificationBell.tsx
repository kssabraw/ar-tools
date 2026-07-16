import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { api } from '../lib/api'

// Personal notification bell in the sidebar header. Polls the logged-in user's
// own notifications (nudges / task assignments / @mentions), shows an unread
// badge + dropdown, and pops a transient toast when a new one arrives while the
// tab is open. Fed by GET /notifications/mine (recipient_profile_id = me).

interface MyNotification {
  id: string
  kind: string
  severity: string
  title: string
  summary?: string | null
  payload?: { link?: string } | null
  status: string
  created_at: string
}
interface MyResp { items: MyNotification[]; unread: number }

const SEV_BAR: Record<string, string> = { info: '#3b82f6', warning: '#f59e0b', critical: '#ef4444' }

export function NotificationBell() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [toast, setToast] = useState<MyNotification | null>(null)
  const lastTopId = useRef<string | null>(null)
  const primed = useRef(false)

  const { data } = useQuery<MyResp>({
    queryKey: ['my-notifications'],
    queryFn: () => api.get<MyResp>('/notifications/mine?limit=30'),
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  })
  const items = data?.items ?? []
  const unread = data?.unread ?? 0

  // Toast on a genuinely new unread notification. Skip the first load (so we
  // don't toast the backlog), then fire whenever the newest id changes.
  useEffect(() => {
    const top = items[0]
    if (!top) return
    if (!primed.current) { primed.current = true; lastTopId.current = top.id; return }
    if (top.id !== lastTopId.current) {
      lastTopId.current = top.id
      if (top.status === 'unread') {
        setToast(top)
        const t = setTimeout(() => setToast(null), 6000)
        return () => clearTimeout(t)
      }
    }
  }, [items])

  const invalidate = () => qc.invalidateQueries({ queryKey: ['my-notifications'] })
  const readOne = useMutation({ mutationFn: (id: string) => api.post(`/notifications/mine/${id}/read`, {}), onSuccess: invalidate })
  const readAll = useMutation({ mutationFn: () => api.post('/notifications/mine/read-all', {}), onSuccess: invalidate })

  const openItem = (n: MyNotification) => {
    if (n.status === 'unread') readOne.mutate(n.id)
    setOpen(false)
    setToast(null)
    const link = n.payload?.link
    if (link) navigate('/' + link.replace(/^\//, ''))
  }

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(o => !o)} title="Notifications" style={bellBtn}>
        <Bell size={18} />
        {unread > 0 && <span style={badge}>{unread > 9 ? '9+' : unread}</span>}
      </button>

      {open && <div onClick={() => setOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 70 }} />}
      {open && (
        <div style={panel}>
          <div style={panelHead}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>Notifications</span>
            {unread > 0 && (
              <button style={linkBtn} onClick={() => readAll.mutate()} disabled={readAll.isPending}>
                Mark all read
              </button>
            )}
          </div>
          <div style={{ maxHeight: 360, overflowY: 'auto' }}>
            {items.length === 0 && (
              <div style={{ padding: 16, color: '#94a3b8', fontSize: 13 }}>You&rsquo;re all caught up.</div>
            )}
            {items.map(n => (
              <div
                key={n.id}
                onClick={() => openItem(n)}
                style={{
                  ...row,
                  borderLeft: `3px solid ${SEV_BAR[n.severity] ?? '#3b82f6'}`,
                  background: n.status === 'unread' ? '#fff' : '#f8fafc',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: n.status === 'unread' ? 600 : 400, color: '#0f172a' }}>
                  {n.title}
                </div>
                {n.summary && <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{n.summary}</div>}
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>
                  {new Date(n.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {toast && (
        <div style={toastStyle} onClick={() => openItem(toast)}>
          <Bell size={15} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>{toast.title}</div>
            {toast.summary && <div style={{ fontSize: 12, opacity: 0.8, marginTop: 2 }}>{toast.summary}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

const bellBtn: CSSProperties = {
  position: 'relative', background: 'none', border: 'none', color: '#cbd5e1',
  cursor: 'pointer', padding: 4, display: 'flex', alignItems: 'center',
}
const badge: CSSProperties = {
  position: 'absolute', top: -3, right: -3, background: '#ef4444', color: '#fff',
  borderRadius: 999, fontSize: 10, fontWeight: 700, minWidth: 16, height: 16,
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 4px',
}
const panel: CSSProperties = {
  position: 'absolute', top: '130%', left: 0, width: 300, background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 10, boxShadow: '0 8px 24px rgba(15,23,42,0.18)',
  zIndex: 80, color: '#0f172a', overflow: 'hidden',
}
const panelHead: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 12px', borderBottom: '1px solid #f1f5f9',
}
const linkBtn: CSSProperties = { background: 'none', border: 'none', color: '#4338ca', cursor: 'pointer', fontSize: 12 }
const row: CSSProperties = { padding: '8px 12px', borderBottom: '1px solid #f1f5f9', cursor: 'pointer' }
const toastStyle: CSSProperties = {
  position: 'fixed', bottom: 20, right: 20, maxWidth: 340, background: '#0f172a',
  color: '#f1f5f9', padding: '12px 14px', borderRadius: 10, boxShadow: '0 8px 24px rgba(15,23,42,0.35)',
  zIndex: 200, display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer',
}
