import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Eye, Zap, AlertTriangle, Plus, Trash2, Check, CalendarClock, Sparkles, FileText, FileDown, Download,
} from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type { Client } from '../lib/types'
// Shared AI Visibility building blocks (LABS-style dashboard rebuild).
import { ENGINE_ORDER, engineMeta } from '../components/aivisibility/engines'
import {
  SOURCE_TYPE_LABELS,
  type CompResult, type Keyword, type Mention, type ScanStatus, type TrendBatch,
} from '../components/aivisibility/types'
import { Chip } from '../components/aivisibility/bits'
import { StatsRow } from '../components/aivisibility/StatsRow'
import { ScanDialog } from '../components/aivisibility/ScanDialog'
import { RecentScansMatrix } from '../components/aivisibility/RecentScansMatrix'
import { ScanResultCards } from '../components/aivisibility/ScanResultCards'
import { ScanDetailSheet } from '../components/aivisibility/ScanDetailSheet'
import { VisibilityTrendsChart } from '../components/aivisibility/VisibilityTrendsChart'
import { CompetitorTrendsChart } from '../components/aivisibility/CompetitorTrendsChart'
import { CompetitorComparisonCard } from '../components/aivisibility/CompetitorComparisonCard'
import { LeadValuationCard } from '../components/aivisibility/LeadValuationCard'
import { ExportReportDialog } from '../components/aivisibility/ExportReportDialog'
import '../components/aivisibility/animations.css'

// ── page-local types (shared data types live in components/aivisibility) ─────
interface Competitor { id: string; competitor_name: string; competitor_website: string | null; google_place_id: string | null; created_at: string | null }
interface ScanStart { job_id: string; scan_batch_id: string; status: string }
interface Schedule {
  cadence: string; day_of_week: number | null; day_of_month: number | null; hour_utc: number
  selected_engines: string[]; include_competitors: boolean; is_active: boolean
  next_run_at: string | null; last_run_at: string | null
}

type Tab = 'overview' | 'keywords' | 'competitors' | 'schedule'

