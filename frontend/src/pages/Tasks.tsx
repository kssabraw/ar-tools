import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CalendarDays, CalendarPlus, CheckCircle2, Circle, KanbanSquare, List, Plus, RotateCcw, Search, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { TaskDetail } from '../components/tasks/TaskDetail'
import { TaskCalendar } from '../components/tasks/TaskCalendar'
import type {
  Client,
  TaskBoardResponse,
  TaskCategory,
  TaskItem,
  TaskSection,
  TaskStatus,
  TaskTrashItem,
} from '../lib/types'

// Native task manager — per-client board/list (Phase 1,
// docs/modules/in-app-task-manager-prd-v1_0.md §6.6). Board columns group by
// status (drag a card to change it); List groups by section (the monthly
// delivery view) with inline quick-add + complete.

interface Member {
  gid: string
  name: string | null
  weekly_hours?: number | null
}

type ViewMode = 'board' | 'list' | 'calendar'
type Preset = '' | 'overdue' | 'due_week' | 'unassigned'

interface ViewConfig {
  view?: ViewMode
  q?: string
  assignee?: string
  category?: string
  section?: string
  preset?: Preset
}

interface SavedView {
  id: string
  name: string
  config: ViewConfig
  shared: boolean
}

const BUILTIN_VIEWS: { key: Preset; label: string }[] = [
  { key: 'overdue', label: 'Overdue' },
  { key: 'due_week', label: 'Due this week' },
  { key: 'unassigned', label: 'Unassigned' },
]

const chip = (color: string | null | undefined, text: string) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: 999, background: (color ?? '#94a3b8') + '1a', color: color ?? '#64748b', fontSize: 11, fontWeight: 600 }}>
    {text}
  </span>
)

function isOverdue(t: TaskItem): boolean {
  return Boolean(t.due_date && !t.completed && t.due_date < new Date().toISOString().slice(0, 10))
}

