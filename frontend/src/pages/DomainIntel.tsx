import { useEffect, useMemo, useState } from 'react'
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

const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits })
const money = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`

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

  const [mode, setMode] = useState<'lookup' | 'gap'>('lookup')
  const [input, setInput] = useState('')
  const [role, setRole] = useState('competitor')
  const [selected, setSelected] = useState<string | null>(null)
  const [job, setJob] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'keywords'>('overview')
  const [gapJob, setGapJob] = useState<string | null>(null)

  // Prefill with the client's own domain, once.
  useEffect(() => {
    if (!input && client?.website_url) {
      try {
        setInput(new URL(client.website_url).hostname.replace(/^www\./, ''))
      } catch { /* ignore */ }
    }
  }, [client?.website_url]) // eslint-disable-line react-hooks/exhaustive-deps

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
  useEffect(() => {
    if (jobStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['domain-intel', id] })
      queryClient.invalidateQueries({ queryKey: ['domain-intel-overview', id, selected] })
      setJob(null)
    } else if (jobStatus?.status === 'failed') {
      setJob(null)
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
      setGapJob(null)
    } else if (gapJobStatus?.status === 'failed') {
      setGapJob(null)
    }
  }, [gapJobStatus?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  const gapRunning = Boolean(gapJob) && gapJobStatus?.status !== 'failed'
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

  const running = Boolean(job) && jobStatus?.status !== 'failed'
  const snap = overview?.snapshot
  const keywords = overview?.ranked_keywords ?? []
  const budget = history?.budget_remaining ?? 0

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

      {/* History chips */}
      {(history?.snapshots.length ?? 0) > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
          {history!.snapshots.map((s) => (
            <button
              key={s.id}
              onClick={() => { setSelected(s.target_domain); setInput(s.target_domain) }}
              style={{ ...chip, ...(selected === s.target_domain ? chipActive : {}) }}
            >
              {s.target_domain}
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
