import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType, RunStatus } from '../lib/types'
import { ArrowLeft, Ban, CheckCircle, XCircle, Clock, Loader, Download, Copy, RotateCcw, Repeat, Play, ExternalLink } from 'lucide-react'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}m ${rem}s`
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

// ---------------------------------------------------------------------------
// Module metadata
// ---------------------------------------------------------------------------

type ModuleKey = keyof RunDetailType['module_outputs']

interface ModuleMeta {
  key: ModuleKey
  label: string
  description: string
  runningStatus: RunStatus
  typicalRange: string
}

const MODULES: ModuleMeta[] = [
  {
    key: 'brief',
    label: 'Brief Generator',
    description: 'Analyzing search intent and building content outline',
    runningStatus: 'brief_running',
    typicalRange: '20–40s',
  },
  {
    key: 'sie',
    label: 'Search Intent Engine',
    description: 'Fetching competitor SERP data and ranking signals',
    runningStatus: 'sie_running',
    typicalRange: '15–30s',
  },
  {
    key: 'research',
    label: 'Research & Citations',
    description: 'Gathering sources, scraping pages, extracting citations',
    runningStatus: 'research_running',
    typicalRange: '30–60s',
  },
  {
    key: 'writer',
    label: 'Content Writer',
    description: 'Drafting the full article with brand voice and SEO structure',
    runningStatus: 'writer_running',
    typicalRange: '2–5 min',
  },
  {
    key: 'sources_cited',
    label: 'Sources Cited',
    description: 'Embedding inline citations and assembling references section',
    runningStatus: 'sources_cited_running',
    typicalRange: '5–15s',
  },
]

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']

// Words that stay lowercase in title case unless they're the first or last word.
// Conservative list following Chicago/AP conventions for short prepositions,
// articles, and coordinating conjunctions.
const TITLE_CASE_MINOR_WORDS = new Set([
  'a', 'an', 'the',
  'and', 'as', 'but', 'for', 'if', 'nor', 'or', 'so', 'yet',
  'at', 'by', 'in', 'of', 'off', 'on', 'per', 'to', 'up', 'via', 'vs',
])

function toTitleCase(str: string): string {
  if (!str) return str
  const tokens = str.split(/(\s+)/) // preserve whitespace tokens

  const wordPositions: number[] = []
  tokens.forEach((t, i) => { if (t.trim()) wordPositions.push(i) })
  if (wordPositions.length === 0) return str
  const firstIdx = wordPositions[0]
  const lastIdx = wordPositions[wordPositions.length - 1]

  return tokens.map((piece, i) => {
    if (!piece.trim()) return piece

    // Preserve mixed-case brand words (TikTok, iPhone, eBay, McDonald's)
    if (/[a-z][A-Z]/.test(piece)) return piece
    // Preserve all-caps acronyms of 2+ chars (FAQ, USA, B2B, AI)
    if (piece.length >= 2 && piece === piece.toUpperCase() && /[A-Z]/.test(piece)) return piece

    const isFirstOrLast = i === firstIdx || i === lastIdx
    const cleaned = piece.toLowerCase().replace(/[^a-z']/g, '')

    if (!isFirstOrLast && TITLE_CASE_MINOR_WORDS.has(cleaned)) {
      return piece.toLowerCase()
    }

    // Capitalize the first letter (skipping leading punctuation),
    // then lowercase the rest of the word.
    return piece.replace(/^([^A-Za-z]*)([A-Za-z])(.*)$/, (_m, lead, first, rest) =>
      lead + first.toUpperCase() + rest.toLowerCase()
    )
  }).join('')
}

function sectionsToMarkdown(article: unknown[], title?: string): string {
  if (!Array.isArray(article)) return ''

  const HEADING_PREFIX: Record<string, string> = {
    H1: '# ',
    H2: '## ',
    H3: '### ',
    H4: '#### ',
  }

  const sorted = article
    .slice()
    .sort((a: any, b: any) => (a.order ?? 0) - (b.order ?? 0))

  const parts: string[] = []
  if (title) parts.push(`# ${toTitleCase(title)}`)

  for (const s of sorted as any[]) {
    // Skip the article's H1 section if we've already rendered the title
    // (writer emits H1 with empty body — it would just duplicate the title)
    if (title && s.level === 'H1' && !(s.body ?? '').trim()) continue

    const prefix = HEADING_PREFIX[s.level] ?? ''
    const heading = s.heading ? `${prefix}${toTitleCase(s.heading)}` : ''
    const body = s.body ?? ''

    if (heading && body) parts.push(`${heading}\n\n${body}`)
    else if (heading) parts.push(heading)
    else if (body) parts.push(body)
  }

  return parts.join('\n\n')
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusChip({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, { bg: string; color: string; label: string }> = {
    queued:                  { bg: '#f1f5f9', color: '#475569', label: 'Queued' },
    brief_running:           { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    sie_running:             { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    research_running:        { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    writer_running:          { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    sources_cited_running:   { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    complete:                { bg: '#dcfce7', color: '#166534', label: 'Complete' },
    failed:                  { bg: '#fee2e2', color: '#991b1b', label: 'Failed' },
    cancelled:               { bg: '#f1f5f9', color: '#475569', label: 'Cancelled' },
  }
  const s = map[status] ?? { bg: '#f1f5f9', color: '#475569', label: status }
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '4px 14px', fontSize: 13, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

function ModuleRow({
  meta,
  runStatus,
  moduleStatus,
  durationMs,
  costUsd,
  liveElapsedMs,
}: {
  meta: ModuleMeta
  runStatus: RunStatus
  moduleStatus?: string
  durationMs?: number | null
  costUsd?: number | null
  liveElapsedMs?: number
}) {
  const isDone = moduleStatus === 'complete'
  const isFailed = moduleStatus === 'failed'
  // Brief + SIE run in parallel, but the orchestrator only emits `brief_running`
  // for that whole phase — `sie_running` is never actually set. Treat both as
  // running while status is `brief_running` (until each module's own status
  // flips to complete/failed).
  const inParallelBriefSiePhase =
    runStatus === 'brief_running' && (meta.key === 'brief' || meta.key === 'sie')
  const isRunning = !isDone && !isFailed && (runStatus === meta.runningStatus || inParallelBriefSiePhase)
  const isPending = !isDone && !isFailed && !isRunning

  let statusIcon
  if (isDone) statusIcon = <CheckCircle size={18} color="#22c55e" style={{ flexShrink: 0 }} />
  else if (isFailed) statusIcon = <XCircle size={18} color="#dc2626" style={{ flexShrink: 0 }} />
  else if (isRunning) statusIcon = <Loader size={18} color="#6366f1" style={{ flexShrink: 0, animation: 'spin 1s linear infinite' }} />
  else statusIcon = <Clock size={18} color="#cbd5e1" style={{ flexShrink: 0 }} />

  const rowBg = isRunning ? '#f8f7ff' : isFailed ? '#fff8f8' : 'transparent'
  const rowBorder = isRunning ? '1px solid #e0e7ff' : isFailed ? '1px solid #fecaca' : '1px solid transparent'

  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      padding: '12px 14px',
      borderRadius: 10,
      background: rowBg,
      border: rowBorder,
      transition: 'background 0.3s',
    }}>
      <div style={{ paddingTop: 1 }}>{statusIcon}</div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            fontSize: 14,
            fontWeight: isRunning || isDone ? 600 : 400,
            color: isDone ? '#0f172a' : isRunning ? '#312e81' : isFailed ? '#7f1d1d' : '#94a3b8',
          }}>
            {meta.label}
          </span>
          {isRunning && (
            <span style={{ fontSize: 12, color: '#6366f1', fontWeight: 500 }}>
              running…
            </span>
          )}
          {isPending && (
            <span style={{ fontSize: 11, color: '#cbd5e1' }}>
              ~{meta.typicalRange}
            </span>
          )}
        </div>

        {(isRunning || (isPending && !TERMINAL.includes(runStatus))) && (
          <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
            {meta.description}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2, flexShrink: 0 }}>
        {isDone && durationMs != null && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{formatElapsed(durationMs)}</span>
        )}
        {isRunning && liveElapsedMs != null && (
          <span style={{ fontSize: 13, fontWeight: 600, color: '#6366f1', fontVariantNumeric: 'tabular-nums' }}>
            {formatElapsed(liveElapsedMs)}
          </span>
        )}
        {isDone && costUsd != null && (
          <span style={{ fontSize: 11, color: '#cbd5e1' }}>${costUsd.toFixed(4)}</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function RunDetail() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: run, isLoading } = useQuery<RunDetailType>({
    queryKey: ['run', id],
    queryFn: () => api.get<RunDetailType>(`/runs/${id}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !TERMINAL.includes(status) ? 3000 : false
    },
  })

  const isLive = !!run && !TERMINAL.includes(run.status)
  const now = useNow(isLive)

  const cancelMutation = useMutation({
    mutationFn: () => api.post<{ id: string; status: RunStatus }>(`/runs/${id}/cancel`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', id] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const rerunMutation = useMutation({
    mutationFn: () => api.post<{ run_id: string; status: RunStatus }>(`/runs/${id}/rerun`, {}),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/runs/${data.run_id}`)
    },
  })

  const resumeMutation = useMutation({
    mutationFn: () => api.post<{ run_id: string; status: RunStatus }>(`/runs/${id}/resume`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', id] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)
  const publishMutation = useMutation({
    mutationFn: () => api.post<{ doc_url: string }>(`/runs/${id}/publish`, {}),
    onSuccess: (data) => {
      setPublishedUrl(data.doc_url)
      window.open(data.doc_url, '_blank')
    },
  })

  if (isLoading) return <div style={{ padding: 40, color: '#64748b' }}>Loading…</div>
  if (!run) return <div style={{ padding: 40, color: '#dc2626' }}>Run not found</div>

  const canCancel = !TERMINAL.includes(run.status)
  const canResume = run.status === 'failed' || run.status === 'cancelled'
  const canRestart = run.status === 'failed' || run.status === 'cancelled'
  const canRerun = run.status === 'complete'

  // Compute per-stage elapsed estimates
  const startMs = run.started_at ? new Date(run.started_at).getTime() : null
  const briMs = run.module_outputs?.brief?.duration_ms ?? null
  const sieMs = run.module_outputs?.sie?.duration_ms ?? null
  const resMs = run.module_outputs?.research?.duration_ms ?? null
  const wriMs = run.module_outputs?.writer?.duration_ms ?? null

  // Stage 1 (brief+sie parallel): starts at run start
  // Stage 2 (research): starts after max(brief, sie)
  // Stage 3 (writer): starts after research
  // Stage 4 (sources_cited): starts after writer
  const stage1DoneMs = briMs != null && sieMs != null ? Math.max(briMs, sieMs)
                      : briMs != null ? briMs
                      : sieMs != null ? sieMs
                      : null
  const stage2StartMs = stage1DoneMs
  const stage3StartMs = stage2StartMs != null && resMs != null ? stage2StartMs + resMs : null
  const stage4StartMs = stage3StartMs != null && wriMs != null ? stage3StartMs + wriMs : null

  function liveFor(stageOffsetMs: number | null): number | undefined {
    if (!startMs || stageOffsetMs == null) return undefined
    const stageStart = startMs + stageOffsetMs
    return Math.max(0, now - stageStart)
  }

  const liveElapsed: Partial<Record<ModuleKey, number>> = {
    brief: liveFor(0),
    sie: liveFor(0),
    research: liveFor(stage2StartMs),
    writer: liveFor(stage3StartMs),
    sources_cited: liveFor(stage4StartMs),
  }

  // Overall elapsed
  const totalElapsedMs = startMs
    ? (run.completed_at ? new Date(run.completed_at).getTime() : now) - startMs
    : null

  // Progress count
  const completedCount = MODULES.filter(m => run.module_outputs?.[m.key]?.status === 'complete').length
  const progressPct = (completedCount / MODULES.length) * 100

  const scPayload = run.module_outputs?.sources_cited?.output_payload
  const enrichedArticle = scPayload?.enriched_article as Record<string, unknown> | undefined
  const articleSections = enrichedArticle?.article as unknown[] | undefined
  const articleTitle = typeof enrichedArticle?.title === 'string' ? enrichedArticle.title : undefined
  const articleMarkdown = articleSections ? sectionsToMarkdown(articleSections, articleTitle) : null

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>

      <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20 }}>
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
            {run.title ?? run.keyword}
          </h1>
          {run.title && (
            <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 4 }}>“{run.keyword}”</div>
          )}
          <div style={{ fontSize: 13, color: '#64748b', display: 'flex', alignItems: 'center', gap: 6 }}>
            {run.started_at
              ? `Started ${new Date(run.started_at).toLocaleString()}`
              : `Created ${new Date(run.created_at).toLocaleString()}`}
            {totalElapsedMs != null && (
              <span style={{
                fontVariantNumeric: 'tabular-nums',
                color: isLive ? '#6366f1' : '#94a3b8',
                fontWeight: isLive ? 600 : 400,
              }}>
                · {isLive ? '⏱ ' : ''}{formatElapsed(totalElapsedMs)}
              </span>
            )}
            {run.total_cost_usd != null && (
              <span>· ${run.total_cost_usd.toFixed(4)}</span>
            )}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusChip status={run.status} />
          {canCancel && (
            <button onClick={() => {
              if (!window.confirm('Cancel this run? In-progress modules will finish, but no further stages will run.')) return
              cancelMutation.mutate()
            }} disabled={cancelMutation.isPending} style={cancelBtn}>
              <Ban size={13} /> {cancelMutation.isPending ? 'Cancelling…' : 'Cancel'}
            </button>
          )}
          {canResume && (
            <button onClick={() => {
              if (!window.confirm('Resume this run from the last completed stage? Already-finished modules will be reused.')) return
              resumeMutation.mutate()
            }} disabled={resumeMutation.isPending} style={resumeBtn}>
              <Play size={13} /> {resumeMutation.isPending ? 'Resuming…' : 'Resume'}
            </button>
          )}
          {canRestart && (
            <button onClick={() => {
              if (!window.confirm('Restart with the same client and keyword? This creates a new run.')) return
              rerunMutation.mutate()
            }} disabled={rerunMutation.isPending} style={restartBtn}>
              <RotateCcw size={13} /> {rerunMutation.isPending ? 'Starting…' : 'Restart'}
            </button>
          )}
          {canRerun && (
            <button onClick={() => {
              if (!window.confirm('Rerun with the same client and keyword? This creates a new run.')) return
              rerunMutation.mutate()
            }} disabled={rerunMutation.isPending} style={rerunBtnStyle}>
              <Repeat size={13} /> {rerunMutation.isPending ? 'Starting…' : 'Rerun'}
            </button>
          )}
        </div>
      </div>

      {/* Mutation errors */}
      {cancelMutation.isError && <ErrorBanner msg={`Failed to cancel: ${cancelMutation.error instanceof Error ? cancelMutation.error.message : 'unknown error'}`} />}
      {rerunMutation.isError && <ErrorBanner msg={`Failed to start new run: ${rerunMutation.error instanceof Error ? rerunMutation.error.message : 'unknown error'}`} />}
      {resumeMutation.isError && <ErrorBanner msg={`Failed to resume: ${resumeMutation.error instanceof Error ? resumeMutation.error.message : 'unknown error'}`} />}

      {/* Pipeline Progress card */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={sectionTitle}>Pipeline Progress</h2>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{completedCount} / {MODULES.length} stages</span>
        </div>

        {/* Progress bar */}
        <div style={{ height: 4, background: '#f1f5f9', borderRadius: 99, marginBottom: 16, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: run.status === 'failed' ? '#dc2626' : run.status === 'cancelled' ? '#94a3b8' : '#6366f1',
            borderRadius: 99,
            transition: 'width 0.5s ease',
          }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {MODULES.map((m) => {
            const mo = run.module_outputs?.[m.key]
            return (
              <ModuleRow
                key={m.key}
                meta={m}
                runStatus={run.status}
                moduleStatus={mo?.status}
                durationMs={mo?.duration_ms}
                costUsd={mo?.cost_usd}
                liveElapsedMs={run.status === m.runningStatus ? liveElapsed[m.key] : undefined}
              />
            )
          })}
        </div>

        {run.error_message && (
          <div style={{ marginTop: 14, padding: '12px 14px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
            <strong>Error{run.error_stage ? ` (${run.error_stage})` : ''}:</strong> {run.error_message}
          </div>
        )}
      </div>

      {/* Article output */}
      {articleMarkdown && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2 style={sectionTitle}>Generated Article</h2>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => navigator.clipboard.writeText(articleMarkdown)} style={ghostBtn}>
                <Copy size={13} /> Copy
              </button>
              <button onClick={() => downloadFile(articleMarkdown, `${run.keyword.replace(/\s+/g, '-')}.md`, 'text/markdown')} style={ghostBtn}>
                <Download size={13} /> Download .md
              </button>
              <button onClick={() => downloadFile(articleMarkdown, `${run.keyword.replace(/\s+/g, '-')}.txt`, 'text/plain')} style={ghostBtn}>
                <Download size={13} /> .txt
              </button>
              {publishedUrl ? (
                <a href={publishedUrl} target="_blank" rel="noreferrer"
                  style={{ ...ghostBtn, textDecoration: 'none', color: '#16a34a', borderColor: '#bbf7d0' }}>
                  <ExternalLink size={13} /> Open Doc
                </a>
              ) : (
                <button
                  onClick={() => publishMutation.mutate()}
                  disabled={publishMutation.isPending}
                  style={{ ...ghostBtn, color: '#6366f1', borderColor: '#c7d2fe' }}
                  title="Publish to the client's Google Drive folder"
                >
                  <ExternalLink size={13} /> {publishMutation.isPending ? 'Publishing…' : 'Publish to Google Docs'}
                </button>
              )}
            </div>
          </div>
          {publishMutation.isError && (
            <div style={{ marginBottom: 12, padding: '10px 12px', background: '#fef2f2', borderRadius: 6, color: '#dc2626', fontSize: 12 }}>
              Failed to publish: {publishMutation.error instanceof Error ? publishMutation.error.message : 'unknown error'}
            </div>
          )}
          <pre style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 20, overflowX: 'auto', fontSize: 13, lineHeight: 1.7, color: '#374151', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 600, overflowY: 'auto' }}>
            {articleMarkdown}
          </pre>
        </div>
      )}

      {run.status === 'failed' && !articleMarkdown && (
        <div style={{ ...cardStyle, textAlign: 'center', padding: 48, color: '#64748b' }}>
          <XCircle size={32} color="#dc2626" style={{ marginBottom: 12 }} />
          <div>This run failed. Check the error above, then use Resume to continue from where it stopped.</div>
        </div>
      )}
    </div>
  )
}

function ErrorBanner({ msg }: { msg: string }) {
  return (
    <div style={{ marginBottom: 12, padding: '10px 14px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
      {msg}
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#0f172a', margin: 0 }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const cancelBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#fff', color: '#dc2626', border: '1px solid #fecaca', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const restartBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#fff', color: '#b45309', border: '1px solid #fde68a', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const resumeBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#fff', color: '#0f766e', border: '1px solid #99f6e4', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const rerunBtnStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#6366f1', color: '#fff', border: '1px solid #6366f1', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
