import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { KeywordSummary } from '../../lib/types'

// Overall trend for the tracked window, as a color-coded arrow + positions
// moved. `direction` is computed server-side (avg_7 vs avg_90 for GSC, sparkline
// endpoints for DataForSEO); the magnitude mirrors that same comparison so the
// arrow and the number never disagree. Lower position = better, so "up" (green)
// = improved.
export function trendPositions(k: KeywordSummary): number | null {
  if (k.avg_7 != null && k.avg_90 != null) return k.avg_90 - k.avg_7 // GSC: +ve = improved
  const pts = k.sparkline.filter((v): v is number => v != null)      // DataForSEO fallback
  if (pts.length >= 2) return pts[0] - pts[pts.length - 1]           // earliest − latest
  return null
}

export function TrendCell({ k, size = 14 }: { k: KeywordSummary; size?: number }) {
  if (k.direction == null) return <span style={{ color: '#cbd5e1' }}>—</span>
  const delta = trendPositions(k)
  const flat = k.direction === 'flat'
  const improved = k.direction === 'up'
  const color = flat ? '#94a3b8' : improved ? '#15803d' : '#c2410c'
  const Icon = flat ? Minus : improved ? TrendingUp : TrendingDown
  const mag = delta == null ? 0 : Math.round(Math.abs(delta))
  const title = flat ? 'Holding steady over the tracked window'
    : `${improved ? 'Improved' : 'Dropped'} ${mag >= 1 ? `~${mag} position${mag === 1 ? '' : 's'}` : 'slightly'} over the tracked window`
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 12, fontWeight: 700, color }}>
      <Icon size={size} /> {!flat && mag >= 1 ? mag : ''}
    </span>
  )
}
