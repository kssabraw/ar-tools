import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, Save, Library, ListChecks, ChevronRight, ChevronDown, GripVertical } from 'lucide-react'
import { api } from '../lib/api'
import type { AsanaLibraryTaskItem, LibraryChecklist } from '../lib/types'

// Task Library — the single source of truth for "how long each standard task
// takes" (+ a default category + a default subtask checklist), keyed by task
// name. Client templates inherit the hours/category by name; the native
// monthly generation copies the checklist onto each generated task as real
// subtasks.
// See docs/modules/in-app-task-manager-prd-v1_0.md §6.9.
export function TaskLibrary() {
  const queryClient = useQueryClient()
  const { data: library } = useQuery<AsanaLibraryTaskItem[]>({
    queryKey: ['asana-task-library'],
    queryFn: () => api.get<AsanaLibraryTaskItem[]>('/asana/task-library'),
  })
  const { data: checklists } = useQuery<LibraryChecklist[]>({
    queryKey: ['task-library-checklists'],
    queryFn: () => api.get<LibraryChecklist[]>('/tasks/library-checklists'),
  })

  const [rows, setRows] = useState<AsanaLibraryTaskItem[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  useEffect(() => { if (library) setRows(library.map((t) => ({ ...t }))) }, [library])

  const savedNames = useMemo(() => new Set((library ?? []).map((t) => t.name.trim().toLowerCase())), [library])
  const countByName = useMemo(() => {
    const m = new Map<string, number>()
    for (const c of checklists ?? []) m.set(c.library_name.trim().toLowerCase(), c.subtasks.length)
    return m
  }, [checklists])

  const save = useMutation({
    mutationFn: () => api.put<AsanaLibraryTaskItem[]>('/asana/task-library', { items: rows }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['asana-task-library'], saved)
      setRows(saved.map((t) => ({ ...t })))
    },
  })

  const update = (i: number, patch: Partial<AsanaLibraryTaskItem>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRow = () =>
    setRows((rs) => [...rs, { name: '', default_hours: null, default_category_name: null, active: true }])
  const removeRow = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i))

  const toggleExpand = (name: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })

  const dirty = JSON.stringify(rows) !== JSON.stringify((library ?? []).map((t) => ({ ...t })))

  return (
    <div style={{ padding: 32, maxWidth: 760 }}>
      <Link to="/clients" style={backLinkStyle}><ArrowLeft size={14} /> Clients</Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Library size={20} color="#4f46e5" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Task Library</h1>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Standard tasks — how long each takes, its default category, and its default subtask
        checklist. Client templates inherit the hours/category by task name; the monthly task
        generator copies the checklist onto each new task as real subtasks.
      </p>

      <section style={card}>
        {rows.length === 0 ? (
          <div style={emptyBox}>No standard tasks yet. Click <strong>Add task</strong> to start your library.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: grid, gap: 8, fontSize: 11, color: '#94a3b8', fontWeight: 600, paddingLeft: 4 }}>
              <span>Task name</span><span>Default hrs</span><span>Default category</span><span>Active</span><span></span>
            </div>
            {rows.map((r, i) => {
              const key = r.name.trim().toLowerCase()
              const isSaved = key !== '' && savedNames.has(key)
              const count = countByName.get(key) ?? 0
              const isOpen = expanded.has(key)
              return (
                <div key={i}>
                  <div style={{ display: 'grid', gridTemplateColumns: grid, gap: 8, alignItems: 'center' }}>
                    <input style={input} placeholder="e.g. GBP Blast" value={r.name}
                      onChange={(e) => update(i, { name: e.target.value })} />
                    <input style={input} type="number" min="0" step="0.5" placeholder="—"
                      value={r.default_hours ?? ''}
                      onChange={(e) => update(i, { default_hours: e.target.value === '' ? null : Number(e.target.value) })} />
                    <input style={input} placeholder="e.g. Link Building" value={r.default_category_name ?? ''}
                      onChange={(e) => update(i, { default_category_name: e.target.value || null })} />
                    <input type="checkbox" checked={r.active} style={{ justifySelf: 'center' }}
                      onChange={(e) => update(i, { active: e.target.checked })} />
                    <button style={{ ...iconBtn, color: '#dc2626' }} title="Remove" onClick={() => removeRow(i)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                  {/* Checklist expander (only for saved tasks — the checklist is keyed by name) */}
                  <div style={{ paddingLeft: 4, marginTop: 4 }}>
                    {isSaved ? (
                      <button style={checklistToggle} onClick={() => toggleExpand(key)}>
                        {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        <ListChecks size={13} />
                        {count > 0 ? `Checklist · ${count} item${count === 1 ? '' : 's'}` : 'Add a default checklist'}
                      </button>
                    ) : (
                      dirty && r.name.trim() && (
                        <span style={{ fontSize: 11, color: '#cbd5e1', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                          <ListChecks size={12} /> Save the library to add this task's checklist
                        </span>
                      )
                    )}
                    {isOpen && isSaved && (
                      <ChecklistEditor
                        libraryName={r.name.trim()}
                        initial={(checklists ?? []).find((c) => c.library_name.trim().toLowerCase() === key)?.subtasks ?? []}
                      />
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button style={ghostBtn} onClick={addRow}><Plus size={14} /> Add task</button>
          <button style={primaryBtn} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            <Save size={14} /> {save.isPending ? 'Saving…' : dirty ? 'Save library' : 'Saved'}
          </button>
        </div>
        {save.isError && <p style={errText}>{(save.error as Error).message}</p>}
      </section>

      <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 14 }}>
        Note: the <strong>category</strong> name should match a Service Type option; hours weight
        auto-distribution. Renaming a task and saving detaches its old-name checklist — re-add it
        under the new name.
      </p>
    </div>
  )
}

// Per-task checklist editor: independent of the library bulk save (the checklist
// is keyed by task name, PUT /tasks/library-checklists replaces one task's list).
function ChecklistEditor({ libraryName, initial }: { libraryName: string; initial: string[] }) {
  const queryClient = useQueryClient()
  const [items, setItems] = useState<string[]>(initial)
  const [draft, setDraft] = useState('')
  useEffect(() => { setItems(initial) }, [initial, libraryName])

  const save = useMutation({
    mutationFn: () =>
      api.put<LibraryChecklist>('/tasks/library-checklists', { library_name: libraryName, subtasks: items }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['task-library-checklists'] }),
  })

  const addItem = () => {
    const v = draft.trim()
    if (!v) return
    setItems((xs) => [...xs, v])
    setDraft('')
  }
  const removeItem = (i: number) => setItems((xs) => xs.filter((_, j) => j !== i))
  const move = (i: number, dir: -1 | 1) =>
    setItems((xs) => {
      const j = i + dir
      if (j < 0 || j >= xs.length) return xs
      const next = [...xs]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })

  const dirty = JSON.stringify(items) !== JSON.stringify(initial)

  return (
    <div style={checklistPanel}>
      {items.length === 0 ? (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8 }}>No checklist items yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
          {items.map((it, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <button style={reorderBtn} title="Move up" onClick={() => move(i, -1)} disabled={i === 0}>
                  <GripVertical size={11} />
                </button>
              </div>
              <input
                style={{ ...input, flex: 1, padding: '5px 8px' }}
                value={it}
                onChange={(e) => setItems((xs) => xs.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button style={{ ...iconBtn, color: '#dc2626', padding: 4 }} title="Remove" onClick={() => removeItem(i)}>
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          style={{ ...input, flex: 1, padding: '5px 8px' }}
          placeholder="Add a checklist step… (Enter)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addItem() }}
        />
        <button style={ghostBtn} onClick={addItem}><Plus size={13} /> Add</button>
        <button style={primaryBtn} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          <Save size={13} /> {save.isPending ? 'Saving…' : dirty ? 'Save checklist' : 'Saved'}
        </button>
      </div>
      {save.isError && <p style={errText}>{(save.error as Error).message}</p>}
    </div>
  )
}

const grid = '1fr 110px 1fr 60px 40px'
const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13,
  color: '#64748b', textDecoration: 'none', marginBottom: 16,
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, background: '#fff' }
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '7px 10px', fontSize: 13,
  border: '1px solid #cbd5e1', borderRadius: 8, color: '#0f172a', background: '#fff',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
  padding: '8px 14px', fontSize: 13, fontWeight: 600, color: '#fff',
  background: '#4f46e5', border: 'none', borderRadius: 8, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 13, fontWeight: 600, color: '#4f46e5', background: '#eef2ff',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 6,
  color: '#64748b', background: 'transparent', border: '1px solid #e2e8f0',
  borderRadius: 6, cursor: 'pointer',
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
const errText: React.CSSProperties = { color: '#dc2626', fontSize: 12, margin: '8px 0 0' }
const checklistToggle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 6px',
  fontSize: 12, fontWeight: 600, color: '#6366f1', background: 'transparent',
  border: 'none', borderRadius: 6, cursor: 'pointer',
}
const checklistPanel: React.CSSProperties = {
  margin: '6px 0 10px', padding: 12, background: '#f8fafc',
  border: '1px solid #eef2ff', borderRadius: 10,
}
const reorderBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 2,
  color: '#cbd5e1', background: 'transparent', border: 'none', cursor: 'pointer',
}
