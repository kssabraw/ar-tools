import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, Radar, RefreshCw, Search, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Domain Intelligence (the "SEMrush clone") — Phase 1: Domain Overview +
// Ranked Keywords. Enter any domain → an async snapshot of its estimated
// traffic/authority + every keyword it ranks for.

interface Snapshot {
  id: string
  target_domain: string
  role: string
  organic_traffic_est: number | null
  ranked_keyword_count: number | null
  dr: number | null
  rd: number | null
  traffic_value_est: number | null
  cost_usd: number | null
  captured_at: string
}
interface RankedKeyword {
  keyword: string
  position: number | null
  url: string | null
  volume: number | null
  cpc_usd: number | null
  keyword_difficulty: number | null
  search_intent: string | null
  est_value: number | null
}
interface HistoryResponse {
  enabled: boolean
  budget_remaining: number
  snapshots: Snapshot[]
}
interface OverviewResponse {
  snapshot: Snapshot | null
  ranked_keywords: RankedKeyword[]
}
interface KeywordGap {
  keyword: string
  competitor_domain: string | null
  competitor_position: number | null
  client_position: number | null
  volume: number | null
  cpc_usd: number | null
  keyword_difficulty: number | null
  gap_type: string | null
  opportunity_score: number | null
}
interface KeywordGapResponse {
  gaps: KeywordGap[]
  captured_at: string | null
  count: number
}
interface CompetitorSuggestion {
  domain: string
  avg_position: number | null
  intersections: number | null
  organic_keywords: number | null
  organic_etv: number | null
  registered: boolean
}
interface DiscoverResponse {
  client_domain: string | null
  suggestions: CompetitorSuggestion[]
  note?: string
}

