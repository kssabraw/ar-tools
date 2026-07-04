import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BrainCircuit, Check, ChevronDown, HelpCircle, Pin, RefreshCw, ShieldAlert, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { StrategyProposal, StrategyReview, StrategyReviewList } from '../lib/types'

// SerMaStr — the "Strategist Review" card on the Action Plan page.
// Latest strategist run for the client: the assessment, cross-signal findings
// with SOP citations, proposals staged for Approve / Dismiss (the strategist
// proposes, never executes), and open questions. Approved proposals pin to the
// top. Renders nothing while the feature flag is off and no reviews exist.
export function StrategistReview({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const [showHistoryNote, setShowHistoryNote] = useState(false)

  const { data } = useQuery<StrategyReviewList>({
    queryKey: ['strategy-reviews', clientId],
    queryFn: () => api.get<StrategyReviewList>(`/clients/${clientId}/strategy-reviews?limit=5`),
    enabled: Boolean(clientId),
    retry: false,
    refetchInterval: (q) =>
      q.state.data?.reviews?.[0]?.status === 'running' ? 5000 : false,
  })

  const run = useMutation({
    mutationFn: () => api.post<{ review_id: string }>(`/clients/${clientId}/strategy-review`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategy-reviews', clientId] }),
  })

  const decide = useMutation({
    mutationFn: ({ reviewId, idx, status }: { reviewId: string; idx: number; status: 'approved' | 'dismissed' }) =>
      api.post(`/strategy-proposals/${reviewId}/${idx}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategy-reviews', clientId] }),
  })

  if (!data) return null
  const reviews = data.reviews ?? []
  const latest = reviews[0]
  // Feature dark (flag off) and nothing ever produced → invisible.
  if (!data.enabled && !latest) return null

  const latestComplete = reviews.find((r) => r.status === 'complete')
  const running = latest?.status === 'running'

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <BrainCircuit size={18} style={{ color: '#7c3aed', flexShrink: 0 }} />
        <span style={{ fontWeight: 700, fontSize: 15, color: '#0f172a' }}>Strategist Review</span>
        <span style={smallMuted}>SerMaStr — proposes only; nothing runs without your approval</span>
        <span style={{ flex: 1 }} />
        {data.enabled && (
          <button
            style={runBtn}
            onClick={() => run.mutate()}
            disabled={run.isPending || running}
          >
            <RefreshCw
              size={13}
              style={running || run.isPending ? { animation: 'spin 1s linear infinite' } : undefined}
            />
            {running ? 'Reviewing…' : 'Run review'}
          </button>
        )}
      </div>

      {decide.isError && (
        <div style={{ ...noteBox, color: '#b45309', background: '#fffbeb', borderColor: '#fde68a' }}>
          {(decide.error as Error)?.message === 'senior_approval_required'
            ? 'This proposal is marked Kyle/Ryan only — an admin has to approve or dismiss it.'
            : `Couldn’t save that decision: ${(decide.error as Error)?.message}`}
        </div>
      )}

      {run.isError && (
        <div style={{ ...noteBox, color: '#b45309', background: '#fffbeb', borderColor: '#fde68a' }}>
          {(run.error as Error)?.message === 'strategist_disabled'
            ? 'The strategist is currently disabled (strategist_enabled is off).'
            : (run.error as Error)?.message === 'strategy_review_in_progress'
              ? 'A review is already running for this client.'
              : `Couldn’t start the review: ${(run.error as Error)?.message}`}
        </div>
      )}

      {!latest ? (
        <div style={smallMuted}>
          No strategist review yet. Run one to get a cross-channel strategic read of this client.
        </div>
      ) : latest.status === 'failed' && !latestComplete ? (
        <div style={{ ...noteBox, color: '#b91c1c', background: '#fef2f2', borderColor: '#fecaca' }}>
          Last review failed{latest.error ? `: ${latest.error}` : ''}.
        </div>
      ) : !latestComplete ? (
        <div style={smallMuted}>Review in progress — this usually takes a minute or two…</div>
      ) : (
        <ReviewBody
          review={latestComplete}
          onDecide={(idx, status) => decide.mutate({ reviewId: latestComplete.id, idx, status })}
          deciding={decide.isPending}
        />
      )}

      {reviews.length > 1 && latestComplete && (
        <button style={disclose} onClick={() => setShowHistoryNote((v) => !v)}>
          <ChevronDown size={12} style={{ transform: showHistoryNote ? 'rotate(180deg)' : 'none' }} />
          {showHistoryNote ? 'Hide' : `${reviews.length - 1} earlier review${reviews.length > 2 ? 's' : ''}`}
        </button>
      )}
      {showHistoryNote && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {reviews.slice(1).map((r) => (
            <div key={r.id} style={smallMuted}>
              {new Date(r.created_at).toLocaleString()} · {triggerLabel(r.trigger)} · {r.status}
              {r.status === 'complete' && ` · ${r.proposals.length} proposal${r.proposals.length !== 1 ? 's' : ''}`}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ReviewBody({
  review, onDecide, deciding,
}: {
  review: StrategyReview
  onDecide: (idx: number, status: 'approved' | 'dismissed') => void
  deciding: boolean
}) {
  const proposals = review.proposals ?? []
  const approved = proposals
    .map((p, i) => [p, i] as [StrategyProposal, number])
    .filter(([p]) => p.status === 'approved')
  const open = proposals
    .map((p, i) => [p, i] as [StrategyProposal, number])
    .filter(([p]) => p.status === 'proposed')
  const dismissed = proposals.filter((p) => p.status === 'dismissed').length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={smallMuted}>
        {triggerLabel(review.trigger)} · {new Date(review.created_at).toLocaleString()}
      </div>
      {review.assessment && (
        <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.55 }}>{review.assessment}</div>
      )}

      {(review.questions ?? []).length > 0 && (
        <div style={questionBox}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: 12, color: '#b45309' }}>
            <HelpCircle size={14} /> Needs a human call
          </div>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {review.questions.map((q, i) => (
              <li key={i} style={{ fontSize: 12.5, color: '#78350f', lineHeight: 1.5, marginBottom: 3 }}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      {(review.findings ?? []).length > 0 && (
        <div>
          <div style={sectionLabel}>Findings</div>
          {review.findings.map((f, i) => (
            <div key={i} style={{ fontSize: 12.5, color: '#334155', lineHeight: 1.5, marginBottom: 5 }}>
              • {f.synthesis}
              {f.sop_citation ? <span style={sopCite}> {f.sop_citation}</span> : null}
            </div>
          ))}
        </div>
      )}

      {approved.length > 0 && (
        <div>
          <div style={sectionLabel}><Pin size={11} style={{ verticalAlign: -1 }} /> Approved — pinned</div>
          {approved.map(([p, idx]) => (
            <ProposalRow key={idx} proposal={p} idx={idx} onDecide={onDecide} deciding={deciding} pinned />
          ))}
        </div>
      )}

      {open.length > 0 && (
        <div>
          <div style={sectionLabel}>Proposals</div>
          {open.map(([p, idx]) => (
            <ProposalRow key={idx} proposal={p} idx={idx} onDecide={onDecide} deciding={deciding} />
          ))}
        </div>
      )}

      {proposals.length === 0 && (review.questions ?? []).length === 0 && (
        <div style={smallMuted}>No proposals — the strategist agrees with the current plan.</div>
      )}
      {dismissed > 0 && (
        <div style={smallMuted}>{dismissed} proposal{dismissed !== 1 ? 's' : ''} dismissed.</div>
      )}
    </div>
  )
}

function ProposalRow({
  proposal: p, idx, onDecide, deciding, pinned,
}: {
  proposal: StrategyProposal
  idx: number
  onDecide: (idx: number, status: 'approved' | 'dismissed') => void
  deciding: boolean
  pinned?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ ...proposalRow, ...(pinned ? { borderColor: '#c7d2fe', background: '#eef2ff66' } : null) }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 13.5, color: '#0f172a' }}>{p.title}</span>
            {p.requires === 'senior' && (
              <span style={seniorPill}><ShieldAlert size={10} style={{ verticalAlign: -1 }} /> Kyle/Ryan only</span>
            )}
            {p.est_cost_usd != null && <span style={metaPill}>~${Math.round(p.est_cost_usd)}</span>}
            {p.effort && <span style={metaPill}>{p.effort} effort</span>}
            {p.assignee_hint && <span style={metaPill}>{p.assignee_hint}</span>}
          </div>
          <div style={{ fontSize: 12.5, color: '#334155', marginTop: 3, lineHeight: 1.5 }}>{p.action}</div>
          <button style={disclose} onClick={() => setOpen((v) => !v)}>
            <ChevronDown size={12} style={{ transform: open ? 'rotate(180deg)' : 'none' }} />
            {open ? 'Hide rationale' : 'Why'}
          </button>
          {open && (
            <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5, marginTop: 2 }}>
              {p.rationale}
              {p.sop_citation ? <span style={sopCite}> {p.sop_citation}</span> : null}
            </div>
          )}
        </div>
        {p.status === 'proposed' ? (
          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
            <button style={approveBtn} disabled={deciding} onClick={() => onDecide(idx, 'approved')}>
              <Check size={13} /> Approve
            </button>
            <button style={dismissBtn} disabled={deciding} onClick={() => onDecide(idx, 'dismissed')}>
              <X size={13} />
            </button>
          </div>
        ) : (
          <span style={{ ...metaPill, color: '#16a34a', background: '#f0fdf4', flexShrink: 0 }}>Approved</span>
        )}
      </div>
    </div>
  )
}

function triggerLabel(trigger: string): string {
  switch (trigger) {
    case 'scheduled': return 'Weekly review'
    case 'escalation': return 'Escalation brief'
    default: return 'On-demand review'
  }
}

const card: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 16px',
  border: '1px solid #ddd6fe', borderRadius: 10, background: '#fff', marginBottom: 20,
}
const smallMuted: React.CSSProperties = { fontSize: 12, color: '#94a3b8' }
const sectionLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
  letterSpacing: '0.03em', marginBottom: 6,
}
const sopCite: React.CSSProperties = {
  fontSize: 11, color: '#7c3aed', fontWeight: 600,
}
const questionBox: React.CSSProperties = {
  border: '1px solid #fde68a', background: '#fffbeb', borderRadius: 8, padding: '10px 12px',
}
const proposalRow: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', background: '#fff',
  marginBottom: 6,
}
const seniorPill: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 3,
  fontSize: 10, fontWeight: 700, color: '#b91c1c', background: '#fef2f2',
  borderRadius: 999, padding: '2px 8px', textTransform: 'uppercase', letterSpacing: '0.03em',
}
const metaPill: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#475569', background: '#f1f5f9',
  borderRadius: 999, padding: '2px 8px',
}
const runBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  fontSize: 12.5, fontWeight: 600, color: '#7c3aed', background: '#f5f3ff',
  border: '1px solid #ddd6fe', borderRadius: 8, padding: '6px 12px', cursor: 'pointer',
}
const approveBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#16a34a', background: '#f0fdf4',
  border: '1px solid #bbf7d0', borderRadius: 8, padding: '6px 10px', cursor: 'pointer',
}
const dismissBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center',
  fontSize: 12, fontWeight: 600, color: '#64748b', background: '#f8fafc',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '6px 8px', cursor: 'pointer',
}
const noteBox: React.CSSProperties = {
  border: '1px solid', borderRadius: 8, padding: '8px 12px', fontSize: 12.5,
}
const disclose: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, alignSelf: 'flex-start',
  fontSize: 11.5, fontWeight: 600, color: '#6366f1', background: 'transparent',
  border: 'none', padding: '3px 0 0', cursor: 'pointer',
}
