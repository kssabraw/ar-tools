import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, CheckCircle2, Circle, Copy, Paperclip, Plus, RotateCcw, Send, Trash2, X } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../context/AuthContext'
import type { TaskCategory, TaskDetailResponse, TaskStatus } from '../../lib/types'

// Right-side drawer for one task: edit fields, work the subtask checklist,
// complete/reopen/trash, and read the activity feed. Shared by the per-client
// Tasks board and My Tasks.

interface Member {
  gid: string
  name: string | null
}

interface TaskDetailProps {
  taskId: string
  statuses: TaskStatus[]
  categories: TaskCategory[]
  members: Member[]
  onClose: () => void
  // Query keys to refresh after any mutation (board / my-tasks callers differ).
  invalidateKeys: unknown[][]
}

const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }
const input: React.CSSProperties = { width: '100%', padding: '7px 9px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, fontFamily: 'inherit', background: '#fff', color: '#0f172a', boxSizing: 'border-box' }

const ACTIVITY_LABELS: Record<string, string> = {
  created: 'created this task',
  renamed: 'renamed the task',
  edited: 'edited the description',
  assigned: 'changed the assignee',
  status_changed: 'changed the status',
  category_changed: 'changed the category',
  due_changed: 'changed a date',
  estimate_changed: 'changed the estimate',
  moved: 'moved the task',
  commented: 'commented',
  attached: 'attached a file',
  completed: 'completed the task',
  reopened: 'reopened the task',
  auto_closed: 'auto-closed (signal resolved)',
  trashed: 'moved to trash',
  restored: 'restored from trash',
}

function formatBytes(n: number | null): string {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function TaskDetail({ taskId, statuses, categories, members, onClose, invalidateKeys }: TaskDetailProps) {
  const queryClient = useQueryClient()
  const { user, isAdmin } = useAuth()
  const fileInput = useRef<HTMLInputElement>(null)
  const [newSubtask, setNewSubtask] = useState('')
  const [newComment, setNewComment] = useState('')
  const [editingComment, setEditingComment] = useState<{ id: string; body: string } | null>(null)
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [descDraft, setDescDraft] = useState<string | null>(null)
  const [clientNoteDraft, setClientNoteDraft] = useState<string | null>(null)

  const { data: task, isLoading } = useQuery<TaskDetailResponse>({
    queryKey: ['task-detail', taskId],
    queryFn: () => api.get<TaskDetailResponse>(`/tasks/${taskId}`),
  })

  // Reset drafts when switching tasks.
  useEffect(() => {
    setNameDraft(null)
    setDescDraft(null)
    setNewSubtask('')
  }, [taskId])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['task-detail', taskId] })
    for (const key of invalidateKeys) queryClient.invalidateQueries({ queryKey: key })
  }

  const patchMut = useMutation({
    mutationFn: (changes: Record<string, unknown>) => api.patch(`/tasks/${taskId}`, changes),
    onSuccess: invalidate,
  })
  const completeMut = useMutation({
    mutationFn: (id: string) => api.post(`/tasks/${id}/complete`, {}),
    onSuccess: invalidate,
  })
  const reopenMut = useMutation({
    mutationFn: (id: string) => api.post(`/tasks/${id}/reopen`, {}),
    onSuccess: invalidate,
  })
  const trashMut = useMutation({
    mutationFn: (id: string) => api.delete(`/tasks/${id}`),
    onSuccess: () => {
      invalidate()
      onClose()
    },
  })
  const trashSubtaskMut = useMutation({
    mutationFn: (id: string) => api.delete(`/tasks/${id}`),
    onSuccess: invalidate,
  })
  const addSubtaskMut = useMutation({
    mutationFn: (name: string) =>
      api.post('/tasks', {
        name,
        parent_task_id: taskId,
        client_id: task?.client_id ?? null,
        section_id: task?.section_id ?? null,
        sort_order: task?.subtasks.length ?? 0,
      }),
    onSuccess: () => {
      setNewSubtask('')
      invalidate()
    },
  })
  const commentMut = useMutation({
    mutationFn: (body: string) => api.post(`/tasks/${taskId}/comments`, { body }),
    onSuccess: () => {
      setNewComment('')
      invalidate()
    },
  })
  const editCommentMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) => api.patch(`/tasks/comments/${id}`, { body }),
    onSuccess: () => {
      setEditingComment(null)
      invalidate()
    },
  })
  const deleteCommentMut = useMutation({
    mutationFn: (id: string) => api.delete(`/tasks/comments/${id}`),
    onSuccess: invalidate,
  })
  const uploadMut = useMutation({
    mutationFn: (file: globalThis.File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload(`/tasks/${taskId}/attachments`, form)
    },
    onSuccess: invalidate,
  })
  const deleteAttachmentMut = useMutation({
    mutationFn: (id: string) => api.delete(`/tasks/attachments/${id}`),
    onSuccess: invalidate,
  })
  const watchMut = useMutation({
    mutationFn: (watching: boolean) =>
      watching ? api.delete(`/tasks/${taskId}/watch`) : api.post(`/tasks/${taskId}/watch`, {}),
    onSuccess: invalidate,
  })
  const duplicateMut = useMutation({
    mutationFn: () => api.post(`/tasks/${taskId}/duplicate`, { with_subtasks: true }),
    onSuccess: () => {
      invalidate()
      onClose()
    },
  })

  const patchField = (field: string, value: unknown) => {
    if (!task) return
    if ((task as unknown as Record<string, unknown>)[field] === value) return
    patchMut.mutate({ [field]: value })
  }

  const setAssignee = (gid: string) => {
    const member = members.find((m) => m.gid === gid)
    patchMut.mutate({ assignee_gid: gid || null, assignee_name: member?.name ?? null })
  }

  return (
    <div
      style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 420, maxWidth: '92vw',
        background: '#fff', borderLeft: '1px solid #e2e8f0', boxShadow: '-8px 0 24px rgba(15,23,42,0.08)',
        zIndex: 50, display: 'flex', flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid #f1f5f9' }}>
        <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>
          {task?.completed ? 'Completed task' : 'Task'}
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {task && (
            task.completed ? (
              <button
                onClick={() => reopenMut.mutate(taskId)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '6px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
              >
                <RotateCcw size={13} /> Reopen
              </button>
            ) : (
              <button
                onClick={() => completeMut.mutate(taskId)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '6px 12px', borderRadius: 8, border: 'none', background: '#22c55e', color: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
              >
                <CheckCircle2 size={13} /> Complete
              </button>
            )
          )}
          {task && (
            <button
              onClick={() => watchMut.mutate(Boolean(user && task.watchers?.includes(user.id)))}
              title={user && task.watchers?.includes(user.id) ? 'Stop watching' : 'Watch this task'}
              style={{ border: 'none', background: 'none', color: user && task.watchers?.includes(user.id) ? '#6366f1' : '#cbd5e1', cursor: 'pointer', padding: 4 }}
            >
              {user && task.watchers?.includes(user.id) ? <Bell size={15} /> : <BellOff size={15} />}
            </button>
          )}
          {task && (
            <button
              onClick={() => duplicateMut.mutate()}
              title="Duplicate (with checklist)"
              style={{ border: 'none', background: 'none', color: '#cbd5e1', cursor: 'pointer', padding: 4 }}
            >
              <Copy size={15} />
            </button>
          )}
          {task && (
            <button
              onClick={() => { if (window.confirm('Move this task to the trash?')) trashMut.mutate(taskId) }}
              title="Move to trash"
              style={{ border: 'none', background: 'none', color: '#cbd5e1', cursor: 'pointer', padding: 4 }}
            >
              <Trash2 size={15} />
            </button>
          )}
          <button onClick={onClose} style={{ border: 'none', background: 'none', color: '#64748b', cursor: 'pointer', padding: 4 }}>
            <X size={17} />
          </button>
        </div>
      </div>

      {isLoading || !task ? (
        <div style={{ padding: 24, color: '#94a3b8', fontSize: 13 }}>Loading…</div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
          {/* Name */}
          <input
            value={nameDraft ?? task.name}
            onChange={(e) => setNameDraft(e.target.value)}
            onBlur={() => {
              if (nameDraft !== null && nameDraft.trim() && nameDraft !== task.name) patchField('name', nameDraft.trim())
              setNameDraft(null)
            }}
            style={{ ...input, fontSize: 16, fontWeight: 700, border: '1px solid transparent', padding: '4px 6px', marginLeft: -6, textDecoration: task.completed ? 'line-through' : 'none', color: task.completed ? '#94a3b8' : '#0f172a' }}
          />

          {/* Fields grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 16 }}>
            <div>
              <div style={label}>Status</div>
              <select value={task.status_key ?? ''} onChange={(e) => patchField('status_key', e.target.value || null)} style={input}>
                {statuses.filter((s) => s.active).map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <div style={label}>Assignee</div>
              <select value={task.assignee_gid ?? ''} onChange={(e) => setAssignee(e.target.value)} style={input}>
                <option value="">Unassigned</option>
                {members.map((m) => (
                  <option key={m.gid} value={m.gid}>{m.name ?? m.gid}</option>
                ))}
              </select>
            </div>
            <div>
              <div style={label}>Service type</div>
              <select value={task.category ?? ''} onChange={(e) => patchField('category', e.target.value || null)} style={input}>
                <option value="">—</option>
                {categories.filter((c) => c.active).map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
                ))}
              </select>
            </div>
            <div>
              <div style={label}>Est. hours</div>
              <input
                type="number" min={0} step={0.25} defaultValue={task.est_hours ?? ''}
                key={`hours-${task.id}-${task.est_hours}`}
                onBlur={(e) => patchField('est_hours', e.target.value === '' ? null : Number(e.target.value))}
                style={input}
              />
            </div>
            <div>
              <div style={label}>Due date</div>
              <input type="date" value={task.due_date ?? ''} onChange={(e) => patchField('due_date', e.target.value || null)} style={input} />
            </div>
            <div>
              <div style={label}>Start date</div>
              <input type="date" value={task.start_date ?? ''} onChange={(e) => patchField('start_date', e.target.value || null)} style={input} />
            </div>
          </div>

          {/* Description */}
          <div style={{ marginTop: 16 }}>
            <div style={label}>Description</div>
            <textarea
              value={descDraft ?? task.description ?? ''}
              onChange={(e) => setDescDraft(e.target.value)}
              onBlur={() => {
                if (descDraft !== null && descDraft !== (task.description ?? '')) patchField('description', descDraft || null)
                setDescDraft(null)
              }}
              rows={4}
              placeholder="Notes, links, acceptance criteria…"
              style={{ ...input, resize: 'vertical' }}
            />
          </div>

          {/* Client note — CLIENT-FACING (Weekly Pulse); the description above
              stays internal and never reaches a client email. */}
          <div style={{ marginTop: 12 }}>
            <div style={label}>Client note <span style={{ fontWeight: 400, color: '#94a3b8' }}>(client-facing — appears in the Weekly Pulse)</span></div>
            <textarea
              value={clientNoteDraft ?? task.client_note ?? ''}
              onChange={(e) => setClientNoteDraft(e.target.value)}
              onBlur={() => {
                if (clientNoteDraft !== null && clientNoteDraft !== (task.client_note ?? '')) patchField('client_note', clientNoteDraft || null)
                setClientNoteDraft(null)
              }}
              rows={2}
              placeholder="Plain-English outcome/explanation for the client, e.g. “Rewrote the homepage intro to target ‘roof repair Miami’”"
              style={{ ...input, resize: 'vertical' }}
            />
          </div>

          {/* Subtasks */}
          <div style={{ marginTop: 18 }}>
            <div style={label}>
              Checklist {task.subtasks.length > 0 && `(${task.subtasks.filter((s) => s.completed).length}/${task.subtasks.length})`}
            </div>
            {task.subtasks.map((s) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid #f8fafc' }}>
                <button
                  onClick={() => (s.completed ? reopenMut : completeMut).mutate(s.id)}
                  style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, color: s.completed ? '#22c55e' : '#cbd5e1', display: 'inline-flex' }}
                >
                  {s.completed ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                </button>
                <span style={{ flex: 1, fontSize: 13, color: s.completed ? '#94a3b8' : '#334155', textDecoration: s.completed ? 'line-through' : 'none' }}>
                  {s.name}
                </span>
                <button
                  onClick={() => trashSubtaskMut.mutate(s.id)}
                  title="Remove"
                  style={{ border: 'none', background: 'none', color: '#e2e8f0', cursor: 'pointer', padding: 2 }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              <input
                value={newSubtask}
                onChange={(e) => setNewSubtask(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && newSubtask.trim()) addSubtaskMut.mutate(newSubtask.trim()) }}
                placeholder="Add checklist item…"
                style={{ ...input, flex: 1 }}
              />
              <button
                onClick={() => newSubtask.trim() && addSubtaskMut.mutate(newSubtask.trim())}
                disabled={!newSubtask.trim() || addSubtaskMut.isPending}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '7px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 12, fontWeight: 600, cursor: 'pointer', opacity: newSubtask.trim() ? 1 : 0.5 }}
              >
                <Plus size={13} /> Add
              </button>
            </div>
          </div>

          {/* Attachments */}
          <div style={{ marginTop: 18 }}>
            <div style={label}>Attachments</div>
            {(task.attachments ?? []).map((a) => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderBottom: '1px solid #f8fafc' }}>
                <Paperclip size={13} color="#94a3b8" />
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer" style={{ flex: 1, fontSize: 13, color: '#4f46e5', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {a.file_name}
                  </a>
                ) : (
                  <span style={{ flex: 1, fontSize: 13, color: '#64748b' }}>{a.file_name}</span>
                )}
                <span style={{ fontSize: 11, color: '#cbd5e1' }}>{formatBytes(a.size_bytes)}</span>
                <button
                  onClick={() => deleteAttachmentMut.mutate(a.id)}
                  title="Remove"
                  style={{ border: 'none', background: 'none', color: '#e2e8f0', cursor: 'pointer', padding: 2 }}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
            <input
              ref={fileInput}
              type="file"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadMut.mutate(f)
                e.target.value = ''
              }}
            />
            <button
              onClick={() => fileInput.current?.click()}
              disabled={uploadMut.isPending}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 8, padding: '6px 12px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
            >
              <Paperclip size={13} /> {uploadMut.isPending ? 'Uploading…' : 'Attach file'}
            </button>
            {uploadMut.isError && (
              <div style={{ fontSize: 12, color: '#dc2626', marginTop: 6 }}>Upload failed — {String((uploadMut.error as Error)?.message ?? 'try again')}</div>
            )}
          </div>

          {/* Comments */}
          <div style={{ marginTop: 18 }}>
            <div style={label}>Comments</div>
            {(task.comments ?? []).map((c) => (
              <div key={c.id} style={{ padding: '8px 0', borderBottom: '1px solid #f8fafc' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>{c.author_name ?? 'Someone'}</span>
                  <span style={{ fontSize: 11, color: '#cbd5e1' }}>
                    {new Date(c.created_at).toLocaleString()}{c.edited_at ? ' · edited' : ''}
                  </span>
                  {user && c.author_id === user.id && editingComment?.id !== c.id && (
                    <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8 }}>
                      <button onClick={() => setEditingComment({ id: c.id, body: c.body })} style={{ border: 'none', background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 11, padding: 0 }}>Edit</button>
                      <button onClick={() => deleteCommentMut.mutate(c.id)} style={{ border: 'none', background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 11, padding: 0 }}>Delete</button>
                    </span>
                  )}
                  {isAdmin && user && c.author_id !== user.id && (
                    <button onClick={() => deleteCommentMut.mutate(c.id)} style={{ marginLeft: 'auto', border: 'none', background: 'none', color: '#cbd5e1', cursor: 'pointer', fontSize: 11, padding: 0 }}>Delete</button>
                  )}
                </div>
                {editingComment?.id === c.id ? (
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    <input
                      value={editingComment.body}
                      onChange={(e) => setEditingComment({ id: c.id, body: e.target.value })}
                      onKeyDown={(e) => { if (e.key === 'Enter' && editingComment.body.trim()) editCommentMut.mutate({ id: c.id, body: editingComment.body.trim() }) }}
                      style={{ ...input, flex: 1 }}
                      autoFocus
                    />
                    <button onClick={() => setEditingComment(null)} style={{ border: 'none', background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 11 }}>Cancel</button>
                  </div>
                ) : (
                  <div style={{ fontSize: 13, color: '#334155', marginTop: 3, whiteSpace: 'pre-wrap' }}>{c.body}</div>
                )}
              </div>
            ))}
            <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
              <input
                value={newComment}
                onChange={(e) => setNewComment(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && newComment.trim()) commentMut.mutate(newComment.trim()) }}
                placeholder="Comment… (@Name to mention)"
                style={{ ...input, flex: 1 }}
              />
              <button
                onClick={() => newComment.trim() && commentMut.mutate(newComment.trim())}
                disabled={!newComment.trim() || commentMut.isPending}
                title="Send"
                style={{ display: 'inline-flex', alignItems: 'center', padding: '7px 12px', borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff', cursor: 'pointer', opacity: newComment.trim() ? 1 : 0.5 }}
              >
                <Send size={14} />
              </button>
            </div>
          </div>

          {/* Activity */}
          <div style={{ marginTop: 22 }}>
            <div style={label}>Activity</div>
            {task.activity.length === 0 ? (
              <div style={{ fontSize: 12, color: '#cbd5e1' }}>No activity yet.</div>
            ) : (
              task.activity.map((a) => (
                <div key={a.id} style={{ fontSize: 12, color: '#94a3b8', padding: '3px 0' }}>
                  {ACTIVITY_LABELS[a.kind] ?? a.kind}
                  {a.detail && typeof a.detail.to === 'string' && a.kind !== 'created' ? ` → ${a.detail.to}` : ''}
                  <span style={{ color: '#cbd5e1' }}> · {new Date(a.created_at).toLocaleString()}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
