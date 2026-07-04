import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCircle, ChevronDown, ChevronRight, RefreshCw, XCircle,
} from 'lucide-react'
import { localSeoApi } from './api'
import type { ScoreHistoryRow, ScoreRunMode } from './types'
import { Spinner } from './Spinner'
import { card, errorBox, relativeTime, scoreColor, statusLabel } from './shared'

// All eight engines, in the canonical order the scorer weights them. Includes the
// deterministic SERP Signal Coverage engine (absent from the live-score view's
// map, but present in stored verdicts).
const ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  gbp_maps: 'GBP / Maps Relevance',
  entity_establishment: 'Entity Establishment',
  icp_alignment: 'ICP Alignment',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  geographic_legitimacy: 'Geographic Legitimacy',
  nearme_intent: 'Hyperlocal / Near-Me',
  serp_signal_coverage: 'SERP Signal Coverage',
}

const MODE_META: Record<ScoreRunMode, { label: string; color: string; bg: string }> = {
  score: { label: 'Score', color: '#475569', bg: '#f1f5f9' },
  generate: { label: 'Generated', color: '#4338ca', bg: '#eef2ff' },
  reoptimize: { label: 'Reoptimized', color: '#15803d', bg: '#f0fdf4' },
  reoptimize_before: { label: 'Before reopt', color: '#b45309', bg: '#fffbeb' },
}

function EngineIcon({ score }: { score: number }) {
  if (score >= 80) return <CheckCircle size={15} color="#16a34a" />
  if (score >= 60) return <AlertTriangle size={15} color="#d97706" />
  return <XCircle size={15} color="#dc2626" />
}

function ModePill({ mode }: { mode: ScoreRunMode }) {
  const m = MODE_META[mode] ?? { label: mode, color: '#475569', bg: '#f1f5f9' }
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color: m.color, background: m.bg,
      padding: '2px 8px', borderRadius: 999, textTransform: 'uppercase', letterSpacing: 0.3,
    }}>{m.label}</span>
  )
}

function EngineBreakdown({ row }: { row: ScoreHistoryRow }) {
  const engines = row.engine_scores
  if (!engines || Object.keys(engines).length === 0) {
    return (
      <p style={{ fontSize: 12, color: '#94a3b8', margin: '12px 16px 16px' }}>
        No per-engine breakdown was stored for this run.
      </p>
    )
  }
  return (
    <div style={{ background: '#f8fafc', borderTop: '1px solid #e2e8f0' }}>
      {Object.entries(ENGINE_LABELS).map(([key, lbl]) => {
        const eng = engines[key]
        if (!eng) return null
        const details = [...(eng.issues ?? []), ...(eng.recommendations ?? [])]
        return (
          <div key={key} style={{ padding: '10px 16px', borderTop: '1px solid #eef2f7' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <EngineIcon score={eng.score} />
              <span style={{ flex: 1, fontSize: 13, color: '#0f172a' }}>{lbl}</span>
              <div style={{ width: 84, height: 7, background: '#e2e8f0', borderRadius: 999, overflow: 'hidden' }}>
                <div style={{ height: '100%', borderRadius: 999, background: scoreColor(eng.score), width: `${eng.score}%` }} />
              </div>
              <span style={{ fontSize: 13, fontWeight: 600, width: 30, textAlign: 'right', color: scoreColor(eng.score) }}>
                {Math.round(eng.score)}
              </span>
            </div>
            {eng.icp_detected && (
              <p style={{ fontSize: 11, color: '#64748b', margin: '6px 0 0 25px' }}>
                ICP detected: {eng.icp_detected}
              </p>
            )}
            {eng.issues && eng.issues.length > 0 && (
              <ul style={{ margin: '6px 0 0 25px', paddingLeft: 14 }}>
                {eng.issues.map((iss, i) => (
                  <li key={i} style={{ fontSize: 12, color: '#dc2626', marginBottom: 2 }}>{iss}</li>
                ))}
              </ul>
            )}
            {eng.recommendations && eng.recommendations.length > 0 && (
              <ul style={{ margin: '4px 0 0 25px', paddingLeft: 14 }}>
                {eng.recommendations.map((rec, i) => (
                  <li key={i} style={{ fontSize: 12, color: '#16a34a', marginBottom: 2 }}>{rec}</li>
                ))}
              </ul>
            )}
            {details.length === 0 && (
              <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0 0 25px' }}>No issues flagged.</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

function HistoryRow({ row }: { row: ScoreHistoryRow }) {
  const [open, setOpen] = useState(false)
  const score = row.composite_score
  const deficiencyCount = row.deficiencies?.length ?? 0
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', background: '#fff' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
          background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
        }}
      >
        {open ? <ChevronDown size={16} color="#94a3b8" /> : <ChevronRight size={16} color="#94a3b8" />}
        {/* Composite */}
        <div style={{
          width: 38, height: 38, borderRadius: 8, flexShrink: 0, display: 'flex',
          flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          background: '#f8fafc', border: `1px solid ${score == null ? '#e2e8f0' : scoreColor(score)}`,
        }}>
          <span style={{ fontSize: 16, fontWeight: 700, lineHeight: 1, color: score == null ? '#94a3b8' : scoreColor(score) }}>
            {score == null ? '—' : Math.round(score)}
          </span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
            <ModePill mode={row.mode} />
            <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {row.keyword}
            </span>
            {row.composite_status && (
              <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'capitalize', color: scoreColor(score) }}>
                {statusLabel(row.composite_status)}
              </span>
            )}
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {relativeTime(row.created_at)}
            {deficiencyCount > 0 && <> · {deficiencyCount} engine{deficiencyCount === 1 ? '' : 's'} below target</>}
            {row.page_url && <> · {row.page_url.replace(/^https?:\/\//, '')}</>}
          </div>
        </div>
      </button>
      {open && <EngineBreakdown row={row} />}
    </div>
  )
}

export function ScoreHistoryView({ clientId }: { clientId: string }) {
  const { data, isLoading, error, refetch, isFetching } = useQuery<ScoreHistoryRow[]>({
    queryKey: ['local-seo-score-history', clientId],
    queryFn: () => localSeoApi.scoreHistory(clientId, { limit: 200 }),
    enabled: Boolean(clientId),
  })

  const rows = useMemo(() => data ?? [], [data])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ ...card, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Score history</h2>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
            Every scoring run — standalone scores, generated pages, and reoptimizations (before &amp; after) — with the
            full 8-engine breakdown. Click a run to see each engine&apos;s score, issues and recommended fixes.
          </p>
        </div>
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          title="Refresh"
          style={{
            display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: '#475569',
            background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 12px',
            cursor: isFetching ? 'default' : 'pointer', opacity: isFetching ? 0.6 : 1, flexShrink: 0,
          }}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error && <div style={errorBox}>{error instanceof Error ? error.message : 'Failed to load score history.'}</div>}

      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}><Spinner size={22} /></div>
      ) : rows.length === 0 ? (
        <p style={{ fontSize: 14, color: '#94a3b8', textAlign: 'center', padding: 32 }}>
          No score runs yet. Scoring a page, generating one, or reoptimizing will record a run here.
        </p>
      ) : (
        rows.map(row => <HistoryRow key={row.id} row={row} />)
      )}
    </div>
  )
}
