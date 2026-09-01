import { Fragment, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../lib/api'

// SerMaStr Action Log — admin-only view of the strategist's audit + learning
// ledger. One row per PROPOSAL: what SerMaStr proposed (title / action / SOP
// citation / rationale), how a human dispositioned it (approved / dismissed /
// still pending / senior-required), and — reused from the intervention loop —
// whether the approved tactic actually worked (worked / partial / no_effect).
// For debugging "what did it propose, who decided, and did it work" and the
// record SerMaStr reads to learn from. Mirrors services/sermastr_audit.py
// (list_log / stats_window).

interface LogRow {
  id: string
  created_at: string
  review_id: string | null
  proposal_idx: number | null
  client_id: string | null
  client_name: string | null
  trigger: string | null
  proposal_kind: string
  title: string | null
  action: string | null
  sop_citation: string | null
  rationale: string | null
  requires: string | null
  est_cost_usd: number | null
  target: Record<string, unknown> | null
  decision: string | null
  decided_by: string | null
  decided_at: string | null
  actor_name: string | null
  actor_role: string | null
  actor_source: string | null
  outcome_verdict: string | null
  outcome_at: string | null
  intervention_id: string | null
}
interface LogPage {
  rows: LogRow[]
  total: number
  limit: number
  offset: number
}
interface StatBlock {
  approved: number
  dismissed: number
  pending: number
  worked: number
  partial: number
  no_effect: number
  total: number
}
interface StatsResp {
  overall: StatBlock
  by_kind: Record<string, StatBlock>
  by_actor: Record<string, StatBlock>
}
interface ClientListItem {
  id: string
  name: string
}

const DECISIONS = ['approved', 'dismissed']
const TRIGGERS = ['scheduled', 'on_demand', 'escalation', 'monthly_plan_review']
const OUTCOMES = ['worked', 'partial', 'no_effect']

const DECISION_COLOR: Record<string, string> = {
  approved: '#16a34a',
  dismissed: '#dc2626',
  pending: '#64748b',
}
const OUTCOME_COLOR: Record<string, string> = {
  worked: '#16a34a',
  partial: '#d97706',
  no_effect: '#dc2626',
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 11,
      fontWeight: 600, color: '#fff', background: color, whiteSpace: 'nowrap',
    }}>{text}</span>
  )
}

