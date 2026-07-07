import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BarChart3, Camera, CheckCircle2, ChevronDown, ChevronRight, Download, Loader2, Pin, PinOff, Plus, RefreshCw, Trash2, TrendingDown, TrendingUp, Minus, Upload, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import type { KeywordStatus, KeywordSummary, KeywordTrendline, KeywordPagesResponse, RankabilityResponse, TrendPoint, DataForSeoRefreshEnqueue, DataForSeoRefreshStatus } from '../../lib/types'
import { toCsv, downloadCsv, parseKeywordsFromCsv } from '../../lib/csv'
import { card, errorBox, outlineBtn, primaryBtn } from '../localseo/shared'
import { STATUS_META, statusRank } from './status'
import { Sparkline } from './Sparkline'
import { PositionChart } from './PositionChart'
import { SerpSnapshots } from './SerpSnapshots'
import { OrganicRankReport } from './OrganicRankReport'

// How long the rankability progress banner polls before handing the remaining
// captures off to the background (a snapshot job can stall on slow backlink
// lookups; the stale-job reaper requeues it, but we don't block the UI on it).
const CAPTURE_TIMEOUT_MS = 6 * 60 * 1000

// `gscConnected` controls whether the GSC-only columns (clicks, impressions,
// CTR, 7/30/60/90 average position) are shown at all. Without GSC the table
// falls back to the DataForSEO live rank ("Today") + trend.
export function RankKeywords({ clientId, gscConnected, onViewRankability }: {
  clientId: string; gscConnected: boolean; onViewRankability?: () => void
}) {
  const queryClient = useQueryClient()
  const { data: keywords, isLoading } = useQuery<KeywordSummary[]>({
    queryKey: ['rank-keywords', clientId],
    queryFn: () => api.get<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`),
  })

  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<KeywordStatus | null>(null)
  const [justAdded, setJustAdded] = useState<KeywordSummary[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
    queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
  }

  const addMut = useMutation({
    mutationFn: (keywords: string[]) =>
      api.post<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`, { keywords }),
    onSuccess: (data) => { invalidate(); setDraft(''); setAdding(false); setJustAdded(data ?? []) },
  })

  // First-entry opt-in: offer to run rankability (capture a snapshot) for the
  // keywords just added. After this, rankability only re-runs on a detected drop
  // (≤1/mo) or on demand.
  //
  // Capturing snapshots is a background job (one per keyword, ~20-30s each,
  // serialized through the single worker), and the scores surface on the
  // separate Rankability tab — so firing the request silently looked like a
  // no-op. Instead we hold a progress banner and poll the rankability endpoint,
  // counting how many of the just-added keywords now have a snapshot, until
  // they're all captured (or we time out and hand off to the background).
  const [capturing, setCapturing] = useState<string[] | null>(null)
  const [captureStartedAt, setCaptureStartedAt] = useState(0)
  const [captureTimedOut, setCaptureTimedOut] = useState(false)

  const rankabilityMut = useMutation({
    mutationFn: (ids: string[]) =>
      Promise.all(ids.map(id => api.post(`/tracked-keywords/${id}/serp-snapshot`, {}))),
  })

  const startRankability = (ids: string[]) => {
    setJustAdded([])
    setCaptureTimedOut(false)
    setCaptureStartedAt(Date.now())
    setCapturing(ids)
    rankabilityMut.mutate(ids)
  }
  const dismissCapture = () => { setCapturing(null); rankabilityMut.reset() }

  const captureIds = capturing ?? []
  // Shares the ['rankability', clientId] cache with the Rankability tab, so its
  // data is already warm the moment the user jumps over.
  const { data: rankData } = useQuery<RankabilityResponse>({
    queryKey: ['rankability', clientId],
    queryFn: () => api.get<RankabilityResponse>(`/clients/${clientId}/rank/rankability`),
    enabled: captureIds.length > 0 && !rankabilityMut.isError,
    refetchInterval: (query) => {
      if (!captureIds.length) return false
      const items = (query.state.data as RankabilityResponse | undefined)?.items ?? []
      const done = items.filter(i => captureIds.includes(i.keyword_id) && i.has_snapshot).length
      if (done >= captureIds.length) return false
      if (captureStartedAt && Date.now() - captureStartedAt > CAPTURE_TIMEOUT_MS) return false
      return 4000
    },
  })

  // Guarantees a render at the timeout boundary (polling stops on its own, so
  // without this the "still processing in the background" copy might never show).
  useEffect(() => {
    if (!capturing) return
    const t = setTimeout(() => setCaptureTimedOut(true), CAPTURE_TIMEOUT_MS)
    return () => clearTimeout(t)
  }, [capturing])

  const captureTotal = captureIds.length
  const captureDone = (rankData?.items ?? [])
    .filter(i => captureIds.includes(i.keyword_id) && i.has_snapshot).length
  const captureComplete = captureTotal > 0 && captureDone >= captureTotal
  const captureStalled = captureTimedOut && !captureComplete

  const onCsvSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return
    const keywords = parseKeywordsFromCsv(await file.text())
    if (keywords.length) addMut.mutate(keywords)
  }
  // "Refresh live ranks" enqueues a background job (one DataForSEO SERP call per
  // GSC-uncovered keyword, ~a minute or two) instead of blocking the request, so
  // the measurement finishes in the worker even if the user leaves this page. We
  // then poll the job to surface progress and refresh the table when it lands.
  const [refreshJobId, setRefreshJobId] = useState<string | null>(null)
  const refreshMut = useMutation({
    mutationFn: () => api.post<DataForSeoRefreshEnqueue>(`/clients/${clientId}/rank/refresh-dataforseo`, {}),
    onSuccess: (data) => { if (data?.job_id) setRefreshJobId(data.job_id) },
  })
  const { data: refreshJob } = useQuery<DataForSeoRefreshStatus>({
    queryKey: ['rank-refresh-job', refreshJobId],
    queryFn: () => api.get<DataForSeoRefreshStatus>(`/clients/${clientId}/rank/refresh-dataforseo/${refreshJobId}`),
    enabled: !!refreshJobId,
    refetchInterval: (query) => {
      const s = (query.state.data as DataForSeoRefreshStatus | undefined)?.status
      return s === 'complete' || s === 'failed' ? false : 4000
    },
  })
  // When the job settles, pull the fresh ranks/status into the table once.
  const refreshStatus = refreshJob?.status
  useEffect(() => {
    if (refreshStatus === 'complete') invalidate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshStatus])
  const refreshRunning = refreshMut.isPending
    || (!!refreshJobId && refreshStatus !== 'complete' && refreshStatus !== 'failed')

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const k of keywords ?? []) c[k.status] = (c[k.status] ?? 0) + 1
    return c
  }, [keywords])

  const rows = useMemo(() => {
    const list = (keywords ?? []).filter(k => !filter || k.status === filter)
    return [...list].sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.keyword.localeCompare(b.keyword))
  }, [keywords, filter])

  const exportCsv = () => {
    const headers = [
      'Keyword', 'Status', 'Source', 'Today (live rank)', 'Prev rank', 'Prev rank date',
      'CPC', 'Volume', 'Est. monthly value',
      'Avg 7d', 'Avg 30d', 'Avg 60d', 'Avg 90d', 'Clicks 30d', 'Impr 30d', 'CTR 30d',
      'Canonical URL', 'Pages', 'Index status',
    ]
    const data = rows.map(k => [
      k.keyword, STATUS_META[k.status].label, k.primary_source, k.today_rank,
      k.prev_rank, k.prev_rank_date,
      k.cpc, k.search_volume, k.est_monthly_value,
      k.avg_7, k.avg_30, k.avg_60, k.avg_90,
      k.clicks_30d, k.impressions_30d, k.ctr_30d,
      k.canonical_url, k.page_count, k.index_status,
    ])
    downloadCsv(`rankings-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, data))
  }

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading keywords…</p>

  const showGsc = gscConnected

  return (
    <div>
      {/* Add keywords + DataForSEO refresh */}
      <div style={{ ...card, marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        {adding ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 280 }}>
            <textarea
              style={textarea} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder="One keyword per line (or comma-separated). e.g. emergency ac repair"
            />
            {addMut.error && <div style={errorBox}>{(addMut.error as Error).message}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={primaryBtn} disabled={!draft.trim() || addMut.isPending}
                onClick={() => addMut.mutate([draft.trim()])}>
                {addMut.isPending ? 'Adding…' : 'Add keywords'}
              </button>
              <button style={outlineBtn} onClick={() => { setAdding(false); setDraft('') }}>Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <button style={primaryBtn} onClick={() => setAdding(true)}>
              <Plus size={14} /> Track keywords
            </button>
            <button style={outlineBtn} onClick={() => fileRef.current?.click()} disabled={addMut.isPending}
              title="Import keywords from a CSV (first column)">
              <Upload size={14} /> {addMut.isPending ? 'Importing…' : 'Import CSV'}
            </button>
            <input ref={fileRef} type="file" accept=".csv,text/csv" style={{ display: 'none' }} onChange={onCsvSelected} />
            {(keywords?.length ?? 0) > 0 && (
              <button style={outlineBtn} onClick={() => refreshMut.mutate()} disabled={refreshRunning}
                title="Fetch DataForSEO ranks now for keywords GSC doesn't cover (runs in the background)">
                <RefreshCw size={14} /> {refreshRunning ? 'Refreshing…' : 'Refresh live ranks'}
              </button>
            )}
            {(keywords?.length ?? 0) > 0 && (
              <button style={outlineBtn} onClick={exportCsv} title="Export the current view to CSV">
                <Download size={14} /> Export CSV
              </button>
            )}
          </>
        )}
      </div>

      {justAdded.length > 0 && !capturing && (
        <div style={rankabilityBanner}>
          <span style={{ flex: 1 }}>
            Added <strong>{justAdded.length}</strong> keyword{justAdded.length === 1 ? '' : 's'}. Run a{' '}
            <strong>rankability score</strong> now? (~{justAdded.length} SERP snapshot{justAdded.length === 1 ? '' : 's'}.
            After this it only re-runs on a detected drop or on demand.)
          </span>
          <button style={primaryBtn} onClick={() => startRankability(justAdded.map(k => k.id))}>
            Run rankability
          </button>
          <button style={outlineBtn} onClick={() => setJustAdded([])}>Not now</button>
        </div>
      )}

      {capturing && (
        <div style={rankabilityBanner}>
          {rankabilityMut.isError ? (
            <>
              <span style={{ flex: 1, color: '#b91c1c' }}>
                Couldn’t start the rankability capture: {(rankabilityMut.error as Error).message}
              </span>
              <button style={primaryBtn} onClick={() => startRankability(captureIds)}>Retry</button>
              <button style={outlineBtn} onClick={dismissCapture}>Dismiss</button>
            </>
          ) : captureComplete ? (
            <>
              <CheckCircle2 size={16} color="#15803d" style={{ flexShrink: 0 }} />
              <span style={{ flex: 1 }}>
                <strong>Rankability ready</strong> — captured {captureDone} of {captureTotal} snapshot
                {captureTotal === 1 ? '' : 's'}. See the scores on the Rankability tab.
              </span>
              {onViewRankability && (
                <button style={primaryBtn} onClick={onViewRankability}>
                  View Rankability <ArrowRight size={14} />
                </button>
              )}
              <button style={outlineBtn} onClick={dismissCapture}>Dismiss</button>
            </>
          ) : (
            <>
              <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
              <Loader2 size={16} color="#4338ca" style={{ flexShrink: 0, animation: 'spin 1s linear infinite' }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 220 }}>
                <span>
                  <strong>Capturing SERP snapshots… {captureDone} of {captureTotal} done.</strong>{' '}
                  {captureStalled
                    ? 'The rest are still processing in the background — check the Rankability tab shortly.'
                    : 'Scores appear on the Rankability tab as each lands. This takes a minute or two — you can leave this page.'}
                </span>
                <div style={captureTrack}>
                  <div style={{ ...captureFill, width: `${captureTotal ? (captureDone / captureTotal) * 100 : 0}%` }} />
                </div>
              </div>
              {onViewRankability && (
                <button style={outlineBtn} onClick={onViewRankability}>
                  View Rankability <ArrowRight size={14} />
                </button>
              )}
              {captureStalled && <button style={outlineBtn} onClick={dismissCapture}>Dismiss</button>}
            </>
          )}
        </div>
      )}

      {refreshMut.isError && (
        <div style={{ ...rankabilityBanner, background: '#fef2f2', borderColor: '#fecaca', color: '#b91c1c' }}>
          <span style={{ flex: 1 }}>Couldn’t start the live-rank refresh: {(refreshMut.error as Error).message}</span>
          <button style={outlineBtn} onClick={() => refreshMut.reset()}>Dismiss</button>
        </div>
      )}

      {refreshJobId && !refreshMut.isError && (
        refreshStatus === 'complete' ? (
          <div style={rankabilityBanner}>
            <CheckCircle2 size={16} color="#15803d" style={{ flexShrink: 0 }} />
            <span style={{ flex: 1 }}>
              <strong>Live ranks refreshed</strong>{typeof refreshJob?.fetched === 'number'
                ? ` — updated ${refreshJob.fetched} keyword${refreshJob.fetched === 1 ? '' : 's'}${refreshJob.failed ? `, ${refreshJob.failed} failed` : ''}.`
                : '.'}
            </span>
            <button style={outlineBtn} onClick={() => setRefreshJobId(null)}>Dismiss</button>
          </div>
        ) : refreshStatus === 'failed' ? (
          <div style={{ ...rankabilityBanner, background: '#fef2f2', borderColor: '#fecaca', color: '#b91c1c' }}>
            <span style={{ flex: 1 }}>Live-rank refresh failed{refreshJob?.error ? `: ${refreshJob.error}` : '.'}</span>
            <button style={outlineBtn} onClick={() => setRefreshJobId(null)}>Dismiss</button>
          </div>
        ) : (
          <div style={rankabilityBanner}>
            <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
            <Loader2 size={16} color="#4338ca" style={{ flexShrink: 0, animation: 'spin 1s linear infinite' }} />
            <span style={{ flex: 1 }}>
              <strong>Refreshing live ranks…</strong> This runs in the background — you can leave this page and the
              ranks will update when it finishes.
            </span>
          </div>
        )
      )}

      {!gscConnected && (keywords?.length ?? 0) > 0 && (
        <div style={dfBanner}>
          No Search Console connection for this client — ranks come from DataForSEO live SERP checks
          (refreshed weekly). Clicks, impressions and Search Console average position aren’t available
          in this mode.
        </div>
      )}

      {/* Status filter chips */}
      {keywords && keywords.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          <Chip active={filter === null} onClick={() => setFilter(null)} label={`All ${keywords.length}`} color="#475569" bg="#f1f5f9" />
          {(Object.keys(STATUS_META) as KeywordStatus[]).filter(s => counts[s])
            .sort((a, b) => statusRank(a) - statusRank(b))
            .map(s => (
              <Chip key={s} active={filter === s} onClick={() => setFilter(filter === s ? null : s)}
                label={`${STATUS_META[s].label} ${counts[s]}`} color={STATUS_META[s].color} bg={STATUS_META[s].bg} />
            ))}
        </div>
      )}

      {keywords && keywords.length === 0 ? (
        <div style={emptyCard}>
          No keywords tracked yet. Add the terms this client wants to rank for — including ones they
          don’t rank for yet (those are tracked via DataForSEO until a position appears).
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={thLeft}>Keyword</th>
                <th style={th}>Trend</th>
                <th style={th}>Status</th>
                <th style={th} title="Live rank (DataForSEO)">Today</th>
                <th style={th} title="Cost per click (DataForSEO)">CPC</th>
                <th style={th} title="Monthly search volume (DataForSEO)">Vol.</th>
                <th style={th} title="Est. monthly value = volume × CTR-at-position × CPC">Est. value</th>
                {showGsc && <><th style={th}>7d</th><th style={th}>30d</th><th style={th}>60d</th><th style={th}>90d</th>
                  <th style={th}>Clicks</th><th style={th}>Impr.</th><th style={th}>CTR</th></>}
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(k => (
                <KeywordRow key={k.id} k={k} clientId={clientId} showGsc={showGsc} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function KeywordRow({ k, clientId, showGsc }: {
  k: KeywordSummary; clientId: string; showGsc: boolean
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [snapshotOpen, setSnapshotOpen] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const meta = STATUS_META[k.status]
  const isDf = k.primary_source === 'dataforseo'

  const { data: trend } = useQuery<KeywordTrendline>({
    queryKey: ['rank-trendline', k.id],
    queryFn: () => api.get<KeywordTrendline>(`/tracked-keywords/${k.id}/trendline`),
    enabled: open,
  })
  const { data: pages } = useQuery<KeywordPagesResponse>({
    queryKey: ['rank-kw-pages', k.id],
    queryFn: () => api.get<KeywordPagesResponse>(`/tracked-keywords/${k.id}/pages`),
    enabled: open && !isDf,
  })

  const deleteMut = useMutation({
    mutationFn: () => api.delete<void>(`/tracked-keywords/${k.id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
      queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
    },
  })
  const checkIndexMut = useMutation({
    mutationFn: () => api.post(`/tracked-keywords/${k.id}/check-index`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] }),
  })
  const pinMut = useMutation({
    mutationFn: (vars: { canonical_url?: string; canonical_url_locked: boolean }) =>
      api.patch(`/tracked-keywords/${k.id}`, vars),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
      queryClient.invalidateQueries({ queryKey: ['rank-kw-pages', k.id] })
    },
  })

  const colSpan = 8 + (showGsc ? 7 : 0)
  // DataForSEO keywords plot tracked_rank; GSC keywords plot gsc_position.
  // For DataForSEO the ranks are sparse weekly checks, so drop the null days and
  // connect the actual checks into a visible line (GSC keeps its daily gaps).
  const trendValues = isDf
    ? (trend?.points ?? [])
        .filter(p => p.tracked_rank != null)
        .map(p => ({ date: p.date, value: p.tracked_rank as number }))
    : (trend?.points ?? []).map(p => ({ date: p.date, value: p.gsc_position }))
  const pointInTime = computePointInTime(trend?.points ?? [], isDf)

  return (
    <>
      <tr style={{ borderBottom: '1px solid #f1f5f9', cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <td style={tdLeft}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {open ? <ChevronDown size={14} color="#94a3b8" /> : <ChevronRight size={14} color="#94a3b8" />}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontWeight: 600, color: '#0f172a' }}>{k.keyword}</span>
                {isDf && <span style={srcBadge}>DataForSEO</span>}
              </div>
              {(k.canonical_url || k.page_count > 1) && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, maxWidth: 320 }}>
                  {k.canonical_url && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: '#94a3b8', overflow: 'hidden', minWidth: 0 }}>
                      {k.canonical_url_locked && <Pin size={10} color="#7c3aed" />}
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.canonical_url}</span>
                    </span>
                  )}
                  {k.page_count > 1 && (
                    <span style={pagesChip} title="Surfaces across multiple pages — expand for the breakdown">
                      +{k.page_count - 1} {k.page_count - 1 === 1 ? 'page' : 'pages'}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </td>
        <td style={td}><Sparkline values={k.sparkline} color={meta.color} /></td>
        <td style={td}><span style={{ ...badge, color: meta.color, background: meta.bg }}>{meta.label}</span></td>
        <td style={td}>
          {k.today_rank != null ? (
            <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end', gap: 3 }}>
              <RankPill rank={k.today_rank} />
              {k.prev_rank != null && <WeekDelta prev={k.prev_rank} now={k.today_rank} date={k.prev_rank_date} />}
            </div>
          ) : <Dash />}
        </td>
        <td style={td}>{k.cpc != null ? `$${k.cpc.toFixed(2)}` : <Dash />}</td>
        <td style={td}>{k.search_volume != null ? k.search_volume.toLocaleString() : <Dash />}</td>
        <td style={td}>{k.est_monthly_value != null
          ? <span style={{ color: '#15803d', fontWeight: 600 }}>${Math.round(k.est_monthly_value).toLocaleString()}</span>
          : <Dash />}</td>
        {showGsc && <>
          <td style={td}><PosCell value={k.avg_7} direction={k.direction} /></td>
          <td style={td}><Pos value={k.avg_30} /></td>
          <td style={td}><Pos value={k.avg_60} /></td>
          <td style={td}><Pos value={k.avg_90} /></td>
          <td style={td}>{k.clicks_30d.toLocaleString()}</td>
          <td style={td}>{k.impressions_30d.toLocaleString()}</td>
          <td style={td}>{k.impressions_30d ? `${(k.ctr_30d * 100).toFixed(1)}%` : <Dash />}</td>
        </>}
        <td style={td} onClick={(e) => e.stopPropagation()}>
          <div style={{ display: 'inline-flex', gap: 6 }}>
            <button style={{ ...outlineBtn, padding: '4px 7px', color: '#6366f1' }}
              onClick={() => setSnapshotOpen(true)} title="Competitive SERP snapshot"><Camera size={13} /></button>
            <button style={{ ...outlineBtn, padding: '4px 7px', color: '#6366f1' }}
              onClick={() => setReportOpen(true)} title="Organic Rank Analysis report"><BarChart3 size={13} /></button>
            <button style={{ ...outlineBtn, padding: '4px 7px', color: '#dc2626' }}
              onClick={() => deleteMut.mutate()} title="Stop tracking"><Trash2 size={13} /></button>
          </div>
        </td>
      </tr>
      {snapshotOpen && (
        <tr><td colSpan={colSpan}>
          <SerpSnapshots keywordId={k.id} keyword={k.keyword} onClose={() => setSnapshotOpen(false)} />
        </td></tr>
      )}
      {reportOpen && (
        <tr><td colSpan={colSpan}>
          <OrganicRankReport keywordId={k.id} keyword={k.keyword} onClose={() => setReportOpen(false)} />
        </td></tr>
      )}
      {open && (
        <tr>
          <td colSpan={colSpan} style={{ padding: 16, background: '#fafbfc', borderBottom: '1px solid #f1f5f9' }}>
            {k.status === 'deindex_risk' && <DeindexBanner k={k}
              checking={checkIndexMut.isPending} onCheck={() => checkIndexMut.mutate()} />}
            {pointInTime && <PointInTime pit={pointInTime} isDf={isDf} />}
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
              {isDf
                ? 'DataForSEO live SERP rank — weekly checks (lower is better; inverted axis)'
                : 'GSC average position — full tracked range (gaps = days the keyword returned no data)'}
            </div>
            <PositionChart points={trendValues} />
            {pages && pages.pages.length > 0 && (
              <PageBreakdown
                pages={pages.pages}
                locked={k.canonical_url_locked}
                pinning={pinMut.isPending}
                onPin={(page) => pinMut.mutate({ canonical_url: page, canonical_url_locked: true })}
                onUnpin={() => pinMut.mutate({ canonical_url_locked: false })}
              />
            )}
          </td>
        </tr>
      )}
    </>
  )
}

