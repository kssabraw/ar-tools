import { useMemo } from 'react'
import { Users, Crown } from 'lucide-react'
import { TrendsChart, type ChartSeries } from './TrendsChart'
import { compResultFor, type Mention, type TrendBatch } from './types'
import './animations.css'

// LABS' "Competitor Visibility Trends": the brand's visibility vs each tracked
// competitor's, per scan batch. Competitor series are computed client-side from
// the competitor_results re-classifications already stored on the brand's
// mention rows (no extra API) — a batch scanned without "include competitors"
// simply contributes null points for them.

const COMPETITOR_COLORS = ['#ef4444', '#f97316', '#8b5cf6', '#0d9488', '#db2777']

function batchLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}/${d.getDate()}`
}

export function CompetitorTrendsChart({ trends, history, competitorNames }: {
  trends: TrendBatch[]
  history: Mention[]
  competitorNames: string[]
}) {
  const { labels, series, hasCompetitorData } = useMemo(() => {
    const labels = trends.map(b => batchLabel(b.created_at))

    // Completed brand rows grouped by batch (competitor results ride on them).
    const rowsByBatch = new Map<string, Mention[]>()
    for (const m of history) {
      if (m.status !== 'completed' || !m.scan_batch_id) continue
      rowsByBatch.set(m.scan_batch_id, [...(rowsByBatch.get(m.scan_batch_id) ?? []), m])
    }

    let any = false
    const compSeries: ChartSeries[] = competitorNames.slice(0, COMPETITOR_COLORS.length).map((name, ci) => ({
      key: `comp-${name}`,
      label: name,
      color: COMPETITOR_COLORS[ci],
      points: trends.map(b => {
        const rows = b.scan_batch_id ? rowsByBatch.get(b.scan_batch_id) ?? [] : []
        let total = 0, found = 0
        for (const m of rows) {
          const cr = compResultFor(m, name)
          if (!cr) continue
          total += 1
          if (cr.found) found += 1
        }
        if (total === 0) return null
        any = true
        return Math.round((found / total) * 100)
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
  }, [trends, history, competitorNames])

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
