import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BrainCircuit, Check, ChevronDown, ExternalLink, FileText, HelpCircle, LifeBuoy, Pin, RefreshCw, ShieldAlert, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { StrategyProposal, StrategyReview, StrategyReviewBudget, StrategyReviewList } from '../lib/types'

// SerMaStr — the "Strategist Review" card on the Action Plan page.
// Latest strategist run for the client: the assessment, cross-signal findings
// with SOP citations, proposals staged for Approve / Dismiss (the strategist
// proposes, never executes), and open questions. Approved proposals pin to the
// top. Open proposals from EARLIER reviews (last 60 days / 5 reviews) stay
// approvable below the latest one, so a recovery plan survives the next weekly
// review. A goal_recovery review adds the root cause, the budget line, per-
// proposal tier pills and "Approve tier" (a client-side loop over the same
// per-proposal endpoint — nothing new runs server-side). Renders nothing while
// the feature flag is off and no reviews exist.
const OPEN_WINDOW_DAYS = 60

export function StrategistReview({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const [showHistoryNote, setShowHistoryNote] = useState(false)
  const [expanded, setExpanded] = useState(false)  // collapsed by default — it's a big card

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

  // "Approve tier": approve every still-open proposal whose tier is at or
  // below the chosen one, one existing per-proposal call each (sequential so a
  // senior-only refusal surfaces per proposal instead of aborting the batch).
  const approveTier = useMutation({
    mutationFn: async ({ reviewId, idxs }: { reviewId: string; idxs: number[] }) => {
      const failed: number[] = []
      for (const idx of idxs) {
        try {
          await api.post(`/strategy-proposals/${reviewId}/${idx}`, { status: 'approved' })
        } catch {
          failed.push(idx)
        }
      }
      return { approved: idxs.length - failed.length, failed }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategy-reviews', clientId] }),
  })

  // Save the internal review to the client's Drive folder as a Google Doc.
  const publish = useMutation({
    mutationFn: (reviewId: string) =>
      api.post<{ doc_url: string }>(`/strategy-reviews/${reviewId}/publish`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['strategy-reviews', clientId] }),
  })

  if (!data) return null
  const reviews = data.reviews ?? []
  const latest = reviews[0]
  // Feature dark (flag off) and nothing ever produced → invisible.
  if (!data.enabled && !latest) return null

  const latestComplete = reviews.find((r) => r.status === 'complete')
  const running = latest?.status === 'running'
  // Earlier reviews (inside the window) that still carry open proposals — a
  // recovery plan must stay approvable after the next weekly review lands.
  const earlierOpen = latestComplete
    ? reviews.filter((r) =>
        r.id !== latestComplete.id && r.status === 'complete' && withinDays(r.created_at, OPEN_WINDOW_DAYS)
        && (r.proposals ?? []).some((p) => p.status === 'proposed'))
    : []
  const earlierOpenCount = earlierOpen.reduce((n, r) => n + r.proposals.filter((p) => p.status === 'proposed').length, 0)

  // One-line summary shown while collapsed.
  const openCount = (latestComplete ? latestComplete.proposals.filter((p) => p.status === 'proposed').length : 0) + earlierOpenCount
  const qCount = latestComplete ? (latestComplete.questions ?? []).length : 0
  const summary = running
    ? 'Reviewing…'
    : !latest
      ? 'No review yet — run one to get a strategic read.'
      : !latestComplete && latest.status === 'failed'
        ? 'Last review failed'
        : latestComplete
          ? [
              openCount ? `${openCount} proposal${openCount !== 1 ? 's' : ''}` : 'no open proposals',
              qCount ? `${qCount} question${qCount !== 1 ? 's' : ''}` : null,
            ].filter(Boolean).join(' · ')
          : 'Review in progress…'

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <BrainCircuit size={18} style={{ color: '#7c3aed', flexShrink: 0 }} />
        <span style={{ fontWeight: 700, fontSize: 15, color: '#0f172a' }}>Strategist Review</span>
        <span style={smallMuted}>SerMaStr — proposes only; nothing runs without your approval</span>
        <span style={{ flex: 1 }} />
        {latestComplete && (
          latestComplete.published_doc_url ? (
            <a style={docLink} href={latestComplete.published_doc_url} target="_blank" rel="noreferrer">
              <ExternalLink size={13} /> Open Doc
            </a>
          ) : (
            <button
              style={saveBtn}
              onClick={() => publish.mutate(latestComplete.id)}
              disabled={publish.isPending}
              title="Save this review as an internal Google Doc in the client's Drive folder"
            >
              <FileText size={13} style={publish.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
              {publish.isPending ? 'Saving…' : 'Save to Drive'}
            </button>
          )
        )}
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

      {/* Collapse toggle — the card is minimized by default; the summary line
          doubles as the expand control. */}
      <button style={collapseToggle} onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
        <ChevronDown size={14} style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform .15s', flexShrink: 0 }} />
        <span>{expanded ? 'Hide review' : summary}</span>
      </button>

      {publish.isError && (
        <div style={{ ...noteBox, color: '#b45309', background: '#fffbeb', borderColor: '#fde68a' }}>
          {publishErrorMessage((publish.error as Error)?.message)}
        </div>
      )}
      {publish.isSuccess && !publish.isPending && (
        <div style={{ ...noteBox, color: '#16a34a', background: '#f0fdf4', borderColor: '#bbf7d0' }}>
          Saved to the client’s Drive folder as an internal Google Doc.
        </div>
      )}

      {approveTier.isSuccess && approveTier.data && approveTier.data.failed.length > 0 && (
        <div style={{ ...noteBox, color: '#b45309', background: '#fffbeb', borderColor: '#fde68a' }}>
          Approved {approveTier.data.approved}; {approveTier.data.failed.length} could not be approved (Kyle/Ryan-only proposals need an admin).
        </div>
      )}

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

      {expanded && (!latest ? (
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
        <>
          <ReviewBody
            review={latestComplete}
            onDecide={(idx, status) => decide.mutate({ reviewId: latestComplete.id, idx, status })}
            onApproveTier={(idxs) => approveTier.mutate({ reviewId: latestComplete.id, idxs })}
            deciding={decide.isPending || approveTier.isPending}
          />
          {earlierOpen.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={sectionLabel}>Still open from earlier reviews</div>
              {earlierOpen.map((r) => (
                <EarlierOpen
                  key={r.id}
                  review={r}
                  onDecide={(idx, status) => decide.mutate({ reviewId: r.id, idx, status })}
                  onApproveTier={(idxs) => approveTier.mutate({ reviewId: r.id, idxs })}
                  deciding={decide.isPending || approveTier.isPending}
                />
              ))}
            </div>
          )}
        </>
      ))}

      {expanded && reviews.length > 1 && latestComplete && (
        <button style={disclose} onClick={() => setShowHistoryNote((v) => !v)}>
          <ChevronDown size={12} style={{ transform: showHistoryNote ? 'rotate(180deg)' : 'none' }} />
          {showHistoryNote ? 'Hide' : `${reviews.length - 1} earlier review${reviews.length > 2 ? 's' : ''}`}
        </button>
      )}
      {expanded && showHistoryNote && (
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

function EarlierOpen({
  review, onDecide, onApproveTier, deciding,
}: {
  review: StrategyReview
  onDecide: (idx: number, status: 'approved' | 'dismissed') => void
  onApproveTier: (idxs: number[]) => void
  deciding: boolean
}) {
  const open = (review.proposals ?? [])
    .map((p, i) => [p, i] as [StrategyProposal, number])
    .filter(([p]) => p.status === 'proposed')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={smallMuted}>
        {triggerLabel(review.trigger)} · {new Date(review.created_at).toLocaleString()}
      </div>
      {review.budget && <TierApproveBar review={review} onApproveTier={onApproveTier} deciding={deciding} />}
      {open.map(([p, idx]) => (
        <ProposalRow key={idx} proposal={p} idx={idx} onDecide={onDecide} deciding={deciding} />
      ))}
    </div>
  )
}

// goal_recovery: "Approve tier" — one button per budget tier that has open
// proposals; approving a tier approves everything at or below it (cumulative).
function TierApproveBar({
  review, onApproveTier, deciding,
}: {
  review: StrategyReview
  onApproveTier: (idxs: number[]) => void
  deciding: boolean
}) {
  const budget = review.budget
  if (!budget) return null
  const order = tierOrder(budget.tier_steps ?? [])
  const open = (review.proposals ?? [])
    .map((p, i) => [p, i] as [StrategyProposal, number])
    .filter(([p]) => p.status === 'proposed')
  const buttons = order
    .map((tier) => {
      const idxs = open.filter(([p]) => tierRank(p.tier, order) <= tierRank(tier, order)).map(([, i]) => i)
      const own = open.filter(([p]) => p.tier === tier).length
      return { tier, idxs, own }
    })
    .filter((b) => b.own > 0)
  if (buttons.length === 0) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <span style={smallMuted}>Approve tier:</span>
      {buttons.map((b) => (
        <button
          key={b.tier}
          style={tierBtn}
          disabled={deciding}
          title={`Approve every open proposal up to this tier (${b.idxs.length})`}
          onClick={() => onApproveTier(b.idxs)}
        >
          <Check size={12} /> {tierLabel(b.tier, budget)} ({b.idxs.length})
        </button>
      ))}
    </div>
  )
}

function ReviewBody({
  review, onDecide, onApproveTier, deciding,
}: {
  review: StrategyReview
  onDecide: (idx: number, status: 'approved' | 'dismissed') => void
  onApproveTier: (idxs: number[]) => void
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
  const superseded = proposals.filter((p) => p.status === 'superseded').length
  const budget = review.budget

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={smallMuted}>
        {triggerLabel(review.trigger)} · {new Date(review.created_at).toLocaleString()}
      </div>
      {review.assessment && (
        <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.55 }}>{review.assessment}</div>
      )}
      {budget && (
        <div style={recoveryBox}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, fontSize: 12, color: '#9f1239' }}>
            <LifeBuoy size={14} /> Recovery plan
            {budget.goals?.length ? (
              <span style={{ fontWeight: 500, color: '#be123c' }}>
                — {budget.goals.map((g) => `${g.label ?? g.goal_type ?? 'goal'} (week ${g.weeks_behind ?? '?'})`).join(', ')}
              </span>
            ) : null}
          </div>
          {budget.root_cause && (
            <div style={{ fontSize: 12.5, color: '#881337', lineHeight: 1.5, marginTop: 4 }}>
              <b>Root cause:</b> {budget.root_cause}
            </div>
          )}
          <div style={{ fontSize: 12, color: '#9f1239', marginTop: 4 }}>
            {budgetLine(budget)}
          </div>
          <div style={{ marginTop: 6 }}>
            <TierApproveBar review={review} onApproveTier={onApproveTier} deciding={deciding} />
          </div>
        </div>
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
      {superseded > 0 && (
        <div style={smallMuted}>{superseded} proposal{superseded !== 1 ? 's' : ''} superseded by a newer recovery plan.</div>
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
            {p.est_cost_usd != null ? (
              <span style={metaPill}>~${Math.round(p.est_cost_usd)}</span>
            ) : p.cost_basis === 'operational' ? (
              <span style={metaPill} title="A paid tool/API run — per-run price pending research">tool cost</span>
            ) : null}
            {p.tier && <span style={{ ...metaPill, ...tierPillStyle(p.tier) }}>{tierPillLabel(p.tier)}</span>}
            {p.effort && <span style={metaPill}>{p.effort} effort</span>}
            {p.assignee_hint && <span style={metaPill}>{p.assignee_hint}</span>}
            {p.asana_task?.url && (
              <a href={p.asana_task.url} target="_blank" rel="noreferrer"
                style={{ ...metaPill, color: '#4f46e5', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                <ExternalLink size={10} /> Asana task
              </a>
            )}
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
    case 'monthly_plan_review': return 'Monthly plan review'
    case 'goal_recovery': return 'Recovery plan'
    default: return 'On-demand review'
  }
}

function withinDays(iso: string, days: number): boolean {
  const t = new Date(iso).getTime()
  return Number.isFinite(t) && Date.now() - t <= days * 86_400_000
}

// Tier helpers — mirror services/goal_recovery.py (within_budget < plus_N… < over).
function tierOrder(steps: number[]): string[] {
  return ['within_budget', ...steps.map((s) => `plus_${Math.round(s * 100)}`)]
}
function tierRank(tier: string | undefined, order: string[]): number {
  if (!tier) return order.length
  const i = order.indexOf(tier)
  return i === -1 ? order.length : i
}
function tierPillLabel(tier: string): string {
  if (tier === 'within_budget') return 'within budget'
  if (tier === 'over') return 'over budget'
  if (tier === 'unbudgeted') return 'unbudgeted'
  if (tier.startsWith('plus_')) return `+${tier.slice(5)}%`
  return tier
}
function tierLabel(tier: string, budget: StrategyReviewBudget): string {
  const ceiling = budget.tiers?.[tier]
  const money = ceiling != null ? ` ≤ $${Math.round(ceiling).toLocaleString()}` : ''
  return tierPillLabel(tier) + money
}
function tierPillStyle(tier: string): React.CSSProperties {
  if (tier === 'within_budget') return { color: '#166534', background: '#f0fdf4' }
  if (tier === 'over' || tier === 'unbudgeted') return { color: '#991b1b', background: '#fef2f2' }
  return { color: '#9a3412', background: '#fff7ed' }
}
function budgetLine(b: StrategyReviewBudget): string {
  const env = b.envelope ?? {}
  const dep = env.deployable != null ? `$${Math.round(env.deployable).toLocaleString()} deployable` : 'no budget on the client card'
  const disc = env.discretionary != null ? ` ($${Math.round(env.discretionary).toLocaleString()} discretionary)` : ''
  const total = b.total_cost_usd != null ? ` · plan total $${Math.round(b.total_cost_usd).toLocaleString()}` : ''
  const steps = b.tier_steps ?? []
  const tiers = steps
    .map((s) => {
      const key = `plus_${Math.round(s * 100)}`
      const ceiling = b.tiers?.[key]
      return ceiling != null ? `+${Math.round(s * 100)}% ≤ $${Math.round(ceiling).toLocaleString()}` : null
    })
    .filter(Boolean)
    .join(', ')
  return `Budget: ${dep}${disc}${total} · ${b.fundable_count ?? 0} within budget` + (tiers ? ` · tiers ${tiers}` : '')
}

function publishErrorMessage(code?: string): string {
  switch (code) {
    case 'missing_google_drive_folder_id':
      return 'This client has no Drive folder set — add one on the client form first.'
    case 'publish_not_configured':
      return 'Google Docs publishing isn’t configured (GOOGLE_APPS_SCRIPT_URL is not set).'
    case 'review_not_complete':
      return 'The review has to finish before it can be saved.'
    default:
      return `Couldn’t save to Drive: ${code ?? 'unknown error'}`
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
const recoveryBox: React.CSSProperties = {
  border: '1px solid #fecdd3', background: '#fff1f2', borderRadius: 8, padding: '10px 12px',
}
const tierBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 11.5, fontWeight: 600, color: '#9f1239', background: '#fff',
  border: '1px solid #fecdd3', borderRadius: 8, padding: '4px 9px', cursor: 'pointer',
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
const saveBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  fontSize: 12.5, fontWeight: 600, color: '#334155', background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '6px 12px', cursor: 'pointer',
}
const docLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  fontSize: 12.5, fontWeight: 600, color: '#16a34a', background: '#f0fdf4',
  border: '1px solid #bbf7d0', borderRadius: 8, padding: '6px 12px',
  textDecoration: 'none',
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
const collapseToggle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
  fontSize: 12.5, fontWeight: 600, color: '#475569', background: 'transparent',
  border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left',
}
