import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Eye, RefreshCw, AlertTriangle, Plus, Trash2, Check, X, CalendarClock, Sparkles, FileText,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// ── engine taxonomy (mirrors services/brand_scan.ENGINE_ORDER) ───────────────
const ENGINE_ORDER = ['chatgpt', 'claude', 'gemini', 'perplexity', 'google_ai_overview', 'google_ai_mode'] as const
const ENGINE_LABELS: Record<string, string> = {
  chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', perplexity: 'Perplexity',
  google_ai_overview: 'Google AIO', google_ai_mode: 'Google AI Mode',
}

// ── types (mirror models/brand.py) ───────────────────────────────────────────
interface Keyword { id: string; keyword: string; category: string | null; is_active: boolean; created_at: string | null }
interface Competitor { id: string; competitor_name: string; competitor_website: string | null; google_place_id: string | null; created_at: string | null }
interface ScanStart { job_id: string; scan_batch_id: string; status: string }
interface ScanStatus { status: string; total: number; completed: number; failed: number; scan_batch_id: string | null; error: string | null }
interface Mention {
  id: string; keyword_id: string | null; scan_batch_id: string | null; engine: string; status: string
  mention_found: boolean | null; mention_type: string | null; sentiment: number | null
  confidence_score: number | null; citations: string[]; competitor_results: unknown[] | null
  reasoning: string | null; snippet: string | null; failure_reason: string | null; created_at: string | null
}
interface TrendBatch {
  scan_batch_id: string | null; created_at: string | null; total: number; found: number
  visibility_pct: number; engines: Record<string, { total: number; found: number; visibility_pct: number }>
}
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
  const [includeCompetitors, setIncludeCompetitors] = useState(false)

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
      if (s === 'complete' || s === 'failed') {
        qc.invalidateQueries({ queryKey: ['brand-history', clientId] })
        qc.invalidateQueries({ queryKey: ['brand-trends', clientId] })
        return false
      }
      return 3000
    },
  })
  const running = Boolean(jobId) && jobStatus?.status !== 'complete' && jobStatus?.status !== 'failed'

  const activeKeywords = keywords.filter(k => k.is_active)
  const runMut = useMutation({
    mutationFn: () => api.post<ScanStart>(`/clients/${clientId}/brand/scan`, { include_competitors: includeCompetitors }),
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
          activeCount={activeKeywords.length}
          keywords={keywords}
          latestByCell={latestByCell}
          latestBatch={latestBatch}
          trends={trends}
          running={running}
          jobStatus={jobStatus}
          includeCompetitors={includeCompetitors}
          setIncludeCompetitors={setIncludeCompetitors}
          onRun={() => runMut.mutate()}
          runError={runMut.isError ? (runMut.error as Error).message : null}
          onManageKeywords={() => setTab('keywords')}
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
  clientId: string; activeCount: number; keywords: Keyword[]; latestByCell: Map<string, Mention>
  latestBatch: TrendBatch | null; trends: TrendBatch[]; running: boolean
  jobStatus: ScanStatus | undefined; includeCompetitors: boolean
  setIncludeCompetitors: (v: boolean) => void; onRun: () => void
  runError: string | null; onManageKeywords: () => void
}) {
  const { clientId, activeCount, keywords, latestByCell, latestBatch, trends, running, jobStatus, includeCompetitors, setIncludeCompetitors, onRun, runError, onManageKeywords } = props
  const activeKeywords = keywords.filter(k => k.is_active)
  const [diagnose, setDiagnose] = useState<{ m: Mention; keyword: string } | null>(null)
  const keywordById = useMemo(() => new Map(keywords.map(k => [k.id, k.keyword])), [keywords])

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
        <button style={{ ...runBtn, opacity: running || activeCount === 0 ? 0.6 : 1 }} disabled={running || activeCount === 0} onClick={onRun}>
          <RefreshCw size={15} /> {running ? 'Scanning…' : 'Run scan now'}
        </button>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569', cursor: 'pointer' }}>
          <input type="checkbox" checked={includeCompetitors} onChange={e => setIncludeCompetitors(e.target.checked)} /> Include competitors
        </label>
        {running && jobStatus && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{jobStatus.completed + jobStatus.failed}/{jobStatus.total || '…'} done</span>
        )}
        {activeCount === 0 && (
          <span style={{ fontSize: 12, color: '#b45309' }}>
            Add keywords first — <button onClick={onManageKeywords} style={linkBtn}>manage keywords</button>
          </span>
        )}
        {latestBatch !== null && (
          <button style={{ ...miniBtn, marginLeft: 'auto' }} disabled={reportRunning} onClick={() => reportMut.mutate()}>
            <FileText size={13} /> {reportRunning ? 'Generating…' : 'Generate report'}
          </button>
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
      {latestBatch === null ? (
        <EmptyState title="No scans yet" body="Run a scan to see whether this brand appears in each AI engine's answers for your tracked keywords." />
      ) : (
        <>
          {/* Per-engine visibility from the latest scan */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 22 }}>
            {ENGINE_ORDER.map(e => {
              const stat = latestBatch.engines[e]
              return <EngineStat key={e} label={ENGINE_LABELS[e]} pct={stat ? stat.visibility_pct : null} />
            })}
            <EngineStat label="Overall" pct={latestBatch.visibility_pct} highlight />
          </div>

          {/* Trend sparkline */}
          {trends.length > 1 && (
            <div style={{ ...card, marginBottom: 22 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>Overall visibility over time</div>
              <TrendLine points={trends.map(t => t.visibility_pct)} />
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>{trends.length} scans · latest {latestBatch.visibility_pct}%</div>
            </div>
          )}

          {/* Visibility matrix: keyword × engine */}
          <div style={tableWrap}>
            <table style={table}>
              <thead>
                <tr>
                  <Th>Keyword</Th>
                  {ENGINE_ORDER.map(e => <Th key={e} center>{ENGINE_LABELS[e]}</Th>)}
                </tr>
              </thead>
              <tbody>
                {activeKeywords.map((k, i) => (
                  <tr key={k.id} style={i % 2 ? rowAlt : undefined}>
                    <Td><strong>{k.keyword}</strong></Td>
                    {ENGINE_ORDER.map(e => (
                      <MentionCell
                        key={e}
                        m={latestByCell.get(`${k.id}::${e}`)}
                        onDiagnose={(m) => setDiagnose({ m, keyword: keywordById.get(k.id) ?? k.keyword })}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 10 }}>
            Tip: click a <X size={11} color="#dc2626" style={{ verticalAlign: 'middle' }} /> cell to diagnose why the brand is invisible there.
          </p>
        </>
      )}
      {diagnose && (
        <DiagnoseModal clientId={clientId} mention={diagnose.m} keyword={diagnose.keyword} onClose={() => setDiagnose(null)} />
      )}
    </div>
  )
}

function DiagnoseModal({ clientId, mention, keyword, onClose }: { clientId: string; mention: Mention; keyword: string; onClose: () => void }) {
  const { data, isLoading, isError, error } = useQuery<{ diagnosis: string }>({
    queryKey: ['brand-diagnose', clientId, mention.id],
    queryFn: () => api.post<{ diagnosis: string }>(`/clients/${clientId}/brand/mentions/${mention.id}/diagnose`, {}),
    retry: false,
  })
  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <strong style={{ fontSize: 15, color: '#0f172a' }}>
            Why invisible · {ENGINE_LABELS[mention.engine] ?? mention.engine}
          </strong>
          <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }} onClick={onClose}><X size={18} /></button>
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>“{keyword}”</div>
        {isLoading && <div style={{ fontSize: 13, color: '#64748b' }}>Analyzing the competitors that did appear…</div>}
        {isError && <Banner kind="error">{(error as Error).message}</Banner>}
        {data && <div style={{ fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{data.diagnosis}</div>}
      </div>
    </div>
  )
}

function EngineStat({ label, pct, highlight }: { label: string; pct: number | null; highlight?: boolean }) {
  const color = pct === null ? '#94a3b8' : pct >= 60 ? '#15803d' : pct >= 25 ? '#b45309' : '#b91c1c'
  return (
    <div style={{ ...card, minWidth: 120, flex: '1 1 120px', borderColor: highlight ? '#c7d2fe' : '#e2e8f0', background: highlight ? '#eef2ff' : '#fff' }}>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{pct === null ? '—' : `${pct}%`}</div>
    </div>
  )
}

function MentionCell({ m, onDiagnose }: { m: Mention | undefined; onDiagnose?: (m: Mention) => void }) {
  let content: React.ReactNode = <span style={{ color: '#cbd5e1' }}>—</span>
  let title = 'Not scanned'
  let notFound = false
  if (m) {
    if (m.status === 'failed') { content = <span style={{ color: '#cbd5e1' }}>—</span>; title = m.failure_reason ?? 'failed' }
    else if (m.status === 'queued' || m.status === 'processing') { content = <span style={{ color: '#94a3b8' }}>…</span>; title = m.status }
    else if (m.mention_found) { content = <Check size={16} color="#15803d" />; title = `Found (${m.mention_type ?? 'direct'})` }
    else { content = <X size={15} color="#dc2626" />; title = 'Not found — click to diagnose'; notFound = true }
  }
  const clickable = notFound && onDiagnose && m
  return (
    <td
      style={{ textAlign: 'center', padding: '8px 12px', borderBottom: '1px solid #f1f5f9', cursor: clickable ? 'pointer' : 'default' }}
      title={title}
      onClick={clickable ? () => onDiagnose!(m!) : undefined}
    >
      {content}
    </td>
  )
}

function TrendLine({ points }: { points: number[] }) {
  const w = 480, h = 48, pad = 4
  if (points.length < 2) return null
  const max = 100, min = 0
  const dx = (w - pad * 2) / (points.length - 1)
  const y = (v: number) => h - pad - ((v - min) / (max - min)) * (h - pad * 2)
  const d = points.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad + i * dx} ${y(v)}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <path d={d} fill="none" stroke="#6366f1" strokeWidth={2} />
      {points.map((v, i) => <circle key={i} cx={pad + i * dx} cy={y(v)} r={2.5} fill="#6366f1" />)}
    </svg>
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
  const addSuggestion = async (kw: string) => { await addMut.mutateAsync(kw); setSuggested(s => (s ? s.filter(x => x !== kw) : s)) }

  return (
    <div>
      <AddRow placeholder="Add a keyword (e.g. emergency plumber sydney)" value={text} setValue={setText} onAdd={() => text.trim() && addMut.mutate(text.trim())} pending={addMut.isPending} />
      <div style={{ marginBottom: 16, marginTop: -6 }}>
        <button style={miniBtn} disabled={suggestMut.isPending} onClick={() => suggestMut.mutate()}>
          <Sparkles size={13} /> {suggestMut.isPending ? 'Thinking…' : 'Suggest keywords'}
        </button>
      </div>
      {suggestMut.isError && <Banner kind="error">{(suggestMut.error as Error).message}</Banner>}
      {suggested && suggested.length > 0 && (
        <div style={{ ...card, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>Suggested for this client — click to add</div>
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
function Th({ children, right, center }: { children: React.ReactNode; right?: boolean; center?: boolean }) {
  return <th style={{ textAlign: center ? 'center' : right ? 'right' : 'left', padding: '8px 12px', fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', borderBottom: '1px solid #e2e8f0' }}>{children}</th>
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
const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 50 }
const modal: React.CSSProperties = { background: '#fff', borderRadius: 14, padding: 22, maxWidth: 560, width: '100%', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(15,23,42,0.2)' }
