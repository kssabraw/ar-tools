import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DollarSign, RefreshCw, TrendingDown, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../../lib/api'
import type { Keyword, Mention } from './types'
import './animations.css'

// LABS' "Lead Valuation Engine": the estimated monthly cost of replacing the
// brand's lost AI visibility with paid demand. Per keyword:
//   opportunity = search_volume × CPC × visibility_gap
// where visibility_gap = share of that keyword's scanned engines where the
// brand was NOT found (current matrix state). CPC/volume come from the rank
// tracker's shared keyword_market cache via /brand/keyword-market (cache-only;
// the paid fill runs server-side as the keyword_market job — the card polls
// while `refreshing`). An estimate for prioritisation — the LABS disclaimer
// applies verbatim.

interface MarketRow {
  keyword: string
  search_volume: number | null
  cpc: number | null
  competition: 'LOW' | 'MEDIUM' | 'HIGH' | null // DataForSEO label (text, not numeric)
}
interface MarketResponse { location_code: number; degraded: string | null; refreshing: boolean; keywords: MarketRow[] }

const money = (v: number) =>
  v.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 })

export function LeadValuationCard({ clientId, activeKeywords, latestByCell }: {
  clientId: string
  activeKeywords: Keyword[]
  latestByCell: Map<string, Mention>
}) {
  const qc = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError, refetch, isFetching } = useQuery<MarketResponse>({
    queryKey: ['brand-keyword-market', clientId],
    queryFn: () => api.get<MarketResponse>(`/clients/${clientId}/brand/keyword-market`),
    staleTime: 6 * 3600e3, // market data refreshes monthly server-side
    retry: false,
    // While a server-side fill job is running, poll until it lands.
    refetchInterval: (q) => (q.state.data?.refreshing ? 4000 : false),
  })
  const refreshMut = useMutation({
    mutationFn: () => api.post<{ refreshing: boolean }>(`/clients/${clientId}/brand/keyword-market/refresh`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['brand-keyword-market', clientId] })
      void refetch()
    },
  })
  const refreshing = Boolean(data?.refreshing) || refreshMut.isPending

  // Per-keyword visibility gap from the current matrix state.
  const rows = useMemo(() => {
    const marketByKw = new Map((data?.keywords ?? []).map(r => [r.keyword.toLowerCase(), r]))
    const out: { keyword: string; volume: number; cpc: number; gap: number; cost: number }[] = []
    for (const k of activeKeywords) {
      let scanned = 0, found = 0
      for (const cell of latestByCell.values()) {
        if (cell.keyword_id !== k.id || cell.status !== 'completed') continue
        scanned += 1
        if (cell.mention_found) found += 1
      }
      if (scanned === 0) continue
      const gap = 1 - found / scanned
      const m = marketByKw.get(k.keyword.toLowerCase())
      const volume = m?.search_volume ?? null
      const cpc = m?.cpc ?? null
      if (volume == null || cpc == null) continue
      out.push({ keyword: k.keyword, volume, cpc, gap, cost: volume * cpc * gap })
    }
    return out.sort((a, b) => b.cost - a.cost)
  }, [data, activeKeywords, latestByCell])

  const total = rows.reduce((a, r) => a + r.cost, 0)
  const withData = rows.length
  const avgCpc = withData ? rows.reduce((a, r) => a + r.cpc, 0) / withData : 0
  const totalSearches = rows.reduce((a, r) => a + r.volume, 0)
  const avgGapPct = withData ? Math.round((rows.reduce((a, r) => a + r.gap, 0) / withData) * 100) : 0
  const hasGap = total > 0.5

  return (
    <div className="aiv-card-enter" style={{ ...cardStyle, ...(hasGap ? { borderColor: '#fecaca', background: '#fffbfb' } : {}) }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <DollarSign size={15} color={hasGap ? '#b91c1c' : '#6366f1'} />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: '#0f172a', flex: 1 }}>Lead valuation engine</span>
        <button
          style={ghostBtn}
          disabled={refreshing}
          onClick={() => refreshMut.mutate()}
          title="Refresh market data (re-queries every keyword)"
          aria-label="Refresh market data"
        >
          <RefreshCw size={13} className={refreshing || isFetching ? 'aiv-spin' : undefined} />
        </button>
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12 }}>Estimated monthly visibility opportunity cost</div>

      {isLoading ? (
        <div style={{ fontSize: 13, color: '#64748b', padding: '14px 0' }}>Loading keyword market data…</div>
      ) : isError ? (
        <div style={{ fontSize: 13, color: '#b91c1c', padding: '8px 0' }}>
          Couldn't load market data. <button style={linkBtn} onClick={() => void refetch()}>Retry</button>
        </div>
      ) : withData === 0 ? (
        <div style={{ fontSize: 13, color: '#64748b', padding: '8px 0' }}>
          {refreshing
            ? 'Fetching market data…'
            : <>
                No CPC/volume data for these keywords yet
                {data?.degraded === 'dataforseo_not_configured' ? ' — DataForSEO isn\'t configured' : ' — try Refresh to re-query'}
                .
              </>}
        </div>
      ) : (
        <>
          {/* hero */}
          {hasGap ? (
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <TrendingDown size={20} color="#b91c1c" style={{ alignSelf: 'center' }} />
              <span style={{ fontSize: 32, fontWeight: 800, color: '#b91c1c' }}>{money(total)}</span>
              <span style={{ fontSize: 13, color: '#94a3b8' }}>/mo</span>
            </div>
          ) : (
            <div style={{ fontSize: 32, fontWeight: 800, color: '#15803d' }}>$0<span style={{ fontSize: 13, color: '#94a3b8', fontWeight: 400 }}> /mo — no visibility gap on valued keywords</span></div>
          )}
          {data?.degraded === 'dataforseo_not_configured' && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11.5, color: '#b45309', marginTop: 6 }}>
              <AlertTriangle size={12} /> Some keywords are missing market data (DataForSEO not configured) — the estimate is partial.
            </div>
          )}

          {/* summary stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, borderTop: '1px solid #f1f5f9', marginTop: 12, paddingTop: 12 }}>
            <div>
              <div style={statLabel}>Avg. CPC</div>
              <div style={statValue}>${avgCpc.toFixed(2)}</div>
            </div>
            <div>
              <div style={statLabel}>Monthly searches</div>
              <div style={statValue}>{totalSearches.toLocaleString()}</div>
            </div>
            <div>
              <div style={statLabel}>Visibility gap</div>
              <div style={{ ...statValue, color: avgGapPct > 0 ? '#b91c1c' : '#15803d' }}>{avgGapPct}%</div>
            </div>
          </div>

          {/* per-keyword breakdown */}
          <button style={{ ...linkBtn, display: 'inline-flex', alignItems: 'center', gap: 4, marginTop: 12 }} onClick={() => setExpanded(e => !e)}>
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />} {expanded ? 'Hide' : 'Show'} keyword breakdown ({withData})
          </button>
          {expanded && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {rows.map(r => (
                <div key={r.keyword} style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#f8fafc', borderRadius: 8, padding: '7px 10px' }}>
                  <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={r.keyword}>{r.keyword}</span>
                  <span style={{ fontSize: 11.5, color: '#64748b', whiteSpace: 'nowrap' }}>
                    {r.volume.toLocaleString()} searches · ${r.cpc.toFixed(2)} CPC · {Math.round(r.gap * 100)}% gap
                  </span>
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: r.cost > 0.5 ? '#b91c1c' : '#15803d', minWidth: 60, textAlign: 'right' }}>
                    {money(r.cost)}
                  </span>
                </div>
              ))}
            </div>
          )}

          <div style={{ fontSize: 10.5, color: '#94a3b8', marginTop: 12 }}>
            This estimate reflects the cost to replace lost AI visibility through paid demand. It is not a guarantee of revenue.
            The gap weighs each scanned engine equally.
          </div>
        </>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, marginBottom: 22,
}
const statLabel: React.CSSProperties = { fontSize: 10.5, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 3 }
const statValue: React.CSSProperties = { fontSize: 17, fontWeight: 700, color: '#0f172a' }
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', background: 'none', border: 'none',
  color: '#64748b', cursor: 'pointer', padding: 4,
}
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer',
  fontSize: 12, fontWeight: 600, padding: 0,
}