// Which landing pages a keyword surfaces for — flags the canonical page,
// surfaces "split across pages" conflicts (PRD §8.5), and lets an admin pin the
// canonical page so the most-clicks heuristic can't reassign it (§5).
function PageBreakdown({ pages, locked, pinning, onPin, onUnpin }: {
  pages: KeywordPagesResponse['pages']
  locked: boolean
  pinning: boolean
  onPin: (page: string) => void
  onUnpin: () => void
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: '#64748b' }}>Landing pages this keyword surfaces for</span>
        {locked && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#7c3aed' }}>
            <Pin size={11} /> canonical pinned
            <button style={{ ...outlineBtn, padding: '2px 8px', fontSize: 11, marginLeft: 6 }}
              onClick={onUnpin} disabled={pinning}>
              <PinOff size={11} /> Unpin
            </button>
          </span>
        )}
      </div>
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
        {pages.map((p, i) => (
          <div key={p.page} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
            <a href={p.page} target="_blank" rel="noreferrer"
              style={{ flex: 1, color: '#6366f1', textDecoration: 'none', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
              {p.page}
            </a>
            {p.is_canonical && <span style={canonChip}>{locked ? 'pinned' : 'canonical'}</span>}
            <span style={{ fontSize: 12, color: '#64748b', width: 60, textAlign: 'right' }}>{p.clicks.toLocaleString()} clk</span>
            <span style={{ fontSize: 12, color: '#94a3b8', width: 70, textAlign: 'right' }}>{p.impressions.toLocaleString()} impr</span>
            <span style={{ fontSize: 12, color: '#64748b', width: 40, textAlign: 'right' }}>{p.avg_position != null ? p.avg_position.toFixed(1) : '—'}</span>
            {!(p.is_canonical && locked) && (
              <button style={{ ...outlineBtn, padding: '3px 8px', fontSize: 11 }}
                onClick={() => onPin(p.page)} disabled={pinning} title="Pin this page as the canonical landing page">
                <Pin size={11} /> Pin
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// For a deindex_risk keyword, surface the URL-Inspection verdict so the message
// becomes "this page is deindexed" rather than just "rankings look low".
function DeindexBanner({ k, checking, onCheck }: {
  k: KeywordSummary; checking: boolean; onCheck: () => void
}) {
  const confirmed = k.index_status === 'not_indexed'
  const indexed = k.index_status === 'indexed'
  const bg = confirmed ? '#fef2f2' : indexed ? '#f0fdf4' : '#fffbeb'
  const border = confirmed ? '#fecaca' : indexed ? '#bbf7d0' : '#fde68a'
  const color = confirmed ? '#b91c1c' : indexed ? '#15803d' : '#b45309'
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 8, padding: '10px 12px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
      {confirmed ? <ShieldAlert size={16} color={color} /> : indexed ? <ShieldCheck size={16} color={color} /> : <ShieldAlert size={16} color={color} />}
      <div style={{ flex: 1, fontSize: 12, color, lineHeight: 1.5 }}>
        {confirmed
          ? <>Confirmed: Google reports this page is <strong>not indexed</strong>{k.index_checked_at ? ` (checked ${new Date(k.index_checked_at).toLocaleDateString()})` : ''}. This is a deindexing, not just a ranking dip.</>
          : indexed
            ? <>URL Inspection says the page is <strong>indexed</strong> — the disappearance is a ranking drop, not deindexing.</>
            : <>Sustained disappearance after an established baseline — possible deindexing. Run a URL Inspection to confirm.</>}
      </div>
      {k.canonical_url && (
        <button style={{ ...outlineBtn, padding: '5px 10px', fontSize: 12 }} onClick={onCheck} disabled={checking}>
          {checking ? 'Checking…' : 'Check index'}
        </button>
      )}
    </div>
  )
}

// --- Point-in-time ranks (7/30/90 days ago + campaign start) ----------------
interface PointInTimeData {
  start: number | null
  d90: number | null
  d30: number | null
  d7: number | null
  now: number | null
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

// Last known rank on-or-before `targetIso`. Ranks are sparse (weekly for
// DataForSEO), so "N days ago" means the most recent check as of that date.
function rankAsOf(series: { date: string; value: number }[], targetIso: string): number | null {
  let out: number | null = null
  for (const p of series) {
    if (p.date <= targetIso) out = p.value
    else break
  }
  return out
}

// Reduce a keyword's trendline (date-ascending) to point-in-time ranks. Campaign
// start = the earliest recorded rank, so 30/90-day-ago read "—" until there's
// enough history behind them.
function computePointInTime(points: TrendPoint[], isDf: boolean): PointInTimeData | null {
  const series = points
    .map(p => ({ date: p.date, value: isDf ? p.tracked_rank : p.gsc_position }))
    .filter((p): p is { date: string; value: number } => p.value != null)
  if (!series.length) return null
  return {
    start: series[0].value,
    d90: rankAsOf(series, isoDaysAgo(90)),
    d30: rankAsOf(series, isoDaysAgo(30)),
    d7: rankAsOf(series, isoDaysAgo(7)),
    now: series[series.length - 1].value,
  }
}

function PointInTime({ pit, isDf }: { pit: PointInTimeData; isDf: boolean }) {
  const fmt = (v: number | null) => (v == null ? '—' : isDf ? `#${v}` : `#${v.toFixed(1)}`)
  const cells: { label: string; value: number | null; isNow?: boolean }[] = [
    { label: 'Campaign start', value: pit.start },
    { label: '90 days ago', value: pit.d90 },
    { label: '30 days ago', value: pit.d30 },
    { label: '7 days ago', value: pit.d7 },
    { label: 'Now', value: pit.now, isNow: true },
  ]
  return (
    <div style={pitWrap}>
      {cells.map(c => {
        // Delta vs now: positive = we were worse then (lower position now = improved).
        const delta = !c.isNow && c.value != null && pit.now != null ? c.value - pit.now : null
        return (
          <div key={c.label} style={{ ...pitTile, ...(c.isNow ? pitTileNow : null) }}>
            <div style={pitLabel}>{c.label}</div>
            <div style={{ ...pitValue, color: c.value == null ? '#cbd5e1' : c.isNow ? '#4338ca' : '#0f172a' }}>{fmt(c.value)}</div>
            {delta != null && delta !== 0 && (
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, fontWeight: 600, color: delta > 0 ? '#15803d' : '#c2410c' }}>
                {delta > 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {Math.abs(delta).toFixed(isDf ? 0 : 1)}
              </div>
            )}
            {delta === 0 && <div style={{ color: '#94a3b8' }}><Minus size={11} /></div>}
          </div>
        )
      })}
    </div>
  )
}

// Live rank as a color-scaled pill so it reads at a glance: green = page-1 top,
// blue = page 1, amber = page 2, red = beyond.
function RankPill({ rank }: { rank: number }) {
  const [bg, color] = rank <= 3 ? ['#dcfce7', '#15803d']
    : rank <= 10 ? ['#e0f2fe', '#0369a1']
    : rank <= 20 ? ['#fef3c7', '#b45309']
    : ['#fee2e2', '#b91c1c']
  return (
    <span style={{ display: 'inline-block', minWidth: 30, textAlign: 'center', borderRadius: 6, padding: '3px 9px', fontWeight: 800, fontSize: 14, background: bg, color }}>
      {rank}
    </span>
  )
}

// Week-over-week movement vs the previous DataForSEO check. Lower rank = better,
// so a decrease is an improvement (green up).
function WeekDelta({ prev, now, date }: { prev: number; now: number; date: string | null }) {
  const delta = prev - now
  const flat = delta === 0
  const improved = delta > 0
  const color = flat ? '#94a3b8' : improved ? '#15803d' : '#c2410c'
  const Icon = flat ? Minus : improved ? TrendingUp : TrendingDown
  const title = `Previous check: #${prev}${date ? ` on ${new Date(date).toLocaleDateString()}` : ''}`
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontSize: 11, fontWeight: 700, color }}>
      <Icon size={11} /> {flat ? '0' : Math.abs(delta)}
    </span>
  )
}

function Pos({ value }: { value: number | null }) {
  return value == null ? <Dash /> : <span style={{ color: '#334155' }}>{value.toFixed(1)}</span>
}
function PosCell({ value, direction }: { value: number | null; direction: KeywordSummary['direction'] }) {
  if (value == null) return <Dash />
  const arrow = direction === 'up' ? <TrendingUp size={13} color="#15803d" />
    : direction === 'down' ? <TrendingDown size={13} color="#c2410c" /> : <Minus size={12} color="#94a3b8" />
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#0f172a', fontWeight: 600 }}>{value.toFixed(1)} {arrow}</span>
}
function Dash() { return <span style={{ color: '#cbd5e1' }}>—</span> }
function Chip({ active, onClick, label, color, bg }: { active: boolean; onClick: () => void; label: string; color: string; bg: string }) {
  return <button onClick={onClick} style={{ border: active ? `1px solid ${color}` : '1px solid transparent', background: bg, color, borderRadius: 999, padding: '4px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{label}</button>
}

const textarea: React.CSSProperties = { width: '100%', minHeight: 80, padding: 10, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 14, fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }
const th: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const td: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', whiteSpace: 'nowrap' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left' }
const badge: React.CSSProperties = { borderRadius: 999, padding: '2px 9px', fontSize: 11, fontWeight: 600 }
const srcBadge: React.CSSProperties = { fontSize: 10, fontWeight: 600, color: '#0369a1', background: '#e0f2fe', borderRadius: 4, padding: '1px 5px' }
const pagesChip: React.CSSProperties = { flexShrink: 0, fontSize: 10, fontWeight: 600, color: '#7c3aed', background: '#f3e8ff', borderRadius: 4, padding: '1px 5px', whiteSpace: 'nowrap' }
const canonChip: React.CSSProperties = { fontSize: 10, fontWeight: 600, color: '#15803d', background: '#dcfce7', borderRadius: 4, padding: '1px 6px' }
const pitWrap: React.CSSProperties = { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }
const pitTile: React.CSSProperties = { flex: '1 1 92px', minWidth: 92, border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', background: '#fff', textAlign: 'center' }
const pitTileNow: React.CSSProperties = { borderColor: '#c7d2fe', background: '#eef2ff' }
const pitLabel: React.CSSProperties = { fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 4 }
const pitValue: React.CSSProperties = { fontSize: 18, fontWeight: 800, marginBottom: 2 }
const emptyCard: React.CSSProperties = { ...card, color: '#64748b', fontSize: 13, lineHeight: 1.6 }
const dfBanner: React.CSSProperties = { background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#0369a1', marginBottom: 14, lineHeight: 1.5 }
const rankabilityBanner: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#3730a3', marginBottom: 14, lineHeight: 1.5, flexWrap: 'wrap' }
const captureTrack: React.CSSProperties = { height: 6, borderRadius: 999, background: '#c7d2fe', overflow: 'hidden' }
const captureFill: React.CSSProperties = { height: '100%', borderRadius: 999, background: '#6366f1', transition: 'width 0.4s ease' }
