import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CalendarPlus, Download, FileText, HelpCircle, Lightbulb, MessageCircleQuestion, Plus, RefreshCw, Search, Sparkles, Trash2, Trophy } from 'lucide-react'
import { api } from '../lib/api'
import { useResumableJob } from '../lib/useResumableJob'
import type { Client } from '../lib/types'

// Keyword Research — the seed-keyword explorer. Enter seed keyword(s) → the
// DataForSEO Labs keyword-ideas endpoint returns the related keyword universe
// (each enriched with volume / CPC / competition / KD / intent), auto-clustered
// into topic groups. Save & CSV export; no content generation. This replaced
// the Topic Fanout behind the "Keyword Research" workspace card.

interface RunSummary {
  id: string
  seeds: string[]
  keyword_count: number
  cluster_count: number
  cost_usd: number | null
  status: string
  created_at: string
}
interface ResearchKeyword {
  keyword: string
  cluster_label: string | null
  volume: number | null
  cpc_usd: number | null
  competition_index: number | null
  keyword_difficulty: number | null
  search_intent: string | null
  is_question: boolean
  opportunity_score: number | null
  relevance_score: number | null
  audience_fit: string | null
}
interface BlogTopic {
  title: string
  angle: string
  target_keywords?: string[]
}
interface TopicCard {
  theme: string
  pillar?: string | null
  problem: string | null
  title: string
  search_intent?: string | null
  funnel_stage?: string | null
  supporting_keywords: { keyword: string; volume: number | null }[]
  questions: string[]
  competitor_examples: string[]
  volume_total: number
  priority: number
  priority_label?: string | null
  rationale?: string | null
  coverage?: string | null
}
interface TopicRun {
  id: string
  topic_count: number
  topics: TopicCard[] | null
  assessment: string | null
  plan: { assessment?: string; pillars?: { pillar: string; rationale?: string }[] } | null
  competitors: { domain: string; informational_keywords: number; sample: { keyword: string; volume: number | null }[] }[] | null
  cost_usd: number | null
  created_at: string
}
interface TopicResearch {
  enabled: boolean
  site: { source: string; topics: string[] }
  intents: string[]
  expansion_seeds: string[]
  anchors: string[]
  relevance?: { gate: string; floor?: number; scored?: number; kept?: number; dropped?: number }
}
interface ClusterSummary {
  label: string
  keyword_count: number
  total_volume: number
}
interface HistoryResponse {
  enabled: boolean
  budget_remaining: number
  runs: RunSummary[]
}
interface SerpCompetitor {
  domain: string
  appearances: number
  best_position: number | null
  seeds: string[]
  sample_title: string | null
  sample_url: string | null
  aio_cited: boolean
  is_client: boolean
}
interface SerpIntel {
  enabled: boolean
  seeds_analyzed: string[]
  competitors: SerpCompetitor[]
  aio: { seeds_with_aio: number; seeds_analyzed: number; sources: { domain: string; url: string | null; title: string | null; count: number }[] }
  paa: string[]
}
interface RunResponse {
  run: (RunSummary & { location_code: number | null; language_code: string | null; serp_intel: SerpIntel | null; topic_research: TopicResearch | null; blog_topics: BlogTopic[] | null }) | null
  keywords: ResearchKeyword[]
  clusters: ClusterSummary[]
  warnings?: string[]
}
interface ReportRow {
  id: string
  run_id: string
  title: string | null
  status: string
  drive_url: string | null
  created_at: string
}
const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits })

// The seed keyword for a Blog Writer run from a topic card: its highest-volume
// supporting keyword (the term the brief/outline is built on), falling back to
// the theme/title. Capped to the run keyword's 150-char limit.
function topicSeedKeyword(t: TopicCard): string {
  const kws = [...(t.supporting_keywords || [])].sort((a, b) => (b.volume || 0) - (a.volume || 0))
  const seed = kws[0]?.keyword || t.theme || t.title || ''
  return seed.slice(0, 150)
}

// The per-run editorial guidance threaded into the Writer — carries the topic's
// angle (title, buyer problem, intent/funnel), the questions to answer, and the
// remaining target keywords. The brief stays keyword-driven; the angle rides here.
function composeWriterNotes(t: TopicCard, seed: string): string {
  const lines: string[] = []
  if (t.title) lines.push(`Working title: ${t.title}`)
  const problem = t.problem
  if (problem) lines.push(`Angle / buyer problem: ${problem}`)
  const meta = [t.search_intent && `intent: ${t.search_intent}`, t.funnel_stage && `funnel stage: ${t.funnel_stage}`]
    .filter(Boolean).join(' · ')
  if (meta) lines.push(meta)
  const qs = (t.questions || []).slice(0, 6)
  if (qs.length) lines.push('Answer these reader questions:\n' + qs.map((q) => `- ${q}`).join('\n'))
  const others = (t.supporting_keywords || []).map((k) => k.keyword).filter((k) => k && k !== seed).slice(0, 8)
  if (others.length) lines.push(`Work in these related keywords naturally: ${others.join(', ')}`)
  lines.push(`Source: Topic Research plan${t.pillar ? ` (pillar: ${t.pillar})` : ''}. Write as an authoritative, buyer-focused blog post.`)
  return lines.join('\n')
}

