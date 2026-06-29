import { useQuery } from '@tanstack/react-query'
import { RefreshCw, AlertTriangle, Users, CheckCircle2 } from 'lucide-react'
import { api } from '../lib/api'
import type { AsanaWorkloadReport, AsanaWorkloadMember } from '../lib/types'

// Team Workload — a suite-level read view of each tracked team member's open
// Asana tasks across all client projects, flagging overall load and same-day
// due-date stacking. Read-only; the proactive alerts are Phase 3.
// See docs/modules/asana-task-integration-plan-v1_0.md §4.
export function TeamWorkload() {
  const { data, isLoading, refetch, isFetching } = useWorkload()
  const report = data

  const banner =
    report && !report.configured
      ? 'Asana isn’t connected yet. Set ASANA_TOKEN + workspace on the platform to see team workload.'
      : report?.note === 'no_team_list'
      ? 'No team list configured. Set asana_team_member_gids (the Asana user GIDs to track) on the platform.'
      : null

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Team Workload</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
            Open Asana tasks per team member across all clients — so you can spot who’s overloaded
            or has too many tasks due the same day.
          </p>
        </div>
        <button style={refreshBtn} onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw size={14} style={isFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {report?.thresholds && (
        <div style={{ fontSize: 12, color: '#94a3b8', margin: '8px 0 20px' }}>
          Flags over {report.thresholds.max_open} open tasks or {report.thresholds.max_due_same_day} due the same day.
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
      ) : !report || report.members.length === 0 ? (
        !banner && (
          <div style={emptyBox}>
            <Users size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
            No tracked team members yet.
          </div>
        )
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {report.members.map((m) => (
            <MemberRow key={m.gid} member={m} maxDueSameDay={report.thresholds.max_due_same_day} />
          ))}
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function useWorkload() {
  const q = useQuery<AsanaWorkloadReport>({
    queryKey: ['asana-workload'],
    queryFn: () => api.get<AsanaWorkloadReport>('/asana/workload'),
  })
  // Alias isFetching for the JSX (keeps the destructure above tidy).
  return { ...q, isFetching: q.isFetching }
}

function MemberRow({ member, maxDueSameDay }: { member: AsanaWorkloadMember; maxDueSameDay: number }) {
  const days = Object.entries(member.due_by_day)
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
          {member.open_count} open task{member.open_count === 1 ? '' : 's'}
        </span>
      </div>

      {member.flags.length > 0 && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: '#dc2626', fontSize: 12 }}>
          {member.flags.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}

      {days.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {days.map(([day, count]) => {
            const hot = count > maxDueSameDay
            return (
              <span
                key={day}
                style={chip(hot ? '#fef2f2' : '#f1f5f9', hot ? '#dc2626' : '#475569', hot ? '#fecaca' : '#e2e8f0')}
                title={`${count} task${count === 1 ? '' : 's'} due ${day}`}
              >
                {day} · {count}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────
const refreshBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
  padding: '8px 14px', fontSize: 13, fontWeight: 600, color: '#475569',
  background: '#fff', border: '1px solid #cbd5e1', borderRadius: 8, cursor: 'pointer',
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff' }
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
const warnBanner: React.CSSProperties = {
  border: '1px solid #fde68a', background: '#fffbeb', color: '#92400e',
  borderRadius: 10, padding: '10px 14px', fontSize: 13, marginBottom: 16,
}
const pill = (bg: string, color: string): React.CSSProperties => ({
  fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 8px', borderRadius: 999,
})
const chip = (bg: string, color: string, border: string): React.CSSProperties => ({
  fontSize: 11, fontWeight: 600, color, background: bg, border: `1px solid ${border}`,
  padding: '3px 8px', borderRadius: 6,
})