function dueLabel(t: TaskItem): string | null {
  if (!t.due_date) return null
  const d = new Date(t.due_date + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function Tasks() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  const [view, setView] = useState<ViewMode>('board')
  const [q, setQ] = useState('')
  const [assignee, setAssignee] = useState('')
  const [category, setCategory] = useState('')
  const [sectionFilter, setSectionFilter] = useState('')
  const [preset, setPreset] = useState<Preset>('')
  const [activeSavedView, setActiveSavedView] = useState<SavedView | null>(null)
  const [showTrash, setShowTrash] = useState(false)
  const [quickAdd, setQuickAdd] = useState<Record<string, string>>({})
  const [boardAdd, setBoardAdd] = useState<Record<string, string>>({})
  const [genResult, setGenResult] = useState<string | null>(null)

  // Drawer state lives in the URL (?task=…) so mention notifications can
  // deep-link straight to a task.
  const selectedTask = searchParams.get('task')
  const setSelectedTask = (taskId: string | null) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (taskId) next.set('task', taskId)
        else next.delete('task')
        return next
      },
      { replace: true },
    )
  }

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data: board, isLoading } = useQuery<TaskBoardResponse>({
    queryKey: ['task-board', id],
    queryFn: () => api.get<TaskBoardResponse>(`/clients/${id}/task-board`),
    enabled: Boolean(id),
  })
  const { data: statuses = [] } = useQuery<TaskStatus[]>({
    queryKey: ['task-statuses'],
    queryFn: () => api.get<TaskStatus[]>('/tasks/statuses'),
  })
  const { data: categories = [] } = useQuery<TaskCategory[]>({
    queryKey: ['task-categories'],
    queryFn: () => api.get<TaskCategory[]>('/tasks/categories'),
  })
  const { data: members = [] } = useQuery<Member[]>({
    queryKey: ['asana-team-members'],
    queryFn: () => api.get<Member[]>('/asana/team-members'),
  })

  const invalidateBoard = () => queryClient.invalidateQueries({ queryKey: ['task-board', id] })

  const generateMut = useMutation({
    mutationFn: () => api.post<{ status: string; section: string; created: number; existing: number; reason?: string }>(`/clients/${id}/tasks/generate-month`, {}),
    onSuccess: (r) => {
      invalidateBoard()
      setGenResult(
        r.status === 'created'
          ? `Created ${r.created} task${r.created === 1 ? '' : 's'} in ${r.section}.`
          : r.status === 'exists'
            ? `${r.section} is already generated.`
            : `Skipped — ${r.reason === 'no_template' ? 'this client has no monthly template yet (set it up under Asana Tasks → templates).' : r.reason}`,
      )
      setTimeout(() => setGenResult(null), 6000)
    },
  })
  const patchMut = useMutation({
    mutationFn: ({ taskId, changes }: { taskId: string; changes: Record<string, unknown> }) =>
      api.patch(`/tasks/${taskId}`, changes),
    onSuccess: invalidateBoard,
  })
  const completeMut = useMutation({
    mutationFn: (taskId: string) => api.post(`/tasks/${taskId}/complete`, {}),
    onSuccess: invalidateBoard,
  })
  const reopenMut = useMutation({
    mutationFn: (taskId: string) => api.post(`/tasks/${taskId}/reopen`, {}),
    onSuccess: invalidateBoard,
  })
  const createMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<TaskItem>('/tasks', body),
    onSuccess: invalidateBoard,
  })
  const createSectionMut = useMutation({
    mutationFn: (name: string) => api.post(`/clients/${id}/task-sections`, { name, kind: 'custom' }),
    onSuccess: invalidateBoard,
  })
  const { data: savedViews = [] } = useQuery<SavedView[]>({
    queryKey: ['task-views'],
    queryFn: () => api.get<SavedView[]>('/tasks/views'),
  })
  const saveViewMut = useMutation({
    mutationFn: ({ name, shared, config }: { name: string; shared: boolean; config: ViewConfig }) =>
      api.post<SavedView>('/tasks/views', { name, shared, config }),
    onSuccess: (v) => {
      setActiveSavedView(v)
      queryClient.invalidateQueries({ queryKey: ['task-views'] })
    },
  })
  const deleteViewMut = useMutation({
    mutationFn: (viewId: string) => api.delete(`/tasks/views/${viewId}`),
    onSuccess: () => {
      setActiveSavedView(null)
      queryClient.invalidateQueries({ queryKey: ['task-views'] })
    },
  })
  const { data: trash = [] } = useQuery<TaskTrashItem[]>({
    queryKey: ['task-trash', id],
    queryFn: () => api.get<TaskTrashItem[]>(`/clients/${id}/tasks/trash`),
    enabled: Boolean(id) && showTrash,
  })
  const invalidateTrash = () => {
    invalidateBoard()
    queryClient.invalidateQueries({ queryKey: ['task-trash', id] })
  }
  const restoreMut = useMutation({
    mutationFn: (taskId: string) => api.post(`/tasks/${taskId}/restore`, {}),
    onSuccess: invalidateTrash,
  })
  const purgeMut = useMutation({
    mutationFn: (taskId: string) => api.delete(`/tasks/${taskId}/permanent`),
    onSuccess: invalidateTrash,
  })

  const sections: TaskSection[] = board?.sections ?? []
  const activeStatuses = statuses.filter((s) => s.active)
  const catByKey = useMemo(() => Object.fromEntries(categories.map((c) => [c.key, c])), [categories])

  const tasks = useMemo(() => {
    let rows = board?.tasks ?? []
    if (q.trim()) {
      const needle = q.trim().toLowerCase()
      rows = rows.filter((t) => t.name.toLowerCase().includes(needle) || (t.description ?? '').toLowerCase().includes(needle))
    }
    if (assignee) rows = rows.filter((t) => t.assignee_gid === assignee)
    if (category) rows = rows.filter((t) => t.category === category)
    if (sectionFilter) rows = rows.filter((t) => t.section_id === sectionFilter)
    if (preset) {
      const today = new Date().toISOString().slice(0, 10)
      const weekEnd = new Date(Date.now() + 7 * 86400_000).toISOString().slice(0, 10)
      if (preset === 'overdue') rows = rows.filter((t) => !t.completed && t.due_date != null && t.due_date < today)
      else if (preset === 'due_week') rows = rows.filter((t) => !t.completed && t.due_date != null && t.due_date >= today && t.due_date <= weekEnd)
      else if (preset === 'unassigned') rows = rows.filter((t) => !t.completed && !t.assignee_gid)
    }
    return rows
  }, [board?.tasks, q, assignee, category, sectionFilter, preset])

  const applyViewConfig = (cfg: ViewConfig) => {
    setView(cfg.view ?? 'board')
    setQ(cfg.q ?? '')
    setAssignee(cfg.assignee ?? '')
    setCategory(cfg.category ?? '')
    setSectionFilter(cfg.section ?? '')
    setPreset(cfg.preset ?? '')
  }

  const onViewSelect = (value: string) => {
    if (!value) return
    if (value === 'save') {
      const name = window.prompt('Name this view:')
      if (!name?.trim()) return
      const shared = window.confirm('Share this view with the whole team?\n(OK = shared, Cancel = private)')
      saveViewMut.mutate({
        name: name.trim(),
        shared,
        config: { view, q, assignee, category, section: sectionFilter, preset },
      })
      return
    }
    if (value.startsWith('builtin:')) {
      setActiveSavedView(null)
      applyViewConfig({ view: 'list', preset: value.slice(8) as Preset })
      return
    }
    const saved = savedViews.find((v) => v.id === value)
    if (saved) {
      setActiveSavedView(saved)
      applyViewConfig(saved.config)
    }
  }

  const onDropToStatus = (taskId: string, status: TaskStatus) => {
    const task = tasks.find((t) => t.id === taskId)
    if (!task || task.status_key === status.key) return
    if (status.is_done && !task.completed) {
      completeMut.mutate(taskId)
    } else if (task.completed && !status.is_done) {
      // Reopening (clears `completed`, resets to the initial status) must land
      // BEFORE the target-status write — otherwise a late reopen overwrites the
      // status and the card snaps back to Not Started. Sequence, don't race.
      reopenMut
        .mutateAsync(taskId)
        .then(() => patchMut.mutate({ taskId, changes: { status_key: status.key } }))
        .catch(() => {})
    } else {
      patchMut.mutate({ taskId, changes: { status_key: status.key } })
    }
  }

  const quickAddTask = (sectionId: string | null) => {
    const key = sectionId ?? 'none'
    const name = (quickAdd[key] ?? '').trim()
    if (!name) return
    createMut.mutate({ name, client_id: id, section_id: sectionId, sort_order: tasks.length })
    setQuickAdd((prev) => ({ ...prev, [key]: '' }))
  }

  // Board quick-add: a task added under a status column is created with that
  // column's status, and lands in the newest month section so it also shows in
  // List view. A "done" column marks it complete (mirrors drag-to-done).
  const quickAddToStatus = (status: TaskStatus) => {
    const name = (boardAdd[status.key] ?? '').trim()
    if (!name) return
    createMut
      .mutateAsync({ name, client_id: id, section_id: sections[0]?.id ?? null, status_key: status.key, sort_order: tasks.length })
      .then((created) => {
        if (status.is_done && created?.id) completeMut.mutate(created.id)
      })
      .catch(() => {})
    setBoardAdd((prev) => ({ ...prev, [status.key]: '' }))
  }

  const card = (t: TaskItem) => {
    const cat = t.category ? catByKey[t.category] : null
    return (
      <div
        key={t.id}
        draggable
        onDragStart={(e) => e.dataTransfer.setData('text/task-id', t.id)}
        onClick={() => setSelectedTask(t.id)}
        style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 12px', marginBottom: 8, cursor: 'pointer', boxShadow: '0 1px 2px rgba(15,23,42,0.04)' }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: t.completed ? '#94a3b8' : '#0f172a', textDecoration: t.completed ? 'line-through' : 'none' }}>
          {t.name}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          {cat && chip(cat.color, cat.label)}
          {t.subtask_total ? (
            <span style={{ fontSize: 11, color: '#94a3b8' }}>☑ {t.subtask_done}/{t.subtask_total}</span>
          ) : null}
          {t.est_hours != null && <span style={{ fontSize: 11, color: '#94a3b8' }}>{t.est_hours}h</span>}
          {t.due_date && (
            <span style={{ fontSize: 11, fontWeight: 600, color: isOverdue(t) ? '#dc2626' : '#94a3b8' }}>{dueLabel(t)}</span>
          )}
          {t.assignee_name && (
            <span style={{ marginLeft: 'auto', fontSize: 11, color: '#64748b', background: '#f1f5f9', borderRadius: 999, padding: '2px 8px' }}>
              {t.assignee_name}
            </span>
          )}
        </div>
      </div>
    )
  }

  const boardView = (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', overflowX: 'auto', paddingBottom: 16 }}>
      {activeStatuses.map((s) => {
        const colTasks = tasks.filter((t) => (t.status_key ?? '') === s.key)
        return (
          <div
            key={s.key}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              const taskId = e.dataTransfer.getData('text/task-id')
              if (taskId) onDropToStatus(taskId, s)
            }}
            style={{ minWidth: 250, width: 250, flexShrink: 0, background: '#f1f5f9', borderRadius: 12, padding: 10 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 4px 10px' }}>
              <span style={{ width: 8, height: 8, borderRadius: 4, background: s.color ?? '#94a3b8' }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: '#334155' }}>{s.label}</span>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>{colTasks.length}</span>
            </div>
            {colTasks.map(card)}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 4px 2px' }}>
              <Plus size={14} color="#94a3b8" />
              <input
                value={boardAdd[s.key] ?? ''}
                onChange={(e) => setBoardAdd((prev) => ({ ...prev, [s.key]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === 'Enter') quickAddToStatus(s) }}
                onBlur={() => quickAddToStatus(s)}
                placeholder="Add a task…"
                style={{ flex: 1, border: 'none', outline: 'none', fontSize: 12, background: 'transparent', color: '#0f172a' }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )

  const listSections: (TaskSection | null)[] = [...sections, null] // null = "No section"
  const listView = (
    <div>
      {listSections.map((s) => {
        const secTasks = tasks.filter((t) => (s ? t.section_id === s.id : !t.section_id))
        if (!s && secTasks.length === 0) return null
        const key = s?.id ?? 'none'
        return (
          <div key={key} style={{ marginBottom: 22 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#334155', marginBottom: 6 }}>
              {s?.name ?? 'No section'}{' '}
              <span style={{ color: '#94a3b8', fontWeight: 500 }}>
                {secTasks.filter((t) => t.completed).length}/{secTasks.length}
              </span>
            </div>
            <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              {secTasks.map((t) => {
                const cat = t.category ? catByKey[t.category] : null
                return (
                  <div
                    key={t.id}
                    onClick={() => setSelectedTask(t.id)}
                    style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderBottom: '1px solid #f8fafc', cursor: 'pointer' }}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        ;(t.completed ? reopenMut : completeMut).mutate(t.id)
                      }}
                      style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, color: t.completed ? '#22c55e' : '#cbd5e1', display: 'inline-flex' }}
                    >
                      {t.completed ? <CheckCircle2 size={17} /> : <Circle size={17} />}
                    </button>
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: t.completed ? '#94a3b8' : '#0f172a', textDecoration: t.completed ? 'line-through' : 'none' }}>
                      {t.name}
                      {t.subtask_total ? (
                        <span style={{ marginLeft: 8, fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>☑ {t.subtask_done}/{t.subtask_total}</span>
                      ) : null}
                    </span>
                    {cat && chip(cat.color, cat.label)}
                    {t.est_hours != null && <span style={{ fontSize: 11, color: '#94a3b8', width: 34, textAlign: 'right' }}>{t.est_hours}h</span>}
                    <span style={{ fontSize: 11, fontWeight: 600, width: 56, textAlign: 'right', color: isOverdue(t) ? '#dc2626' : '#94a3b8' }}>
                      {dueLabel(t) ?? ''}
                    </span>
                    <span style={{ fontSize: 11, color: '#64748b', width: 90, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {t.assignee_name ?? ''}
                    </span>
                  </div>
                )
              })}
              {/* Quick add */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px' }}>
                <Plus size={15} color="#cbd5e1" />
                <input
                  value={quickAdd[key] ?? ''}
                  onChange={(e) => setQuickAdd((prev) => ({ ...prev, [key]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') quickAddTask(s?.id ?? null) }}
                  placeholder="Add a task…"
                  style={{ flex: 1, border: 'none', outline: 'none', fontSize: 13, background: 'transparent', color: '#0f172a' }}
                />
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )

  const toolbarBtn = (active: boolean): React.CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', gap: 5, padding: '7px 12px', borderRadius: 8,
    border: '1px solid #e2e8f0', background: active ? '#eef2ff' : '#fff', color: active ? '#4f46e5' : '#334155',
    fontSize: 12, fontWeight: 600, cursor: 'pointer',
  })
  const selectStyle: React.CSSProperties = { padding: '7px 9px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12, background: '#fff', color: '#334155' }

  return (
    <div style={{ padding: 32 }}>
      <Link to={`/clients/${id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#6366f1', textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <KanbanSquare size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Tasks</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 18 }}>
        {client?.name}'s delivery board — native tasks, organized by month. Drag cards between status columns; click a card for details & checklist.
      </p>

      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <button onClick={() => setView('board')} style={toolbarBtn(view === 'board')}><KanbanSquare size={14} /> Board</button>
        <button onClick={() => setView('list')} style={toolbarBtn(view === 'list')}><List size={14} /> List</button>
        <button onClick={() => setView('calendar')} style={toolbarBtn(view === 'calendar')}><CalendarDays size={14} /> Calendar</button>
        <select value="" onChange={(e) => onViewSelect(e.target.value)} style={selectStyle}>
          <option value="">Views…</option>
          {BUILTIN_VIEWS.map((b) => (
            <option key={b.key} value={`builtin:${b.key}`}>{b.label}</option>
          ))}
          {savedViews.length > 0 && <option disabled>— saved —</option>}
          {savedViews.map((v) => (
            <option key={v.id} value={v.id}>{v.name}{v.shared ? ' (team)' : ''}</option>
          ))}
          <option value="save">＋ Save current view…</option>
        </select>
        {activeSavedView && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 999, background: '#eef2ff', color: '#4f46e5', fontSize: 12, fontWeight: 600 }}>
            {activeSavedView.name}
            {(!activeSavedView.shared || isAdmin) && (
              <button
                onClick={() => deleteViewMut.mutate(activeSavedView.id)}
                title="Delete this saved view"
                style={{ border: 'none', background: 'none', color: '#a5b4fc', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
              >
                <X size={12} />
              </button>
            )}
          </span>
        )}
        {preset && !activeSavedView && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 999, background: '#fef3c7', color: '#b45309', fontSize: 12, fontWeight: 600 }}>
            {BUILTIN_VIEWS.find((b) => b.key === preset)?.label}
            <button onClick={() => setPreset('')} style={{ border: 'none', background: 'none', color: '#d0a24a', cursor: 'pointer', padding: 0, display: 'inline-flex' }}>
              <X size={12} />
            </button>
          </span>
        )}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff' }}>
          <Search size={13} color="#94a3b8" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" style={{ border: 'none', outline: 'none', fontSize: 12, width: 130, background: 'transparent', color: '#0f172a' }} />
        </span>
        <select value={assignee} onChange={(e) => setAssignee(e.target.value)} style={selectStyle}>
          <option value="">All assignees</option>
          {members.map((m) => <option key={m.gid} value={m.gid}>{m.name ?? m.gid}</option>)}
        </select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} style={selectStyle}>
          <option value="">All types</option>
          {categories.filter((c) => c.active).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
        </select>
        <select value={sectionFilter} onChange={(e) => setSectionFilter(e.target.value)} style={selectStyle}>
          <option value="">All sections</option>
          {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        <button onClick={() => setShowTrash((v) => !v)} style={toolbarBtn(showTrash)} title="Trash">
          <Trash2 size={14} /> Trash
        </button>
        <button
          onClick={() => {
            const name = window.prompt('New section name:')
            if (name?.trim()) createSectionMut.mutate(name.trim())
          }}
          style={toolbarBtn(false)}
        >
          <Plus size={14} /> Section
        </button>
        <button onClick={() => generateMut.mutate()} disabled={generateMut.isPending} style={{ ...toolbarBtn(false), background: '#6366f1', color: '#fff', border: 'none' }}>
          <CalendarPlus size={14} /> {generateMut.isPending ? 'Generating…' : 'Generate this month'}
        </button>
      </div>

      {genResult && (
        <div style={{ marginBottom: 14, padding: '8px 12px', borderRadius: 8, background: '#eef2ff', color: '#4f46e5', fontSize: 13 }}>{genResult}</div>
      )}

      {showTrash ? (
        <div style={{ maxWidth: 720 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#334155', marginBottom: 6 }}>
            Trash <span style={{ color: '#94a3b8', fontWeight: 500 }}>{trash.length}</span>
          </div>
          {trash.length === 0 ? (
            <div style={{ color: '#94a3b8', fontSize: 13, padding: '16px 0' }}>Trash is empty.</div>
          ) : (
            <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              {trash.map((t) => (
                <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px', borderBottom: '1px solid #f8fafc' }}>
                  <span style={{ flex: 1, fontSize: 13, color: '#64748b' }}>
                    {t.name}
                    {t.parent_task_id && <span style={{ fontSize: 11, color: '#cbd5e1' }}> (subtask)</span>}
                  </span>
                  <span style={{ fontSize: 11, color: '#cbd5e1' }}>{new Date(t.deleted_at).toLocaleDateString()}</span>
                  <button
                    onClick={() => restoreMut.mutate(t.id)}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 7, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
                  >
                    <RotateCcw size={11} /> Restore
                  </button>
                  {isAdmin && (
                    <button
                      onClick={() => { if (window.confirm(`Permanently delete "${t.name}"? This cannot be undone.`)) purgeMut.mutate(t.id) }}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px', borderRadius: 7, border: '1px solid #fecaca', background: '#fff', color: '#dc2626', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}
                    >
                      <Trash2 size={11} /> Delete forever
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : tasks.length === 0 && sections.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>
          No tasks yet. Hit <strong>Generate this month</strong> to build the month from this client's template, or add a section and create tasks manually.
        </div>
      ) : view === 'board' ? boardView : view === 'calendar' ? (
        <TaskCalendar tasks={tasks} onSelect={setSelectedTask} />
      ) : listView}

      {selectedTask && (
        <TaskDetail
          taskId={selectedTask}
          statuses={statuses}
          categories={categories}
          members={members}
          onClose={() => setSelectedTask(null)}
          invalidateKeys={[['task-board', id]]}
        />
      )}
    </div>
  )
}
