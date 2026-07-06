import { useMemo, useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { TrendsChart, type ChartSeries } from './TrendsChart'
import { ENGINE_ORDER, ENGINES, EngineIcon } from './engines'
import type { TrendBatch } from './types'
import './animations.css'

// LABS' "Visibility Trends" card: per-engine visibility % over time with an
// interactive color-swatch legend and a date-range toggle. One deliberate
// divergence from LABS: the x-axis is scan batches (this tool scans weekly/
// monthly, not daily), so the ranges are 30d/90d/All instead of 7d/30d/60d.

type Range = '30d' | '90d' | 'all'
const RANGE_DAYS: Record<Range, number | null> = { '30d': 30, '90d': 90, all: null }

function batchLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}/${d.getDate()}`
}

export function VisibilityTrendsChart({ trends }: { trends: TrendBatch[] }) {
  const [range, setRange] = useState<Range>('all')

  const batches = useMemo(() => {
    const days = RANGE_DAYS[range]
    if (days == null) return trends
    const cut = Date.now() - days * 864e5
    return trends.filter(t => t.created_at && new Date(t.created_at).getTime() >= cut)
  }, [trends, range])

  const labels = batches.map(b => batchLabel(b.created_at))
  const series: ChartSeries[] = useMemo(() => [
    {
      key: 'overall', label: 'Overall', color: '#6366f1', emphasize: true,
      points: batches.map(b => b.visibility_pct),
    },
    ...ENGINE_ORDER.map(e => ({
      key: e, label: ENGINES[e].label, color: ENGINES[e].color,
      icon: <EngineIcon engine={e} size={13} />,
      points: batches.map(b => b.engines[e]?.visibility_pct ?? null),
    })),
  ], [batches])

  return (
    <div className="aiv-card-enter" style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TrendingUp size={15} color="#6366f1" />
          <span style={{ fontSize: 13.5, fontWeight: 700, color: '#0f172a' }}>Visibility trends</span>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>visibility % by engine, per scan</span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {(['30d', '90d', 'all'] as Range[]).map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              style={{
                padding: '4px 10px', fontSize: 11.5, fontWeight: 600, borderRadius: 7, cursor: 'pointer',
                background: range === r ? '#6366f1' : '#fff',
                color: range === r ? '#fff' : '#475569',
                border: `1px solid ${range === r ? '#6366f1' : '#e2e8f0'}`,
              }}
            >
              {r === 'all' ? 'All' : r}
            </button>
          ))}
        </div>
      </div>
      <TrendsChart labels={labels} series={series} />
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16,
}
