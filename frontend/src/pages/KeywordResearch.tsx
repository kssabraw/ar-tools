import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, FileText, HelpCircle, RefreshCw, Search } from 'lucide-react'
import { api } from '../lib/api'
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
interface RunResponse {
  run: (RunSummary & { location_code: number | null; language_code: string | null }) | null
  keywords: ResearchKeyword[]
  clusters: ClusterSummary[]
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

export function KeywordResearch() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

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
  const [job, setJob] = useState<string | null>(null)
  const [activeCluster, setActiveCluster] = useState<string | null>(null)
  const [onlyQuestions, setOnlyQuestions] = useState(false)

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

  const research = useMutation({
    mutationFn: (raw: string) =>
      api.post<{ job_id: string; seeds: string[] }>(`/clients/${id}/keyword-research`, { seeds: raw }),
    onSuccess: (r) => setJob(r.job_id),
  })

  const { data: jobStatus } = useQuery<{ status: string; error?: string; result?: { run_id?: string } }>({
    queryKey: ['keyword-research-job', id, job],
    queryFn: () => api.get(`/clients/${id}/keyword-research/jobs/${job}`),
    enabled: Boolean(job),
    refetchInterval: (q) => (['complete', 'failed'].includes(q.state.data?.status ?? '') ? false : 2500),
  })
  useEffect(() => {
    if (jobStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['keyword-research', id] })
      if (jobStatus.result?.run_id) { setRunId(jobStatus.result.run_id); setActiveCluster(null) }
    }
  }, [jobStatus?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const running = Boolean(job) && !['complete', 'failed'].includes(jobStatus?.status ?? '')
  const budget = history?.budget_remaining ?? 0
  const keywords = useMemo(() => runData?.keywords ?? [], [runData])
  const clusters = useMemo(() => runData?.clusters ?? [], [runData])

  const filtered = useMemo(() => {
    let ks = keywords
    if (activeCluster) ks = ks.filter((k) => (k.cluster_label ?? 'other') === activeCluster)
    if (onlyQuestions) ks = ks.filter((k) => k.is_question)
    return ks
  }, [keywords, activeCluster, onlyQuestions])

  // --- Client-facing PDF report ---
  const { data: reportsData } = useQuery<{ reports: ReportRow[] }>({
    queryKey: ['keyword-research-reports', id],
    queryFn: () => api.get(`/clients/${id}/keyword-research/reports`),
    enabled: Boolean(id),
  })
  const genReport = useMutation({
    mutationFn: (rid: string) =>
      api.post<{ report_id: string; download_url: string | null; drive_url: string | null }>(
        `/clients/${id}/keyword-research/runs/${rid}/report`, {}),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['keyword-research-reports', id] })
      if (r.download_url) window.open(r.download_url, '_blank')
    },
  })
  const runReports = useMemo(
    () => (reportsData?.reports ?? []).filter((r) => r.run_id === runId),
    [reportsData, runId],
  )
  const downloadReport = async (reportId: string) => {
    try {
      const { download_url } = await api.get<{ download_url: string }>(`/clients/${id}/keyword-research/reports/${reportId}/download`)
      if (download_url) window.open(download_url, '_blank')
    } catch { /* ignore */ }
  }

  const submit = () => { if (seeds.trim()) research.mutate(seeds) }

  const exportCsv = () => {
    if (!filtered.length) return
    const header = ['keyword', 'cluster', 'volume', 'cpc_usd', 'competition_index', 'keyword_difficulty', 'search_intent', 'is_question', 'opportunity_score']
    const rows = filtered.map((k) => [
      k.keyword, k.cluster_label ?? '', k.volume ?? '', k.cpc_usd ?? '', k.competition_index ?? '',
      k.keyword_difficulty ?? '', k.search_intent ?? '', k.is_question ? 'yes' : 'no', k.opportunity_score ?? '',
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
        <button style={primaryBtn} disabled={running || research.isPending || budget <= 0 || !seeds.trim()} onClick={submit}>
          <RefreshCw size={14} style={running ? { animation: 'spin 1s linear infinite' } : undefined} />
          {running ? 'Researching…' : 'Research keywords'}
        </button>
      </div>
      {research.isError && <div style={errBox}>{(research.error as Error)?.message ?? 'Failed to start research.'}</div>}
      {jobStatus?.status === 'failed' && (
        <div style={errBox}>Research failed{jobStatus.error ? `: ${jobStatus.error === 'budget_exceeded' ? ' daily budget reached' : ` ${jobStatus.error}`}` : ''}.</div>
      )}

      {/* Run history chips */}
      {(history?.runs?.length ?? 0) > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
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
        </div>
      )}

      {!runId && !running && (
        <div style={emptyBox}>Enter a seed keyword above to run your first research.</div>
      )}

      {runId && (loadingRun ? (
        <div style={emptyBox}>Loading…</div>
      ) : !runData?.run ? (
        <div style={emptyBox}>{running ? 'Research in progress…' : 'No run found.'}</div>
      ) : (
        <>
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

          {/* Keyword table */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              Showing {num(filtered.length)}{activeCluster ? ` in "${activeCluster}"` : ''}{onlyQuestions ? ' · questions' : ''}
            </span>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={ghostBtn} onClick={() => runId && genReport.mutate(runId)} disabled={!keywords.length || genReport.isPending}>
                <FileText size={14} /> {genReport.isPending ? 'Building…' : 'Client PDF report'}
              </button>
              <button style={ghostBtn} onClick={exportCsv} disabled={!filtered.length}>
                <Download size={14} /> Export CSV
              </button>
            </div>
          </div>
          {genReport.isError && <div style={errBox}>{(genReport.error as Error)?.message ?? 'Report failed.'}</div>}
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
          <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr>
                  {['Keyword', 'Cluster', 'Volume', 'CPC', 'Comp', 'KD', 'Intent', 'Opportunity'].map((h) => (
                    <th key={h} style={th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((k, i) => (
                  <tr key={`${k.keyword}-${i}`} style={{ borderTop: '1px solid #f1f5f9' }}>
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
                    <td style={{ ...td, fontWeight: 600, color: '#0f172a' }}>{num(k.opportunity_score)}</td>
                  </tr>
                ))}
                {!filtered.length && (
                  <tr><td style={{ ...td, color: '#94a3b8' }} colSpan={8}>No keywords match this filter.</td></tr>
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
const clusterChipActive: React.CSSProperties = { background: '#eff6ff', color: '#1d4ed8', borderColor: '#93c5fd', fontWeight: 600 }
const th: React.CSSProperties = { textAlign: 'left', padding: '9px 12px', background: '#f8fafc', color: '#475569', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 12px', color: '#334155' }
const emptyBox: React.CSSProperties = { padding: 40, textAlign: 'center', color: '#94a3b8', border: '1px dashed #e2e8f0', borderRadius: 8 }
const errBox: React.CSSProperties = { padding: '10px 14px', background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 16 }