export function AiVisibility() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [jobId, setJobId] = useState<string | null>(null)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })
  const { data: keywords = [] } = useQuery<Keyword[]>({
    queryKey: ['brand-keywords', clientId],
    queryFn: () => api.get<Keyword[]>(`/clients/${clientId}/brand/keywords`),
    enabled: Boolean(clientId),
  })
  const { data: competitors = [] } = useQuery<Competitor[]>({
    queryKey: ['brand-competitors', clientId],
    queryFn: () => api.get<Competitor[]>(`/clients/${clientId}/brand/competitors`),
    enabled: Boolean(clientId),
  })
  const { data: history = [] } = useQuery<Mention[]>({
    queryKey: ['brand-history', clientId],
    queryFn: () => api.get<Mention[]>(`/clients/${clientId}/brand/history?limit=500`),
    enabled: Boolean(clientId),
  })
  const { data: trends = [] } = useQuery<TrendBatch[]>({
    queryKey: ['brand-trends', clientId],
    queryFn: () => api.get<TrendBatch[]>(`/clients/${clientId}/brand/trends`),
    enabled: Boolean(clientId),
  })

  // Poll the active scan job; refresh results when it finishes.
  const { data: jobStatus } = useQuery<ScanStatus>({
    queryKey: ['brand-scan-job', clientId, jobId],
    queryFn: () => api.get<ScanStatus>(`/clients/${clientId}/brand/scan/${jobId}`),
    enabled: Boolean(clientId && jobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'complete' || s === 'failed' ? false : 3000
    },
  })
  // Refresh the matrix/trends once a scan reaches a terminal state.
  useEffect(() => {
    if (jobStatus?.status === 'complete' || jobStatus?.status === 'failed') {
      qc.invalidateQueries({ queryKey: ['brand-history', clientId] })
      qc.invalidateQueries({ queryKey: ['brand-trends', clientId] })
    }
  }, [jobStatus?.status, clientId, qc])
  const running = Boolean(jobId) && jobStatus?.status !== 'complete' && jobStatus?.status !== 'failed'

  const activeKeywords = keywords.filter(k => k.is_active)
  const runMut = useMutation({
    mutationFn: (body: { engines: string[]; include_competitors: boolean }) =>
      api.post<ScanStart>(`/clients/${clientId}/brand/scan`, body),
    onSuccess: (r) => setJobId(r.job_id),
  })

  // Latest result per keyword×engine → the current visibility matrix.
  const latestByCell = useMemo(() => {
    const m = new Map<string, Mention>()
    for (const row of history) {
      const key = `${row.keyword_id}::${row.engine}`
      if (!m.has(key)) m.set(key, row) // history is newest-first
    }
    return m
  }, [history])

  const latestBatch = trends.length ? trends[trends.length - 1] : null

  return (
    <div style={{ padding: 32, maxWidth: 1080 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Eye size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>AI Visibility</h1>
        {running && <span style={pill}>Scanning…</span>}
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px' }}>
        {client?.name ?? 'This client'} · does this brand show up when AI assistants answer your keywords? Tracks ChatGPT, Claude, Gemini, Perplexity &amp; Google AI Overviews.
      </p>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 20 }}>
        <TabButton active={tab === 'overview'} onClick={() => setTab('overview')} label="Overview" />
        <TabButton active={tab === 'keywords'} onClick={() => setTab('keywords')} label={`Keywords (${keywords.length})`} />
        <TabButton active={tab === 'competitors'} onClick={() => setTab('competitors')} label={`Competitors (${competitors.length})`} />
        <TabButton active={tab === 'schedule'} onClick={() => setTab('schedule')} label="Schedule" />
      </div>

      {tab === 'overview' && (
        <Overview
          clientId={clientId!}
          brandName={client?.name ?? 'This brand'}
          activeKeywords={activeKeywords}
          keywords={keywords}
          competitors={competitors}
          history={history}
          latestByCell={latestByCell}
          latestBatch={latestBatch}
          trends={trends}
          running={running}
          runPending={runMut.isPending}
          jobStatus={jobStatus}
          onRun={(engines, includeCompetitors) => runMut.mutate({ engines, include_competitors: includeCompetitors })}
          runError={runMut.isError ? (runMut.error as Error).message : null}
          onManageKeywords={() => setTab('keywords')}
          onManageCompetitors={() => setTab('competitors')}
        />
      )}
      {tab === 'keywords' && <Keywords clientId={clientId!} keywords={keywords} />}
      {tab === 'competitors' && <Competitors clientId={clientId!} competitors={competitors} />}
      {tab === 'schedule' && <ScheduleTab clientId={clientId!} />}
    </div>
  )
}

