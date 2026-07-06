import { useMemo } from 'react'
import { Users, Crown } from 'lucide-react'
import { TrendsChart, type ChartSeries } from './TrendsChart'
import { batchLabel, type TrendBatch } from './types'
import './animations.css'

// LABS' "Competitor Visibility Trends": the brand's visibility vs each tracked
// competitor's, per scan batch. Both series come from the server-side trends
// rollup (compute_trends aggregates the competitor_results re-classifications
// over the full 2000-row window — the client-fetched history is capped at 500
// rows and would truncate older batches). A batch scanned without "include
// competitors" simply contributes null points.

const COMPETITOR_COLORS = ['#ef4444', '#f97316', '#8b5cf6', '#0d9488', '#db2777']

export function CompetitorTrendsChart({ trends, competitorNames }: {
  trends: TrendBatch[]
  competitorNames: string[]
}) {
  const { labels, series, hasCompetitorData } = useMemo(() => {
    const labels = trends.map(b => batchLabel(b.created_at))

    let any = false
    const compSeries: ChartSeries[] = competitorNames.slice(0, COMPETITOR_COLORS.length).map((name, ci) => ({
      key: `comp-${name}`,
      label: name,
      color: COMPETITOR_COLORS[ci],
      points: trends.map(b => {
        const c = b.competitors?.[name]
        if (!c || c.total === 0) return null
        any = true
        return Math.round(c.visibility_pct)
      }),
    }))

    const series: ChartSeries[] = [
      {
        key: 'brand', label: 'This brand', suffix: '(You)', color: '#6366f1', emphasize: true,
        icon: <Crown size={12} color="#6366f1" />,
        points: trends.map(b => b.visibility_pct),
      },
      ...compSeries,
    ]
    return { labels, series, hasCompetitorData: any }
  }, [trends, competitorNames])

  // Nothing to compare until at least one competitor-included scan exists.
  if (!hasCompetitorData || trends.length < 2) return null

  return (
    <div className="aiv-card-enter" style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <Users size={15} color="#6366f1" />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: '#0f172a' }}>Competitor visibility trends</span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>from competitor-included scans</span>
      </div>
      <TrendsChart labels={labels} series={series} height={220} />
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, marginTop: 16,
}
