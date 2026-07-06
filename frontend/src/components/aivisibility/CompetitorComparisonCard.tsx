import { useMemo } from 'react'
import { Users } from 'lucide-react'
import { HealthScoreGauge } from './HealthScoreGauge'
import { batchLabel, type TrendBatch } from './types'
import './animations.css'

// LABS' "Competitive Visibility" card: side-by-side health-score tiles — your
// brand vs tracked competitors — from the latest COMPETITOR-INCLUDED scan
// batch (a brand-only scan in between doesn't blank the tiles). Stats come
// from the server-side trends rollup (compute_trends aggregates the
// competitor_results re-classifications). Dashed placeholder slots invite
// adding competitors.

interface CompStat { name: string; healthScore: number | null; visibilityPct: number | null; cells: number }

const MAX_TILES = 2 // competitors shown beside the brand (LABS layout: 3 tiles)

export function CompetitorComparisonCard({ brandName, healthScore, latestBatch, trends, competitorNames, onManageCompetitors }: {
  brandName: string
  healthScore: number | null
  latestBatch: TrendBatch | null
  trends: TrendBatch[]
  competitorNames: string[]
  onManageCompetitors: () => void
}) {
  // Newest batch that actually carries competitor re-classifications.
  const compBatch = useMemo(() => {
    for (let i = trends.length - 1; i >= 0; i--) {
      if (Object.keys(trends[i].competitors ?? {}).length > 0) return trends[i]
    }
    return null
  }, [trends])

  const compStats = useMemo<CompStat[]>(() => {
    if (!compBatch) return []
    return competitorNames.map(name => {
      const c = compBatch.competitors?.[name]
      return {
        name,
        healthScore: c?.health_score ?? null,
        visibilityPct: c && c.total > 0 ? Math.round(c.visibility_pct) : null,
        cells: c?.total ?? 0,
      }
    })
      // Strongest competitors first; unscanned ones sink.
      .sort((a, b) => (b.visibilityPct ?? -1) - (a.visibilityPct ?? -1))
  }, [compBatch, competitorNames])

  const shown = compStats.slice(0, MAX_TILES)
  const extra = Math.max(0, compStats.length - MAX_TILES)
  const emptySlots = Math.max(0, MAX_TILES - shown.length)

  return (
    <div className="aiv-card-enter" style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Users size={15} color="#6366f1" />
        <span style={{ fontSize: 13.5, fontWeight: 700, color: '#0f172a' }}>Competitive visibility</span>
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 14 }}>
        Side-by-side health score comparison, from the latest competitor-included scan
        {compBatch && compBatch.scan_batch_id !== latestBatch?.scan_batch_id && <> ({batchLabel(compBatch.created_at)})</>}
        {extra > 0 && <> · top {MAX_TILES} of {compStats.length} tracked shown</>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }}>
        {/* Your brand */}
        <div style={{ ...tile, background: '#eef2ff', borderColor: '#c7d2fe' }}>
          <span style={tileLabel}>Your brand</span>
          <span style={tileName} title={brandName}>{brandName}</span>
          <HealthScoreGauge score={healthScore} size="sm" />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
            {latestBatch ? `${latestBatch.visibility_pct}%` : '—'}
          </span>
          <span style={tileSub}>{latestBatch ? `${latestBatch.total} answers scanned` : 'no scans yet'}</span>
        </div>

        {shown.map(c => (
          <div key={c.name} style={{ ...tile, background: '#fef2f2', borderColor: '#fecaca' }}>
            <span style={tileLabel}>Competitor</span>
            <span style={tileName} title={c.name}>{c.name}</span>
            <HealthScoreGauge score={c.healthScore} size="sm" />
            <span style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
              {c.visibilityPct == null ? '—' : `${c.visibilityPct}%`}
            </span>
            <span style={tileSub}>
              {c.cells > 0 ? `${c.cells} answers checked` : 'not scanned yet — run a scan with competitors'}
            </span>
          </div>
        ))}

        {Array.from({ length: emptySlots }, (_, i) => (
          <button key={i} style={emptyTile} onClick={onManageCompetitors}>
            <Users size={20} color="#cbd5e1" />
            <span style={{ fontSize: 12, color: '#94a3b8' }}>Add a competitor to compare</span>
          </button>
        ))}
      </div>
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, marginBottom: 22,
}
const tile: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
  border: '1px solid', borderRadius: 12, padding: '14px 12px', minWidth: 0,
}
const tileLabel: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em',
}
const tileName: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: '#0f172a', maxWidth: '100%',
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
}
const tileSub: React.CSSProperties = { fontSize: 11, color: '#94a3b8', textAlign: 'center' }
const emptyTile: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8,
  border: '1px dashed #cbd5e1', borderRadius: 12, padding: 14, minHeight: 180,
  background: 'none', cursor: 'pointer',
}
