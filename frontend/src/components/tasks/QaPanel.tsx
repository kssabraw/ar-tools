import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, ExternalLink, HelpCircle, MinusCircle, ShieldCheck, XCircle } from 'lucide-react'
import { api } from '../../lib/api'
import type { QaCheck, QaReview } from '../../lib/types'

// QA panel for the task drawer (qa-agent-plan Phase 3 surface): latest verdict
// + per-check breakdown, review history, and an on-demand "Run QA" button.
// Reviews are produced by the async qa_review job, so after enqueueing we poll
// the history until a review newer than the enqueue moment lands (bounded).

const POLL_MS = 4000
const POLL_MAX_MS = 3 * 60 * 1000

const VERDICT_META: Record<QaReview['verdict'], { label: string; color: string; bg: string; Icon: typeof CheckCircle2 }> = {
  pass: { label: 'Passed', color: '#15803d', bg: '#f0fdf4', Icon: CheckCircle2 },
  fail: { label: 'Failed', color: '#b91c1c', bg: '#fef2f2', Icon: XCircle },
  needs_human: { label: 'Needs a human', color: '#b45309', bg: '#fffbeb', Icon: AlertTriangle },
  skipped: { label: 'Not QA-checked', color: '#64748b', bg: '#f8fafc', Icon: MinusCircle },
}

const RUBRIC_LABELS: Record<string, string> = {
  blog_article: 'Blog article',
  website_page: 'Website page',
  gbp_posts: 'GBP post',
  citations: 'Citations',
  guest_posts: 'Guest post',
  niche_edits: 'Niche edit',
  press_release: 'Press release',
  map_embeds: 'Map embeds',
  skip: 'Not checked (owner ruling)',
  handoff_sermastr: 'SerMaStr territory',
  generic: 'No checklist for this type',
}

// The rubrics a user can explicitly pick on a task (the checkable ones + the
// two "don't check / hand off" outcomes). "" = auto-detect from the task name.
// Order chosen for the dropdown; labels reuse RUBRIC_LABELS above.
const RUBRIC_CHOICES: string[] = [
  'website_page', 'blog_article', 'gbp_posts', 'citations',
  'guest_posts', 'niche_edits', 'press_release', 'map_embeds', 'skip',
]

const label: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }
const fieldInput: React.CSSProperties = { width: '100%', padding: '6px 9px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12.5, fontFamily: 'inherit', background: '#fff', color: '#0f172a', boxSizing: 'border-box' }

function CheckRow({ c }: { c: QaCheck }) {
  const icon =
    c.ok === true ? <CheckCircle2 size={14} color="#22c55e" /> :
    c.ok === false ? <XCircle size={14} color={c.blocking ? '#ef4444' : '#f59e0b'} /> :
    <HelpCircle size={14} color="#f59e0b" />
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 7, padding: '4px 0' }}>
      <span style={{ marginTop: 1, flexShrink: 0 }}>{icon}</span>
      <span style={{ fontSize: 12.5, color: c.ok === false && c.blocking ? '#b91c1c' : '#334155', overflowWrap: 'anywhere' }}>
        {c.label}
        {!c.blocking && <span style={{ color: '#94a3b8' }}> (advisory)</span>}
        {c.note && <span style={{ color: '#94a3b8' }}> — {c.note}</span>}
      </span>
    </div>
  )
}

