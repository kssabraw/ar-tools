import { useState } from 'react'
import { AlertTriangle, CheckCircle, ChevronDown, ChevronUp, XCircle } from 'lucide-react'
import type { ScoreResult } from '../localseo/types'
import { card, scoreColor } from '../localseo/shared'
import { SearchCoveragePanel } from '../coverage/SearchCoveragePanel'

// Read-only render of a ScoreResult: composite + per-engine breakdown (issues +
// recommendations, expandable) + the Search-coverage panel (entity usage / gaps
// and per-term targets). Deliberately NO reoptimize/fix affordances — this is the
// "score only" surface shared by all four writers. Engines are rendered in the
// adapter's engineLabels order; engines absent from the result are skipped.

function EngineIcon({ score }: { score: number }) {
  if (score >= 80) return <CheckCircle size={16} color="#16a34a" />
  if (score >= 60) return <AlertTriangle size={16} color="#d97706" />
  return <XCircle size={16} color="#dc2626" />
}

export function ScoreResultView({
  result, engineLabels,
}: { result: ScoreResult; engineLabels: Record<string, string> }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) => setExpanded(prev => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  const issueCount = (result.deficiencies ?? []).reduce((n, d) => n + (d.issues?.length ?? 1), 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Composite */}
      <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 24 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 48, fontWeight: 700, lineHeight: 1, color: scoreColor(result.composite_score) }}>
            {Math.round(result.composite_score)}
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>/ 100</div>
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize', color: scoreColor(result.composite_score) }}>
            {(result.composite_status ?? '').replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
            {(result.deficiencies?.length ?? 0) === 0 ? 'No gaps found.' : `${issueCount} issue(s) noted.`}
          </div>
        </div>
      </div>

      {/* Engine breakdown */}
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', borderBottom: '1px solid #e2e8f0' }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Engine breakdown</h2>
        </div>
        {Object.entries(engineLabels).map(([key, lbl], idx) => {
          const eng = result.engine_scores?.[key]
          if (!eng) return null
          const isOpen = expanded.has(key)
          const hasDetails = (eng.issues?.length || 0) + (eng.recommendations?.length || 0) > 0
          return (
            <div key={key} style={{ borderTop: idx ? '1px solid #f1f5f9' : 'none' }}>
              <button
                onClick={() => hasDetails && toggle(key)}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 12, padding: '12px 20px',
                  background: 'none', border: 'none', cursor: hasDetails ? 'pointer' : 'default', textAlign: 'left',
                }}
              >
                <EngineIcon score={eng.score} />
                <span style={{ flex: 1, fontSize: 14, color: '#0f172a' }}>{lbl}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ width: 96, height: 8, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ height: '100%', borderRadius: 999, background: scoreColor(eng.score), width: `${eng.score}%` }} />
                  </div>
                  <span style={{ fontSize: 14, fontWeight: 600, width: 32, textAlign: 'right', color: scoreColor(eng.score) }}>{eng.score}</span>
                  {hasDetails && (isOpen ? <ChevronUp size={16} color="#94a3b8" /> : <ChevronDown size={16} color="#94a3b8" />)}
                </div>
              </button>
              {isOpen && hasDetails && (
                <div style={{ padding: '0 20px 16px', background: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {eng.issues && eng.issues.length > 0 && (
                    <div>
                      <p style={{ fontSize: 12, fontWeight: 600, color: '#dc2626', margin: '0 0 4px' }}>Issues</p>
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {eng.issues.map((iss, i) => <li key={i} style={{ fontSize: 12, color: '#64748b' }}>{iss}</li>)}
                      </ul>
                    </div>
                  )}
                  {eng.recommendations && eng.recommendations.length > 0 && (
                    <div>
                      <p style={{ fontSize: 12, fontWeight: 600, color: '#16a34a', margin: '0 0 4px' }}>Recommended fixes</p>
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {eng.recommendations.map((rec, i) => <li key={i} style={{ fontSize: 12, color: '#64748b' }}>{rec}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Search coverage — entity usage / gaps + per-term targets + per-zone breakdown */}
      <SearchCoveragePanel coverage={result.engine_scores?.serp_signal_coverage} />
    </div>
  )
}