function qs(params: Record<string, string | number | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function SermastrLog() {
  const [clientId, setClientId] = useState('')
  const [kind, setKind] = useState('')
  const [decision, setDecision] = useState('')
  const [trigger, setTrigger] = useState('')
  const [outcome, setOutcome] = useState('')
  const [offset, setOffset] = useState(0)
  const [expanded, setExpanded] = useState<string | null>(null)
  const limit = 100

  const { data: clients } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    staleTime: 5 * 60_000,
  })

  const filterQs = qs({
    client_id: clientId, proposal_kind: kind, decision, trigger,
    outcome_verdict: outcome, limit, offset,
  })
  const { data, isLoading, isFetching, refetch } = useQuery<LogPage>({
    queryKey: ['sermastr-log', clientId, kind, decision, trigger, outcome, offset],
    queryFn: () => api.get<LogPage>(`/strategist/action-log${filterQs}`),
  })
  const { data: stats } = useQuery<StatsResp>({
    queryKey: ['sermastr-log-stats', clientId, kind],
    queryFn: () => api.get<StatsResp>(`/strategist/action-log/stats${qs({ client_id: clientId, proposal_kind: kind })}`),
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const ov = stats?.overall
  // Proposal kinds present in this window, for the filter dropdown.
  const kinds = useMemo(() => Object.keys(stats?.by_kind ?? {}).sort(), [stats])

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
        <h1 style={{ margin: 0, fontSize: 22 }}>SerMaStr Action Log</h1>
        <button
          onClick={() => refetch()}
          title="Refresh"
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 6, border: '1px solid #cbd5e1', background: '#fff', cursor: 'pointer', fontSize: 13 }}
        >
          <RefreshCw size={14} className={isFetching ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <p style={{ marginTop: 0, color: '#64748b', fontSize: 13 }}>
        Every strategist proposal, how a human dispositioned it, and whether the
        approved tactic actually worked. For debugging "what did SerMaStr propose,
        who decided, and did it work" — and the record it reads to learn from.
      </p>

      {/* Summary strip */}
      {ov && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, margin: '14px 0' }}>
          <Stat label="Total" value={ov.total} />
          <Stat label="Approved" value={ov.approved} color="#16a34a" />
          <Stat label="Dismissed" value={ov.dismissed} color="#dc2626" />
          <Stat label="Pending" value={ov.pending} color="#64748b" />
          <Stat label="Worked" value={ov.worked} color="#16a34a" />
          <Stat label="Partial" value={ov.partial} color="#d97706" />
          <Stat label="No effect" value={ov.no_effect} color="#dc2626" />
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
        <select value={clientId} onChange={(e) => { setClientId(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">All clients</option>
          {(clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => { setKind(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">All proposal kinds</option>
          {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={decision} onChange={(e) => { setDecision(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">Any decision</option>
          {DECISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select value={trigger} onChange={(e) => { setTrigger(e.target.value); resetOffset() }} style={selectStyle}>
          <option value="">Any trigger</option>
          {TRIGGERS.map((t) => <option key={t} value={t}>{t}</option>)}
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
              <th style={th}>Kind</th>
              <th style={th}>Client</th>
              <th style={th}>Proposed</th>
              <th style={th}>Decision</th>
              <th style={th}>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>Loading…</td></tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 20, textAlign: 'center', color: '#64748b' }}>No matching proposals logged yet.</td></tr>
            )}
            {rows.map((r) => {
              const open = expanded === r.id
              const decisionText = r.decision ?? 'pending'
              return (
                <Fragment key={r.id}>
                  <tr style={{ borderTop: '1px solid #f1f5f9', cursor: 'pointer' }}
                      onClick={() => setExpanded(open ? null : r.id)}>
                    <td style={td}>{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: '#475569' }}>{r.created_at?.replace('T', ' ').slice(0, 16)}</td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{r.proposal_kind}</td>
                    <td style={td}>{r.client_name || (r.client_id ? clientName[r.client_id] : '') || '—'}</td>
                    <td style={{ ...td, maxWidth: 360, color: '#334155' }}>{r.title || r.action || '—'}</td>
                    <td style={td}>
                      <Badge text={decisionText} color={DECISION_COLOR[decisionText] || '#64748b'} />
                      {r.requires === 'senior' && !r.decision && (
                        <span style={{ marginLeft: 4 }}><Badge text="senior" color="#7c3aed" /></span>
                      )}
                    </td>
                    <td style={td}>{r.outcome_verdict
                      ? <Badge text={r.outcome_verdict} color={OUTCOME_COLOR[r.outcome_verdict] || '#64748b'} />
                      : '—'}</td>
                  </tr>
                  {open && (
                    <tr style={{ background: '#f8fafc' }}>
                      <td></td>
                      <td colSpan={6} style={{ padding: '10px 14px', fontSize: 12.5, color: '#334155' }}>
                        {r.action && <Line k="Action" v={r.action} />}
                        {r.rationale && <Line k="Rationale" v={r.rationale} />}
                        {r.sop_citation && <Line k="SOP" v={r.sop_citation} />}
                        <Line k="Requires" v={r.requires || '—'} />
                        {r.trigger && <Line k="Trigger" v={r.trigger} />}
                        {typeof r.est_cost_usd === 'number' && <Line k="Est. cost" v={`$${r.est_cost_usd}`} />}
                        {r.target && Object.keys(r.target).length > 0 && <Line k="Target" v={JSON.stringify(r.target)} mono />}
                        {r.decision && (
                          <Line k="Decision"
                                v={`${r.decision} by ${r.actor_name || r.actor_role || r.decided_by || '—'}${r.decided_at ? ` (${r.decided_at.replace('T', ' ').slice(0, 16)})` : ''}`}
                                color={DECISION_COLOR[r.decision]} />
                        )}
                        {r.outcome_verdict && (
                          <Line k="Outcome"
                                v={`${r.outcome_verdict}${r.outcome_at ? ` (${r.outcome_at.replace('T', ' ').slice(0, 16)})` : ''}`}
                                color={OUTCOME_COLOR[r.outcome_verdict]} />
                        )}
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
