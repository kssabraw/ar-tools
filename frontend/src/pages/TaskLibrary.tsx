import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, Save, Library } from 'lucide-react'
import { api } from '../lib/api'
import type { AsanaLibraryTaskItem } from '../lib/types'

// Task Library — the single source of truth for "how long each standard task
// takes" (+ a default category), keyed by task name. Client templates inherit
// these defaults by name when a row's own value is blank.
// See docs/modules/asana-task-integration-plan-v1_0.md.
export function TaskLibrary() {
  const queryClient = useQueryClient()
  const { data: library } = useQuery<AsanaLibraryTaskItem[]>({
    queryKey: ['asana-task-library'],
    queryFn: () => api.get<AsanaLibraryTaskItem[]>('/asana/task-library'),
  })

  const [rows, setRows] = useState<AsanaLibraryTaskItem[]>([])
  useEffect(() => { if (library) setRows(library.map((t) => ({ ...t }))) }, [library])

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

  const dirty = JSON.stringify(rows) !== JSON.stringify((library ?? []).map((t) => ({ ...t })))

  return (
    <div style={{ padding: 32, maxWidth: 760 }}>
      <Link to="/clients" style={backLinkStyle}><ArrowLeft size={14} /> Clients</Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Library size={20} color="#4f46e5" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Task Library</h1>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Standard tasks and how long each takes. Client templates inherit these by task name —
        define “GBP Blast = 1.5h” once and every client’s “GBP Blast” uses it (each client can
        still override by filling in its own hours). Durations feed the Workload view &
        auto-distribution.
      </p>

      <section style={card}>
        {rows.length === 0 ? (
          <div style={emptyBox}>No standard tasks yet. Click <strong>Add task</strong> to start your library.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'grid', gridTemplateColumns: grid, gap: 8, fontSize: 11, color: '#94a3b8', fontWeight: 600, paddingLeft: 4 }}>
              <span>Task name</span><span>Default hrs</span><span>Default category</span><span>Active</span><span></span>
            </div>
            {rows.map((r, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: grid, gap: 8, alignItems: 'center' }}>
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
            ))}
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
        Note: the <strong>category</strong> name must match a Service Type option in the
        client’s Asana project; hours only reach Asana once an “Est. hours” number field exists
        on the projects, but they already weight auto-distribution.
      </p>
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
