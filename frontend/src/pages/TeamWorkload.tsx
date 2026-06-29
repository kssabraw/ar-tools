import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, AlertTriangle, Users, CheckCircle2, Plus, Trash2, Save } from 'lucide-react'
import { api } from '../lib/api'
import type { AsanaWorkloadReport, AsanaWorkloadMember, AsanaTeamMember, AsanaUser } from '../lib/types'

// Team Workload — a suite-level read view of each tracked team member's open
// Asana tasks across all clients, effort-weighted by estimated hours vs each
// person's weekly capacity. Flags same-day over-capacity + backlog. Includes a
// "Team & capacity" editor. The daily proactive alert is server-side (Phase 3).
// See docs/modules/asana-task-integration-plan-v1_0.md §4.
export function TeamWorkload() {
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
        <button style={refreshBtn} onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw size={14} style={isFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

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
        {defaultWeekly != null ? ` (${defaultWeekly}h/wk)` : ''}.
      </p>

      {!configured && (
        <div style={{ ...warnBanner, marginBottom: 12 }}>
          <AlertTriangle size={16} style={{ verticalAlign: -3, marginRight: 6 }} />
          Connect Asana to pick team members.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map((r, i) => (
            <div key={r.gid} style={{ display: 'grid', gridTemplateColumns: '1fr 160px 36px', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#0f172a' }}>{r.name ?? r.gid}</span>
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
              <button
                style={{ ...iconBtn, color: '#dc2626' }}
                title="Remove"
                onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <select style={{ ...input, maxWidth: 280 }} value={picker} disabled={!configured} onChange={(e) => addMember(e.target.value)}>
          <option value="">+ Add team member…</option>
          {available.map((u) => <option key={u.gid} value={u.gid}>{u.name ?? u.gid}</option>)}
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
