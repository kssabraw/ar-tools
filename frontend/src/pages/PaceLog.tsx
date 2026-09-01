import { Fragment, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../lib/api'

// PACE Action Log — admin-only view of the audit + learning ledger. Every PACE
// action that affected a client campaign + every human decision (approve /
// approve-with-modifications / deny / defer / cancel), so you can debug "what
// happened and why" and read PACE's approve/deny/modify track record. Mirrors
// services/pace_audit.py (list_log / stats_window).

interface LogRow {
  id: string
  created_at: string
  action: string
  origin: string
  decision: string | null
  outcome: string
  client_id: string | null
  client_name: string | null
  target_type: string | null
  target_name: string | null
  actor_name: string | null
  actor_role: string | null
  actor_source: string | null
  reason: string | null
  args: Record<string, unknown> | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  modifications: Record<string, unknown> | null
  result: string | null
  error: string | null
}
interface LogPage {
  rows: LogRow[]
  total: number
  limit: number
  offset: number
}
interface StatBlock {
  approved: number
  approved_with_modifications: number
  denied: number
  deferred: number
  cancelled: number
  auto: number
  executed: number
  failed: number
  total: number
}
interface StatsResp {
  overall: StatBlock
  by_action: Record<string, StatBlock>
  by_actor: Record<string, StatBlock>
}
interface ClientListItem {
  id: string
  name: string
}

const ACTIONS = [
  'reassign_task', 'assign_task', 'set_task_due', 'set_task_status', 'unblock_task',
  'triage_task', 'rename_task', 'generate_client_month', 'nudge_assignee',
  'run_qa_review', 'intervention_disposition',
]
const DECISIONS = ['approved', 'approved_with_modifications', 'denied', 'deferred', 'cancelled', 'auto']
const OUTCOMES = ['executed', 'failed', 'skipped', 'denied', 'deferred', 'cancelled']

const DECISION_COLOR: Record<string, string> = {
  approved: '#16a34a',
  approved_with_modifications: '#0891b2',
  denied: '#dc2626',
  deferred: '#d97706',
  cancelled: '#64748b',
  auto: '#7c3aed',
}
const OUTCOME_COLOR: Record<string, string> = {
  executed: '#16a34a',
  failed: '#dc2626',
  skipped: '#64748b',
  denied: '#dc2626',
  deferred: '#d97706',
  cancelled: '#64748b',
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 11,
      fontWeight: 600, color: '#fff', background: color, whiteSpace: 'nowrap',
    }}>{text}</span>
  )
}

