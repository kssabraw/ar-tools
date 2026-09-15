import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, FileText, Flame, Search, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import { useResumableJob } from '../lib/useResumableJob'
import { toCsv, downloadCsv } from '../lib/csv'
import type { Client } from '../lib/types'

// --- types --------------------------------------------------------------------
interface TrendRunSummary {
  id: string
  seeds: string[]
  category_name: string | null
  trends_type: string
  rising_count: number
  qualified_count: number
  cost_usd: number | null
  created_at: string
}
interface HistoryResponse {
  enabled: boolean
  budget_remaining: number
  runs: TrendRunSummary[]
}
interface TrendKeyword {
  query: string
  bucket: string
  rising_value: number | null
  is_breakout: boolean
  volume: number | null
  cpc_usd: number | null
  keyword_difficulty: number | null
  search_intent: string | null
  is_question: boolean
  qualified: boolean
  trend_score: number | null
}
interface RunResponse {
  run: TrendRunSummary & { category_code: number | null; location_code: number | null }
  keywords: TrendKeyword[]
}
interface TrendsCategory { category_code: number; category_name: string; parent_code: number | null }

const TYPES = ['web', 'news', 'youtube', 'images', 'froogle'] as const

function velocityLabel(k: TrendKeyword): string {
  if (k.is_breakout) return 'Breakout'
  if (k.rising_value == null) return '—'
  return `+${Math.round(k.rising_value)}%`
}

// The seed keyword for a Blog Writer run from a rising query: the query itself
// (the term the brief/outline is built on). Capped to the run keyword's 150-char limit.
function trendSeedKeyword(k: TrendKeyword): string {
  return (k.query || '').slice(0, 150)
}

// The per-run editorial guidance threaded into the Writer — carries the trend's
// angle (rising/breakout velocity, intent, demand) so the post is framed around a
// search that is climbing now. The brief stays keyword-driven; the angle rides here.
function composeTrendWriterNotes(k: TrendKeyword, run: RunResponse['run']): string {
  const lines: string[] = []
  lines.push(`Working title angle: ${k.query}`)
  const velocity = k.is_breakout
    ? 'a BREAKOUT rising search (surging demand — very new interest)'
    : k.rising_value != null
      ? `a rising search, up +${Math.round(k.rising_value)}% in interest`
      : 'a rising search'
  lines.push(`This is ${velocity} on Google Trends${run.category_name ? ` in ${run.category_name}` : ''}. Write to capture the momentum while it's climbing — lead with what's new / why interest is spiking.`)
  const meta = [
    k.search_intent && `intent: ${k.search_intent}`,
    k.volume != null && `~${k.volume.toLocaleString()} monthly searches`,
    k.cpc_usd != null && `$${k.cpc_usd.toFixed(2)} CPC`,
  ].filter(Boolean).join(' · ')
  if (meta) lines.push(meta)
  if (k.is_question) lines.push('This is a question — answer it directly and early (AEO-friendly).')
  const seeds = run.seeds?.length ? run.seeds.join(', ') : ''
  if (seeds) lines.push(`Related to the client's seed topic(s): ${seeds}.`)
  lines.push('Source: Google Trends Discovery. Write as an authoritative, buyer-focused blog post.')
  return lines.join('\n')
}

