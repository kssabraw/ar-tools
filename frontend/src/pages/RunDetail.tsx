import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType, RunStatus } from '../lib/types'
import { ArrowLeft, Ban, CheckCircle, XCircle, Clock, Loader, Download, Copy, Check, RotateCcw, Repeat, Play, ExternalLink, AlertTriangle } from 'lucide-react'
import {
  BriefCacheDecisionModal,
  type BriefCacheStatus,
} from '../components/BriefCacheDecisionModal'
import { sectionsToMarkdown, toTitleCase } from '../lib/sectionsToMarkdown'
import { sectionsToHtml, escapeHtml } from '../lib/sectionsToHtml'
import { FeedbackButton } from '../components/FeedbackButton'
import { ServicePageRunView } from '../components/ServicePageRunView'
import { FeaturedImagePicker } from '../components/FeaturedImagePicker'

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
    service_brief_running:   { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    service_writer_running:  { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
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
    mutationFn: (forceRefresh: boolean) =>
      api.post<{ run_id: string; status: RunStatus }>(
        `/runs/${id}/rerun?brief_force_refresh=${forceRefresh}`,
        {},
      ),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      navigate(`/runs/${data.run_id}`)
    },
  })

  // PRD v2.6 — cache-decision modal state for the rerun button.
  // When the user clicks Restart, we first check whether the brief
  // for this keyword is cached. If yes, the modal opens; if no, we
  // rerun straight away.
  const [rerunCacheStatus, setRerunCacheStatus] = useState<BriefCacheStatus | null>(null)
  const [rerunModalOpen, setRerunModalOpen] = useState(false)

  async function handleRerunClick() {
    if (!run) return
    try {
      const status = await api.get<BriefCacheStatus>(
        `/briefs/cache-status?keyword=${encodeURIComponent(run.keyword)}&location_code=2840`,
      )
      if (status?.exists) {
        setRerunCacheStatus(status)
        setRerunModalOpen(true)
        return
      }
    } catch {
      // Pre-flight failure is non-fatal — fall through and rerun
      // without prompting (preserves prior behavior).
    }
    rerunMutation.mutate(false)
  }

  const resumeMutation = useMutation({
    mutationFn: () => api.post<{ run_id: string; status: RunStatus }>(`/runs/${id}/resume`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', id] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)
  const [wpUrl, setWpUrl] = useState<string | null>(null)
  const [wpStatus, setWpStatus] = useState<'draft' | 'publish'>('draft')
  const [fmt, setFmt] = useState<'markdown' | 'html'>('markdown')
  const publishMutation = useMutation({
    mutationFn: () => api.post<{ doc_url: string }>(`/runs/${id}/publish`, {}),
    onSuccess: (data) => {
      setPublishedUrl(data.doc_url)
      window.open(data.doc_url, '_blank')
    },
  })
  const wpPublishMutation = useMutation({
    mutationFn: () => api.post<{ url: string; edit_url: string }>(
      `/runs/${id}/publish`, { destination: 'wordpress', status: wpStatus },
    ),
    onSuccess: (data) => {
      const link = data.edit_url || data.url
      setWpUrl(link)
      if (link) window.open(link, '_blank')
    },
  })
  const featuredImageMutation = useMutation({
    mutationFn: (url: string | null) =>
      api.put<{ featured_image_url: string | null }>(`/runs/${id}/featured-image`, { url }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', id] }),
  })

  if (isLoading) return <div style={{ padding: 40, color: '#64748b' }}>Loading…</div>
  if (!run) return <div style={{ padding: 40, color: '#dc2626' }}>Run not found</div>

  // Service + location pages run the same distinct two-stage pipeline and
  // carry their own renderings (markdown/html/wordpress) + JSON-LD + score —
  // render the dedicated view for both.
  if (run.content_type === 'service_page' || run.content_type === 'location_page')
    return <ServicePageRunView run={run} />

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
  const articleHtml = articleSections ? sectionsToHtml(articleSections, articleTitle) : null

  // The exported article is a single self-contained document: the SEO/meta
  // title (labelled, since it's metadata — not body prose) and the on-page H1
  // sit above the body, so one Copy/Download grabs everything. The two strings
  // are often near-identical, so the H1 renders as the real heading while the
  // SEO title is a labelled line to avoid looking like a duplicated headline.
  // `sectionsTo*` already injects a leading heading from `articleTitle`; we
  // strip it and re-add the H1 from `run.h1` so it matches the "Title & H1"
  // section exactly (falling back to the article title when h1 is absent).
  const bodyMarkdown = articleMarkdown ? articleMarkdown.replace(/^# [^\n]*\n+/, '') : null
  const bodyHtml = articleHtml ? articleHtml.replace(/^<h1>.*?<\/h1>\n?/, '') : null
  const h1Heading = run.h1 ?? (articleTitle ? toTitleCase(articleTitle) : undefined)

  const fullMarkdown = articleMarkdown
    ? [
        run.title ? `**SEO Title:** ${run.title}` : null,
        h1Heading ? `# ${h1Heading}` : null,
        bodyMarkdown,
      ].filter(Boolean).join('\n\n')
    : null
  const fullHtml = articleHtml
    ? [
        run.title ? `<p><strong>SEO Title:</strong> ${escapeHtml(run.title)}</p>` : null,
        h1Heading ? `<h1>${escapeHtml(h1Heading)}</h1>` : null,
        bodyHtml,
      ].filter(Boolean).join('\n')
    : null
  const termUsageByZone = run.module_outputs?.writer?.output_payload?.term_usage_by_zone as
    | Record<string, { related_keywords: any[]; entities: any[]; quadgrams: any[] }>
    | undefined

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>

      <Link to="/runs" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20 }}>
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
              handleRerunClick()
            }} disabled={rerunMutation.isPending} style={restartBtn}>
              <RotateCcw size={13} /> {rerunMutation.isPending ? 'Starting…' : 'Restart'}
            </button>
          )}
          {canRerun && (
            <button onClick={() => {
              if (!window.confirm('Rerun with the same client and keyword? This creates a new run.')) return
              handleRerunClick()
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

      {/* QA checks - surfaces the review flags the pipeline already records
          but previously buried in module output payloads and logs. */}
      <QaChecksCard run={run} />

      {/* Title + H1 (each individually copyable). The title is the SEO/meta
          title (browser tab, SERP); the H1 is the on-page main heading.
          Often the same string but they're independently editable concepts. */}
      {(run.title || run.h1) && (
        <div style={cardStyle}>
          <h2 style={sectionTitle}>Title & H1</h2>
          {run.title && (
            <CopyableLine
              label="Title (SEO / meta)"
              text={run.title}
              hint="Browser tab, SERP snippet, og:title"
            />
          )}
          {run.h1 && (
            <CopyableLine
              label="H1 (on-page heading)"
              text={run.h1}
              hint="First H1 in the article body"
            />
          )}
        </div>
      )}

      {/* Article output */}
      {articleMarkdown && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <h2 style={sectionTitle}>Generated Article</h2>
              <div style={{ display: 'inline-flex', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
                {(['markdown', 'html'] as const).map(f => (
                  <button key={f} onClick={() => setFmt(f)} style={{
                    padding: '5px 12px', fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer',
                    background: fmt === f ? '#6366f1' : '#fff', color: fmt === f ? '#fff' : '#64748b',
                  }}>
                    {f === 'markdown' ? 'Markdown' : 'HTML'}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <FeedbackButton
                baseStyle={ghostBtn}
                doneLabel="Copied!"
                onAction={() => navigator.clipboard.writeText(fmt === 'html' ? (fullHtml ?? '') : (fullMarkdown ?? ''))}
              >
                <Copy size={13} /> Copy {fmt === 'html' ? 'HTML' : 'Markdown'}
              </FeedbackButton>
              {fmt === 'html' ? (
                <FeedbackButton
                  baseStyle={ghostBtn}
                  doneLabel="Downloaded!"
                  onAction={() => downloadFile(fullHtml ?? '', `${run.keyword.replace(/\s+/g, '-')}.html`, 'text/html')}
                >
                  <Download size={13} /> Download .html
                </FeedbackButton>
              ) : (
                <>
                  <FeedbackButton
                    baseStyle={ghostBtn}
                    doneLabel="Downloaded!"
                    onAction={() => downloadFile(fullMarkdown ?? '', `${run.keyword.replace(/\s+/g, '-')}.md`, 'text/markdown')}
                  >
                    <Download size={13} /> Download .md
                  </FeedbackButton>
                  <FeedbackButton
                    baseStyle={ghostBtn}
                    doneLabel="Saved!"
                    onAction={() => downloadFile(fullMarkdown ?? '', `${run.keyword.replace(/\s+/g, '-')}.txt`, 'text/plain')}
                  >
                    <Download size={13} /> .txt
                  </FeedbackButton>
                </>
              )}
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
              {wpUrl ? (
                <a href={wpUrl} target="_blank" rel="noreferrer"
                  style={{ ...ghostBtn, textDecoration: 'none', color: '#16a34a', borderColor: '#bbf7d0' }}>
                  <ExternalLink size={13} /> Open in WP
                </a>
              ) : (
                <div style={{ display: 'inline-flex', border: '1px solid #c7d2fe', borderRadius: 8, overflow: 'hidden' }}>
                  <select
                    value={wpStatus}
                    onChange={e => setWpStatus(e.target.value as 'draft' | 'publish')}
                    style={{ border: 'none', background: '#fff', color: '#6366f1', fontSize: 12, fontWeight: 600, padding: '0 6px', cursor: 'pointer' }}
                    title="Draft saves to WordPress unpublished; Publish goes live"
                  >
                    <option value="draft">Draft</option>
                    <option value="publish">Publish</option>
                  </select>
                  <button
                    onClick={() => wpPublishMutation.mutate()}
                    disabled={wpPublishMutation.isPending}
                    style={{ ...ghostBtn, border: 'none', borderLeft: '1px solid #c7d2fe', borderRadius: 0, color: '#6366f1' }}
                    title="Publish directly to the client's WordPress site"
                  >
                    <ExternalLink size={13} /> {wpPublishMutation.isPending ? 'Publishing…' : 'Publish to WP'}
                  </button>
                </div>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14, paddingBottom: 14, borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>Featured image</span>
            <FeaturedImagePicker
              value={run.featured_image_url ?? null}
              onChange={(url) => featuredImageMutation.mutateAsync(url).then(() => undefined)}
            />
          </div>
          {(publishMutation.isError || wpPublishMutation.isError) && (
            <div style={{ marginBottom: 12, padding: '10px 12px', background: '#fef2f2', borderRadius: 6, color: '#dc2626', fontSize: 12 }}>
              Failed to publish: {(publishMutation.error || wpPublishMutation.error) instanceof Error ? ((publishMutation.error || wpPublishMutation.error) as Error).message : 'unknown error'}
            </div>
          )}
          <pre style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: 20, overflowX: 'auto', fontSize: 13, lineHeight: 1.7, color: '#374151', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 600, overflowY: 'auto' }}>
            {fmt === 'html' ? fullHtml : fullMarkdown}
          </pre>
        </div>
      )}

      {/* Per-zone term usage breakdown — what related keywords, entities,
          and quadgrams actually appear in each zone of the article. */}
      {termUsageByZone && articleMarkdown && (
        <TermUsageCard usage={termUsageByZone} />
      )}

      {run.status === 'failed' && !articleMarkdown && (
        <div style={{ ...cardStyle, textAlign: 'center', padding: 48, color: '#64748b' }}>
          <XCircle size={32} color="#dc2626" style={{ marginBottom: 12 }} />
          <div>This run failed. Check the error above, then use Resume to continue from where it stopped.</div>
        </div>
      )}

      <BriefCacheDecisionModal
        open={rerunModalOpen}
        cacheStatus={rerunCacheStatus}
        busy={rerunMutation.isPending}
        onReuse={() => {
          rerunMutation.mutate(false)
          setRerunModalOpen(false)
          setRerunCacheStatus(null)
        }}
        onRegenerate={() => {
          rerunMutation.mutate(true)
          setRerunModalOpen(false)
          setRerunCacheStatus(null)
        }}
        onCancel={() => {
          setRerunModalOpen(false)
          setRerunCacheStatus(null)
        }}
      />
    </div>
  )
}

type TermEntry = { term: string; count: number; entity_category?: string }
type QuadgramEntry = { phrase: string; count: number }
type ZoneUsage = {
  related_keywords: TermEntry[]
  entities: TermEntry[]
  quadgrams: QuadgramEntry[]
}

const ZONE_LABEL: Record<string, string> = {
  title: 'Title',
  h1: 'H1',
  subheadings: 'Subheadings',
  body: 'Body',
}
const ZONE_HINT: Record<string, string> = {
  title: 'SEO/meta title',
  h1: 'On-page main heading',
  subheadings: 'All H2 + H3 heading text',
  body: 'All paragraph prose (citations stripped)',
}
const ZONE_ORDER: string[] = ['title', 'h1', 'subheadings', 'body']

function TermUsageCard({ usage }: { usage: Record<string, ZoneUsage> }) {
  return (
    <div style={cardStyle}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={sectionTitle}>Term Usage by Zone</h2>
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
          Which SIE-recommended related keywords, named entities, and most-frequent
          4-word phrases (quadgrams) actually appear in each zone of the article.
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {ZONE_ORDER.map((zone) => {
          const z = usage[zone]
          if (!z) return null
          const isEmpty =
            z.related_keywords.length === 0 &&
            z.entities.length === 0 &&
            z.quadgrams.length === 0
          return (
            <div
              key={zone}
              style={{
                border: '1px solid #e2e8f0',
                borderRadius: 8,
                padding: 14,
                background: '#fafbfc',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>
                  {ZONE_LABEL[zone] ?? zone}
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>{ZONE_HINT[zone]}</span>
              </div>
              {isEmpty ? (
                <div style={{ fontSize: 12, color: '#94a3b8', fontStyle: 'italic' }}>
                  No SIE-tracked terms or quadgram signal in this zone.
                </div>
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                    gap: 14,
                  }}
                >
                  <TermColumn
                    title="Related keywords"
                    items={z.related_keywords.map((t) => ({
                      label: t.term,
                      count: t.count,
                    }))}
                  />
                  <TermColumn
                    title="Entities"
                    items={z.entities.map((t) => ({
                      label: t.term,
                      count: t.count,
                      sub: t.entity_category,
                    }))}
                  />
                  <TermColumn
                    title="Quadgrams"
                    items={z.quadgrams.map((q) => ({
                      label: q.phrase,
                      count: q.count,
                    }))}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TermColumn({
  title,
  items,
}: {
  title: string
  items: { label: string; count: number; sub?: string }[]
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: '#64748b',
          textTransform: 'uppercase',
          letterSpacing: 0.4,
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: 12, color: '#cbd5e1', fontStyle: 'italic' }}>—</div>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {items.map((item, idx) => (
            <li
              key={`${item.label}-${idx}`}
              style={{
                fontSize: 12,
                color: '#0f172a',
                display: 'flex',
                justifyContent: 'space-between',
                gap: 8,
                lineHeight: 1.4,
              }}
            >
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.label}
                {item.sub && (
                  <span style={{ marginLeft: 6, fontSize: 10, color: '#94a3b8' }}>{item.sub}</span>
                )}
              </span>
              <span
                style={{
                  flexShrink: 0,
                  fontVariantNumeric: 'tabular-nums',
                  fontWeight: 600,
                  color: '#6366f1',
                }}
              >
                {item.count}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CopyableLine({ label, text, hint }: { label: string; text: string; hint?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.4 }}>
          {label}
        </span>
        <button
          onClick={() => {
            navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          style={{ ...ghostBtn, ...(copied ? { color: '#16a34a', borderColor: '#bbf7d0', background: '#f0fdf4' } : {}) }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />} {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <div style={{
        background: '#f8fafc',
        border: '1px solid #e2e8f0',
        borderRadius: 6,
        padding: '8px 12px',
        fontSize: 14,
        color: '#0f172a',
        lineHeight: 1.5,
        wordBreak: 'break-word',
      }}>
        {text}
      </div>
      {hint && (
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{hint}</div>
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

// ---------------------------------------------------------------------------
// QA checks card - surfaces the review flags the pipeline records (writer
// metadata + brief intent flags) that previously lived only in the raw
// payload JSON and server logs. Renders after the writer completes: a green
// all-clear when nothing is flagged, otherwise an amber list per flag.
// ---------------------------------------------------------------------------

type QaFlag = { severity: 'warn' | 'info'; text: string }

function collectQaFlags(run: RunDetailType): QaFlag[] {
  const flags: QaFlag[] = []
  const brief = run.module_outputs?.brief?.output_payload as Record<string, any> | null | undefined
  const wmeta = (run.module_outputs?.writer?.output_payload as Record<string, any> | null | undefined)
    ?.metadata as Record<string, any> | undefined
  const fmt = (run.module_outputs?.writer?.output_payload as Record<string, any> | null | undefined)
    ?.format_compliance as Record<string, any> | undefined

  // Format QA - the "right kind of article?" verdict.
  if (wmeta?.format_qa_matches_intent === false) {
    flags.push({
      severity: 'warn',
      text: `Format QA: structure may not match the keyword${
        wmeta.format_qa_expected_archetype ? ` (expected ${wmeta.format_qa_expected_archetype}, wrote ${brief?.intent_type ?? 'unknown'})` : ''
      }.${wmeta.format_qa_note ? ` ${wmeta.format_qa_note}` : ''}`,
    })
  }
  // Notes-landed judge - a writer note the article may not have honored.
  for (const v of (wmeta?.user_notes_verdicts as { note?: string; landed?: boolean; evidence?: string }[] | undefined) ?? []) {
    if (v.landed === false) {
      flags.push({
        severity: 'warn',
        text: `Writer note may not have been honored: "${v.note ?? 'unknown directive'}"${v.evidence ? ` - ${v.evidence}` : ''}`,
      })
    }
  }
  // Intent classified at low confidence - the brief flagged itself for review.
  if (brief?.intent_review_required === true) {
    flags.push({
      severity: 'warn',
      text: `Intent needs review: classified "${brief.intent_type}" at ${
        typeof brief.intent_confidence === 'number' ? brief.intent_confidence.toFixed(2) : '?'
      } confidence.`,
    })
  }
  for (const w of (wmeta?.structure_warnings as string[] | undefined) ?? []) {
    flags.push({ severity: 'warn', text: `Structure: ${w}` })
  }
  const leaked = (wmeta?.banned_terms_leaked_in_body as string[] | undefined) ?? []
  if (leaked.length > 0) {
    flags.push({ severity: 'warn', text: `Banned terms leaked into body: ${leaked.join(', ')}` })
  }
  const underLength = (wmeta?.under_length_h2_sections as unknown[] | undefined) ?? []
  if (underLength.length > 0) {
    flags.push({ severity: 'warn', text: `${underLength.length} section(s) below the word floor after retry.` })
  }
  const underCited = (wmeta?.under_cited_sections as unknown[] | undefined) ?? []
  if (underCited.length > 0) {
    flags.push({ severity: 'info', text: `${underCited.length} section(s) under 50% citation coverage after retry.` })
  }
  if (fmt && fmt.directives_satisfied === false) {
    flags.push({
      severity: 'info',
      text: `Format directives unmet: lists ${fmt.lists_present}/${fmt.lists_required}, tables ${fmt.tables_present}/${fmt.tables_required}.`,
    })
  }
  if (wmeta?.brand_mention_landed === false) {
    flags.push({ severity: 'info', text: 'Brand mention did not land in its anchor section.' })
  }
  if (wmeta?.icp_callout_landed === false) {
    flags.push({ severity: 'info', text: 'ICP callout did not land in its anchor section.' })
  }
  const droppedDupes = (wmeta?.duplicate_h2_headings_dropped as unknown[] | undefined) ?? []
  const droppedFaq = (wmeta?.faq_like_h2_content_dropped as unknown[] | undefined) ?? []
  if (droppedDupes.length + droppedFaq.length > 0) {
    flags.push({
      severity: 'info',
      text: `Heading sanitizer dropped ${droppedDupes.length + droppedFaq.length} H2(s) from the brief outline.`,
    })
  }
  return flags
}

function QaChecksCard({ run }: { run: RunDetailType }) {
  const writerDone = run.module_outputs?.writer?.status === 'complete'
  if (!writerDone) return null
  const flags = collectQaFlags(run)
  const wmeta = (run.module_outputs?.writer?.output_payload as Record<string, any> | null | undefined)
    ?.metadata as Record<string, any> | undefined
  const formatQaPassed = wmeta?.format_qa_matches_intent === true

  return (
    <div style={cardStyle}>
      <h2 style={{ ...sectionTitle, marginBottom: 12 }}>QA Checks</h2>
      {flags.length === 0 ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#16a34a' }}>
          <CheckCircle size={15} />
          All QA checks passed
          {formatQaPassed && ' - structure matches the keyword’s expected format'}
          {wmeta?.user_notes_landed_all === true && ' - writer notes honored'}
          .
        </div>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {flags.map((f, i) => (
            <li key={i} style={{
              display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, lineHeight: 1.5,
              padding: '8px 12px', borderRadius: 8,
              background: f.severity === 'warn' ? '#fffbeb' : '#f8fafc',
              color: f.severity === 'warn' ? '#92400e' : '#475569',
              border: `1px solid ${f.severity === 'warn' ? '#fde68a' : '#e2e8f0'}`,
            }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2, color: f.severity === 'warn' ? '#d97706' : '#94a3b8' }} />
              <span>{f.text}</span>
            </li>
          ))}
        </ul>
      )}
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
