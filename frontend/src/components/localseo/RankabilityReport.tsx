import { AlertTriangle, CheckCircle2, MapPin, Star, XCircle } from 'lucide-react'
import type { RankabilityResult } from './types'
import { card } from './shared'

// Map-pack rankability report card. Renders the verdict banner, the deterministic
// points breakdown, the live competitor 3-pack, review metrics, and plain-English
// barrier notes. A transient error sets verdict === "unknown" → show just the message.

const BREAKDOWN_ROWS: Array<{ label: string; key: string; max: number }> = [
  { label: 'Category match', key: 'category_match', max: 35 },
  { label: 'Competition barrier', key: 'competition_barrier', max: 15 },
  { label: 'Distance to target city', key: 'distance', max: 20 },
  { label: 'Keyword in competitor names', key: 'keyword_in_competitor_names', max: 25 },
  { label: 'Appears in Google Maps', key: 'in_maps_results', max: 5 },
]

type Theme = { bg: string; border: string; accent: string; icon: typeof CheckCircle2; label: string }

function verdictTheme(verdict: string): Theme {
  switch (verdict) {
    case 'strong':
      return { bg: '#f0fdf4', border: '#bbf7d0', accent: '#16a34a', icon: CheckCircle2, label: 'Strong rankability' }
    case 'moderate':
      return { bg: '#fffbeb', border: '#fde68a', accent: '#d97706', icon: AlertTriangle, label: 'Moderate — achievable with work' }
    case 'difficult':
      return { bg: '#fef2f2', border: '#fecaca', accent: '#dc2626', icon: XCircle, label: 'Difficult — real barriers present' }
    default:
      return { bg: '#fef2f2', border: '#fecaca', accent: '#b91c1c', icon: XCircle, label: 'Very difficult — consider a different keyword or location' }
  }
}

