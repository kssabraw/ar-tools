import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, AlertTriangle, Users, CheckCircle2, Plus, Trash2, Save, DownloadCloud } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { AsanaWorkloadReport, AsanaWorkloadMember, AsanaTeamMember, AsanaUser } from '../lib/types'

// Team Workload — a suite-level read view of each tracked team member's open
// Asana tasks across all clients, effort-weighted by estimated hours vs each
// person's weekly capacity. Flags same-day over-capacity + backlog. Includes a
// "Team & capacity" editor. The daily proactive alert is server-side (Phase 3).
// See docs/modules/asana-task-integration-plan-v1_0.md §4.
interface ImportStatus {
  status: string
  result?: Record<string, unknown> | null
  error?: string | null
}

export function TeamWorkload() {
  const { isAdmin } = useAuth()
  const importQc = useQueryClient()
  const [importStarted, setImportStarted] = useState(false)
  const { data: importStatus } = useQuery<ImportStatus>({
    queryKey: ['task-import-status'],
    queryFn: () => api.get<ImportStatus>('/tasks/import/asana/status'),
    enabled: isAdmin,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return importStarted && (s === 'pending' || s === 'running') ? 4000 : false
    },
  })
  const importMut = useMutation({
    mutationFn: () => api.post<{ status: string }>('/tasks/import/asana', {}),
    onSuccess: () => {
      setImportStarted(true)
      importQc.invalidateQueries({ queryKey: ['task-import-status'] })
    },
  })
  const queryClient = useQueryClient()

  const { data: report, isLoading, refetch, isFetching } = useQuery<AsanaWorkloadReport>({
    queryKey: ['asana-workload'],
    queryFn: () => api.get<AsanaWorkloadReport>('/asana/workload'),
  })
  const configured = report?.configured ?? false

  const banner =
    report && !report.configured
      ? 'Asana isn’t connected yet. Set ASANA_TOKEN + workspace on the platform to see team workload.'
      : report?.note === 'no_team_list'
      ? 'No team members tracked yet. Add them in “Team & capacity” below.'
      : null

  const defaultWeekly = report?.thresholds?.default_weekly_hours

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Team Workload</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
            Open Asana tasks per team member across all clients, weighted by estimated hours vs
            each person’s weekly capacity — so you can spot who’s over capacity or has too much
            due the same day.
          </p>
        </div>
        <span style={{ display: 'inline-flex', gap: 8 }}>
          {isAdmin && (
            <button
              style={refreshBtn}
              onClick={() => importMut.mutate()}
              disabled={importMut.isPending || importStatus?.status === 'running' || importStatus?.status === 'pending'}
              title="Snapshot every mapped client's Asana board into the native task manager (idempotent — re-runs only fill gaps)"
            >
              <DownloadCloud size={14} />
              {importMut.isPending || importStatus?.status === 'running' || importStatus?.status === 'pending'
                ? 'Importing from Asana…'
                : 'Import Asana boards'}
            </button>
          )}
          <button style={refreshBtn} onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw size={14} style={isFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
            {isFetching ? 'Refreshing…' : 'Refresh'}
          </button>
        </span>
      </div>
      {importStatus?.status === 'complete' && importStatus.result && (
        <div style={{ margin: '10px 0 0', padding: '8px 12px', borderRadius: 8, background: '#f0fdf4', color: '#15803d', fontSize: 13 }}>
          Asana import done — {String(importStatus.result.tasks ?? 0)} tasks (+{String(importStatus.result.subtasks ?? 0)} subtasks)
          across {String(importStatus.result.clients ?? 0)} clients; {String(importStatus.result.existing ?? 0)} already imported,
          {' '}{String(importStatus.result.checklists_seeded ?? 0)} library checklists seeded.
        </div>
      )}
      {importStatus?.status === 'failed' && (
        <div style={{ margin: '10px 0 0', padding: '8px 12px', borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 13 }}>
          Asana import failed — {importStatus.error ?? 'see server logs'}.
        </div>
      )}

      {report?.thresholds && (
        <div style={{ fontSize: 12, color: '#94a3b8', margin: '8px 0 20px' }}>
          Flags when a day’s due hours exceed daily capacity or the open backlog exceeds{' '}
          {report.thresholds.backlog_weeks} weeks of capacity. Unestimated tasks count as{' '}
          {report.thresholds.default_task_hours}h.
          {report.overloaded.length > 0 && (
            <strong style={{ color: '#dc2626' }}> · {report.overloaded.length} overloaded</strong>
          )}
        </div>
      )}

      {banner && (
        <div style={warnBanner}>
          <AlertTriangle size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
          {banner}
        </div>
      )}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : report && report.members.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 28 }}>
          {report.members.map((m) => <MemberRow key={m.gid} member={m} />)}
        </div>
      ) : !banner ? (
        <div style={{ ...emptyBox, marginBottom: 28 }}>
          <Users size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
          No tracked team members yet.
        </div>
      ) : null}

      <TeamEditor
        configured={configured}
        defaultWeekly={defaultWeekly}
        onSaved={() => {
          queryClient.invalidateQueries({ queryKey: ['asana-workload'] })
        }}
      />
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function MemberRow({ member }: { member: AsanaWorkloadMember }) {
  const days = Object.entries(member.due_hours_by_day)
  const cap = member.daily_capacity
  return (
    <div style={{ ...card, borderColor: member.overloaded ? '#fecaca' : '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{member.name}</span>
          {member.overloaded ? (
            <span style={pill('#fef2f2', '#dc2626')}>Overloaded</span>
          ) : (
            <span style={pill('#f0fdf4', '#16a34a')}>
              <CheckCircle2 size={11} style={{ verticalAlign: -2, marginRight: 3 }} />OK
            </span>
          )}
        </div>
        <span style={{ fontSize: 13, color: '#475569', fontWeight: 600 }}>
          {member.open_hours}h open · {member.open_count} task{member.open_count === 1 ? '' : 's'}
          {member.weekly_hours != null && <span style={{ color: '#94a3b8', fontWeight: 400 }}> · {member.weekly_hours}h/wk</span>}
        </span>
      </div>

      {member.unestimated > 0 && (
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
          {member.unestimated} task{member.unestimated === 1 ? '' : 's'} unestimated
        </div>
      )}

      {member.flags.length > 0 && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: '#dc2626', fontSize: 12 }}>
          {member.flags.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}

      {days.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {days.map(([day, hours]) => {
            const hot = cap != null && hours > cap
            return (
              <span
                key={day}
                style={chip(hot ? '#fef2f2' : '#f1f5f9', hot ? '#dc2626' : '#475569', hot ? '#fecaca' : '#e2e8f0')}
                title={`${hours}h due ${day}`}
              >
                {day} · {hours}h
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Team & capacity editor ───────────────────────────────────────────────
function TeamEditor({ configured, defaultWeekly, onSaved }: {
  configured: boolean
  defaultWeekly?: number
  onSaved: () => void
}) {
  const queryClient = useQueryClient()
  const { data: members } = useQuery<AsanaTeamMember[]>({
    queryKey: ['asana-team-members'],
    queryFn: () => api.get<AsanaTeamMember[]>('/asana/team-members'),
  })
  const { data: users } = useQuery<AsanaUser[]>({
    queryKey: ['asana-users'],
    queryFn: () => api.get<AsanaUser[]>('/asana/workspace-users'),
    enabled: configured,
  })
  // Suite login users, for the identity-bridge link (reuses the mention
  // candidates endpoint — id + full_name, external 'client' viewers excluded).
  const { data: profiles } = useQuery<{ id: string; full_name: string }[]>({
    queryKey: ['task-mention-candidates'],
    queryFn: () => api.get<{ id: string; full_name: string }[]>('/tasks/mention-candidates'),
  })

  const [rows, setRows] = useState<AsanaTeamMember[]>([])
  const [picker, setPicker] = useState('')
  useEffect(() => { if (members) setRows(members.map((m) => ({ ...m }))) }, [members])

  const save = useMutation({
    mutationFn: () => api.put<AsanaTeamMember[]>('/asana/team-members', { members: rows }),
    onSuccess: (saved) => {
      queryClient.setQueryData(['asana-team-members'], saved)
      setRows(saved.map((m) => ({ ...m })))
      onSaved()
    },
  })

  const tracked = new Set(rows.map((r) => r.gid))
  const available = (users ?? []).filter((u) => !tracked.has(u.gid))
  const dirty = JSON.stringify(rows) !== JSON.stringify((members ?? []).map((m) => ({ ...m })))
  // gid → email (from the live workspace-users read) — disambiguates same-name
  // accounts (e.g. a work account vs a personal-gmail duplicate).
  const emailByGid = new Map((users ?? []).map((u) => [u.gid, u.email]))

  const addMember = (gid: string) => {
    const u = users?.find((x) => x.gid === gid)
    if (!u || tracked.has(gid)) return
    setRows((rs) => [...rs, { gid: u.gid, name: u.name ?? null, weekly_hours: null, active: true }])
    setPicker('')
  }

  return (
    <section style={card}>
      <h2 style={cardTitle}>Team &amp; capacity</h2>
      <p style={cardSub}>
        Who to track + each person’s weekly hours. Blank capacity uses the default
        {defaultWeekly != null ? ` (${defaultWeekly}h/wk)` : ''}. Link a member to a
        suite login so their <strong>My Tasks</strong> opens on their own tasks automatically.
      </p>

      {!configured && (
        <div style={{ ...warnBanner, marginBottom: 12 }}>
          <AlertTriangle size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
          Connect Asana to pick team members.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 130px 190px 36px', gap: 8, fontSize: 11, color: '#94a3b8', fontWeight: 600, paddingLeft: 2 }}>
            <span>Member</span><span>Hrs / week</span><span>Suite user (My Tasks)</span><span />
          </div>
          {rows.map((r, i) => {
            // A profile already linked to a DIFFERENT member can't be picked here.
            const takenElsewhere = new Set(
              rows.filter((_, j) => j !== i).map((x) => x.profile_id).filter(Boolean) as string[],
            )
            return (
            <div key={r.gid} style={{ display: 'grid', gridTemplateColumns: '1fr 130px 190px 36px', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#0f172a' }}>
                {r.name ?? r.gid}
                {emailByGid.get(r.gid) && (
                  <span style={{ fontSize: 11.5, color: '#94a3b8', marginLeft: 8 }}>{emailByGid.get(r.gid)}</span>
                )}
              </span>
              <input
                style={input}
                type="number"
                min="0"
                step="0.5"
                placeholder={defaultWeekly != null ? `${defaultWeekly} (default)` : 'h / week'}
                value={r.weekly_hours ?? ''}
                onChange={(e) => {
                  const v = e.target.value === '' ? null : Number(e.target.value)
                  setRows((rs) => rs.map((x, j) => (j === i ? { ...x, weekly_hours: v } : x)))
                }}
              />
              <select
                style={input}
                value={r.profile_id ?? ''}
                onChange={(e) => {
                  const v = e.target.value || null
                  setRows((rs) => rs.map((x, j) => (j === i ? { ...x, profile_id: v } : x)))
                }}
                title="Link this member to a suite login so their My Tasks auto-resolves"
              >
                <option value="">— not linked —</option>
                {(profiles ?? [])
                  .filter((p) => !takenElsewhere.has(p.id))
                  .map((p) => (
                    <option key={p.id} value={p.id}>{p.full_name}</option>
                  ))}
              </select>
              <button
                style={{ ...iconBtn, color: '#dc2626' }}
                title="Remove"
                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
              >
                <Trash2 size={14} />
              </button>
            </div>
            )
          })}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <select style={{ ...input, maxWidth: 280 }} value={picker} disabled={!configured} onChange={(e) => addMember(e.target.value)}>
          <option value="">+ Add team member…</option>
          {available.map((u) => (
            <option key={u.gid} value={u.gid}>
              {u.name ?? u.gid}{u.email ? ` — ${u.email}` : ''}
            </option>
          ))}
        </select>
        <button style={primaryBtn} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          <Save size={14} /> {save.isPending ? 'Saving…' : dirty ? 'Save team' : 'Saved'}
        </button>
        <button style={ghostBtn} onClick={() => addMemberManual(setRows, tracked)} title="Add a member by Asana user GID">
          <Plus size={14} /> GID
        </button>
      </div>
      {save.isError && <p style={errText}>{(save.error as Error).message}</p>}
    </section>
  )
}

// Manual add by GID — fallback when the picker can't reach Asana (e.g. unconfigured).
function addMemberManual(
  setRows: React.Dispatch<React.SetStateAction<AsanaTeamMember[]>>,
  tracked: Set<string>,
) {
  const gid = window.prompt('Asana user GID')?.trim()
  if (!gid || tracked.has(gid)) return
  setRows((rs) => [...rs, { gid, name: null, weekly_hours: null, active: true }])
}

// ── Styles ─────────────────────────────────────────────────────────────
const refreshBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
  padding: '8px 14px', fontSize: 13, fontWeight: 600, color: '#475569',
  background: '#fff', border: '1px solid #cbd5e1', borderRadius: 8, cursor: 'pointer',
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff' }
const cardTitle: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }
const cardSub: React.CSSProperties = { fontSize: 12, color: '#94a3b8', margin: '4px 0 12px' }
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '7px 10px', fontSize: 13,
  border: '1px solid #cbd5e1', borderRadius: 8, color: '#0f172a', background: '#fff',
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
const warnBanner: React.CSSProperties = {
  border: '1px solid #fde68a', background: '#fffbeb', color: '#92400e',
  borderRadius: 10, padding: '10px 14px', fontSize: 13, marginBottom: 16,
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
const errText: React.CSSProperties = { color: '#dc2626', fontSize: 12, margin: '8px 0 0' }
const pill = (bg: string, color: string): React.CSSProperties => ({
  fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 8px', borderRadius: 999,
})
const chip = (bg: string, color: string, border: string): React.CSSProperties => ({
  fontSize: 11, fontWeight: 600, color, background: bg, border: `1px solid ${border}`,
  padding: '3px 8px', borderRadius: 6,
})
