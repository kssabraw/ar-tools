// Shared lead-quality badge. One component so a "good lead" reads identically everywhere it
// appears: the scan coverage table (Outreach.tsx), the CRM call queue + board, and the lead drawer
// (OutreachLeads.tsx). A colour-banded decile grade — the top decile reads green.
//
// HONESTY CAVEAT (../CLAUDE.md / outreach): the number is the value/reply model's, and every
// coefficient is an unvalidated elicited prior until ~100 real replies land. So it reads as
// PRIORITY ORDER — who's most worth calling first — never a win-probability %.

function fmtScore(s: number | string | null): string | null {
  if (s == null) return null
  const n = typeof s === 'string' ? Number(s) : s
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : null
}

export function ScorePill({ score, decile, pitch }: {
  score: number | string | null
  decile: number | null
  // Optional primary-pitch chip rendered beside the grade (the CRM drawer shows it; the queue keeps
  // the pitch in its own meta line, so it passes none).
  pitch?: string | null
}) {
  const s = fmtScore(score)
  if (s == null) return null
  const strong = (decile ?? 0) >= 8
  const grade = (
    <span title="Priority order (value/reply model) — not a win probability"
      style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 700,
        background: strong ? '#dcfce7' : '#f1f5f9', color: strong ? '#166534' : '#475569' }}>
      {s}{decile != null ? ` · D${decile}` : ''}
    </span>
  )
  if (!pitch) return grade
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {grade}
      <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#eff6ff',
        color: '#0369a1', fontWeight: 600 }}>{pitch}</span>
    </span>
  )
}