// The fields that actually changed, before→after, for a task action.
function diffFields(before: Record<string, unknown> | null, after: Record<string, unknown> | null): string[] {
  if (!before || !after) return []
  const out: string[] = []
  for (const k of Object.keys(after)) {
    const a = JSON.stringify(before[k])
    const b = JSON.stringify(after[k])
    if (a !== b) out.push(`${k}: ${before[k] ?? '—'} → ${after[k] ?? '—'}`)
  }
  return out
}

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function PaceLog() {
  const [clientId, setClientId] = useState('')
  const [action, setAction] = useState('')
  const [decision, setDecision] = useState('')
  const [outcome, setOutcome] = useState('')
  const [offset, setOffset] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const limit = 100

  const { data: clients } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    staleTime: 5 * 60_000,
  })

  const filterQs = qs({ client_id: clientId, action, decision, outcome, limit, offset })
  const { data, isLoading, isFetching, refetch } = useQuery<LogPage>({
    queryKey: ['pace-log', clientId, action, decision, outcome, offset],
    queryFn: () => api.get<LogPage>(`/pace/action-log${filterQs}`),
  })
  const { data: stats } = useQuery<StatsResp>({
    queryKey: ['pace-log-stats', clientId, action],
    queryFn: () => api.get<StatsResp>(`/pace/action-log/stats${qs({ client_id: clientId, action })}`),
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const ov = stats?.overall

  const resetOffset = () => setOffset(0)
  const clientName = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of clients ?? []) m[c.id] = c.name
    return m
  }, [clients])

  const selectStyle = { padding: '6px 8px', borderRadius: 6, border: '1px solid #cbd5e1', fontSize: 13, background: '#fff' }

  return (
    <div style={{ padding: 32, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <ScrollText size={22} />
        <h1 style={{ margin: 0, fontSize: 22 }}>PACE Action Log</h1>
        <button
          onClick={() => refetch()}
          title="Refresh"
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 6, border: '1px solid #cbd5e1', background: '#fff', cursor: 'pointer', fontSize: 13 }}
        >
          <RefreshCw size={14} className={isFetching ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <p style={{ marginTop: 0, color: '#64748b', fontSize: 13 }}>
        Every PACE action that touched a client campaign, plus how a human dispositioned it.
        For debugging "what happened and why" — and the record PACE reads to learn from.
      </p>

      {/* Summary strip */}
      {ov && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, margin: '14px 0' }}>
          <Stat label="Total" value={ov.total} />
          <Stat label="Executed" value={ov.executed} color="#16a34a" />
          <Stat label="Approved" value={ov.approved} color="#16a34a" />
          <Stat label="w/ mods" value={ov.approved_with_modifications} color="#0891b2" />
          <Stat label="Denied / cancelled" value={ov.denied + ov.cancelled} color="#dc2626" />
          <Stat label="Deferred" value={ov.deferred} color="#d97706" />
          <Stat label="Failed" value={ov.failed} color="#dc2626" />
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
        <select value={clientId} onChange={(e) => { setClientId(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">All clients</option>
          {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={action} onChange={(e) => { setAction(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">All actions</option>
          {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select value={decision} onChange={(e) => { setDecision(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">Any decision</option>
          {DECISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select value={outcome} onChange={(e) => { setOutcome(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">Any outcome</option>
          {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>

      {/* Table */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
              <th style={th}></th>
              <th style={th}>When</th>
              <th style={th}>Action</th>
              <th style={th}>Client</th>
              <th style={th}>Actor</th>
              <th style={th}>Decision</th>
              <th style={th}>Outcome</th>
              <th style={th}>Why</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>Loading…</td></tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr><td colSpan={8} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>No matching actions logged yet.</td></tr>
            )}
            {rows.map((r) => {
              const open = expanded === r.id
              const diffs = diffFields(r.before, r.after)
              return (
                <Fragment key={r.id}>
                  <tr style={{ borderTop: '1px solid #f1f5f9', cursor: 'pointer' }}
                      onClick={() => setExpanded(open ? null : r.id)}>
                    <td style={td}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: '#475569' }}>{r.created_at?.replace('T', ' ').slice(0, 16)}</td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{r.action}</td>
                    <td style={td}>{r.client_name || (r.client_id ? clientName[r.client_id] : '') || '—'}</td>
                    <td style={td}>{r.actor_name || r.actor_role || (r.actor_source === 'system' ? 'system' : '—')}</td>
                    <td style={td}>{r.decision ? <Badge text={r.decision} color={DECISION_COLOR[r.decision] || '#64748b'} /> : '—'}</td>
                    <td style={td}><Badge text={r.outcome} color={OUTCOME_COLOR[r.outcome] || '#64748b'} /></td>
                    <td style={{ ...td, maxWidth: 320, color: '#334155' }}>{r.reason || r.target_name || '—'}</td>
                  </tr>
                  {open && (
                    <tr style={{ background: '#f8fafc' }}>
                      <td></td>
                      <td colSpan={7} style={{ padding: '10px 14px', fontSize: 12.5, color: '#334155' }}>
                        {r.target_name && <Line k="Target" v={`${r.target_type || 'task'}: ${r.target_name}`} />}
                        <Line k="Origin" v={r.origin} />
                        <Line k="Source" v={r.actor_source || '—'} />
                        {diffs.length > 0 && <Line k="Changed" v={diffs.join('  ·  ')} />}
                        {r.modifications && <Line k="Modifications" v={JSON.stringify(r.modifications)} />}
                        {r.result && <Line k="Result" v={r.result} />}
                        {r.error && <Line k="Error" v={r.error} color="#dc2626" />}
                        {r.args && Object.keys(r.args).length > 0 && <Line k="Args" v={JSON.stringify(r.args)} mono />}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Paging */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12, fontSize: 13, color: '#475569' }}>
        <span>{total === 0 ? '0' : `${offset + 1}–${Math.min(offset + limit, total)}`} of {total}</span>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} style={pageBtn(offset === 0)}>Prev</button>
        <button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)} style={pageBtn(offset + limit >= total)}>Next</button>
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', minWidth: 90, background: '#fff' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || '#0f172a' }}>{value}</div>
      <div style={{ fontSize: 11, color: '#64748b' }}>{label}</div>
    </div>
  )
}

function Line({ k, v, color, mono }: { k: string; v: string; color?: string; mono?: boolean }) {
  return (
    <div style={{ marginBottom: 3 }}>
      <span style={{ color: '#64748b', fontWeight: 600 }}>{k}: </span>
      <span style={{ color: color || '#334155', fontFamily: mono ? 'monospace' : undefined, wordBreak: 'break-word' }}>{v}</span>
    </div>
  )
}

const th: CSSProperties = { padding: '8px 10px', fontWeight: 600, color: '#475569', fontSize: 12 }
const td: CSSProperties = { padding: '8px 10px', verticalAlign: 'top' }
const pageBtn = (disabled: boolean): CSSProperties => ({
  padding: '4px 12px', borderRadius: 6, border: '1px solid #cbd5e1',
  background: disabled ? '#f1f5f9' : '#fff', color: disabled ? '#94a3b8' : '#334155',
  cursor: disabled ? 'default' : 'pointer', fontSize: 13,
})
