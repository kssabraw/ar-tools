import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Plus, Trash2, ChevronUp, ChevronDown, Save, CalendarPlus,
  AlertTriangle, CheckCircle2,
} from 'lucide-react'
import { api } from '../lib/api'
import type {
  Client, AsanaProjectMapping, AsanaTaskTemplateItem, AsanaUser,
  AsanaCategoryOption, AsanaGenerateMonthResponse,
} from '../lib/types'

// Asana Tasks — the per-client monthly task template editor + a "Generate this
// month" trigger. Defines what tasks a client should get every month (name +
// assignee + category); the monthly job (auto on the 1st, or this button)
// creates those tasks in the client's Asana project under a new "<Month YYYY>"
// section. See docs/modules/asana-task-integration-plan-v1_0.md.
export function AsanaTasks() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: status } = useQuery<{ configured: boolean }>({
    queryKey: ['asana-status'],
    queryFn: () => api.get<{ configured: boolean }>(`/asana/status`),
  })
  const configured = status?.configured ?? false

  const { data: mapping } = useQuery<AsanaProjectMapping | null>({
    queryKey: ['asana-project', id],
    queryFn: () => api.get<AsanaProjectMapping | null>(`/clients/${id}/asana/project`),
    enabled: Boolean(id),
  })

  const { data: templates } = useQuery<AsanaTaskTemplateItem[]>({
    queryKey: ['asana-templates', id],
    queryFn: () => api.get<AsanaTaskTemplateItem[]>(`/clients/${id}/asana/task-templates`),
    enabled: Boolean(id),
  })

  const { data: users } = useQuery<AsanaUser[]>({
    queryKey: ['asana-users'],
    queryFn: () => api.get<AsanaUser[]>(`/asana/workspace-users`),
    enabled: configured,
  })

  const { data: categories } = useQuery<AsanaCategoryOption[]>({
    queryKey: ['asana-categories', id],
    queryFn: () => api.get<AsanaCategoryOption[]>(`/clients/${id}/asana/category-options`),
    enabled: Boolean(id) && configured && Boolean(mapping?.project_gid),
  })

  // ── Local editable state ────────────────────────────────────────────
  const [projectGid, setProjectGid] = useState('')
  const [rows, setRows] = useState<AsanaTaskTemplateItem[]>([])
  const [genResult, setGenResult] = useState<AsanaGenerateMonthResponse | null>(null)

  useEffect(() => {
    if (mapping?.project_gid !== undefined) setProjectGid(mapping?.project_gid ?? '')
  }, [mapping?.project_gid])

  useEffect(() => {
    if (templates) setRows(templates.map((t) => ({ ...t })))
  }, [templates])

  // ── Mutations ───────────────────────────────────────────────────────
  const saveMapping = useMutation({
    mutationFn: () =>
      api.put<AsanaProjectMapping>(`/clients/${id}/asana/project`, { project_gid: projectGid.trim() }),
    onSuccess: (m) => {
      queryClient.setQueryData(['asana-project', id], m)
      queryClient.invalidateQueries({ queryKey: ['asana-categories', id] })
    },
  })

  const saveTemplates = useMutation({
    mutationFn: () =>
      api.put<AsanaTaskTemplateItem[]>(`/clients/${id}/asana/task-templates`, {
        items: rows.map((r, i) => ({ ...r, sort_order: i })),
      }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['asana-templates', id], saved)
      setRows(saved.map((t) => ({ ...t })))
    },
  })

  const generate = useMutation({
    mutationFn: () =>
      api.post<AsanaGenerateMonthResponse>(`/clients/${id}/asana/generate-month`, {}),
    onSuccess: (r) => setGenResult(r),
  })

  // ── Row helpers ─────────────────────────────────────────────────────
  const updateRow = (i: number, patch: Partial<AsanaTaskTemplateItem>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const addRow = () =>
    setRows((rs) => [
      ...rs,
      { name: '', assignee_gid: null, assignee_name: null, category_option_gid: null, category_name: null, est_hours: null, sort_order: rs.length, active: true },
    ])
  const removeRow = (i: number) => setRows((rs) => rs.filter((_, j) => j !== i))
  const move = (i: number, dir: -1 | 1) =>
    setRows((rs) => {
      const j = i + dir
      if (j < 0 || j >= rs.length) return rs
      const copy = [...rs]
      ;[copy[i], copy[j]] = [copy[j], copy[i]]
      return copy
    })

  const dirty = JSON.stringify(rows) !== JSON.stringify((templates ?? []).map((t) => ({ ...t })))
  const mappingDirty = projectGid.trim() !== (mapping?.project_gid ?? '')
  const canGenerate = configured && Boolean(mapping?.project_gid) && rows.some((r) => r.active && r.name.trim())

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Asana Tasks</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Define the tasks this client should get every month. The monthly job creates them in
        Asana under a new “Month Year” section — assigned, categorized, status “Not Started”,
        no due dates. Runs automatically each month, or on demand below.
      </p>

      {!configured && (
        <div style={{ ...banner, borderColor: '#fde68a', background: '#fffbeb', color: '#92400e' }}>
          <AlertTriangle size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
          Asana isn’t connected yet. You can still edit the task list, but the assignee/category
          pickers and “Generate this month” stay disabled until <code>ASANA_TOKEN</code> +
          workspace are set on the platform.
        </div>
      )}

      {/* ── Project mapping ─────────────────────────────────────────── */}
      <section style={card}>
        <h2 style={cardTitle}>Asana project</h2>
        <p style={cardSub}>The Asana project GID for this client (where the monthly sections are created).</p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            style={input}
            placeholder="e.g. 1209876543210987"
            value={projectGid}
            onChange={(e) => setProjectGid(e.target.value)}
          />
          <button
            style={primaryBtn}
            disabled={!mappingDirty || !projectGid.trim() || saveMapping.isPending}
            onClick={() => saveMapping.mutate()}
          >
            <Save size={14} /> {saveMapping.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
        {saveMapping.isError && <p style={errText}>{(saveMapping.error as Error).message}</p>}
      </section>

      {/* ── Task template ───────────────────────────────────────────── */}
      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2 style={cardTitle}>Monthly task template</h2>
            <p style={cardSub}>One row per task. Order here is the order they’re created in Asana. Est. hrs (optional) feeds the Team Workload view.</p>
          </div>
          <button style={ghostBtn} onClick={addRow}><Plus size={14} /> Add task</button>
        </div>

        {rows.length === 0 ? (
          <div style={emptyBox}>No tasks yet. Click <strong>Add task</strong> to start the template.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: rowGrid, gap: 8, fontSize: 11, color: '#94a3b8', fontWeight: 600, paddingLeft: 4 }}>
              <span>Task</span><span>Assignee</span><span>Category</span><span>Est. hrs</span><span>Active</span><span></span>
            </div>
            {rows.map((r, i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: rowGrid, gap: 8, alignItems: 'center' }}>
                <input
                  style={input}
                  placeholder="Task name"
                  value={r.name}
                  onChange={(e) => updateRow(i, { name: e.target.value })}
                />
                <select
                  style={input}
                  value={r.assignee_gid ?? ''}
                  disabled={!configured}
                  onChange={(e) => {
                    const u = users?.find((x) => x.gid === e.target.value)
                    updateRow(i, { assignee_gid: u?.gid ?? null, assignee_name: u?.name ?? null })
                  }}
                >
                  <option value="">{r.assignee_name ?? 'Unassigned'}</option>
                  {(users ?? []).map((u) => (
                    <option key={u.gid} value={u.gid}>{u.name ?? u.gid}</option>
                  ))}
                </select>
                <select
                  style={input}
                  value={r.category_option_gid ?? ''}
                  disabled={!configured}
                  onChange={(e) => {
                    const c = categories?.find((x) => x.gid === e.target.value)
                    updateRow(i, { category_option_gid: c?.gid ?? null, category_name: c?.name ?? null })
                  }}
                >
                  <option value="">{r.category_name ?? 'None'}</option>
                  {(categories ?? []).map((c) => (
                    <option key={c.gid} value={c.gid}>{c.name ?? c.gid}</option>
                  ))}
                </select>
                <input
                  style={input}
                  type="number"
                  min="0"
                  step="0.5"
                  placeholder="—"
                  value={r.est_hours ?? ''}
                  onChange={(e) => updateRow(i, { est_hours: e.target.value === '' ? null : Number(e.target.value) })}
                />
                <input
                  type="checkbox"
                  checked={r.active}
                  onChange={(e) => updateRow(i, { active: e.target.checked })}
                  style={{ justifySelf: 'center' }}
                />
                <div style={{ display: 'flex', gap: 2 }}>
                  <button style={iconBtn} title="Move up" onClick={() => move(i, -1)}><ChevronUp size={14} /></button>
                  <button style={iconBtn} title="Move down" onClick={() => move(i, 1)}><ChevronDown size={14} /></button>
                  <button style={{ ...iconBtn, color: '#dc2626' }} title="Remove" onClick={() => removeRow(i)}><Trash2 size={14} /></button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button
            style={primaryBtn}
            disabled={!dirty || saveTemplates.isPending}
            onClick={() => saveTemplates.mutate()}
          >
            <Save size={14} /> {saveTemplates.isPending ? 'Saving…' : dirty ? 'Save template' : 'Saved'}
          </button>
        </div>
        {saveTemplates.isError && <p style={errText}>{(saveTemplates.error as Error).message}</p>}
      </section>

      {/* ── Generate this month ─────────────────────────────────────── */}
      <section style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2 style={cardTitle}>Generate this month</h2>
            <p style={cardSub}>
              Creates the current month’s section + tasks now. Idempotent — if it already exists,
              nothing is duplicated. {dirty && <strong>Save the template first.</strong>}
            </p>
          </div>
          <button
            style={primaryBtn}
            disabled={!canGenerate || dirty || generate.isPending}
            onClick={() => { setGenResult(null); generate.mutate() }}
          >
            <CalendarPlus size={14} /> {generate.isPending ? 'Generating…' : 'Generate this month'}
          </button>
        </div>
        {generate.isError && <p style={errText}>{(generate.error as Error).message}</p>}
        {genResult && (
          <div
            style={{
              ...banner,
              marginTop: 12,
              ...(genResult.status === 'created'
                ? { borderColor: '#bbf7d0', background: '#f0fdf4', color: '#166534' }
                : genResult.status === 'exists'
                ? { borderColor: '#bae6fd', background: '#f0f9ff', color: '#075985' }
                : { borderColor: '#fde68a', background: '#fffbeb', color: '#92400e' }),
            }}
          >
            <CheckCircle2 size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
            {genResult.status === 'created'
              ? `Created “${genResult.section}” with ${genResult.created} task${genResult.created === 1 ? '' : 's'}.`
              : genResult.status === 'exists'
              ? `“${genResult.section}” already exists — nothing duplicated.`
              : `Skipped: ${genResult.reason ?? 'not ready'}.`}
            {genResult.errors.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 12 }}>
                {genResult.errors.length} task{genResult.errors.length === 1 ? '' : 's'} failed: {genResult.errors.join('; ')}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────
const rowGrid = '1fr 140px 140px 70px 46px 86px'
const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13,
  color: '#64748b', textDecoration: 'none', marginBottom: 16,
}
const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, marginBottom: 16, background: '#fff',
}
const cardTitle: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }
const cardSub: React.CSSProperties = { fontSize: 12, color: '#94a3b8', margin: '4px 0 12px' }
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
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px',
  fontSize: 13, fontWeight: 600, color: '#4f46e5', background: '#eef2ff',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 6,
  color: '#64748b', background: 'transparent', border: '1px solid #e2e8f0',
  borderRadius: 6, cursor: 'pointer',
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, marginTop: 12,
  fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
const banner: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px', fontSize: 13, marginBottom: 16,
}
const errText: React.CSSProperties = { color: '#dc2626', fontSize: 12, margin: '8px 0 0' }