const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits })
const money = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`

// Estimated organic CTR by SERP position — mirrors the backend curve
// (services/keyword_market.py) so the per-page estimated traffic below stays
// consistent with the est_value the server already computed.
const CTR_BY_POSITION: Record<number, number> = {
  1: 0.281, 2: 0.152, 3: 0.106, 4: 0.073, 5: 0.053,
  6: 0.040, 7: 0.030, 8: 0.024, 9: 0.020, 10: 0.017,
}
function ctrForPosition(position: number | null): number {
  if (position === null || position === undefined) return 0
  const p = Math.round(position)
  if (CTR_BY_POSITION[p] !== undefined) return CTR_BY_POSITION[p]
  if (p <= 20) return 0.015
  if (p <= 50) return 0.005
  if (p <= 100) return 0.001
  return 0
}
// Estimated monthly organic clicks a keyword sends to its ranking page.
function estTraffic(volume: number | null, position: number | null): number {
  if (!volume) return 0
  return volume * ctrForPosition(position)
}

// DataForSEO's four main_intent buckets, plus "unknown" for missing intent.
const INTENTS = ['informational', 'commercial', 'transactional', 'navigational', 'unknown'] as const
type Intent = (typeof INTENTS)[number]
const INTENT_COLOR: Record<Intent, string> = {
  informational: '#2563eb', commercial: '#d97706', transactional: '#16a34a',
  navigational: '#7c3aed', unknown: '#94a3b8',
}
const INTENT_LABEL: Record<Intent, string> = {
  informational: 'Informational', commercial: 'Commercial', transactional: 'Transactional',
  navigational: 'Navigational', unknown: 'Unknown',
}
function normIntent(s: string | null | undefined): Intent {
  const v = (s ?? '').toLowerCase()
  return (INTENTS as readonly string[]).includes(v) ? (v as Intent) : 'unknown'
}

interface PageRow {
  url: string
  keywordCount: number
  estTraffic: number
  estValue: number
  bestPosition: number | null
  dominantIntent: Intent
  keywords: RankedKeyword[]
}

// Group ranked keywords by the page that ranks for them, summing estimated
// traffic/value and assigning each page a traffic-weighted dominant intent
// (keyword count breaks ties). Sorted most-traffic-first. Pure.
function buildPageBreakdown(keywords: RankedKeyword[]): PageRow[] {
  const byUrl = new Map<string, RankedKeyword[]>()
  for (const k of keywords) {
    const url = k.url || '(unknown URL)'
    const arr = byUrl.get(url)
    if (arr) arr.push(k)
    else byUrl.set(url, [k])
  }
  const pages: PageRow[] = []
  for (const [url, kws] of byUrl) {
    const trafficByIntent = new Map<Intent, number>()
    const countByIntent = new Map<Intent, number>()
    let estTrafficSum = 0
    let estValueSum = 0
    let bestPosition: number | null = null
    for (const k of kws) {
      const intent = normIntent(k.search_intent)
      const t = estTraffic(k.volume, k.position)
      estTrafficSum += t
      estValueSum += k.est_value ?? 0
      trafficByIntent.set(intent, (trafficByIntent.get(intent) ?? 0) + t)
      countByIntent.set(intent, (countByIntent.get(intent) ?? 0) + 1)
      if (k.position !== null && (bestPosition === null || k.position < bestPosition)) bestPosition = k.position
    }
    let dominantIntent: Intent = 'unknown'
    let bestT = -1
    let bestC = -1
    for (const intent of INTENTS) {
      const c = countByIntent.get(intent) ?? 0
      if (c === 0) continue
      const t = trafficByIntent.get(intent) ?? 0
      if (t > bestT || (t === bestT && c > bestC)) { bestT = t; bestC = c; dominantIntent = intent }
    }
    pages.push({
      url, keywordCount: kws.length, estTraffic: estTrafficSum, estValue: estValueSum,
      bestPosition, dominantIntent, keywords: kws,
    })
  }
  pages.sort((a, b) =>
    b.estTraffic - a.estTraffic || b.estValue - a.estValue || b.keywordCount - a.keywordCount)
  return pages
}

// Distribution of pages (by dominant intent) and keywords (by intent). Pure.
function buildIntentDist(keywords: RankedKeyword[], pages: PageRow[]) {
  const pageByIntent = new Map<Intent, number>()
  const kwByIntent = new Map<Intent, number>()
  for (const p of pages) pageByIntent.set(p.dominantIntent, (pageByIntent.get(p.dominantIntent) ?? 0) + 1)
  for (const k of keywords) {
    const i = normIntent(k.search_intent)
    kwByIntent.set(i, (kwByIntent.get(i) ?? 0) + 1)
  }
  return { pageByIntent, kwByIntent }
}

export function DomainIntel() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data: history } = useQuery<HistoryResponse>({
    queryKey: ['domain-intel', id],
    queryFn: () => api.get<HistoryResponse>(`/clients/${id}/domain-intel`),
    enabled: Boolean(id),
  })

  const [mode, setMode] = useState<'lookup' | 'gap' | 'discover'>('lookup')
  const [input, setInput] = useState('')
  const [role, setRole] = useState('competitor')
  const [selected, setSelected] = useState<string | null>(null)
  const [job, setJob] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'keywords' | 'pages'>('overview')
  const [expandedPages, setExpandedPages] = useState<Set<string>>(new Set())
  const [gapJob, setGapJob] = useState<string | null>(null)
  const [discovered, setDiscovered] = useState<DiscoverResponse | null>(null)
  const [added, setAdded] = useState<Record<string, boolean>>({})

  // Prefill with the client's own domain, once (adjust-during-render — the
  // client record arrives async, so useState initializers can't see it).
  const [prefilled, setPrefilled] = useState(false)
  if (!prefilled && client?.website_url) {
    setPrefilled(true)
    if (!input) {
      try {
        setInput(new URL(client.website_url).hostname.replace(/^www\./, ''))
      } catch { /* ignore */ }
    }
  }

  const { data: overview, isFetching: loadingOverview } = useQuery<OverviewResponse>({
    queryKey: ['domain-intel-overview', id, selected],
    queryFn: () => api.get<OverviewResponse>(`/clients/${id}/domain-intel/overview/${encodeURIComponent(selected!)}`),
    enabled: Boolean(id && selected),
  })

  const analyze = useMutation({
    mutationFn: (domain: string) =>
      api.post<{ job_id: string; target_domain: string }>(`/clients/${id}/domain-intel/overview`, {
        target_domain: domain, role,
      }),
    onSuccess: (r) => { setJob(r.job_id); setSelected(r.target_domain) },
  })

  const { data: jobStatus } = useQuery<{ status: string; error?: string }>({
    queryKey: ['domain-intel-job', id, job],
    queryFn: () => api.get(`/clients/${id}/domain-intel/jobs/${job}`),
    enabled: Boolean(job),
    refetchInterval: (q) => (['complete', 'failed'].includes(q.state.data?.status ?? '') ? false : 2500),
  })
  // On completion, refetch the views. The job id is deliberately NOT cleared on
  // a terminal status: clearing it changes the status-query key, which blanks
  // `jobStatus` and made failure banners vanish within one render. Polling
  // already stops via refetchInterval; a new run replaces the id.
  useEffect(() => {
    if (jobStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['domain-intel', id] })
      queryClient.invalidateQueries({ queryKey: ['domain-intel-overview', id, selected] })
    }
  }, [jobStatus?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // --- Keyword Gap (client vs registered competitors) ---
  const { data: gapData } = useQuery<KeywordGapResponse>({
    queryKey: ['domain-intel-gap', id],
    queryFn: () => api.get<KeywordGapResponse>(`/clients/${id}/domain-intel/keyword-gap`),
    enabled: Boolean(id && mode === 'gap'),
  })
  const runGap = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${id}/domain-intel/keyword-gap`, {}),
    onSuccess: (r) => setGapJob(r.job_id),
  })
  const { data: gapJobStatus } = useQuery<{ status: string; error?: string; result?: { note?: string } }>({
    queryKey: ['domain-intel-gap-job', id, gapJob],
    queryFn: () => api.get(`/clients/${id}/domain-intel/jobs/${gapJob}`),
    enabled: Boolean(gapJob),
    refetchInterval: (q) => (['complete', 'failed'].includes(q.state.data?.status ?? '') ? false : 2500),
  })
  useEffect(() => {
    if (gapJobStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['domain-intel-gap', id] })
    }
  }, [gapJobStatus?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  const gapRunning = Boolean(gapJob) && !['complete', 'failed'].includes(gapJobStatus?.status ?? '')
  const gaps = gapData?.gaps ?? []

  const exportGapCsv = () => {
    if (!gaps.length) return
    const header = ['keyword', 'gap_type', 'competitor_domain', 'competitor_position', 'client_position', 'volume', 'cpc_usd', 'keyword_difficulty', 'opportunity_score']
    const rows = gaps.map((g) => [
      g.keyword, g.gap_type ?? '', g.competitor_domain ?? '', g.competitor_position ?? '',
      g.client_position ?? '', g.volume ?? '', g.cpc_usd ?? '', g.keyword_difficulty ?? '', g.opportunity_score ?? '',
    ])
    const csv = [header, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = `keyword-gap.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  // --- Discover competitors (SERP overlap) ---
  const discover = useMutation({
    // POST — it's a paid call with side effects (budget), not an idempotent read.
    mutationFn: () => api.post<DiscoverResponse>(`/clients/${id}/domain-intel/discover`, {}),
    onSuccess: (d) => setDiscovered(d),
  })
  const addCompetitor = useMutation({
    mutationFn: (domain: string) => api.post(`/clients/${id}/competitors`, { name: domain, domain }),
    onSuccess: (_r, domain) => setAdded((m) => ({ ...m, [domain]: true })),
  })

  const running = Boolean(job) && !['complete', 'failed'].includes(jobStatus?.status ?? '')
  const snap = overview?.snapshot
  const keywords = useMemo(() => overview?.ranked_keywords ?? [], [overview])
  const budget = history?.budget_remaining ?? 0
  const analyzedDomains = useMemo(
    () => [...new Set((history?.snapshots ?? []).map((s) => s.target_domain))],
    [history],
  )

  const submit = () => {
    const v = input.trim()
    if (v) analyze.mutate(v)
  }

  const exportCsv = () => {
    if (!keywords.length || !snap) return
    const header = ['keyword', 'position', 'volume', 'cpc_usd', 'keyword_difficulty', 'search_intent', 'est_value', 'url']
    const rows = keywords.map((k) => [
      k.keyword, k.position ?? '', k.volume ?? '', k.cpc_usd ?? '', k.keyword_difficulty ?? '',
      k.search_intent ?? '', k.est_value ?? '', k.url ?? '',
    ])
    const csv = [header, ...rows]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = `${snap.target_domain}-ranked-keywords.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  const sortedKeywords = useMemo(
    () => [...keywords].sort((a, b) => (b.est_value ?? -1) - (a.est_value ?? -1)),
    [keywords],
  )
  const pageBreakdown = useMemo(() => buildPageBreakdown(keywords), [keywords])
  const intentDist = useMemo(() => buildIntentDist(keywords, pageBreakdown), [keywords, pageBreakdown])
  const togglePage = (url: string) =>
    setExpandedPages((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })

  const exportPagesCsv = () => {
    if (!pageBreakdown.length || !snap) return
    const header = ['url', 'keywords', 'est_monthly_traffic', 'est_traffic_value_usd', 'best_position', 'dominant_intent']
    const rows = pageBreakdown.map((p) => [
      p.url, p.keywordCount, Math.round(p.estTraffic), Math.round(p.estValue),
      p.bestPosition ?? '', p.dominantIntent,
    ])
    const csv = [header, ...rows]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a')
    a.href = url; a.download = `${snap.target_domain}-pages.csv`; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 4px' }}>
        <Radar size={22} color="#2563eb" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Domain Intelligence</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 20px' }}>
        Enter any domain to estimate its organic traffic, authority, and every keyword it ranks for.
        {' '}<span style={{ color: budget > 0 ? '#64748b' : '#dc2626' }}>Budget left today: {num(budget)} calls.</span>
      </p>

      {/* Mode toggle */}
      <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', padding: 3, borderRadius: 8, marginBottom: 20 }}>
        <button style={mode === 'lookup' ? segActive : segBtn} onClick={() => setMode('lookup')}>Domain lookup</button>
        <button style={mode === 'gap' ? segActive : segBtn} onClick={() => setMode('gap')}>Keyword gap</button>
        <button style={mode === 'discover' ? segActive : segBtn} onClick={() => setMode('discover')}>Discover</button>
      </div>

      {mode === 'gap' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <p style={{ color: '#64748b', fontSize: 13, margin: 0, maxWidth: 620 }}>
              Keywords your registered competitors rank for that {client?.name ?? 'this client'} doesn't — or ranks poorly for. Add competitors in Competitive Intel first.
              {gapData?.captured_at ? ` Last run ${new Date(gapData.captured_at).toLocaleString()}.` : ''}
            </p>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={ghostBtn} onClick={exportGapCsv} disabled={!gaps.length}><Download size={14} /> Export CSV</button>
              <button style={primaryBtn} disabled={gapRunning || runGap.isPending || budget <= 0} onClick={() => runGap.mutate()}>
                <RefreshCw size={14} style={gapRunning ? { animation: 'spin 1s linear infinite' } : undefined} />
                {gapRunning ? 'Analyzing…' : 'Run gap analysis'}
              </button>
            </div>
          </div>
          {gapJobStatus?.status === 'failed' && <div style={errBox}>Gap analysis failed{gapJobStatus.error ? `: ${gapJobStatus.error}` : ''}.</div>}
          {gapJobStatus?.result?.note === 'no_competitors' && <div style={errBox}>No competitors registered — add some in Competitive Intel, then re-run.</div>}
          {!gaps.length && !gapRunning ? (
            <div style={emptyBox}>No keyword gaps yet — click Run gap analysis.</div>
          ) : (
            <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    {['Keyword', 'Gap', 'Competitor', 'Comp pos', 'Your pos', 'Volume', 'CPC', 'KD', 'Opportunity'].map((h) => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {gaps.map((g, i) => (
                    <tr key={`${g.keyword}-${i}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                      <td style={{ ...td, fontWeight: 500, color: '#0f172a' }}>{g.keyword}</td>
                      <td style={td}><span style={g.gap_type === 'missing' ? badgeMissing : badgeWeak}>{g.gap_type ?? '—'}</span></td>
                      <td style={{ ...td, color: '#64748b' }}>{g.competitor_domain ?? '—'}</td>
                      <td style={td}>{g.competitor_position ?? '—'}</td>
                      <td style={td}>{g.client_position ?? '—'}</td>
                      <td style={td}>{num(g.volume)}</td>
                      <td style={td}>{g.cpc_usd === null ? '—' : `$${g.cpc_usd.toFixed(2)}`}</td>
                      <td style={td}>{g.keyword_difficulty === null ? '—' : num(g.keyword_difficulty)}</td>
                      <td style={{ ...td, fontWeight: 600, color: '#0f172a' }}>{num(g.opportunity_score, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {mode === 'discover' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <p style={{ color: '#64748b', fontSize: 13, margin: 0, maxWidth: 620 }}>
              Domains that share the most search results with {client?.name ?? 'this client'} — candidate competitors. Add the relevant ones to the registry.
            </p>
            <button style={primaryBtn} disabled={discover.isPending || budget <= 0} onClick={() => discover.mutate()}>
              <RefreshCw size={14} style={discover.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
              {discover.isPending ? 'Finding…' : 'Find competitors'}
            </button>
          </div>
          {discover.isError && <div style={errBox}>{(discover.error as Error)?.message ?? 'Discovery failed.'}</div>}
          {discovered?.note && <div style={errBox}>Client website unknown — set it on the client first.</div>}
          {discovered && !discovered.note && (
            discovered.suggestions.length ? (
              <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr>{['Domain', 'Shared keywords', 'Avg pos', 'Organic keywords', ''].map((h) => <th key={h} style={th}>{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {discovered.suggestions.map((s) => {
                      const isAdded = s.registered || added[s.domain]
                      return (
                        <tr key={s.domain} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={{ ...td, fontWeight: 500, color: '#0f172a' }}>{s.domain}</td>
                          <td style={td}>{num(s.intersections)}</td>
                          <td style={td}>{s.avg_position === null ? '—' : num(s.avg_position, 1)}</td>
                          <td style={td}>{num(s.organic_keywords)}</td>
                          <td style={td}>
                            {isAdded
                              ? <span style={{ color: '#16a34a', fontSize: 12, fontWeight: 600 }}>Registered</span>
                              : <button style={ghostBtn} disabled={addCompetitor.isPending} onClick={() => addCompetitor.mutate(s.domain)}>Add</button>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : <div style={emptyBox}>No competitor suggestions returned.</div>
          )}
          {!discovered && <div style={emptyBox}>Click Find competitors to discover domains that overlap in search.</div>}
        </div>
      )}

      {mode === 'lookup' && (<>
      {/* Analyze bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: 1, minWidth: 260 }}>
          <Search size={15} style={{ position: 'absolute', left: 10, top: 11, color: '#94a3b8' }} />
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
            placeholder="competitor.com"
            style={{ ...inputStyle, paddingLeft: 30, width: '100%' }}
          />
        </div>
        <select value={role} onChange={(e) => setRole(e.target.value)} style={inputStyle}>
          <option value="competitor">Competitor</option>
          <option value="prospect">Prospect</option>
          <option value="client">Own site</option>
        </select>
        <button style={primaryBtn} disabled={running || analyze.isPending || budget <= 0} onClick={submit}>
          <RefreshCw size={14} style={running ? { animation: 'spin 1s linear infinite' } : undefined} />
          {running ? 'Analyzing…' : 'Analyze'}
        </button>
      </div>
      {analyze.isError && (
        <div style={errBox}>{(analyze.error as Error)?.message ?? 'Failed to start analysis.'}</div>
      )}
      {jobStatus?.status === 'failed' && (
        <div style={errBox}>Analysis failed{jobStatus.error ? `: ${jobStatus.error}` : ''}.</div>
      )}

      {/* History chips — snapshots are newest-first and retained per domain,
          so dedupe by domain to one chip each. */}
      {analyzedDomains.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
          {analyzedDomains.map((d) => (
            <button
              key={d}
              onClick={() => { setSelected(d); setInput(d) }}
              style={{ ...chip, ...(selected === d ? chipActive : {}) }}
            >
              {d}
            </button>
          ))}
        </div>
      )}

      {!selected && !running && (
        <div style={emptyBox}>Enter a domain above to run your first analysis.</div>
      )}

      {selected && (loadingOverview ? (
        <div style={emptyBox}>Loading…</div>
      ) : !snap ? (
        <div style={emptyBox}>{running ? 'Analysis in progress…' : 'No snapshot yet — click Analyze.'}</div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button style={tab === 'overview' ? tabActive : tabBtn} onClick={() => setTab('overview')}>Overview</button>
            <button style={tab === 'keywords' ? tabActive : tabBtn} onClick={() => setTab('keywords')}>
              Ranked Keywords ({num(keywords.length)})
            </button>
            <button style={tab === 'pages' ? tabActive : tabBtn} onClick={() => setTab('pages')}>
              Pages ({num(pageBreakdown.length)})
            </button>
          </div>

          {tab === 'overview' && (
            <div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                <Kpi label="Est. monthly traffic" value={num(snap.organic_traffic_est)} icon={<TrendingUp size={16} />} />
                <Kpi label="Keywords ranked" value={num(snap.ranked_keyword_count)} />
                <Kpi label="Domain Rating" value={snap.dr === null ? '—' : num(snap.dr, 1)} />
                <Kpi label="Referring domains" value={num(snap.rd)} />
                <Kpi label="Est. traffic value" value={money(snap.traffic_value_est)} />
              </div>
              <p style={{ color: '#94a3b8', fontSize: 12, marginTop: 14 }}>
                Snapshot {new Date(snap.captured_at).toLocaleString()} · role: {snap.role}
                {snap.cost_usd ? ` · cost $${snap.cost_usd.toFixed(2)}` : ''}
              </p>

              {/* Content mix — pages classified by their dominant search intent
                  (traffic-weighted), plus the keyword-level intent split. */}
              {keywords.length > 0 && (
                <div style={{ marginTop: 24 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', marginBottom: 4 }}>Content mix</div>
                  <p style={{ color: '#64748b', fontSize: 12, margin: '0 0 12px', maxWidth: 620 }}>
                    Pages grouped by their dominant search intent (weighted by estimated traffic). Shows whether the
                    site is built for informational, commercial, transactional or navigational queries.
                  </p>
                  <IntentBar title={`Pages (${pageBreakdown.length})`} counts={intentDist.pageByIntent} total={pageBreakdown.length} />
                  <div style={{ height: 12 }} />
                  <IntentBar title={`Keywords (${keywords.length})`} counts={intentDist.kwByIntent} total={keywords.length} />
                </div>
              )}
            </div>
          )}

          {tab === 'pages' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                <p style={{ color: '#64748b', fontSize: 13, margin: 0, maxWidth: 640 }}>
                  Which pages pull the traffic — ranked keywords grouped by the page that ranks, with estimated monthly
                  clicks (volume × CTR-at-position). Expand a page to see the keywords it ranks for.
                </p>
                <button style={ghostBtn} onClick={exportPagesCsv} disabled={!pageBreakdown.length}>
                  <Download size={14} /> Export CSV
                </button>
              </div>
              {!pageBreakdown.length ? (
                <div style={emptyBox}>No pages captured.</div>
              ) : (
                <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr>
                        {['Page', 'Keywords', 'Est. traffic/mo', 'Est. value', 'Best pos', 'Dominant intent'].map((h) => (
                          <th key={h} style={th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {pageBreakdown.map((p) => {
                        const open = expandedPages.has(p.url)
                        const hasUrl = p.url !== '(unknown URL)'
                        return (
                          <Fragment key={p.url}>
                            <tr style={{ borderTop: '1px solid #f1f5f9', cursor: 'pointer' }} onClick={() => togglePage(p.url)}>
                              <td style={{ ...td, fontWeight: 500, color: '#0f172a', maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                <span style={{ color: '#94a3b8', marginRight: 6 }}>{open ? '▾' : '▸'}</span>
                                {hasUrl
                                  ? <a href={p.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{ color: '#2563eb' }}>{p.url.replace(/^https?:\/\//, '')}</a>
                                  : <span style={{ color: '#94a3b8' }}>{p.url}</span>}
                              </td>
                              <td style={td}>{num(p.keywordCount)}</td>
                              <td style={{ ...td, fontWeight: 600, color: '#0f172a' }}>{num(Math.round(p.estTraffic))}</td>
                              <td style={td}>{money(p.estValue)}</td>
                              <td style={td}>{p.bestPosition ?? '—'}</td>
                              <td style={td}><IntentBadge intent={p.dominantIntent} /></td>
                            </tr>
                            {open && (
                              <tr>
                                <td colSpan={6} style={{ padding: 0, background: '#f8fafc', borderTop: '1px solid #f1f5f9' }}>
                                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                                    <thead>
                                      <tr>{['Keyword', 'Pos', 'Volume', 'Est. traffic/mo', 'Intent'].map((h) => <th key={h} style={{ ...th, background: '#eef2f7' }}>{h}</th>)}</tr>
                                    </thead>
                                    <tbody>
                                      {[...p.keywords].sort((a, b) => estTraffic(b.volume, b.position) - estTraffic(a.volume, a.position)).map((k, i) => (
                                        <tr key={`${k.keyword}-${i}`} style={{ borderTop: '1px solid #e2e8f0' }}>
                                          <td style={{ ...td, color: '#0f172a' }}>{k.keyword}</td>
                                          <td style={td}>{k.position ?? '—'}</td>
                                          <td style={td}>{num(k.volume)}</td>
                                          <td style={td}>{num(Math.round(estTraffic(k.volume, k.position)))}</td>
                                          <td style={td}><IntentBadge intent={normIntent(k.search_intent)} /></td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {tab === 'keywords' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                <button style={ghostBtn} onClick={exportCsv} disabled={!keywords.length}>
                  <Download size={14} /> Export CSV
                </button>
              </div>
              <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr>
                      {['Keyword', 'Pos', 'Volume', 'CPC', 'KD', 'Intent', 'Est. value', 'URL'].map((h) => (
                        <th key={h} style={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedKeywords.map((k, i) => (
                      <tr key={`${k.keyword}-${i}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                        <td style={{ ...td, fontWeight: 500, color: '#0f172a' }}>{k.keyword}</td>
                        <td style={td}>{k.position ?? '—'}</td>
                        <td style={td}>{num(k.volume)}</td>
                        <td style={td}>{k.cpc_usd === null ? '—' : `$${k.cpc_usd.toFixed(2)}`}</td>
                        <td style={td}>{k.keyword_difficulty === null ? '—' : num(k.keyword_difficulty)}</td>
                        <td style={{ ...td, color: '#64748b' }}>{k.search_intent ?? '—'}</td>
                        <td style={td}>{money(k.est_value)}</td>
                        <td style={{ ...td, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {k.url ? <a href={k.url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>{k.url.replace(/^https?:\/\//, '')}</a> : '—'}
                        </td>
                      </tr>
                    ))}
                    {!keywords.length && (
                      <tr><td style={{ ...td, color: '#94a3b8' }} colSpan={8}>No ranked keywords captured.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ))}
      </>)}
    </div>
  )
}

function Kpi({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: '12px 14px', background: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 12 }}>{icon}{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>{value}</div>
    </div>
  )
}

function IntentBadge({ intent }: { intent: Intent }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#334155',
    }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: INTENT_COLOR[intent], display: 'inline-block' }} />
      {INTENT_LABEL[intent]}
    </span>
  )
}

// A horizontal stacked bar of intent proportions + a legend with counts.
function IntentBar({ title, counts, total }: { title: string; counts: Map<Intent, number>; total: number }) {
  const present = INTENTS.filter((i) => (counts.get(i) ?? 0) > 0)
  return (
    <div>
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'flex', width: '100%', height: 14, borderRadius: 7, overflow: 'hidden', background: '#f1f5f9' }}>
        {present.map((i) => {
          const c = counts.get(i) ?? 0
          const pct = total > 0 ? (c / total) * 100 : 0
          return <div key={i} title={`${INTENT_LABEL[i]}: ${c} (${pct.toFixed(0)}%)`} style={{ width: `${pct}%`, background: INTENT_COLOR[i] }} />
        })}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, marginTop: 8 }}>
        {present.map((i) => {
          const c = counts.get(i) ?? 0
          const pct = total > 0 ? (c / total) * 100 : 0
          return (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#334155' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: INTENT_COLOR[i] }} />
              {INTENT_LABEL[i]} <strong style={{ color: '#0f172a' }}>{c}</strong>
              <span style={{ color: '#94a3b8' }}>({pct.toFixed(0)}%)</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}

const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 16 }
const inputStyle: React.CSSProperties = { padding: '9px 12px', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 14, color: '#0f172a', outline: 'none' }
const primaryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', background: '#fff', color: '#475569', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer' }
const chip: React.CSSProperties = { padding: '5px 12px', background: '#f1f5f9', color: '#475569', border: '1px solid transparent', borderRadius: 999, fontSize: 12, cursor: 'pointer' }
const chipActive: React.CSSProperties = { background: '#dbeafe', color: '#1d4ed8', borderColor: '#93c5fd' }
const tabBtn: React.CSSProperties = { padding: '7px 14px', background: 'transparent', color: '#64748b', border: 'none', borderBottom: '2px solid transparent', fontSize: 14, fontWeight: 500, cursor: 'pointer' }
const tabActive: React.CSSProperties = { ...tabBtn, color: '#2563eb', borderBottom: '2px solid #2563eb' }
const th: React.CSSProperties = { textAlign: 'left', padding: '9px 12px', background: '#f8fafc', color: '#475569', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 12px', color: '#334155' }
const emptyBox: React.CSSProperties = { padding: 40, textAlign: 'center', color: '#94a3b8', border: '1px dashed #e2e8f0', borderRadius: 8 }
const segBtn: React.CSSProperties = { padding: '6px 14px', background: 'transparent', color: '#64748b', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer' }
const segActive: React.CSSProperties = { ...segBtn, background: '#fff', color: '#0f172a', boxShadow: '0 1px 2px rgba(0,0,0,0.06)' }
const badgeMissing: React.CSSProperties = { padding: '2px 8px', borderRadius: 999, background: '#fef2f2', color: '#b91c1c', fontSize: 11, fontWeight: 600 }
const badgeWeak: React.CSSProperties = { padding: '2px 8px', borderRadius: 999, background: '#fffbeb', color: '#b45309', fontSize: 11, fontWeight: 600 }
const errBox: React.CSSProperties = { padding: '10px 14px', background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 16 }