function ReviewCard({ review }: { review: QaReview }) {
  const meta = VERDICT_META[review.verdict] ?? VERDICT_META.needs_human
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', background: meta.bg }}>
        <meta.Icon size={16} color={meta.color} />
        <span style={{ fontSize: 13, fontWeight: 700, color: meta.color }}>{meta.label}</span>
        {review.composite != null && (
          <span style={{ fontSize: 12, fontWeight: 600, color: meta.color }}>· {Math.round(review.composite)}/100</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#94a3b8' }}>
          {RUBRIC_LABELS[review.rubric] ?? review.rubric} · {new Date(review.created_at).toLocaleString()}
        </span>
      </div>
      <div style={{ padding: '8px 12px' }}>
        {review.narrative && (
          <div style={{ fontSize: 12.5, color: '#475569', marginBottom: review.checks.length ? 8 : 0 }}>
            {review.narrative}
          </div>
        )}
        {review.checks.map((c, i) => <CheckRow key={`${c.key}-${i}`} c={c} />)}
        {review.urls.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {review.urls.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer"
                 style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: '#4f46e5', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                <ExternalLink size={11} style={{ flexShrink: 0 }} /> {u}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Website-page sub-types QA can compare structure against (must match the
// client's stored reference-structure keys). "" = auto (priority order).
const PAGE_TYPE_CHOICES: { value: string; label: string }[] = [
  { value: 'service', label: 'Service page' },
  { value: 'local_landing', label: 'Local landing page' },
  { value: 'location', label: 'Location page' },
]

type QaReadiness = {
  rubric: string | null
  rubric_label: string
  ready: boolean
  have: string[]
  missing: string[]
  autodetected: { url?: string; keyword?: string }
  notes: string[]
}

// Rubrics that review an external URL (so the 'Page URL to review' field applies).
const URL_RUBRICS = new Set(['website_page', 'citations', 'guest_posts', 'niche_edits', 'press_release', 'map_embeds'])

export function QaPanel({
  taskId, rubric, onRubricChange, pageType, onPageTypeChange,
  deliverableUrl, onDeliverableUrlChange, keyword, onKeywordChange,
}: {
  taskId: string
  // The task's explicit QA rubric (null/undefined = auto-detect from name).
  rubric?: string | null
  onRubricChange?: (rubric: string | null) => void
  // The task's website-page sub-type (null = auto); drives the structural
  // design-fit reference selection.
  pageType?: string | null
  onPageTypeChange?: (pageType: string | null) => void
  // First-class QA inputs (the guided panel): page URL + target keyword.
  deliverableUrl?: string | null
  onDeliverableUrlChange?: (url: string | null) => void
  keyword?: string | null
  onKeywordChange?: (keyword: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [urlDraft, setUrlDraft] = useState<string | null>(null)
  const [kwDraft, setKwDraft] = useState<string | null>(null)

  // "Can QA run yet, and what's missing" — plain English for the VA.
  const { data: readiness } = useQuery<QaReadiness>({
    queryKey: ['task-qa-readiness', taskId],
    queryFn: () => api.get<QaReadiness>(`/tasks/${taskId}/qa-readiness`),
  })
  // After a field PATCH round-trips (props change), re-check readiness.
  useEffect(() => {
    queryClient.invalidateQueries({ queryKey: ['task-qa-readiness', taskId] })
  }, [queryClient, taskId, rubric, pageType, deliverableUrl, keyword])

  const rubricKey = readiness?.rubric ?? rubric ?? ''
  const showUrl = !!onDeliverableUrlChange && (URL_RUBRICS.has(rubricKey) || rubricKey === '')
  const showKeyword = !!onKeywordChange && (rubricKey === 'website_page' || rubricKey === '')
  // Set when a run was enqueued; polling stops once a newer review lands
  // (or after POLL_MAX_MS so a stuck job can't poll forever).
  const [pendingSince, setPendingSince] = useState<number | null>(null)
  const [showHistory, setShowHistory] = useState(false)

  const { data: reviews = [], isLoading } = useQuery<QaReview[]>({
    queryKey: ['task-qa', taskId],
    queryFn: () => api.get<QaReview[]>(`/tasks/${taskId}/qa-reviews`),
    refetchInterval: pendingSince ? POLL_MS : false,
  })

  const latest = reviews[0]
  const history = reviews.slice(1)

  useEffect(() => {
    setPendingSince(null)
    setShowHistory(false)
    setUrlDraft(null)
    setKwDraft(null)
  }, [taskId])

  // A review newer than the enqueue moment (or a timeout) ends the run state.
  useEffect(() => {
    if (!pendingSince) return
    if (latest && new Date(latest.created_at).getTime() >= pendingSince) setPendingSince(null)
    else if (Date.now() - pendingSince > POLL_MAX_MS) setPendingSince(null)
  }, [pendingSince, latest])

  const runMut = useMutation({
    mutationFn: () => api.post(`/tasks/${taskId}/qa`, {}),
    onSuccess: () => {
      setPendingSince(Date.now())
      queryClient.invalidateQueries({ queryKey: ['task-qa', taskId] })
    },
  })

  const running = pendingSince !== null
  // Block the run until QA can actually work (missing URL/keyword/rubric) — the
  // banner already says what's missing, so don't let a click produce a
  // confusing needs-human. `undefined` readiness (still loading) never blocks.
  const notReady = readiness ? readiness.ready === false : false
  const runDisabled = running || runMut.isPending || notReady

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ ...label, marginBottom: 0, flex: 1 }}>QA</div>
        <button
          onClick={() => runMut.mutate()}
          disabled={runDisabled}
          title={notReady ? 'Add what the panel lists below before running QA' : undefined}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 11px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 12, fontWeight: 600, cursor: runDisabled ? 'default' : 'pointer', opacity: runDisabled ? 0.6 : 1 }}
        >
          <ShieldCheck size={13} /> {running ? 'Reviewing…' : 'Run QA'}
        </button>
      </div>
      {readiness && (
        <div
          style={{
            marginTop: 8, borderRadius: 8, padding: '8px 10px', fontSize: 12.5, lineHeight: 1.45,
            ...(readiness.ready
              ? { background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#15803d' }
              : { background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' }),
          }}
        >
          {readiness.ready
            ? <span style={{ fontWeight: 600 }}>✓ Ready to QA{readiness.rubric_label ? ` · ${readiness.rubric_label}` : ''}</span>
            : readiness.missing.length
              ? <span><b>Before QA can run, add:</b> {readiness.missing.join(', ')}.</span>
              : <span>Not QA-ready.</span>}
          {(readiness.autodetected?.url || readiness.autodetected?.keyword) && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
              Auto-detected{readiness.autodetected.keyword ? ` keyword “${readiness.autodetected.keyword}”` : ''}
              {readiness.autodetected.url ? ` · page ${readiness.autodetected.url}` : ''} — nothing to set.
            </div>
          )}
          {(readiness.notes ?? []).map((n, i) => (
            <div key={i} style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>{n}</div>
          ))}
        </div>
      )}
      {onRubricChange && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...label, marginBottom: 3 }}>Rubric</div>
          <select
            value={rubric ?? ''}
            onChange={(e) => onRubricChange(e.target.value || null)}
            style={{ width: '100%', padding: '6px 9px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12.5, fontFamily: 'inherit', background: '#fff', color: '#0f172a', boxSizing: 'border-box' }}
          >
            <option value="">Auto-detect from task name</option>
            {RUBRIC_CHOICES.map((r) => (
              <option key={r} value={r}>{RUBRIC_LABELS[r] ?? r}</option>
            ))}
          </select>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>
            Which checklist QA grades this task against — pick one so the title can be anything.
          </div>
        </div>
      )}
      {onPageTypeChange && rubricKey === 'website_page' && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...label, marginBottom: 3 }}>Page type</div>
          <select
            value={pageType ?? ''}
            onChange={(e) => onPageTypeChange(e.target.value || null)}
            style={{ width: '100%', padding: '6px 9px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12.5, fontFamily: 'inherit', background: '#fff', color: '#0f172a', boxSizing: 'border-box' }}
          >
            <option value="">Auto (Service → Local landing → Location)</option>
            {PAGE_TYPE_CHOICES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>
            Which reference-page structure the design-fit check compares this page against.
          </div>
        </div>
      )}
      {showUrl && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...label, marginBottom: 3 }}>Page URL to review</div>
          <input
            value={urlDraft ?? deliverableUrl ?? ''}
            onChange={(e) => setUrlDraft(e.target.value)}
            onBlur={() => {
              if (urlDraft !== null && urlDraft !== (deliverableUrl ?? '')) onDeliverableUrlChange!(urlDraft.trim() || null)
              setUrlDraft(null)
            }}
            placeholder="https://client.com/the-page-you-posted/"
            style={fieldInput}
          />
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>
            Paste the live page you posted — this is exactly what QA opens and checks.
          </div>
        </div>
      )}
      {showKeyword && (
        <div style={{ marginTop: 8 }}>
          <div style={{ ...label, marginBottom: 3 }}>Target keyword</div>
          <input
            value={kwDraft ?? keyword ?? ''}
            onChange={(e) => setKwDraft(e.target.value)}
            onBlur={() => {
              if (kwDraft !== null && kwDraft !== (keyword ?? '')) onKeywordChange!(kwDraft.trim() || null)
              setKwDraft(null)
            }}
            placeholder="e.g. practice management coral springs"
            style={fieldInput}
          />
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>
            The phrase the page should rank for — QA checks it's in the title, URL and H1.
          </div>
        </div>
      )}
      {runMut.isError && (
        <div style={{ fontSize: 12, color: '#dc2626', marginTop: 6 }}>
          Could not start QA — {String((runMut.error as Error)?.message ?? 'try again')}
        </div>
      )}
      <div style={{ marginTop: 8 }}>
        {isLoading ? (
          <div style={{ fontSize: 12, color: '#cbd5e1' }}>Loading…</div>
        ) : !latest ? (
          <div style={{ fontSize: 12, color: '#cbd5e1' }}>
            {running ? 'Review in progress…' : 'No QA reviews yet — move the task to In QA or hit Run QA.'}
          </div>
        ) : (
          <>
            {running && (
              <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 6 }}>Review in progress — showing the last result…</div>
            )}
            <ReviewCard review={latest} />
            {history.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <button
                  onClick={() => setShowHistory((v) => !v)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4, border: 'none', background: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: 0 }}
                >
                  {showHistory ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  {history.length} earlier review{history.length === 1 ? '' : 's'}
                </button>
                {showHistory && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                    {history.map((r) => <ReviewCard key={r.id} review={r} />)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
