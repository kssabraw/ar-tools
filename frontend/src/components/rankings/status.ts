import type { KeywordStatus } from '../../lib/types'

// Single source of truth for status label + color (double-encodes status as
// color on sparklines/badges, per PRD §8.2/§8.3).
export const STATUS_META: Record<KeywordStatus, { label: string; color: string; bg: string }> = {
  climbing:     { label: 'Climbing',     color: '#15803d', bg: '#dcfce7' },
  stable:       { label: 'Stable',       color: '#475569', bg: '#f1f5f9' },
  volatile:     { label: 'Volatile',     color: '#b45309', bg: '#fef3c7' },
  dropping:     { label: 'Dropping',     color: '#c2410c', bg: '#ffedd5' },
  deindex_risk: { label: 'At risk',      color: '#b91c1c', bg: '#fee2e2' },
  no_data:      { label: 'No data yet',  color: '#94a3b8', bg: '#f8fafc' },
}

// "Needs attention" first — drives the default triage sort (PRD §8.3).
export const STATUS_ORDER: KeywordStatus[] = [
  'deindex_risk', 'dropping', 'volatile', 'climbing', 'stable', 'no_data',
]

export function statusRank(s: KeywordStatus): number {
  const i = STATUS_ORDER.indexOf(s)
  return i === -1 ? STATUS_ORDER.length : i
}
