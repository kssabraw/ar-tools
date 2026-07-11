import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Circle, ListChecks } from 'lucide-react'
import { api } from '../lib/api'
import { TaskDetail } from '../components/tasks/TaskDetail'
import type { MyTasksResponse, TaskCategory, TaskItem, TaskStatus } from '../lib/types'

// My Tasks — suite-level, cross-client view of one team member's open tasks
// grouped by due bucket (PRD §6.6). Assignees are Asana member gids in v1
// (identity unification is deferred), so "me" is a persisted "viewing as"
// selection rather than the login user.

const BUCKETS: { key: keyof MyTasksResponse['buckets']; label: string; color: string }[] = [
  { key: 'overdue', label: 'Overdue', color: '#dc2626' },
  { key: 'today', label: 'Due today', color: '#d97706' },
  { key: 'this_week', label: 'This week', color: '#4f46e5' },
  { key: 'later', label: 'Later', color: '#334155' },
  { key: 'no_date', label: 'No due date', color: '#94a3b8' },
]

const GID_STORAGE_KEY = 'ar-tools:my-tasks-gid'

export function MyTasks() {
  const queryClient = useQueryClient()
  const [gid, setGid] = useState<string>(() => localStorage.getItem(GID_STORAGE_KEY) ?? '')
  const [selectedTask, setSelectedTask] = useState<string | null>(null)

  const { data, isLoading } = useQuery<MyTasksResponse>({
    queryKey: ['my-tasks', gid],
    queryFn: () => api.get<MyTasksResponse>(`/tasks/mine${gid ? `?gid=${encodeURIComponent(gid)}` : ''}`),
  })
  const { data: statuses = [] } = useQuery<TaskStatus[]>({
    queryKey: ['task-statuses'],
    queryFn: () => api.get<TaskStatus[]>('/tasks/statuses'),
  })
  const { data: categories = [] } = useQuery<TaskCategory[]>({
    queryKey: ['task-categories'],
    queryFn: () => api.get<TaskCategory[]>('/tasks/categories'),
  })

  // On first load, adopt the logged-in user's own linked member (identity
  // bridge) when there's one — so a linked person lands on THEIR tasks — else
  // the server's resolved default (first member). A later manual pick is kept
  // in localStorage and wins.
  useEffect(() => {
    if (!gid) setGid(data?.my_gid || data?.gid || '')
  }, [gid, data?.my_gid, data?.gid])

  const completeMut = useMutation({
    mutationFn: (taskId: string) => api.post(`/tasks/${taskId}/complete`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['my-tasks'] }),
  })

  const pickMember = (value: string) => {
    setGid(value)
    localStorage.setItem(GID_STORAGE_KEY, value)
  }

  const members = data?.members ?? []
  const buckets = data?.buckets ?? {}
  const total = BUCKETS.reduce((n, b) => n + (buckets[b.key]?.length ?? 0), 0)

  const row = (t: TaskItem) => (
    <div
      key={t.id}
      onClick={() => setSelectedTask(t.id)}
      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderBottom: '1px solid #f8fafc', cursor: 'pointer' }}
    >
      <button
        onClick={(e) => {
          e.stopPropagation()
          completeMut.mutate(t.id)
        }}
        title="Mark complete"
        style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, color: '#cbd5e1', display: 'inline-flex' }}
      >
        <Circle size={17} />
      </button>
      <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: '#0f172a' }}>{t.name}</span>
      {t.client_id && (
        <Link
          to={`/clients/${t.client_id}/tasks`}
          onClick={(e) => e.stopPropagation()}
          style={{ fontSize: 11, color: '#6366f1', textDecoration: 'none', background: '#eef2ff', borderRadius: 999, padding: '2px 9px', fontWeight: 600 }}
        >
          {t.client_name ?? 'Client'}
        </Link>
      )}
      {t.est_hours != null && <span style={{ fontSize: 11, color: '#94a3b8', width: 34, textAlign: 'right' }}>{t.est_hours}h</span>}
      <span style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', width: 70, textAlign: 'right' }}>
        {t.due_date ? new Date(t.due_date + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''}
      </span>
    </div>
  )

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <ListChecks size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>My Tasks</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 18 }}>
        Everything assigned to you across all clients, grouped by due date.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>Viewing as</span>
        <select
          value={data?.gid ?? gid}
          onChange={(e) => pickMember(e.target.value)}
          style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, background: '#fff', color: '#0f172a' }}
        >
          {members.map((m) => (
            <option key={m.gid} value={m.gid}>{m.name}{m.gid === data?.my_gid ? ' (you)' : ''}</option>
          ))}
        </select>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>{total} open task{total === 1 ? '' : 's'}</span>
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : members.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 13 }}>
          No team members tracked yet — add them on the <Link to="/workload" style={{ color: '#6366f1' }}>Workload</Link> page first.
        </div>
      ) : total === 0 ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#16a34a', fontSize: 14, padding: '24px 0' }}>
          <CheckCircle2 size={18} /> All clear — nothing open.
        </div>
      ) : (
        BUCKETS.map((b) => {
          const rows = buckets[b.key] ?? []
          if (rows.length === 0) return null
          return (
            <div key={b.key} style={{ marginBottom: 22 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: b.color, marginBottom: 6 }}>
                {b.label} <span style={{ color: '#94a3b8', fontWeight: 500 }}>{rows.length}</span>
              </div>
              <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
                {rows.map(row)}
              </div>
            </div>
          )
        })
      )}

      {selectedTask && (
        <TaskDetail
          taskId={selectedTask}
          statuses={statuses}
          categories={categories}
          members={members.map((m) => ({ gid: m.gid, name: m.name }))}
          onClose={() => setSelectedTask(null)}
          invalidateKeys={[['my-tasks']]}
        />
      )}
    </div>
  )
}
