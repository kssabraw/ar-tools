import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowLeft, CheckCircle, ChevronDown, ChevronUp, XCircle,
} from 'lucide-react'
import { ecommerceApi } from './api'
import { useResumableJob } from '../../lib/useResumableJob'
import type { EcommercePageDetail, EcommercePageType, ReoptimizeUrlResult, ScoreResult } from './types'
import { Spinner } from '../localseo/Spinner'
import { backLink, card, errorBox, outlineBtn, primaryBtn, scoreColor } from '../localseo/shared'

// Pages scoring at/above this are skipped server-side (kept in sync with the
// backend threshold). Surfaced here only as copy.
const SCORE_THRESHOLD = 75

// The 8 ecommerce scoring engines, rendered in this order with human labels.
export const ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  commercial_intent: 'Commercial Intent',
  product_content_depth: 'Product Content Depth',
  entity_establishment: 'Entity Establishment',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  conversion_readiness: 'Conversion Readiness',
  structured_data: 'Structured Data (Schema)',
  serp_signal_coverage: 'SERP Signal Coverage',
}

function EngineIcon({ score }: { score: number }) {
  if (score >= 80) return <CheckCircle size={16} color="#16a34a" />
  if (score >= 60) return <AlertTriangle size={16} color="#d97706" />
  return <XCircle size={16} color="#dc2626" />
}

interface Props {
  clientId: string
  keyword: string
  pageType: EcommercePageType
  // Provide at least one source for the page being scored.
  pageUrl?: string | null
  pageHtml?: string | null
  onBack: () => void
  onReoptimized: (page: EcommercePageDetail, prevScore: number) => void
  onCreateNew: () => void
  // Leave the score screen while the background reoptimize keeps running; the
  // page lands in Saved Pages when done.
  onLeaveBackground?: () => void
}

