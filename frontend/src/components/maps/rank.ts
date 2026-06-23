// Rank color scale + trend-metric config for the Maps geo-grid ranker. Kept in a
// non-component module (no JSX) so the .tsx visuals keep Fast Refresh, matching
// the components/rankings/status.ts convention.

// Color band for a 1-based rank (grey = not ranked / null).
export function rankColor(rank: number | null): string {
  if (rank == null || rank < 1) return '#e5e7eb'
  if (rank <= 3) return '#16a34a'
  if (rank <= 7) return '#65a30d'
  if (rank <= 10) return '#ca8a04'
  if (rank <= 15) return '#ea580c'
  return '#dc2626'
}

export type TrendMetric = 'top3_pct' | 'top10_pct' | 'found_pct' | 'average_rank'
export const TREND_METRICS: Array<{ key: TrendMetric; label: string; unit: string; lowerIsBetter: boolean; fixedMax?: number }> = [
  { key: 'top3_pct', label: 'Top 3 %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'top10_pct', label: 'Top 10 %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'found_pct', label: 'Found %', unit: '%', lowerIsBetter: false, fixedMax: 100 },
  { key: 'average_rank', label: 'Avg rank', unit: '', lowerIsBetter: true },
]