export function GoogleTrends() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [seeds, setSeeds] = useState('')
  const [categoryCode, setCategoryCode] = useState<string>('')
  const [trendsType, setTrendsType] = useState<string>('web')
  const [runId, setRunId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [qualifiedOnly, setQualifiedOnly] = useState(true)

  // "Write this post" — create a Blog Writer run seeded from a rising query.
  const [writeRow, setWriteRow] = useState<TrendKeyword | null>(null)
  const [writeKeyword, setWriteKeyword] = useState('')
  const [writeNotes, setWriteNotes] = useState('')
  const [writeError, setWriteError] = useState<string | null>(null)
  const [createdRunId, setCreatedRunId] = useState<string | null>(null)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: history } = useQuery<HistoryResponse>({
    queryKey: ['google-trends', id],
    queryFn: () => api.get<HistoryResponse>(`/clients/${id}/google-trends`),
    enabled: Boolean(id),
  })

  const { data: categories } = useQuery<{ categories: TrendsCategory[] }>({
    queryKey: ['google-trends-categories'],
    queryFn: () => api.get(`/google-trends/categories`),
    enabled: Boolean(history?.enabled),
    staleTime: 1000 * 60 * 60,
  })

  const { data: runData, isFetching: loadingRun } = useQuery<RunResponse>({
    queryKey: ['google-trends-run', id, runId],
    queryFn: () => api.get<RunResponse>(`/clients/${id}/google-trends/runs/${runId}`),
    enabled: Boolean(id && runId),
  })

  const scanJob = useResumableJob<{ run_id?: string } | null, undefined>({
    storageKey: `google-trends:scan:${id}`,
    poll: async (jobId) => {
      const st = await api.get<{ status: string; error?: string; result?: { run_id?: string } }>(
        `/clients/${id}/google-trends/jobs/${jobId}`)
      return { status: st.status, result: st.result ?? null, error: st.error }
    },
    onComplete: (result) => {
      queryClient.invalidateQueries({ queryKey: ['google-trends', id] })
      if (result?.run_id) setRunId(result.run_id)
    },
    onError: (err) => setError(
      err === 'budget_exceeded'
        ? "Today's Google Trends budget is used up — try again tomorrow or raise the cap."
        : err === 'no_seeds'
          ? 'Enter at least one seed keyword.'
          : err === 'google_trends_not_enabled'
            ? 'Google Trends Discovery is not enabled yet.'
            : err === 'job_failed'
              ? 'The scan failed — check the logs.'
              : err || 'The scan failed to start.'),
    intervalMs: 2500,
  })

  function runScan() {
    setError('')
    const body = {
      seeds,
      category_code: categoryCode ? Number(categoryCode) : null,
      category_name: categories?.categories.find((c) => String(c.category_code) === categoryCode)?.category_name ?? null,
      trends_type: trendsType,
    }
    void scanJob.start(async () => {
      const r = await api.post<{ job_id: string; seeds: string[] }>(`/clients/${id}/google-trends/scan`, body)
      return r.job_id
    }, undefined)
  }

  function openWrite(k: TrendKeyword) {
    if (!runData) return
    const seed = trendSeedKeyword(k)
    setWriteRow(k)
    setWriteKeyword(seed)
    setWriteNotes(composeTrendWriterNotes(k, runData.run))
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

  const rows = useMemo(() => {
    const ks = runData?.keywords ?? []
    return qualifiedOnly ? ks.filter((k) => k.qualified) : ks
  }, [runData, qualifiedOnly])

  function exportCsv() {
    if (!runData) return
    const csv = toCsv(
      ['query', 'velocity', 'volume', 'cpc_usd', 'keyword_difficulty', 'intent', 'question', 'qualified', 'trend_score'],
      (runData.keywords).map((k) => [
        k.query, velocityLabel(k), k.volume ?? '', k.cpc_usd ?? '', k.keyword_difficulty ?? '',
        k.search_intent ?? '', k.is_question ? 'yes' : '', k.qualified ? 'yes' : 'no', k.trend_score ?? '',
      ]),
    )
    downloadCsv(`google-trends-${runData.run.seeds.join('-').slice(0, 40)}.csv`, csv)
  }

  const enabled = history?.enabled
  const running = scanJob.running
  const cats = categories?.categories ?? []
  const runs = history?.runs ?? []

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
      <Link to={id ? `/clients/${id}` : '/'} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none' }}>
        <ArrowLeft size={14} /> Back to workspace
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <TrendingUp size={22} color="#0ea5e9" />
        <h1 style={{ fontSize: 22, fontWeight: 800, margin: 0 }}>Google Trends Discovery</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 6 }}>
        Find <strong>rising</strong> searches related to a seed before competitors do — each one qualified with real
        volume &amp; CPC, so you only chase trends with a market. {client?.name ? `Client: ${client.name}.` : ''}
      </p>

      {enabled === false && (
        <div style={{ marginTop: 20, padding: 16, borderRadius: 10, background: '#fff7ed', border: '1px solid #fed7aa', color: '#9a3412', fontSize: 14 }}>
          <strong>Not enabled yet.</strong> Google Trends Discovery ships dark. An admin flips <code>google_trends_enabled</code>
          {' '}on the PLATFORM service after a one-time live check (<code>scripts/verify_google_trends.py</code>).
        </div>
      )}

      {enabled && (
        <>
          {/* Scan form */}
          <div style={{ marginTop: 20, padding: 16, borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff' }}>
            <label style={{ fontSize: 13, fontWeight: 700, color: '#334155' }}>Seed keyword(s)</label>
            <textarea
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
              placeholder="e.g. collagen peptides, bpc 157 — one per line or comma-separated (max 5)"
              rows={2}
              style={{ width: '100%', marginTop: 6, padding: 10, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 14, resize: 'vertical' }}
            />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 10, alignItems: 'flex-end' }}>
              <div>
                <label style={{ fontSize: 12, color: '#64748b', display: 'block' }}>Category (optional)</label>
                {cats.length ? (
                  <select value={categoryCode} onChange={(e) => setCategoryCode(e.target.value)}
                    style={{ padding: 8, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, minWidth: 200 }}>
                    <option value="">All categories</option>
                    {cats.map((c) => (
                      <option key={c.category_code} value={c.category_code}>{c.category_name}</option>
                    ))}
                  </select>
                ) : (
                  <input value={categoryCode} onChange={(e) => setCategoryCode(e.target.value)} placeholder="code"
                    style={{ padding: 8, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, width: 100 }} />
                )}
              </div>
              <div>
                <label style={{ fontSize: 12, color: '#64748b', display: 'block' }}>Type</label>
                <select value={trendsType} onChange={(e) => setTrendsType(e.target.value)}
                  style={{ padding: 8, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13 }}>
                  {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <button onClick={runScan} disabled={running || !seeds.trim()}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 16px', borderRadius: 8, border: 'none', background: running || !seeds.trim() ? '#94a3b8' : '#0ea5e9', color: '#fff', fontWeight: 700, fontSize: 14, cursor: running || !seeds.trim() ? 'default' : 'pointer' }}>
                <Search size={15} /> {running ? 'Scanning…' : 'Find rising queries'}
              </button>
              <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto' }}>
                Budget left today: {history?.budget_remaining ?? '—'} calls
              </span>
            </div>
            {error && <div style={{ marginTop: 10, color: '#b91c1c', fontSize: 13 }}>{error}</div>}
            {running && <div style={{ marginTop: 10, color: '#0ea5e9', fontSize: 13 }}>Pulling Trends &amp; qualifying with DataForSEO… you can leave — it finishes in the background.</div>}
          </div>

          {/* Results */}
          {runId && (
            <div style={{ marginTop: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                <h2 style={{ fontSize: 16, fontWeight: 800, margin: 0 }}>Rising queries</h2>
                {runData && <span style={{ fontSize: 13, color: '#64748b' }}>{runData.run.qualified_count} with demand / {runData.run.rising_count} rising</span>}
                <label style={{ fontSize: 13, color: '#475569', marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <input type="checkbox" checked={qualifiedOnly} onChange={(e) => setQualifiedOnly(e.target.checked)} /> Qualified only
                </label>
                <button onClick={exportCsv} disabled={!runData?.keywords.length}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff', fontSize: 13, cursor: 'pointer' }}>
                  <Download size={14} /> CSV
                </button>
              </div>
              {loadingRun && !runData ? (
                <div style={{ color: '#94a3b8', fontSize: 14, padding: 16 }}>Loading…</div>
              ) : rows.length === 0 ? (
                <div style={{ padding: 16, borderRadius: 10, background: '#f8fafc', border: '1px solid #e2e8f0', color: '#64748b', fontSize: 14 }}>
                  No {qualifiedOnly ? 'qualified ' : ''}rising queries for these seeds. Trends surfaced {runData?.run.rising_count ?? 0} rising terms; try a broader seed, a different category, or untick “Qualified only” to inspect the raw list.
                </div>
              ) : (
                <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 10 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#f8fafc', textAlign: 'left', color: '#475569' }}>
                        <th style={{ padding: '8px 10px' }}>Query</th>
                        <th style={{ padding: '8px 10px' }}>Velocity</th>
                        <th style={{ padding: '8px 10px' }}>Volume</th>
                        <th style={{ padding: '8px 10px' }}>CPC</th>
                        <th style={{ padding: '8px 10px' }}>KD</th>
                        <th style={{ padding: '8px 10px' }}>Intent</th>
                        <th style={{ padding: '8px 10px' }}>Trend score</th>
                        <th style={{ padding: '8px 10px' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((k) => (
                        <tr key={k.query} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '8px 10px', fontWeight: 600 }}>
                            {k.query}{!k.qualified && <span style={{ marginLeft: 6, fontSize: 11, color: '#94a3b8' }}>(no demand)</span>}
                          </td>
                          <td style={{ padding: '8px 10px', color: k.is_breakout ? '#dc2626' : '#0f172a', fontWeight: k.is_breakout ? 700 : 400 }}>
                            {k.is_breakout && <Flame size={12} style={{ verticalAlign: -1, marginRight: 3 }} />}{velocityLabel(k)}
                          </td>
                          <td style={{ padding: '8px 10px' }}>{k.volume?.toLocaleString() ?? '—'}</td>
                          <td style={{ padding: '8px 10px' }}>{k.cpc_usd != null ? `$${k.cpc_usd.toFixed(2)}` : '—'}</td>
                          <td style={{ padding: '8px 10px' }}>{k.keyword_difficulty ?? '—'}</td>
                          <td style={{ padding: '8px 10px' }}>{k.search_intent ?? '—'}</td>
                          <td style={{ padding: '8px 10px', fontWeight: 700 }}>{k.trend_score ?? '—'}</td>
                          <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                            {k.qualified && (
                              <button onClick={() => openWrite(k)} title="Create a Blog Writer draft from this rising query"
                                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 7, border: '1px solid #ddd6fe', background: '#f5f3ff', color: '#6d28d9', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                                <FileText size={12} /> Write
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* History */}
          {runs.length ? (
            <div style={{ marginTop: 28 }}>
              <h2 style={{ fontSize: 15, fontWeight: 800, margin: '0 0 8px' }}>Recent scans</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {runs.map((r) => (
                  <button key={r.id} onClick={() => setRunId(r.id)}
                    style={{ textAlign: 'left', padding: '10px 12px', borderRadius: 8, border: runId === r.id ? '1px solid #0ea5e9' : '1px solid #e2e8f0', background: runId === r.id ? '#f0f9ff' : '#fff', cursor: 'pointer', fontSize: 13 }}>
                    <strong>{r.seeds.join(', ')}</strong>
                    {r.category_name ? <span style={{ color: '#64748b' }}> · {r.category_name}</span> : null}
                    <span style={{ color: '#94a3b8' }}> · {r.qualified_count}/{r.rising_count} qualified · {new Date(r.created_at).toLocaleDateString()}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}

      {writeRow && (
        <div onClick={() => !createDraft.isPending && setWriteRow(null)}
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
                    <button onClick={() => setWriteRow(null)}
                      style={{ fontSize: 13, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', cursor: 'pointer' }}>Close</button>
                  </div>
                </div>
              ) : (
                <>
                  <p style={{ fontSize: 12.5, color: '#64748b', marginTop: 0 }}>
                    Creates a blog post in the Blog Writer for this client — seeded with the rising query below, with its trend angle as writer guidance.
                  </p>
                  <label style={{ display: 'block', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.4, color: '#94a3b8', margin: '12px 0 4px' }}>
                    Seed keyword <span style={{ textTransform: 'none', color: '#cbd5e1' }}>(drives the outline)</span>
                  </label>
                  <input value={writeKeyword} onChange={(e) => setWriteKeyword(e.target.value)} maxLength={150}
                    style={{ width: '100%', fontSize: 13, padding: '8px 10px', border: '1px solid #cbd5e1', borderRadius: 8, boxSizing: 'border-box' }} />
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
                    <button disabled={createDraft.isPending} onClick={() => setWriteRow(null)}
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