export function KeywordResearch() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data: history } = useQuery<HistoryResponse>({
    queryKey: ['keyword-research', id],
    queryFn: () => api.get<HistoryResponse>(`/clients/${id}/keyword-research`),
    enabled: Boolean(id),
  })

  const [seeds, setSeeds] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [researchError, setResearchError] = useState<string | null>(null)
  const [activeCluster, setActiveCluster] = useState<string | null>(null)
  const [downloadErr, setDownloadErr] = useState<string | null>(null)
  const [onlyQuestions, setOnlyQuestions] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Selection is per-run — clear it when the run changes.
  useEffect(() => { setSelected(new Set()) }, [runId])

  // Open the newest run by default once history loads.
  const [pickedInitial, setPickedInitial] = useState(false)
  if (!pickedInitial && history?.runs?.length) {
    setPickedInitial(true)
    if (!runId) setRunId(history.runs[0].id)
  }

  const { data: runData, isFetching: loadingRun } = useQuery<RunResponse>({
    queryKey: ['keyword-research-run', id, runId],
    queryFn: () => api.get<RunResponse>(`/clients/${id}/keyword-research/runs/${runId}`),
    enabled: Boolean(id && runId),
  })

  // The keyword-research run is a background async_jobs job. Its id is persisted
  // (keyed by client), so navigating away and back reconnects to the in-flight
  // run and opens it when it lands — instead of losing tracking in useState.
  const researchJob = useResumableJob<{ run_id?: string } | null, undefined>({
    storageKey: `keyword-research:run:${id}`,
    poll: async (jobId) => {
      const st = await api.get<{ status: string; error?: string; result?: { run_id?: string } }>(
        `/clients/${id}/keyword-research/jobs/${jobId}`)
      return { status: st.status, result: st.result ?? null, error: st.error }
    },
    onComplete: (result) => {
      queryClient.invalidateQueries({ queryKey: ['keyword-research', id] })
      if (result?.run_id) { setRunId(result.run_id); setActiveCluster(null) }
    },
    onError: (err) => setResearchError(err === 'job_failed' ? '' : err),
    intervalMs: 2500,
  })

  const [suggested, setSuggested] = useState<string[] | null>(null)
  const suggest = useMutation({
    mutationFn: () =>
      api.get<{ seeds: string[]; grounded: boolean; source: string }>(
        `/clients/${id}/keyword-research/seed-suggestions`),
    onSuccess: (r) => setSuggested(r.seeds),
  })
  // Append a suggested seed to the textarea (one per line), skipping duplicates.
  const addSeed = (kw: string) => setSeeds((prev) => {
    const lines = prev.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
    if (lines.some((l) => l.toLowerCase() === kw.toLowerCase())) return prev
    return prev.trim() ? `${prev.trim()}\n${kw}` : kw
  })

  // --- Problem-first Topic Research (distinct from keyword expansion) ---
  const { data: topicData } = useQuery<{ runs: unknown[]; latest: TopicRun | null; budget_remaining: number }>({
    queryKey: ['topic-research', id],
    queryFn: () => api.get(`/clients/${id}/topic-research`),
    enabled: Boolean(id),
  })
  const [topicError, setTopicError] = useState(false)
  const [topicRan, setTopicRan] = useState(false)
  const topicJob = useResumableJob<unknown, undefined>({
    storageKey: `keyword-research:topics:${id}`,
    poll: async (jobId) => {
      const st = await api.get<{ status: string; error?: string }>(`/clients/${id}/topic-research/jobs/${jobId}`)
      return { status: st.status, error: st.error }
    },
    onComplete: () => {
      setTopicRan(true)
      queryClient.invalidateQueries({ queryKey: ['topic-research', id] })
    },
    onError: () => setTopicError(true),
  })
  const runTopics = () => {
    setTopicError(false)
    void topicJob.start(async () => {
      const r = await api.post<{ job_id: string }>(`/clients/${id}/topic-research`, { seeds })
      return r.job_id
    }, undefined)
  }
  const topicRunning = topicJob.running
  const topics = useMemo<TopicCard[]>(() => topicData?.latest?.topics ?? [], [topicData])
  const topicAssessment = topicData?.latest?.assessment ?? topicData?.latest?.plan?.assessment ?? null
  const [topicGapsOnly, setTopicGapsOnly] = useState(false)
  // "Write this post" — create a Blog Writer run seeded from a topic card.
  const [writeTopic, setWriteTopic] = useState<TopicCard | null>(null)
  const [writeKeyword, setWriteKeyword] = useState('')
  const [writeNotes, setWriteNotes] = useState('')
  const [writeError, setWriteError] = useState<string | null>(null)
  const [createdRunId, setCreatedRunId] = useState<string | null>(null)
  function openWrite(t: TopicCard) {
    const seed = topicSeedKeyword(t)
    setWriteTopic(t)
    setWriteKeyword(seed)
    setWriteNotes(composeWriterNotes(t, seed))
    setWriteError(null)
    setCreatedRunId(null)
  }
  const createDraft = useMutation({
    mutationFn: (body: { client_id: string; keyword: string; content_type: string; writer_notes?: string }) =>
      api.post<{ run_id: string; status: string }>('/runs', body),
    onSuccess: (resp) => {
      setCreatedRunId(resp.run_id)
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    },
    onError: (e: unknown) => {
      const detail = e instanceof Error ? e.message : ''
      setWriteError(
        detail === 'concurrency_limit' ? 'Too many drafts are generating right now (max 5). Try again shortly.'
        : detail === 'client_frozen' ? 'This client is frozen — content creation is paused.'
        : 'Could not create the draft. Please try again.')
    },
  })
  const topicCoveredCount = useMemo(() => topics.filter((t) => t.coverage === 'covered').length, [topics])
  // Group cards under their pillar (topical-authority structure), preserving the
  // priority order the backend already applied; optionally hide already-covered topics.
  const topicPillars = useMemo(() => {
    const groups: { pillar: string; cards: TopicCard[] }[] = []
    for (const c of topics) {
      if (topicGapsOnly && c.coverage === 'covered') continue
      const label = c.pillar ?? c.theme ?? 'Topics'
      let g = groups.find((x) => x.pillar === label)
      if (!g) { g = { pillar: label, cards: [] }; groups.push(g) }
      g.cards.push(c)
    }
    return groups
  }, [topics, topicGapsOnly])

  const clearAll = useMutation({
    mutationFn: () => api.delete<{ deleted: number }>(`/clients/${id}/keyword-research`),
    onSuccess: () => {
      setRunId(null)
      researchJob.reset()
      setActiveCluster(null)
      setPickedInitial(true) // don't auto-reopen a run after clearing
      queryClient.invalidateQueries({ queryKey: ['keyword-research', id] })
      queryClient.invalidateQueries({ queryKey: ['keyword-research-reports', id] })
    },
  })

  // Remove one seed (and the keywords it solely produced) from the open run.
  const removeSeed = useMutation({
    mutationFn: (seed: string) =>
      api.post<{ seeds: string[]; removed_keywords: number }>(
        `/clients/${id}/keyword-research/runs/${runId}/remove-seed`, { seed }),
    onSuccess: () => {
      setActiveCluster(null)
      queryClient.invalidateQueries({ queryKey: ['keyword-research-run', id, runId] })
      queryClient.invalidateQueries({ queryKey: ['keyword-research', id] })
    },
  })
  // Append every listed keyword to the seed box (dedup-aware) — used to promote
  // People Also Ask questions into seeds for a follow-up run.
  const addSeeds = (kws: string[]) => setSeeds((prev) => {
    const have = new Set(prev.split(/[\n,]+/).map((s) => s.trim().toLowerCase()).filter(Boolean))
    const fresh = kws.filter((k) => { const key = k.trim().toLowerCase(); if (have.has(key)) return false; have.add(key); return true })
    if (!fresh.length) return prev
    return prev.trim() ? `${prev.trim()}\n${fresh.join('\n')}` : fresh.join('\n')
  })

  const running = researchJob.running
  const budget = history?.budget_remaining ?? 0
  const keywords = useMemo(() => runData?.keywords ?? [], [runData])
  const clusters = useMemo(() => runData?.clusters ?? [], [runData])
  const serpIntel = runData?.run?.serp_intel ?? null
  const topicResearch = runData?.run?.topic_research ?? null

  const filtered = useMemo(() => {
    let ks = keywords
    if (activeCluster) ks = ks.filter((k) => (k.cluster_label ?? 'other') === activeCluster)
    if (onlyQuestions) ks = ks.filter((k) => k.is_question)
    return ks
  }, [keywords, activeCluster, onlyQuestions])

  // --- Selection + "Send to Content Scheduler" ---
  const allShownSelected = filtered.length > 0 && filtered.every((k) => selected.has(k.keyword))
  const toggleAllShown = () => setSelected((prev) => {
    const next = new Set(prev)
    if (allShownSelected) filtered.forEach((k) => next.delete(k.keyword))
    else filtered.forEach((k) => next.add(k.keyword))
    return next
  })
  const toggleOne = (kw: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(kw)) next.delete(kw); else next.add(kw)
    return next
  })
  // Send selected keywords to the SUITE Content Scheduler (not the Topic Fan-out).
  // They're persisted server-side as a per-client draft first, so they survive a
  // refresh / navigation and can't be lost before the batch is created; the
  // Content Scheduler seeds its form from that draft. The user picks the page type
  // + cadence there and clicks Create/Schedule to actually create the pages.
  const sendToScheduler = useMutation({
    mutationFn: (kws: string[]) =>
      api.post(`/clients/${id}/content-scheduler-draft`, { keywords: kws }),
    onSuccess: () => navigate(`/clients/${id}/content-scheduler`),
  })

  // --- Client-facing PDF report ---
  const { data: reportsData } = useQuery<{ reports: ReportRow[] }>({
    queryKey: ['keyword-research-reports', id],
    queryFn: () => api.get(`/clients/${id}/keyword-research/reports`),
    enabled: Boolean(id),
  })
  // The PDF report renders as a background job — the user can navigate away while
  // it builds (and gets a completion notification in the activity sidebar). The
  // in-flight report id persists per run, so returning reconnects and opens the
  // download when it lands.
  const [reportError, setReportError] = useState<string | null>(null)
  const reportJob = useResumableJob<{ download_url: string | null }, null>({
    storageKey: `keyword-research:report:${id}:${runId ?? 'none'}`,
    poll: async (reportId) => {
      const r = await api.get<{ status: string; download_url: string | null; error?: string | null }>(
        `/clients/${id}/keyword-research/reports/${reportId}`)
      return { status: r.status, result: { download_url: r.download_url }, error: r.error }
    },
    onComplete: (result) => {
      queryClient.invalidateQueries({ queryKey: ['keyword-research-reports', id] })
      if (result?.download_url) window.open(result.download_url, '_blank')
    },
    onError: (err) => setReportError(err === 'no_keywords'
      ? 'This run has no keywords to report on yet.' : 'Report failed.'),
  })
  const startReport = (rid: string) => {
    setReportError(null)
    void reportJob.start(async () => {
      const { report_id } = await api.post<{ report_id: string }>(
        `/clients/${id}/keyword-research/runs/${rid}/report`, {})
      return report_id
    }, null)
  }
  const genTopics = useMutation({
    mutationFn: (rid: string) =>
      api.post<{ topics: BlogTopic[]; generated: boolean; reason?: string }>(
        `/clients/${id}/keyword-research/runs/${rid}/blog-topics`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keyword-research-run', id, runId] }),
  })
  const blogTopics = useMemo<BlogTopic[]>(
    () => genTopics.data?.topics ?? runData?.run?.blog_topics ?? [],
    [genTopics.data, runData],
  )
  const runReports = useMemo(
    () => (reportsData?.reports ?? []).filter((r) => r.run_id === runId),
    [reportsData, runId],
  )
  const downloadReport = async (reportId: string) => {
    setDownloadErr(null)
    try {
      const { download_url } = await api.get<{ download_url: string }>(`/clients/${id}/keyword-research/reports/${reportId}/download`)
      if (download_url) window.open(download_url, '_blank')
      else setDownloadErr('No download link was returned for that report.')
    } catch (e) {
      console.error('keyword-research report download failed', e)
      setDownloadErr((e as Error)?.message ?? 'Report download failed — please try again.')
    }
  }

  const submit = () => {
    if (!seeds.trim()) return
    setResearchError(null)
    void researchJob.start(async () => {
      const r = await api.post<{ job_id: string; seeds: string[] }>(`/clients/${id}/keyword-research`, { seeds })
      return r.job_id
    }, undefined)
  }

  const exportCsv = () => {
    if (!filtered.length) return
    const header = ['keyword', 'cluster', 'volume', 'cpc_usd', 'competition_index', 'keyword_difficulty', 'search_intent', 'is_question', 'relevance_score', 'opportunity_score']
    const rows = filtered.map((k) => [
      k.keyword, k.cluster_label ?? '', k.volume ?? '', k.cpc_usd ?? '', k.competition_index ?? '',
      k.keyword_difficulty ?? '', k.search_intent ?? '', k.is_question ? 'yes' : 'no', k.relevance_score ?? '', k.opportunity_score ?? '',
    ])
    const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = `keyword-research.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 4px' }}>
        <Search size={22} color="#2563eb" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Keyword Research</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 20px' }}>
        Enter a seed keyword or two (one per line, or comma-separated) to discover the related keyword universe —
        with search volume, CPC, competition, difficulty and intent — auto-grouped into topic clusters.
        {' '}<span style={{ color: budget > 0 ? '#64748b' : '#dc2626' }}>Budget left today: {num(budget)} calls.</span>
      </p>

      {/* Seed input */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <textarea
          value={seeds}
          onChange={(e) => setSeeds(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
          placeholder={'emergency plumber\nblocked drain'}
          rows={2}
          style={{ ...inputStyle, flex: 1, minWidth: 260, resize: 'vertical', fontFamily: 'inherit' }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button style={primaryBtn} disabled={running || budget <= 0 || !seeds.trim()} onClick={submit}>
            <RefreshCw size={14} style={running ? { animation: 'spin 1s linear infinite' } : undefined} />
            {running ? 'Researching…' : 'Research keywords'}
          </button>
          <button
            style={ghostBtn}
            onClick={() => suggest.mutate()}
            disabled={suggest.isPending}
            title="Suggest seed topics from this client's business, services and location"
          >
            <Lightbulb size={14} /> {suggest.isPending ? 'Thinking…' : 'Suggest topics'}
          </button>
        </div>
      </div>

      {/* Seed suggestions */}
      {suggest.isError && <div style={errBox}>{(suggest.error as Error)?.message ?? 'Could not suggest topics.'}</div>}
      {suggested !== null && (
        suggested.length ? (
          <div style={{ ...warnBox, background: '#f0f9ff', color: '#0c4a6e', borderColor: '#bae6fd', flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, marginBottom: 8 }}>
              <Lightbulb size={14} /> Suggested topics to research — click to add a seed
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {suggested.map((s) => (
                <button key={s} style={suggestChip} onClick={() => addSeed(s)} title="Add to seeds">
                  <Plus size={12} /> {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div style={warnBox}>
            <HelpCircle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>No topic suggestions yet — add this client's website, GBP category, or business location on their Setup page, then try again.</span>
          </div>
        )
      )}
      {researchError !== null && (
        <div style={errBox}>Research failed{researchError ? `: ${researchError === 'budget_exceeded' ? ' daily budget reached' : ` ${researchError}`}` : ''}.</div>
      )}

      {/* Run history chips */}
      {(history?.runs?.length ?? 0) > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
          {history!.runs.map((r) => (
            <button
              key={r.id}
              onClick={() => { setRunId(r.id); setActiveCluster(null) }}
              style={{ ...chip, ...(runId === r.id ? chipActive : {}) }}
              title={`${r.keyword_count} keywords · ${new Date(r.created_at).toLocaleString()}`}
            >
              {(r.seeds ?? []).join(', ') || 'run'} · {num(r.keyword_count)}
            </button>
          ))}
          <button
            style={{ ...ghostBtn, height: 28, padding: '3px 10px', fontSize: 12, color: '#b91c1c', borderColor: '#fecaca' }}
            onClick={() => {
              if (window.confirm('Clear ALL keyword research runs for this client? This removes every saved run, its keywords, and its reports. This cannot be undone.')) {
                clearAll.mutate()
              }
            }}
            disabled={clearAll.isPending}
            title="Delete all research runs and start over"
          >
            <Trash2 size={13} /> {clearAll.isPending ? 'Clearing…' : 'Clear all'}
          </button>
        </div>
      )}
      {clearAll.isError && <div style={errBox}>{(clearAll.error as Error)?.message ?? 'Could not clear runs.'}</div>}

      {/* Problem-first Topic Research — buyer problems (ICP + your site) → real
          demand (People Also Ask + suggestions) + competitor topics. Distinct from
          keyword expansion below: this researches TOPICS, not seed variations. */}
      <div style={{ border: '1px solid #ddd6fe', borderRadius: 12, padding: '16px 18px', marginBottom: 20, background: '#faf9ff' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ ...intelHead, fontSize: 14 }}><Sparkles size={15} /> Topic Research <span style={{ fontSize: 10, fontWeight: 700, color: '#7c3aed', background: '#f3e8ff', borderRadius: 6, padding: '1px 6px', marginLeft: 4 }}>BETA</span></div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 3, maxWidth: 640 }}>
              Starts from your buyer's problems (ICP + your site's themes), validates each with real search demand (People Also Ask + suggestions), and mines competitor topics — not just variations of the seed.
            </div>
          </div>
          <button style={{ ...primaryBtn, background: '#7c3aed' }}
            onClick={runTopics} disabled={topicRunning}>
            <Sparkles size={14} /> {topicRunning ? 'Researching…' : topics.length ? 'Re-research topics' : 'Research topics'}
          </button>
        </div>
        {topicError && <div style={{ ...errBox, marginTop: 12, marginBottom: 0 }}>Couldn't start topic research — please try again.</div>}
        {topicRunning && <div style={{ fontSize: 12, color: '#7c3aed', marginTop: 12 }}>Researching buyer problems, real demand, and competitor topics… (~30s)</div>}
        {!topicRunning && topicAssessment && (
          <div style={{ fontSize: 12.5, color: '#0f172a', background: '#f3e8ff', border: '1px solid #e9d5ff', borderRadius: 8, padding: '10px 12px', marginTop: 12, lineHeight: 1.5 }}>
            <strong style={{ color: '#6d28d9' }}>Strategy:</strong> {topicAssessment}
          </div>
        )}
        {!topicRunning && topicCoveredCount > 0 && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569', marginTop: 12, cursor: 'pointer' }}>
            <input type="checkbox" checked={topicGapsOnly} onChange={(e) => setTopicGapsOnly(e.target.checked)} style={{ cursor: 'pointer' }} />
            Show gaps only <span style={{ color: '#94a3b8' }}>({topicCoveredCount} already covered on the client's content)</span>
          </label>
        )}
        {!topicRunning && topicPillars.map((group) => (
          <div key={group.pillar} style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#5b21b6', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 8 }}>{group.pillar}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 12 }}>
              {group.cards.map((t, i) => (
                <div key={`${t.title}-${i}`} style={{ border: '1px solid #e9e5ff', borderRadius: 10, padding: '12px 14px', background: '#fff' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{t.title}</div>
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      {t.coverage === 'covered' && (
                        <span title="You likely already have a base for this on the client's content" style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', borderRadius: 6, padding: '1px 6px', background: '#e0f2fe', color: '#0369a1' }}>covered</span>
                      )}
                      {t.priority_label && (
                        <span style={{ fontSize: 10, fontWeight: 700, textTransform: 'uppercase', borderRadius: 6, padding: '1px 6px',
                          background: t.priority_label === 'high' ? '#dcfce7' : t.priority_label === 'low' ? '#f1f5f9' : '#fef9c3',
                          color: t.priority_label === 'high' ? '#15803d' : t.priority_label === 'low' ? '#64748b' : '#a16207' }}>{t.priority_label}</span>
                      )}
                    </div>
                  </div>
                  {(t.search_intent || t.funnel_stage) && (
                    <div style={{ display: 'flex', gap: 6, margin: '4px 0' }}>
                      {t.search_intent && <span style={{ fontSize: 10, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '1px 6px' }}>{t.search_intent}</span>}
                      {t.funnel_stage && <span style={{ fontSize: 10, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '1px 6px' }}>{t.funnel_stage}</span>}
                    </div>
                  )}
                  {t.problem && <div style={{ fontSize: 12, color: '#475569', margin: '4px 0 8px' }}>{t.problem}</div>}
                  {t.supporting_keywords.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', marginBottom: 3 }}>Keywords{t.volume_total ? ` (${num(t.volume_total)} vol)` : ''}</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {t.supporting_keywords.slice(0, 8).map((k) => (
                          <span key={k.keyword} style={{ padding: '2px 8px', background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe', borderRadius: 999, fontSize: 11 }}>
                            {k.keyword}{k.volume ? ` · ${num(k.volume)}` : ''}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {t.questions.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', marginBottom: 3 }}>Questions people ask</div>
                      <ul style={{ margin: 0, paddingLeft: 15, display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {t.questions.slice(0, 5).map((q) => <li key={q} style={{ fontSize: 12, color: '#334155' }}>{q}</li>)}
                      </ul>
                    </div>
                  )}
                  {t.rationale && <div style={{ fontSize: 11, color: '#64748b', fontStyle: 'italic' }}>{t.rationale}</div>}
                  <button
                    onClick={() => openWrite(t)}
                    style={{ marginTop: 10, display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: '#6d28d9', background: '#f5f3ff', border: '1px solid #ddd6fe', borderRadius: 7, padding: '5px 10px', cursor: 'pointer' }}>
                    <FileText size={13} /> Write this post
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
        {!topicRunning && topicRan && topics.length === 0 && (
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 12 }}>No topics were generated — this client may need an ICP or site content on file for problem-first research.</div>
        )}
      </div>

      {!runId && !running && (
        <div style={emptyBox}>Enter a seed keyword above to run your first research.</div>
      )}

      {runId && (loadingRun ? (
        <div style={emptyBox}>Loading…</div>
      ) : !runData?.run ? (
        <div style={emptyBox}>{running ? 'Research in progress…' : 'No run found.'}</div>
      ) : (
        <>
          {/* Relevance / brand-seed advisories */}
          {(runData?.warnings?.length ?? 0) > 0 && (
            <div style={warnBox}>
              <HelpCircle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <div>
                {runData!.warnings!.map((w, i) => (
                  <div key={i} style={{ marginBottom: i < runData!.warnings!.length - 1 ? 4 : 0 }}>{w}</div>
                ))}
              </div>
            </div>
          )}

          {/* Seeds in this run — removable when the run has more than 2 seeds */}
          {(runData?.run?.seeds?.length ?? 0) > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
              <span style={{ fontSize: 12, color: '#94a3b8', marginRight: 2 }}>Seeds:</span>
              {(runData!.run!.seeds ?? []).map((s) => {
                const canRemove = (runData!.run!.seeds?.length ?? 0) > 2
                return (
                  <span key={s} style={seedChip}>
                    {s}
                    {canRemove && (
                      <button
                        style={seedRemoveBtn}
                        title={`Remove "${s}" and the keywords only it produced`}
                        disabled={removeSeed.isPending}
                        onClick={() => {
                          if (window.confirm(`Remove seed "${s}" and the keywords only it produced from this run?`)) {
                            removeSeed.mutate(s)
                          }
                        }}
                      >×</button>
                    )}
                  </span>
                )
              })}
              {(runData!.run!.seeds?.length ?? 0) > 2 && (
                <span style={{ fontSize: 11, color: '#cbd5e1' }}>· click × to drop a seed (keeps ≥2)</span>
              )}
            </div>
          )}
          {removeSeed.isError && <div style={errBox}>{((removeSeed.error as Error)?.message === 'min_two_seeds') ? 'A run must keep at least two seeds.' : (removeSeed.error as Error)?.message ?? 'Could not remove that seed.'}</div>}

          {/* Client-grounded topical research: the intents we fanned out + the
              client's own site topics that grounded relevance and broadened the run. */}
          {topicResearch?.enabled && ((topicResearch.intents?.length ?? 0) > 0 || (topicResearch.site?.topics?.length ?? 0) > 0) && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12, marginBottom: 16 }}>
              {topicResearch.intents.length > 0 && (
                <div style={intelCard}>
                  <div style={intelHead}><Sparkles size={14} /> Topics behind your seeds</div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>
                    Sub-intents we researched beyond the literal seed{topicResearch.expansion_seeds.length > 0 && ` · also researched ${topicResearch.expansion_seeds.length} extra seed${topicResearch.expansion_seeds.length === 1 ? '' : 's'}`}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {topicResearch.intents.map((t) => (
                      <span key={t} style={{ padding: '4px 10px', background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe', borderRadius: 999, fontSize: 12 }}>{t}</span>
                    ))}
                  </div>
                </div>
              )}
              {topicResearch.site.topics.length > 0 && (
                <div style={intelCard}>
                  <div style={intelHead}><FileText size={14} /> Topics on the client's site</div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>
                    From their {topicResearch.site.source === 'google_index' ? 'indexed pages' : 'sitemap'} — used to keep results relevant to the business
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {topicResearch.site.topics.slice(0, 30).map((t) => (
                      <span key={t} style={{ padding: '4px 10px', background: '#f8fafc', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 999, fontSize: 12 }}>{t}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Competitive intelligence + People Also Ask (SERP enrichment) */}
          {serpIntel?.enabled && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12, marginBottom: 16 }}>
              {/* Competitors */}
              {serpIntel.competitors.length > 0 && (
                <div style={intelCard}>
                  <div style={intelHead}><Trophy size={14} /> Top competitors in these SERPs</div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>
                    Domains ranking across {serpIntel.seeds_analyzed.length} analyzed seed{serpIntel.seeds_analyzed.length === 1 ? '' : 's'}
                    {serpIntel.aio.seeds_with_aio > 0 && ` · AI Overview on ${serpIntel.aio.seeds_with_aio}/${serpIntel.aio.seeds_analyzed}`}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {serpIntel.competitors.map((c) => (
                      <div key={c.domain} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '3px 0' }}>
                        <span style={{ width: 30, color: '#64748b', flexShrink: 0 }}>#{c.best_position ?? '—'}</span>
                        <a href={c.sample_url ?? `https://${c.domain}`} target="_blank" rel="noreferrer"
                          style={{ color: c.is_client ? '#059669' : '#0f172a', fontWeight: c.is_client ? 700 : 500, textDecoration: 'none', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={c.sample_title ?? c.domain}>
                          {c.domain}{c.is_client && ' (you)'}
                        </a>
                        {c.aio_cited && <Sparkles size={12} color="#7c3aed" aria-label="Cited in AI Overview" />}
                        <span style={{ color: '#94a3b8', flexShrink: 0 }} title={`Ranks for ${c.seeds.length} seed(s)`}>×{c.appearances}</span>
                      </div>
                    ))}
                  </div>
                  {serpIntel.competitors.some((c) => c.aio_cited) && (
                    <div style={{ fontSize: 10, color: '#a78bfa', marginTop: 6 }}><Sparkles size={9} /> = cited in Google's AI Overview</div>
                  )}
                </div>
              )}
              {/* People Also Ask */}
              {serpIntel.paa.length > 0 && (
                <div style={intelCard}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <div style={intelHead}><MessageCircleQuestion size={14} /> People Also Ask ({serpIntel.paa.length})</div>
                    <button style={{ ...linkBtn, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                      onClick={() => addSeeds(serpIntel.paa)} title="Add every question to the seed box for a follow-up run">
                      <Plus size={12} /> Add all as seeds
                    </button>
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 8 }}>
                    Questions Google shows for your seeds — also included in the keyword table below.
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 16, display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {serpIntel.paa.map((q) => (
                      <li key={q} style={{ fontSize: 12, color: '#334155' }}>
                        {q}
                        <button style={{ ...linkBtn, marginLeft: 8 }} onClick={() => addSeed(q)} title="Add as a seed">+ seed</button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Cluster rail */}
          {clusters.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>
                  {clusters.length} topic cluster{clusters.length === 1 ? '' : 's'} · {num(keywords.length)} keywords
                </span>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
                  <input type="checkbox" checked={onlyQuestions} onChange={(e) => setOnlyQuestions(e.target.checked)} />
                  <HelpCircle size={13} /> Questions only
                </label>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button style={{ ...clusterChip, ...(activeCluster === null ? clusterChipActive : {}) }} onClick={() => setActiveCluster(null)}>
                  All
                </button>
                {clusters.map((c) => (
                  <button
                    key={c.label}
                    style={{ ...clusterChip, ...(activeCluster === c.label ? clusterChipActive : {}) }}
                    onClick={() => setActiveCluster(c.label)}
                    title={`${num(c.total_volume)} total monthly searches`}
                  >
                    {c.label} <span style={{ opacity: 0.6 }}>({c.keyword_count})</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Blog topic ideas — buyer-fit keywords + ICP → post ideas for a writer */}
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: '14px 16px', marginBottom: 16, background: '#fbfaff' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
              <div style={intelHead}><Lightbulb size={14} /> Blog topic ideas</div>
              <button style={{ ...primaryBtn, height: 34, padding: '7px 14px', fontSize: 13 }}
                onClick={() => runId && genTopics.mutate(runId)} disabled={!keywords.length || genTopics.isPending}>
                <Lightbulb size={14} /> {genTopics.isPending ? 'Thinking…' : blogTopics.length ? 'Regenerate' : 'Generate blog topics'}
              </button>
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
              Post ideas built from the buyer-fit keywords + this client's ideal customer — ready to hand a writer.
            </div>
            {genTopics.isError && <div style={{ ...errBox, marginTop: 10, marginBottom: 0 }}>Couldn't generate topics — please try again.</div>}
            {!genTopics.isPending && genTopics.data && !blogTopics.length && (
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 10 }}>No topic ideas were generated for this run.</div>
            )}
            {blogTopics.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10, marginTop: 12 }}>
                {blogTopics.map((t, i) => (
                  <div key={`${t.title}-${i}`} style={{ border: '1px solid #e9e5ff', borderRadius: 8, padding: '10px 12px', background: '#fff' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>{t.title}</div>
                    {t.angle && <div style={{ fontSize: 12, color: '#475569', marginBottom: 6 }}>{t.angle}</div>}
                    {(t.target_keywords?.length ?? 0) > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {t.target_keywords!.slice(0, 6).map((k) => (
                          <span key={k} style={{ padding: '2px 8px', background: '#f5f3ff', color: '#6d28d9', border: '1px solid #ddd6fe', borderRadius: 999, fontSize: 11 }}>{k}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Keyword table */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              Showing {num(filtered.length)}{activeCluster ? ` in "${activeCluster}"` : ''}{onlyQuestions ? ' · questions' : ''}
            </span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button
                style={{ ...primaryBtn, height: 34, padding: '7px 14px', fontSize: 13, opacity: selected.size === 0 ? 0.5 : 1 }}
                onClick={() => sendToScheduler.mutate([...selected])}
                disabled={selected.size === 0 || sendToScheduler.isPending}
                title="Save these keywords to the Content Scheduler, ready to pick a page type and schedule"
              >
                <CalendarPlus size={14} />
                {sendToScheduler.isPending ? 'Sending…' : `Send${selected.size ? ` ${selected.size}` : ''} to Content Scheduler`}
              </button>
              <button style={ghostBtn} onClick={() => runId && startReport(runId)} disabled={!keywords.length || reportJob.running}>
                <FileText size={14} /> {reportJob.running ? 'Building… (you can leave)' : 'Client PDF report'}
              </button>
              <button style={ghostBtn} onClick={exportCsv} disabled={!filtered.length}>
                <Download size={14} /> Export CSV
              </button>
            </div>
          </div>
          {sendToScheduler.isError && <div style={errBox}>{(sendToScheduler.error as Error)?.message ?? 'Could not send to the Content Scheduler.'}</div>}
          {reportError && <div style={errBox}>{reportError}</div>}
          {downloadErr && <div style={errBox}>{downloadErr}</div>}
          {runReports.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {runReports.map((r) => (
                <span key={r.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 10px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#475569' }}>
                  <FileText size={12} /> {new Date(r.created_at).toLocaleDateString()}
                  <button style={linkBtn} onClick={() => downloadReport(r.id)}>Download</button>
                  {r.drive_url && <a href={r.drive_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb', textDecoration: 'none' }}>Drive</a>}
                </span>
              ))}
            </div>
          )}
          <div className="scroll-x" style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ ...th, width: 34, textAlign: 'center' }}>
                    <input type="checkbox" checked={allShownSelected} onChange={toggleAllShown}
                      title={allShownSelected ? 'Clear shown' : 'Select all shown'}
                      style={{ cursor: 'pointer' }} />
                  </th>
                  {['Keyword', 'Cluster', 'Volume', 'CPC', 'Comp', 'KD', 'Intent', 'Relevance', 'Opportunity'].map((h) => (
                    <th key={h} style={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((k, i) => (
                  <tr key={`${k.keyword}-${i}`} style={{ borderTop: '1px solid #f1f5f9', background: selected.has(k.keyword) ? '#f0f7ff' : undefined }}>
                    <td style={{ ...td, textAlign: 'center' }}>
                      <input type="checkbox" checked={selected.has(k.keyword)} onChange={() => toggleOne(k.keyword)} style={{ cursor: 'pointer' }} />
                    </td>
                    <td style={{ ...td, fontWeight: 500, color: '#0f172a' }}>
                      {k.keyword}
                      {k.is_question && <HelpCircle size={12} style={{ marginLeft: 6, color: '#94a3b8', verticalAlign: 'middle' }} />}
                    </td>
                    <td style={{ ...td, color: '#64748b' }}>{k.cluster_label ?? '—'}</td>
                    <td style={td}>{num(k.volume)}</td>
                    <td style={td}>{k.cpc_usd === null ? '—' : `$${k.cpc_usd.toFixed(2)}`}</td>
                    <td style={td}>{k.competition_index === null ? '—' : num(k.competition_index)}</td>
                    <td style={td}>{k.keyword_difficulty === null ? '—' : num(k.keyword_difficulty)}</td>
                    <td style={{ ...td, color: '#64748b' }}>{k.search_intent ?? '—'}</td>
                    <td style={td}>{k.relevance_score === null || k.relevance_score === undefined ? '—' : `${Math.round(k.relevance_score * 100)}%`}</td>
                    <td style={{ ...td, fontWeight: 600, color: '#0f172a' }}>{num(k.opportunity_score)}</td>
                  </tr>
                ))}
                {!filtered.length && (
                  <tr><td style={{ ...td, color: '#94a3b8' }} colSpan={10}>No keywords match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {runData.run.cost_usd ? (
            <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 12 }}>
              Run {new Date(runData.run.created_at).toLocaleString()} · cost ${runData.run.cost_usd.toFixed(2)}
            </p>
          ) : null}
        </>
      ))}

      {writeTopic && (
        <div onClick={() => !createDraft.isPending && setWriteTopic(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 16 }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{ background: '#fff', borderRadius: 12, maxWidth: 560, width: '100%', maxHeight: '85vh', overflow: 'auto', boxShadow: '0 20px 50px rgba(0,0,0,0.25)' }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: 8 }}>
              <FileText size={16} color="#6d28d9" />
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>Write this post</div>
            </div>
            <div style={{ padding: 20 }}>
              {createdRunId ? (
                <div>
                  <div style={{ fontSize: 14, color: '#0f172a', marginBottom: 6 }}>✅ Draft queued.</div>
                  <p style={{ fontSize: 13, color: '#475569', marginTop: 0 }}>
                    The Blog Writer is generating <strong>{writeKeyword}</strong>. It’ll appear in Runs when ready.
                  </p>
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                    <button onClick={() => navigate(`/runs/${createdRunId}`)}
                      style={{ fontSize: 13, fontWeight: 600, color: '#fff', background: '#6d28d9', border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer' }}>View the draft</button>
                    <button onClick={() => setWriteTopic(null)}
                      style={{ fontSize: 13, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', cursor: 'pointer' }}>Close</button>
                  </div>
                </div>
              ) : (
                <>
                  <p style={{ fontSize: 12.5, color: '#64748b', marginTop: 0 }}>
                    Creates a blog post in the Blog Writer for this client — seeded with the keyword below, with the topic’s angle as writer guidance.
                  </p>
                  <label style={{ display: 'block', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', margin: '12px 0 4px' }}>
                    Seed keyword <span style={{ textTransform: 'none', color: '#cbd5e1' }}>(drives the outline)</span>
                  </label>
                  {writeTopic.supporting_keywords.length > 1 ? (
                    <select value={writeKeyword} onChange={(e) => setWriteKeyword(e.target.value)}
                      style={{ width: '100%', fontSize: 13, padding: '8px 10px', border: '1px solid #cbd5e1', borderRadius: 8, background: '#fff' }}>
                      {writeTopic.supporting_keywords.map((k) => (
                        <option key={k.keyword} value={k.keyword}>{k.keyword}{k.volume ? ` · ${num(k.volume)} vol` : ''}</option>
                      ))}
                    </select>
                  ) : (
                    <input value={writeKeyword} onChange={(e) => setWriteKeyword(e.target.value)} maxLength={150}
                      style={{ width: '100%', fontSize: 13, padding: '8px 10px', border: '1px solid #cbd5e1', borderRadius: 8, boxSizing: 'border-box' }} />
                  )}
                  <label style={{ display: 'block', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', margin: '14px 0 4px' }}>Writer guidance (angle)</label>
                  <textarea value={writeNotes} onChange={(e) => setWriteNotes(e.target.value)} rows={9} maxLength={4000}
                    style={{ width: '100%', fontSize: 12.5, padding: '8px 10px', border: '1px solid #cbd5e1', borderRadius: 8, resize: 'vertical', fontFamily: 'inherit', boxSizing: 'border-box', lineHeight: 1.5 }} />
                  {writeError && <div style={{ fontSize: 12.5, color: '#b91c1c', marginTop: 8 }}>{writeError}</div>}
                  <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                    <button disabled={!writeKeyword.trim() || createDraft.isPending}
                      onClick={() => id && createDraft.mutate({ client_id: id, keyword: writeKeyword.trim().slice(0, 150), content_type: 'blog_post', writer_notes: writeNotes.trim() || undefined })}
                      style={{ fontSize: 13, fontWeight: 600, color: '#fff', background: '#6d28d9', border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer', opacity: (!writeKeyword.trim() || createDraft.isPending) ? 0.6 : 1 }}>
                      {createDraft.isPending ? 'Creating…' : 'Create draft'}
                    </button>
                    <button disabled={createDraft.isPending} onClick={() => setWriteTopic(null)}
                      style={{ fontSize: 13, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', cursor: 'pointer' }}>Cancel</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 16 }
const inputStyle: React.CSSProperties = { padding: '9px 12px', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 14, color: '#0f172a', outline: 'none' }
const primaryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer', height: 40 }
const ghostBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', background: '#fff', color: '#475569', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer' }
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', color: '#2563eb', fontSize: 12, cursor: 'pointer', padding: 0 }
const chip: React.CSSProperties = { padding: '5px 12px', background: '#f1f5f9', color: '#475569', border: '1px solid transparent', borderRadius: 999, fontSize: 12, cursor: 'pointer' }
const chipActive: React.CSSProperties = { background: '#dbeafe', color: '#1d4ed8', borderColor: '#93c5fd' }
const clusterChip: React.CSSProperties = { padding: '5px 12px', background: '#fff', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, cursor: 'pointer' }
const suggestChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, padding: '5px 10px', background: '#fff', color: '#0369a1', border: '1px solid #bae6fd', borderRadius: 999, fontSize: 12, fontWeight: 500, cursor: 'pointer' }
const seedChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px 4px 12px', background: '#eef2ff', color: '#3730a3', border: '1px solid #c7d2fe', borderRadius: 999, fontSize: 12, fontWeight: 500 }
const seedRemoveBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, marginLeft: 2, padding: 0, background: 'transparent', color: '#6366f1', border: 'none', borderRadius: 999, fontSize: 14, lineHeight: 1, cursor: 'pointer' }
const intelCard: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px', background: '#fff' }
const intelHead: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 4 }
const clusterChipActive: React.CSSProperties = { background: '#eff6ff', color: '#1d4ed8', borderColor: '#93c5fd', fontWeight: 600 }
const th: React.CSSProperties = { textAlign: 'left', padding: '9px 12px', background: '#f8fafc', color: '#475569', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 12px', color: '#334155' }
const emptyBox: React.CSSProperties = { padding: 40, textAlign: 'center', color: '#94a3b8', border: '1px dashed #e2e8f0', borderRadius: 8 }
const errBox: React.CSSProperties = { padding: '10px 14px', background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 16 }
const warnBox: React.CSSProperties = { display: 'flex', gap: 8, padding: '10px 14px', background: '#fffbeb', color: '#92400e', border: '1px solid #fde68a', borderRadius: 8, fontSize: 13, marginBottom: 16 }
