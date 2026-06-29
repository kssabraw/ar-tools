import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { BrandSearchResponse } from '../../lib/types'
import { card, errorBox } from '../localseo/shared'

// Per-client Rankings "Brand search" tab. Branded vs non-branded Google Search
// Console demand over time — a brand-health signal derived from the ingested
// gsc_query_daily history. Empty until a GSC property is verified.
export function BrandSearch({ clientId }: { clientId: string }) {
  const { data, isLoading, error } = useQuery<BrandSearchResponse>({
    queryKey: ['brand-search', clientId],
    queryFn: () => api.get<BrandSearchResponse>(`/clients/${clientId}/rank/brand-search`),
  })

  if (isLoading) return <div style={card}>Loading…</div>
  if (error) return <div style={errorBox}>{(error as Error).message}</div>
  if (!data) return null

  if (!data.gsc_connected) {
    return (
      <div style={card}>
        <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
          Connect a verified Google Search Console property for this client to see branded vs non-branded
          search demand.
        </p>
      </div>
    )
  }

  const series = data.series
  const totals = data.totals
  const hasData = series.some(w => w.branded_impressions + w.nonbranded_impressions > 0)
  const first = series.find(w => w.branded_share_pct != null)
  const last = [...series].reverse().find(w => w.branded_share_pct != null)
  const delta = first?.branded_share_pct != null && last?.branded_share_pct != null
    ? Math.round((last.branded_share_pct - first.branded_share_pct) * 10) / 10
    : null

  return (
    <div style={card}>
      <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Brand search demand</h2>
      <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 14px' }}>
        Branded vs non-branded Google searches over the last ~90 days. Branded = queries containing your
        business name. Rising branded demand signals a strengthening brand.
        {data.brand_terms.length > 0 && (
          <> <span style={{ color: '#94a3b8' }}>Brand terms: {data.brand_terms.join(', ')}.</span></>
        )}
      </p>

      {!hasData ? (
        <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>No search-impression data in this window yet.</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginBottom: 16 }}>
            <Kpi label="Branded impressions" value={totals.branded_impressions.toLocaleString()} />
            <Kpi label="Non-branded impressions" value={totals.nonbranded_impressions.toLocaleString()} />
            <Kpi
              label="Branded share"
              value={totals.branded_share_pct != null ? `${totals.branded_share_pct}%` : '—'}
              hint={delta != null ? `${delta >= 0 ? '▲' : '▼'} ${Math.abs(delta)} pts vs start` : undefined}
              hintColor={delta != null ? (delta >= 0 ? '#16a34a' : '#dc2626') : undefined}
            />
          </div>
          <StackedBars series={series} />
        </>
      )}
    </div>
  )
}

function Kpi({ label, value, hint, hintColor }: { label: string; value: string; hint?: string; hintColor?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', marginTop: 2 }}>{value}</div>
      {hint && <div style={{ fontSize: 12, color: hintColor ?? '#94a3b8', fontWeight: 600 }}>{hint}</div>}
    </div>
  )
}

// Per-week stacked bar: branded (indigo) over non-branded (slate), height by
// total impressions, so volume and mix are both legible without a chart lib.
function StackedBars({ series }: { series: BrandSearchResponse['series'] }) {
  const max = Math.max(...series.map(w => w.branded_impressions + w.nonbranded_impressions), 1)
  const H = 120
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: H + 28, overflowX: 'auto' }}>
      {series.map(w => {
        const total = w.branded_impressions + w.nonbranded_impressions
        const h = Math.round((total / max) * H)
        const bh = total ? Math.round((w.branded_impressions / total) * h) : 0
        return (
          <div key={w.week} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 22 }}
            title={`${w.week}\nBranded: ${w.branded_impressions.toLocaleString()} (${w.branded_share_pct ?? 0}%)\nNon-branded: ${w.nonbranded_impressions.toLocaleString()}`}>
            <div style={{ width: 16, height: h, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', borderRadius: 3, overflow: 'hidden', background: '#e2e8f0' }}>
              <div style={{ height: bh, background: '#6366f1' }} />
            </div>
            <div style={{ fontSize: 8, color: '#cbd5e1', marginTop: 4, writingMode: 'vertical-rl', whiteSpace: 'nowrap' }}>{w.week.slice(5)}</div>
          </div>
        )
      })}
    </div>
  )
}