export function RankabilityReport({ result }: { result: RankabilityResult }) {
  // Transient error state — show only the message.
  if (result.verdict === 'unknown') {
    return (
      <div style={{ display: 'flex', gap: 8, padding: '10px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, color: '#64748b' }}>
        <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>{result.message || 'Could not retrieve map pack data.'}</span>
      </div>
    )
  }

  const theme = verdictTheme(result.verdict)
  const Icon = theme.icon
  const top3 = result.competitors.slice(0, 3)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Verdict banner */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '16px 18px', background: theme.bg, border: `1px solid ${theme.border}`, borderRadius: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 64 }}>
          <span style={{ fontSize: 30, fontWeight: 800, lineHeight: 1, color: theme.accent }}>{result.score}</span>
          <span style={{ fontSize: 11, color: theme.accent, opacity: 0.8 }}>/ 100</span>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 15, fontWeight: 700, color: theme.accent }}>
            <Icon size={17} /> {theme.label}
          </div>
          {result.message && (
            <p style={{ fontSize: 13, color: '#475569', margin: '4px 0 0' }}>{result.message}</p>
          )}
        </div>
      </div>

      {/* Score breakdown bars */}
      <div style={{ ...card, padding: 18, display: 'flex', flexDirection: 'column', gap: 9, fontSize: 13 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 2 }}>Score breakdown</span>
        {BREAKDOWN_ROWS.map(({ label, key, max }) => {
          const pts = result.score_breakdown[key] ?? 0
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ flex: 1, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
              <div style={{ width: 90, height: 6, borderRadius: 999, background: '#f1f5f9', overflow: 'hidden', flexShrink: 0 }}>
                <div style={{ height: '100%', borderRadius: 999, background: '#6366f1', width: `${Math.max(0, Math.min(100, (pts / max) * 100))}%`, transition: 'width 0.4s' }} />
              </div>
              <span style={{ width: 44, textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: '#64748b' }}>{pts}/{max}</span>
            </div>
          )
        })}
        {result.sab_pack_mismatch && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#dc2626', fontWeight: 600 }}>
            <span style={{ flex: 1 }}>SAB vs physical pack penalty</span>
            <span style={{ width: 44, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{result.score_breakdown['sab_penalty'] ?? -40}</span>
          </div>
        )}
      </div>

      {/* Competitor 3-pack */}
      {top3.length > 0 && (
        <div style={{ ...card, padding: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Map pack competitors</span>
          {top3.map((c, i) => {
            const isClient = result.in_maps_results && result.maps_position === i + 1
            return (
              <div key={`${c.name}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, background: isClient ? '#eef2ff' : '#f8fafc', border: `1px solid ${isClient ? '#c7d2fe' : '#f1f5f9'}` }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', minWidth: 16 }}>{i + 1}</span>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.name}{isClient && <span style={{ marginLeft: 6, fontSize: 11, color: '#6366f1' }}>(you)</span>}
                  </div>
                  {c.has_keyword_in_name && (
                    <span style={{ fontSize: 11, color: '#d97706' }}>keyword in name</span>
                  )}
                </div>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b', flexShrink: 0 }}>
                  {c.rating != null && (<><Star size={12} color="#f59e0b" fill="#f59e0b" /> {c.rating}</>)}
                  {c.review_count != null && <span style={{ opacity: 0.8 }}>({c.review_count})</span>}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Review metrics + barrier notes */}
      <div style={{ ...card, padding: 18, display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13, color: '#475569' }}>
        {(result.min_reviews_in_pack != null || result.avg_rating_in_pack != null) && (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', color: '#64748b' }}>
            {result.min_reviews_in_pack != null && result.max_reviews_in_pack != null && (
              <span>Pack reviews: {result.min_reviews_in_pack}–{result.max_reviews_in_pack}</span>
            )}
            {result.avg_rating_in_pack != null && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Star size={12} color="#f59e0b" fill="#f59e0b" /> {result.avg_rating_in_pack} avg
              </span>
            )}
          </div>
        )}

        {result.review_gap != null && (
          <Note ok={result.review_gap === 0}>
            {result.review_gap === 0
              ? 'Enough reviews to match the weakest competitor'
              : `Need ${result.review_gap} more review${result.review_gap === 1 ? '' : 's'} to match the weakest competitor`}
          </Note>
        )}

        {result.distance_miles != null && (
          <Note ok={result.distance_ok}>
            {result.distance_ok
              ? `${result.distance_miles} mi from the target city — good proximity`
              : `${result.distance_miles} mi from the target city — proximity disadvantage`}
          </Note>
        )}

        {result.in_maps_results && result.maps_position != null && (
          <Note ok>Business already appears at position {result.maps_position} in the Maps top 10</Note>
        )}

        {result.keyword_in_competitor_names > 0 && (
          <Note ok={false}>
            {result.keyword_in_competitor_names} competitor{result.keyword_in_competitor_names === 1 ? '' : 's'} have the keyword in their name
            {result.competitor_name_examples.length > 0 && `: ${result.competitor_name_examples.slice(0, 3).join(', ')}`}
          </Note>
        )}

        {result.category_match === 'none' && (
          <Note ok={false}>Your GBP category doesn't match any business in the Maps pack</Note>
        )}

        {!result.has_map_pack && (
          <div style={{ display: 'flex', gap: 7, color: '#94a3b8' }}>
            <MapPin size={14} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>No local pack rendered in the organic SERP for this query.</span>
          </div>
        )}

        {result.ranking_categories.length > 0 && (
          <span style={{ color: '#94a3b8', fontSize: 12 }}>
            Pack categories: {result.ranking_categories.slice(0, 3).map(rc => rc.category).join(', ')}
          </span>
        )}
      </div>
    </div>
  )
}

function Note({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 7, color: ok ? '#166534' : '#b45309' }}>
      {ok ? <CheckCircle2 size={14} style={{ flexShrink: 0, marginTop: 1 }} /> : <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />}
      <span>{children}</span>
    </div>
  )
}