export function ProductScoreView({
  clientId, keyword, pageType, pageUrl, pageHtml, onBack, onReoptimized, onCreateNew, onLeaveBackground,
}: Props) {
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [reoptimizing, setReoptimizing] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const startedRef = useRef(false)
  // Reoptimize runs as a background job we poll. detachedRef short-circuits the
  // poll loop when the user leaves; pollRef lets unmount cancel the pending tick.
  const reoptPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reoptDetachedRef = useRef(false)

  useEffect(() => () => {
    reoptDetachedRef.current = true
    if (reoptPollRef.current) clearTimeout(reoptPollRef.current)
  }, [])

  // Score runs as a background job (it analyzes competitors first, which can take
  // minutes). The in-flight job id is persisted, so navigating away and back
  // reconnects and re-displays the score when it lands.
  const scoreJob = useResumableJob<ScoreResult, null>({
    storageKey: `ecommerce:score:${clientId}:${keyword}:${pageUrl ?? 'html'}`,
    poll: async (jobId) => {
      const [st] = await ecommerceApi.jobsStatus(clientId, [jobId])
      return st
        ? { status: st.status, result: (st.result as unknown as ScoreResult | null) ?? null, error: st.error }
        : { status: 'running' }
    },
    onComplete: (data) => {
      if (!data) { setError('Scoring returned no result.'); return }
      setResult(data)
    },
    onError: (err) => setError(err || 'Scoring failed'),
  })

  const runScore = async () => {
    setError('')
    await scoreJob.start(async () => {
      const { job_id } = await ecommerceApi.score(clientId, {
        keyword, page_type: pageType,
        page_url: pageUrl ?? null,
        page_content: pageHtml ?? null,
      })
      return job_id
    }, null)
  }
  const scoring = scoreJob.running

  // Auto-score on mount — the user explicitly opted into scoring this page —
  // unless a prior score job was already in flight (the hook reconnects to it).
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    if (scoreJob.phase === 'idle' && !result) void runScore()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Reoptimize via the bulk endpoint (single target). Needs a live page URL —
  // a generated page with no source URL can only be scored.
  const runReoptimize = async () => {
    if (!result || !pageUrl) return
    setReoptimizing(true)
    setError('')
    reoptDetachedRef.current = false
    const prevScore = result.composite_score
    try {
      const res = await ecommerceApi.reoptimizeBulk(clientId, {
        targets: [{ page_url: pageUrl, keyword, page_type: pageType }],
        score_threshold: SCORE_THRESHOLD,
      })
      const jobId = res.jobs?.[0]?.job_id
      if (!jobId) {
        setError('Could not start reoptimization.')
        setReoptimizing(false)
        return
      }

      const poll = async () => {
        if (reoptDetachedRef.current) return
        try {
          const [status] = await ecommerceApi.jobsStatus(clientId, [jobId])
          if (reoptDetachedRef.current) return
          if (!status || status.status === 'pending' || status.status === 'running') {
            reoptPollRef.current = setTimeout(() => { void poll() }, 4000)
            return
          }
          if (status.status === 'complete') {
            const outcome = status.result as unknown as ReoptimizeUrlResult | undefined
            if (outcome?.status === 'skipped') {
              setError(outcome.reason || `Page scored at/above ${SCORE_THRESHOLD} — no rewrite needed.`)
              setReoptimizing(false)
              return
            }
            const pageId = outcome?.page?.id
            if (!pageId) {
              setError('Reoptimize finished but returned no page.')
              setReoptimizing(false)
              return
            }
            const page = await ecommerceApi.getPage(pageId)
            if (reoptDetachedRef.current) return
            setReoptimizing(false)
            onReoptimized(page, prevScore)
            return
          }
          // failed / cancelled
          setError(status.error || 'Reoptimize failed')
          setReoptimizing(false)
        } catch (e) {
          if (reoptDetachedRef.current) return
          setError(e instanceof Error ? e.message : 'Reoptimize failed')
          setReoptimizing(false)
        }
      }
      void poll()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reoptimize failed')
      setReoptimizing(false)
    }
  }

  const leaveBackground = () => {
    reoptDetachedRef.current = true
    if (reoptPollRef.current) clearTimeout(reoptPollRef.current)
    onLeaveBackground?.()
  }

  const toggleExpand = (key: string) => setExpanded(prev => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <button onClick={onBack} style={backLink}><ArrowLeft size={14} /> Back</button>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Page Score</h1>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
        Keyword: <span style={{ fontWeight: 600 }}>{keyword}</span> · <span style={{ textTransform: 'capitalize' }}>{pageType}</span>
        {pageUrl && <> · <a href={pageUrl} target="_blank" rel="noreferrer" style={{ color: '#6366f1' }}>{pageUrl}</a></>}
      </p>

      {error && <div style={{ ...errorBox, marginBottom: 16 }}>{error}</div>}

      {!result && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center' }}>
          {scoring ? (
            <>
              <Spinner size={22} />
              <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
                Analyzing competitors &amp; scoring across 8 engines… (usually 1–3 minutes)
              </p>
            </>
          ) : (
            <button style={{ ...primaryBtn, width: '100%' }} onClick={runScore}>Score this page</button>
          )}
        </div>
      )}

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Composite */}
          <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 24 }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 48, fontWeight: 700, lineHeight: 1, color: scoreColor(result.composite_score) }}>{Math.round(result.composite_score)}</div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>/ 100</div>
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize', color: scoreColor(result.composite_score) }}>
                {result.composite_status.replace(/_/g, ' ')}
              </div>
              <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
                {result.deficiencies.length === 0
                  ? 'No improvements needed.'
                  : `${result.deficiencies.reduce((n, d) => n + (d.issues?.length ?? 1), 0)} issue(s) to address.`}
              </div>
            </div>
          </div>

          {/* Engine breakdown */}
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid #e2e8f0' }}>
              <h2 style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Engine Breakdown</h2>
            </div>
            {Object.entries(ENGINE_LABELS).map(([key, lbl], idx) => {
              const eng = result.engine_scores[key]
              if (!eng) return null
              const isOpen = expanded.has(key)
              const hasDetails = (eng.issues?.length || 0) + (eng.recommendations?.length || 0) > 0
              return (
                <div key={key} style={{ borderTop: idx ? '1px solid #f1f5f9' : 'none' }}>
                  <button
                    onClick={() => hasDetails && toggleExpand(key)}
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

          {/* Improve CTA */}
          <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {result.deficiencies.length > 0 && pageUrl ? (
              <>
                <div>
                  <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Improve this page</p>
                  <p style={{ fontSize: 13, color: '#64748b', margin: '2px 0 0' }}>
                    Rewrites the live page against the failing engines. The reoptimized page is saved as a new version.
                  </p>
                </div>
                <button
                  style={{ ...primaryBtn, width: '100%', opacity: reoptimizing ? 0.6 : 1 }}
                  disabled={reoptimizing}
                  onClick={runReoptimize}
                >
                  {reoptimizing ? <><Spinner size={16} color="#fff" /> Rewriting page… (1–4 min)</> : 'Fix all issues'}
                </button>
                {reoptimizing && onLeaveBackground ? (
                  <button style={{ ...outlineBtn, width: '100%' }} onClick={leaveBackground}>
                    Leave &amp; finish in the background
                  </button>
                ) : (
                  <button style={{ ...outlineBtn, width: '100%' }} disabled={reoptimizing} onClick={onCreateNew}>
                    Create a new page instead
                  </button>
                )}
              </>
            ) : result.deficiencies.length > 0 ? (
              <>
                <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
                  This page has {result.deficiencies.length} improvement area(s). Reoptimization runs against a live URL —
                  publish this page (or paste its live URL in the Reoptimize tab) to rewrite it.
                </p>
                <button style={{ ...outlineBtn, width: '100%' }} onClick={onCreateNew}>Create a new page instead</button>
              </>
            ) : (
              <>
                <p style={{ fontSize: 14, color: '#16a34a', fontWeight: 600, textAlign: 'center', margin: 0 }}>No reoptimizations advised.</p>
                <button style={{ ...outlineBtn, width: '100%' }} onClick={onCreateNew}>Create a new page anyway</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
