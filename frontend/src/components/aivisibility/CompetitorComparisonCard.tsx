import { useMemo } from 'react'
import { Users } from 'lucide-react'
import { HealthScoreGauge } from './HealthScoreGauge'
import { computeHealthScore, compResultFor, type Mention, type TrendBatch } from './types'
import './animations.css'

// LABS' "Competitive Visibility" card: side-by-side health-score tiles — your
// brand vs tracked competitors — from the latest scan batch. Competitor stats
// come from the competitor_results re-classifications on the brand's own rows
// (no extra API); a competitor scanned without "include competitors" simply
// has no data yet. Dashed placeholder slots invite adding competitors.

interface CompStat { name: string; healthScore: number | null; visibilityPct: number | null; cells: number }

const MAX_TILES = 2 // competitors shown beside the brand (LABS layout: 3 tiles)

export function CompetitorComparisonCard({ brandName, healthScore, latestBatch, history, competitorNames, onManageCompetitors }: {
  brandName: string
  healthScore: number | null
  latestBatch: TrendBatch | null
  history: Mention[]
  competitorNames: string[]
  onManageCompetitors: () => void
}) {
  const compStats = useMemo<CompStat[]>(() => {
    if (!latestBatch?.scan_batch_id) return []
    const rows = history.filter(h => h.scan_batch_id === latestBatch.scan_batch_id && h.status === 'completed')
    return competitorNames.map(name => {
      let total = 0, found = 0
      const confs: number[] = []
      for (const m of rows) {
        const cr = compResultFor(m, name)
        if (!cr) continue
        total += 1
        if (cr.found) found += 1
        if (cr.confidence != null) confs.push(cr.confidence)
      }
      const vis = total > 0 ? Math.round((found / total) * 100) : null
      const avgConf = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null
      return { name, healthScore: computeHealthScore(vis, avgConf), visibilityPct: vis, cells: total }
    })
      // Strongest competitors first; unscanned ones sink.
      .sort((a, b) => (b.visibilityPct ?? -1) - (a.visibilityPct ?? -1))
  }, [latestBatch, history, competitorNames])

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
              {c.cells > 0 ? `${c.cells} answers checked` : 'not in the latest scan — run one with competitors'}
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