// ── Overview ─────────────────────────────────────────────────────────────────
function Overview(props: {
  clientId: string; brandName: string; activeKeywords: Keyword[]; keywords: Keyword[]; competitors: Competitor[]; history: Mention[]
  latestByCell: Map<string, Mention>
  latestBatch: TrendBatch | null; trends: TrendBatch[]; running: boolean; runPending: boolean
  jobStatus: ScanStatus | undefined
  onRun: (engines: string[], includeCompetitors: boolean) => void
  runError: string | null; onManageKeywords: () => void; onManageCompetitors: () => void
}) {
  const { clientId, brandName, activeKeywords, keywords, competitors, history, latestByCell, latestBatch, trends, running, runPending, jobStatus, onRun, runError, onManageKeywords, onManageCompetitors } = props
  const activeCount = activeKeywords.length
  const [diagnose, setDiagnose] = useState<{ m: Mention; keyword: string } | null>(null)
  const [scanOpen, setScanOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  // Page-level so the choice survives closing/reopening the scan dialog.
  const [includeCompetitors, setIncludeCompetitors] = useState(false)
  const keywordById = useMemo(() => new Map(keywords.map(k => [k.id, k.keyword])), [keywords])

  // LABS health score — computed server-side in the trends rollup (the single
  // source shared with the HTML report).
  const healthScore = latestBatch?.health_score ?? null
  const enginePcts = useMemo(() => {
    const out: Record<string, number | null> = {}
    for (const [engine, stat] of Object.entries(latestBatch?.engines ?? {})) out[engine] = stat.visibility_pct
    return out
  }, [latestBatch])

  // Latest batch's rows as LABS-style result cards (keyword order, then engine order).
  const latestBatchMentions = useMemo(() => {
    if (!latestBatch?.scan_batch_id) return []
    const kwOrder = new Map(activeKeywords.map((k, i) => [k.id, i]))
    const engOrder = new Map<string, number>(ENGINE_ORDER.map((e, i) => [e, i]))
    return history
      .filter(h => h.scan_batch_id === latestBatch.scan_batch_id)
      .sort((a, b) =>
        ((kwOrder.get(a.keyword_id ?? '') ?? 999) - (kwOrder.get(b.keyword_id ?? '') ?? 999))
        || ((engOrder.get(a.engine) ?? 99) - (engOrder.get(b.engine) ?? 99)))
  }, [history, latestBatch, activeKeywords])

  // Matrix view: the client's own brand, or a tracked competitor's mentions
  // (re-classified from the same answers, available only on competitor-included scans).
  const [view, setView] = useState<string>('brand')
  // A competitor removed (or never scanned) shouldn't leave the matrix stuck on it.
  const viewing = view !== 'brand' && competitors.some(c => c.competitor_name === view) ? view : 'brand'

  // Export the full scan history (every keyword×engine row over time) as CSV.
  // Engine values keep the labels earlier exports used ('Google AIO', not the
  // UI's shorter 'AI Overview') so appended/pivoted spreadsheets stay joinable.
  const CSV_ENGINE_LABELS: Record<string, string> = {
    google_ai_overview: 'Google AIO',
    google_ai_mode: 'Google AI Mode',
  }
  const exportHistoryCsv = () => {
    const headers = [
      'Scan date', 'Keyword', 'Engine', 'Brand mentioned', 'Mention type', 'Sentiment',
      'Confidence', 'Status', 'Citations', 'Competitors mentioned',
      'Position', 'Prominence', 'AIO mention kind', 'Your site cited', 'Discovered competitors',
    ]
    const rows = history.map(h => {
      const comps = Array.isArray(h.competitor_results) ? (h.competitor_results as CompResult[]) : []
      const mentioned = comps.filter(c => c?.found).map(c => c.name)
      const ra = h.response_analysis
      return [
        h.created_at ? new Date(h.created_at).toLocaleString() : '',
        keywordById.get(h.keyword_id ?? '') ?? '',
        CSV_ENGINE_LABELS[h.engine] ?? engineMeta(h.engine).label,
        h.mention_found == null ? '' : h.mention_found ? 'Yes' : 'No',
        h.mention_type ?? '',
        h.sentiment == null ? '' : h.sentiment.toFixed(2),
        h.confidence_score == null ? '' : `${Math.round(h.confidence_score * 100)}%`,
        h.status,
        (h.citations ?? []).length,
        mentioned.join('; '),
        ra?.position?.rank ?? '',
        ra?.prominence ?? '',
        ra?.aio ? ra.aio.mention_kind : '',
        ra?.sources?.client_cited ? 'Yes' : '',
        (ra?.discovered_competitors ?? []).map(b => b.name).join('; '),
      ]
    })
    downloadCsv(`ai-visibility-history-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, rows))
  }

  const [reportJob, setReportJob] = useState<string | null>(null)
  const reportMut = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${clientId}/brand/report`, {}),
    onSuccess: (r) => setReportJob(r.job_id),
  })
  const { data: report } = useQuery<{ status: string; doc_url: string | null; error: string | null }>({
    queryKey: ['brand-report-job', clientId, reportJob],
    queryFn: () => api.get(`/clients/${clientId}/brand/report/${reportJob}`),
    enabled: Boolean(reportJob),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'complete' || s === 'failed' ? false : 3000
    },
  })
  const reportRunning = Boolean(reportJob) && report?.status !== 'complete' && report?.status !== 'failed'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <button
          className={history.length === 0 && activeCount > 0 ? 'aiv-scan-pulse' : undefined}
          style={{ ...runBtn, opacity: activeCount === 0 ? 0.6 : 1 }}
          disabled={activeCount === 0}
          onClick={() => setScanOpen(true)}
        >
          <Zap size={15} /> {running ? 'Scanning…' : 'Run scan'}
        </button>
        {running && jobStatus && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{jobStatus.completed + jobStatus.failed}/{jobStatus.total || '…'} done</span>
        )}
        {activeCount === 0 && (
          <span style={{ fontSize: 12, color: '#b45309' }}>
            Add keywords first — <button onClick={onManageKeywords} style={linkBtn}>manage keywords</button>
          </span>
        )}
        {(history.length > 0 || latestBatch !== null) && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 0 }}>
            {latestBatch !== null && (
              <button style={miniBtn} onClick={() => setExportOpen(true)}>
                <FileDown size={13} /> Export report
              </button>
            )}
            {latestBatch !== null && (
              <button style={miniBtn} disabled={reportRunning} onClick={() => reportMut.mutate()} title="Publish a visibility report to the client's Drive folder">
                <FileText size={13} /> {reportRunning ? 'Generating…' : 'Google Doc'}
              </button>
            )}
            {history.length > 0 && (
              <button style={miniBtn} onClick={exportHistoryCsv}>
                <Download size={13} /> Export CSV
              </button>
            )}
          </div>
        )}
      </div>

      {runError && <Banner kind="error">{runError}</Banner>}
      {report?.status === 'complete' && report.doc_url && (
        <div style={{ ...card, marginBottom: 16, borderColor: '#bbf7d0', background: '#f0fdf4' }}>
          <span style={{ fontSize: 13, color: '#166534' }}>Report ready — </span>
          <a href={report.doc_url} target="_blank" rel="noreferrer" style={{ color: '#15803d', fontWeight: 600, fontSize: 13 }}>open the Google Doc</a>
        </div>
      )}
      {report?.status === 'failed' && <Banner kind="error">Report failed: {report.error ?? 'unknown_error'}</Banner>}
      {/* LABS-style stats row: health gauge, visibility share, keywords, engines */}
      <StatsRow
        healthScore={healthScore}
        visibilityPct={latestBatch?.visibility_pct ?? null}
        scansCount={latestBatch?.total ?? 0}
        activeKeywordCount={activeCount}
        enginePcts={enginePcts}
        onKeywordsClick={onManageKeywords}
      />

      {latestBatch === null ? (
        <EmptyState title="No visibility data yet" body="Run a scan to see whether this brand appears in each AI engine's answers for your tracked keywords." />
      ) : (
        <>
          {/* Trend charts: multi-engine visibility + competitor comparison */}
          {trends.length > 1 && (
            <div style={{ marginBottom: 22 }}>
              <VisibilityTrendsChart trends={trends} />
              <CompetitorTrendsChart
                trends={trends}
                competitorNames={competitors.map(c => c.competitor_name)}
              />
            </div>
          )}

          {/* Competitive comparison + lead valuation */}
          <CompetitorComparisonCard
            brandName={brandName}
            healthScore={healthScore}
            latestBatch={latestBatch}
            trends={trends}
            competitorNames={competitors.map(c => c.competitor_name)}
            onManageCompetitors={onManageCompetitors}
          />
          <LeadValuationCard clientId={clientId} activeKeywords={activeKeywords} latestByCell={latestByCell} />

          {/* Whose mentions the matrix shows: this brand, or a tracked competitor. */}
          {competitors.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#64748b' }}>Show visibility for</span>
              <select style={{ ...input, padding: '6px 10px' }} value={viewing} onChange={e => setView(e.target.value)}>
                <option value="brand">This brand</option>
                {competitors.map(c => <option key={c.id} value={c.competitor_name}>{c.competitor_name}</option>)}
              </select>
              {viewing !== 'brand' && (
                <span style={{ fontSize: 12, color: '#94a3b8' }}>from competitor-included scans</span>
              )}
            </div>
          )}

          {/* Visibility matrix: keyword × engine (LABS icon-badge rows) */}
          <RecentScansMatrix
            keywords={activeKeywords}
            latestByCell={latestByCell}
            viewing={viewing}
            onOpenCell={(m, keyword) => setDiagnose({ m, keyword })}
          />
          <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 10 }}>
            {viewing === 'brand'
              ? <>Tip: click any cell for the full breakdown — position, sources the AI trusted, competitor reasons, and (for not-found cells) why the brand is invisible. On Google columns, <span style={{ color: '#7c3aed' }}>🔗</span> = linked inline in the answer, <span style={{ color: '#94a3b8' }}>◦</span> = cited in the sources strip only.</>
              : <>Showing where <strong>{viewing}</strong> appears. A dimmed engine means that keyword×engine wasn't scanned with competitors included.</>}
          </p>

          {/* Latest scan results — LABS-style cards (brand view only; the cards show brand analysis) */}
          {viewing === 'brand' && latestBatchMentions.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 10 }}>
                Latest scan results
              </div>
              <ScanResultCards
                mentions={latestBatchMentions}
                keywordById={keywordById}
                onOpen={(m, keyword) => setDiagnose({ m, keyword })}
              />
            </div>
          )}

          <BatchInsights clientId={clientId} scanBatchId={latestBatch.scan_batch_id} />
        </>
      )}
      {diagnose && (
        <ScanDetailSheet clientId={clientId} mention={diagnose.m} keyword={diagnose.keyword} onClose={() => setDiagnose(null)} />
      )}
      {scanOpen && (
        <ScanDialog
          activeKeywordCount={activeCount}
          competitorCount={competitors.length}
          running={running}
          starting={runPending}
          startError={runError}
          jobStatus={jobStatus}
          includeCompetitors={includeCompetitors}
          onIncludeCompetitorsChange={setIncludeCompetitors}
          onRun={onRun}
          onClose={() => setScanOpen(false)}
        />
      )}
      {exportOpen && (
        <ExportReportDialog clientId={clientId} clientName={brandName} onClose={() => setExportOpen(false)} />
      )}
    </div>
  )
}
function BatchInsights({ clientId, scanBatchId }: { clientId: string; scanBatchId: string | null }) {
  const qc = useQueryClient()
  const { data } = useQuery<{
    consensus: { businesses: { name: string; engines: string[]; count: number; attributes: string[] }[]; engines_total: number }
    discovered_competitors: { name: string; engines: string[]; count: number; attributes: string[] }[]
    aio_mention_kinds: Record<string, number>
    source_types: Record<string, number>
  }>({
    queryKey: ['brand-scan-insights', clientId, scanBatchId],
    queryFn: () => api.get(`/clients/${clientId}/brand/scans/${scanBatchId}/insights`),
    enabled: Boolean(scanBatchId),
  })
  const trackMut = useMutation({
    mutationFn: (name: string) => api.post(`/clients/${clientId}/brand/competitors`, { competitor_name: name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['brand-competitors', clientId] }),
  })
  if (!data) return null
  const consensus = data.consensus?.businesses ?? []
  const discovered = data.discovered_competitors ?? []
  const sourceTypes = Object.entries(data.source_types ?? {}).sort((a, b) => b[1] - a[1])
  if (consensus.length === 0 && discovered.length === 0 && sourceTypes.length === 0) return null

  return (
    <div className="aiv-card-enter" style={{ ...card, marginTop: 20 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 12 }}>Latest scan — cross-engine insights</div>

      {discovered.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>Untracked competitors the AI surfaced</div>
          {discovered.slice(0, 10).map((b, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#334155', marginBottom: 4 }}>
              <span><strong>{b.name}</strong> <span style={{ color: '#94a3b8' }}>· {b.count} engine{b.count === 1 ? '' : 's'}</span>{b.attributes.length > 0 && <span style={{ color: '#64748b' }}> — {b.attributes.slice(0, 3).join(', ')}</span>}</span>
              <button style={{ ...miniBtn, padding: '2px 8px' }} disabled={trackMut.isPending} onClick={() => trackMut.mutate(b.name)}><Plus size={11} /> Track</button>
            </div>
          ))}
        </div>
      )}

      {consensus.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>Consensus winners (named across engines)</div>
          {consensus.slice(0, 8).map((b, i) => (
            <div key={i} style={{ fontSize: 12, color: '#334155', marginBottom: 3 }}>
              <strong>{b.name}</strong> <span style={{ color: '#94a3b8' }}>· {b.count}/{data.consensus.engines_total} engines</span>{b.attributes.length > 0 && <span style={{ color: '#64748b' }}> — {b.attributes.slice(0, 3).join(', ')}</span>}
            </div>
          ))}
        </div>
      )}

      {sourceTypes.length > 0 && (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>What kinds of sources the AIs trust here</div>
          <div>{sourceTypes.map(([t, n]) => <Chip key={t}>{SOURCE_TYPE_LABELS[t] ?? t}: {n}</Chip>)}</div>
        </div>
      )}
    </div>
  )
}

// ── Keywords tab ─────────────────────────────────────────────────────────────
function Keywords({ clientId, keywords }: { clientId: string; keywords: Keyword[] }) {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [suggested, setSuggested] = useState<string[] | null>(null)
  const invalidate = () => qc.invalidateQueries({ queryKey: ['brand-keywords', clientId] })
  const addMut = useMutation({ mutationFn: (keyword: string) => api.post(`/clients/${clientId}/brand/keywords`, { keyword }), onSuccess: () => { setText(''); invalidate() } })
  const toggleMut = useMutation({ mutationFn: (k: Keyword) => api.patch(`/clients/${clientId}/brand/keywords/${k.id}`, { is_active: !k.is_active }), onSuccess: invalidate })
  const delMut = useMutation({ mutationFn: (id: string) => api.delete(`/clients/${clientId}/brand/keywords/${id}`), onSuccess: invalidate })
  const suggestMut = useMutation({
    mutationFn: () => api.post<{ keywords: string[] }>(`/clients/${clientId}/brand/suggest-keywords`, {}),
    onSuccess: (r) => setSuggested(r.keywords),
  })
  const existing = new Set(keywords.map(k => k.keyword.toLowerCase()))
  const addSuggestion = async (kw: string) => {
    try { await addMut.mutateAsync(kw); setSuggested(s => (s ? s.filter(x => x !== kw) : s)) }
    catch { /* surfaced via addMut.isError banner */ }
  }

  return (
    <div>
      <AddRow placeholder="Add a keyword (e.g. emergency plumber sydney)" value={text} setValue={setText} onAdd={() => text.trim() && addMut.mutate(text.trim())} pending={addMut.isPending} />
      <div style={{ marginBottom: 16, marginTop: -6 }}>
        <button style={miniBtn} disabled={suggestMut.isPending} onClick={() => suggestMut.mutate()}>
          <Sparkles size={13} /> {suggestMut.isPending ? 'Thinking…' : 'Suggest AI queries'}
        </button>
      </div>
      {suggestMut.isError && <Banner kind="error">{(suggestMut.error as Error).message}</Banner>}
      {suggested && suggested.length > 0 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>Conversational AI queries from this client’s tracked keywords — click to add</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {suggested.map(kw => {
              const dupe = existing.has(kw.toLowerCase())
              return (
                <button key={kw} disabled={dupe || addMut.isPending} onClick={() => addSuggestion(kw)}
                  style={{ ...chip, opacity: dupe ? 0.45 : 1, cursor: dupe ? 'default' : 'pointer' }}>
                  {dupe ? <Check size={12} /> : <Plus size={12} />} {kw}
                </button>
              )
            })}
          </div>
        </div>
      )}
      {addMut.isError && <Banner kind="error">{(addMut.error as Error).message}</Banner>}
      {keywords.length === 0 ? (
        <EmptyState title="No keywords yet" body="Add the search queries you want to check this brand's AI visibility for." />
      ) : (
        <div style={tableWrap}>
          <table style={table}>
            <thead><tr><Th>Keyword</Th><Th>Status</Th><Th right>Actions</Th></tr></thead>
            <tbody>
              {keywords.map((k, i) => (
                <tr key={k.id} style={i % 2 ? rowAlt : undefined}>
                  <Td><strong>{k.keyword}</strong></Td>
                  <Td>{k.is_active ? <span style={badgeOn}>Active</span> : <span style={badgeOff}>Paused</span>}</Td>
                  <Td right>
                    <button style={miniBtn} onClick={() => toggleMut.mutate(k)}>{k.is_active ? 'Pause' : 'Activate'}</button>
                    <button style={{ ...miniBtn, color: '#b91c1c' }} onClick={() => delMut.mutate(k.id)}><Trash2 size={13} /></button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Competitors tab ──────────────────────────────────────────────────────────
function Competitors({ clientId, competitors }: { clientId: string; competitors: Competitor[] }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const invalidate = () => qc.invalidateQueries({ queryKey: ['brand-competitors', clientId] })
  const addMut = useMutation({ mutationFn: (n: string) => api.post(`/clients/${clientId}/brand/competitors`, { competitor_name: n }), onSuccess: () => { setName(''); invalidate() } })
  const delMut = useMutation({ mutationFn: (id: string) => api.delete(`/clients/${clientId}/brand/competitors/${id}`), onSuccess: invalidate })

  return (
    <div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 12px' }}>
        Competitors are checked against the <em>same</em> AI answers as your brand (no extra cost) when you tick “Include competitors” on a scan.
      </p>
      <AddRow placeholder="Add a competitor name" value={name} setValue={setName} onAdd={() => name.trim() && addMut.mutate(name.trim())} pending={addMut.isPending} />
      {addMut.isError && <Banner kind="error">{(addMut.error as Error).message}</Banner>}
      {competitors.length === 0 ? (
        <EmptyState title="No competitors yet" body="Add rival brands to compare their AI visibility against this client's." />
      ) : (
        <div style={tableWrap}>
          <table style={table}>
            <thead><tr><Th>Competitor</Th><Th right>Actions</Th></tr></thead>
            <tbody>
              {competitors.map((c, i) => (
                <tr key={c.id} style={i % 2 ? rowAlt : undefined}>
                  <Td><strong>{c.competitor_name}</strong></Td>
                  <Td right><button style={{ ...miniBtn, color: '#b91c1c' }} onClick={() => delMut.mutate(c.id)}><Trash2 size={13} /></button></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Schedule tab ─────────────────────────────────────────────────────────────
const DOW = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function ScheduleTab({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const { data: sched } = useQuery<Schedule>({
    queryKey: ['brand-schedule', clientId],
    queryFn: () => api.get<Schedule>(`/clients/${clientId}/brand/schedule`),
    enabled: Boolean(clientId),
  })
  const [form, setForm] = useState<Schedule | null>(null)
  const s = form ?? sched
  const saveMut = useMutation({
    mutationFn: (body: Partial<Schedule>) => api.put<Schedule>(`/clients/${clientId}/brand/schedule`, body),
    onSuccess: (r) => { setForm(r); qc.invalidateQueries({ queryKey: ['brand-schedule', clientId] }) },
  })
  if (!s) return <EmptyState title="Loading…" body="" />

  const set = (patch: Partial<Schedule>) => setForm({ ...s, ...patch })
  return (
    <div style={{ ...card, maxWidth: 560 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <CalendarClock size={18} color="#6366f1" />
        <strong style={{ fontSize: 15, color: '#0f172a' }}>Recurring scan</strong>
      </div>

      <Field label="Frequency">
        <select style={input} value={s.cadence} onChange={e => set({ cadence: e.target.value })}>
          <option value="disabled">Off</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
      </Field>

      {s.cadence === 'weekly' && (
        <Field label="Day of week">
          <select style={input} value={s.day_of_week ?? 0} onChange={e => set({ day_of_week: Number(e.target.value) })}>
            {DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
        </Field>
      )}
      {s.cadence === 'monthly' && (
        <Field label="Day of month">
          <select style={input} value={s.day_of_month ?? 1} onChange={e => set({ day_of_month: Number(e.target.value) })}>
            {Array.from({ length: 28 }, (_, i) => i + 1).map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </Field>
      )}
      {s.cadence !== 'disabled' && (
        <>
          <Field label="Hour (UTC)">
            <select style={input} value={s.hour_utc} onChange={e => set({ hour_utc: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, i) => i).map(h => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
            </select>
          </Field>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#475569', margin: '8px 0 4px', cursor: 'pointer' }}>
            <input type="checkbox" checked={s.include_competitors} onChange={e => set({ include_competitors: e.target.checked })} /> Include competitors
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#475569', margin: '4px 0 8px', cursor: 'pointer' }}>
            <input type="checkbox" checked={s.is_active} onChange={e => set({ is_active: e.target.checked })} /> Schedule enabled
          </label>
        </>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
        <button style={runBtn} disabled={saveMut.isPending} onClick={() => saveMut.mutate({
          cadence: s.cadence, day_of_week: s.day_of_week, day_of_month: s.day_of_month,
          hour_utc: s.hour_utc, selected_engines: s.selected_engines, include_competitors: s.include_competitors, is_active: s.is_active,
        })}>
          {saveMut.isPending ? 'Saving…' : 'Save schedule'}
        </button>
        {sched?.next_run_at && sched.is_active && sched.cadence !== 'disabled' && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>Next run {new Date(sched.next_run_at).toLocaleString()}</span>
        )}
      </div>
      {saveMut.isError && <div style={{ marginTop: 10 }}><Banner kind="error">{(saveMut.error as Error).message}</Banner></div>}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 5 }}>{label}</label>
      {children}
    </div>
  )
}

function AddRow({ placeholder, value, setValue, onAdd, pending }: { placeholder: string; value: string; setValue: (v: string) => void; onAdd: () => void; pending: boolean }) {
  return (
    <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
      <input style={{ ...input, flex: 1 }} placeholder={placeholder} value={value} onChange={e => setValue(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') onAdd() }} />
      <button style={{ ...runBtn, opacity: pending ? 0.6 : 1 }} disabled={pending} onClick={onAdd}><Plus size={15} /> Add</button>
    </div>
  )
}

// ── shared bits ──────────────────────────────────────────────────────────────
function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return <button onClick={onClick} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '8px 14px', fontSize: 13, fontWeight: 600, color: active ? '#6366f1' : '#64748b', borderBottom: active ? '2px solid #6366f1' : '2px solid transparent' }}>{label}</button>
}
function EmptyState({ title, body }: { title: string; body: string }) {
  return <div style={{ textAlign: 'center', padding: '48px 24px', background: '#f8fafc', border: '1px dashed #e2e8f0', borderRadius: 12 }}>
    <div style={{ fontSize: 15, fontWeight: 600, color: '#475569', marginBottom: 6 }}>{title}</div>
    <div style={{ fontSize: 13, color: '#94a3b8', maxWidth: 460, margin: '0 auto' }}>{body}</div>
  </div>
}
function Banner({ kind, children }: { kind: 'error' | 'warn'; children: React.ReactNode }) {
  const color = kind === 'error' ? '#b91c1c' : '#b45309'
  const bg = kind === 'error' ? '#fef2f2' : '#fffbeb'
  const border = kind === 'error' ? '#fecaca' : '#fde68a'
  return <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', background: bg, border: `1px solid ${border}`, color, borderRadius: 10, padding: '12px 14px', fontSize: 13, marginBottom: 16 }}>
    <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} /> <span>{children}</span>
  </div>
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th style={{ textAlign: right ? 'right' : 'left', padding: '8px 12px', fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', borderBottom: '1px solid #e2e8f0' }}>{children}</th>
}
function Td({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <td style={{ textAlign: right ? 'right' : 'left', padding: '8px 12px', fontSize: 13, color: '#334155', borderBottom: '1px solid #f1f5f9' }}>{children}</td>
}

// ── styles ───────────────────────────────────────────────────────────────────
const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0 }
const pill: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#6366f1', background: '#eef2ff', borderRadius: 999, padding: '3px 10px' }
const runBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const miniBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, background: '#fff', color: '#475569', border: '1px solid #e2e8f0', borderRadius: 7, padding: '5px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer', marginLeft: 6 }
const linkBtn: React.CSSProperties = { background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', fontSize: 12, fontWeight: 600, padding: 0, textDecoration: 'underline' }
const input: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#0f172a', outline: 'none', background: '#fff' }
const tableWrap: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse' }
const rowAlt: React.CSSProperties = { background: '#fafbfc' }
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16 }
const badgeOn: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#15803d', background: '#dcfce7', borderRadius: 999, padding: '2px 8px' }
const badgeOff: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#64748b', background: '#f1f5f9', borderRadius: 999, padding: '2px 8px' }
const chip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, background: '#f8fafc', color: '#334155', border: '1px solid #e2e8f0', borderRadius: 999, padding: '5px 12px', fontSize: 12, fontWeight: 600 }
