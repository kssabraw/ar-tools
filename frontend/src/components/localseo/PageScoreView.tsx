import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowLeft, CheckCircle, ChevronDown, ChevronUp, XCircle,
} from 'lucide-react'
import { localSeoApi } from './api'
import type { AnalysisResult, Deficiency, LocalSeoPageDetail, ScoreResult } from './types'
import { Spinner } from './Spinner'
import {
  backLink, card, errorBox, outlineBtn, primaryBtn, scoreColor,
} from './shared'

interface Props {
  clientId: string
  keyword: string
  location: string
  // Provide exactly one source for the page being scored/reoptimized.
  pageUrl?: string | null
  pageHtml?: string | null
  serpAnalysis?: AnalysisResult | null
  onBack: () => void
  onReoptimized: (page: LocalSeoPageDetail, prevScore: number) => void
  onCreateNew: () => void
  // Leave the score screen while the background reoptimize keeps running; the
  // page lands in Saved Pages when done.
  onLeaveBackground?: () => void
}

const ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  gbp_maps: 'GBP / Maps Relevance',
  entity_establishment: 'Entity Establishment',
  icp_alignment: 'ICP Alignment',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  geographic_legitimacy: 'Geographic Legitimacy',
  nearme_intent: 'Hyperlocal / Near-Me',
}

function EngineIcon({ score }: { score: number }) {
  if (score >= 80) return <CheckCircle size={16} color="#16a34a" />
  if (score >= 60) return <AlertTriangle size={16} color="#d97706" />
  return <XCircle size={16} color="#dc2626" />
}

export function PageScoreView({
  clientId, keyword, location, pageUrl, pageHtml, serpAnalysis, onBack, onReoptimized, onCreateNew,
  onLeaveBackground,
}: Props) {
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [scoring, setScoring] = useState(false)
  const [reoptimizing, setReoptimizing] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const startedRef = useRef(false)
  // Reoptimize runs as a background job we poll. detachedRef short-circuits the
  // poll loop when the user leaves; pollRef lets unmount cancel the pending tick.
  const reoptPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reoptDetachedRef = useRef(false)

  useEffect(() => () => {
    reoptDetachedRef.current = true
    if (reoptPollRef.current) clearTimeout(reoptPollRef.current)
  }, [])

  const runScore = async () => {
    setScoring(true)
    setError('')
    try {
      const data = await localSeoApi.score(clientId, {
        keyword, location,
        page_url: pageUrl ?? null,
        page_content: pageHtml ?? null,
        serp_analysis: serpAnalysis ?? null,
      })
      setResult(data)
      setSelected(new Set(data.deficiencies.map(d => d.engine_key)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Scoring failed')
    } finally {
      setScoring(false)
    }
  }

  // Auto-score on mount — the user explicitly opted into scoring this page.
  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    void runScore()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const runReoptimize = async (deficiencies: Deficiency[]) => {
    if (!result) return
    setReoptimizing(true)
    setError('')
    reoptDetachedRef.current = false
    const prevScore = result.composite_score
    try {
      const res = await localSeoApi.reoptimizeAsync(clientId, {
        keyword, location,
        existing_page_html: pageHtml ?? null,
        existing_page_url: pageUrl ?? null,
        deficiencies: deficiencies as unknown as Array<Record<string, unknown>>,
        serp_analysis: result.serp_analysis ?? serpAnalysis ?? null,
      })
      const jobId = res.job_id

      const poll = async () => {
        if (reoptDetachedRef.current) return
        try {
          const [status] = await localSeoApi.jobsStatus(clientId, [jobId])
          if (reoptDetachedRef.current) return
          if (!status || status.status === 'pending' || status.status === 'running') {
            reoptPollRef.current = setTimeout(() => { void poll() }, 4000)
            return
          }
          if (status.status === 'complete') {
            const pageId = status.result?.page_id as string | undefined
            if (!pageId) {
              setError('Reoptimize finished but returned no page.')
              setReoptimizing(false)
              return
            }
            const page = await localSeoApi.getPage(pageId)
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
  const toggleSelect = (key: string) => setSelected(prev => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <button onClick={onBack} style={backLink}><ArrowLeft size={14} /> Back</button>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Page Score</h1>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
        Keyword: <span style={{ fontWeight: 600 }}>{keyword}</span>
        {pageUrl && <> · <a href={pageUrl} target="_blank" rel="noreferrer" style={{ color: '#6366f1' }}>{pageUrl}</a></>}
      </p>

      {error && <div style={{ ...errorBox, marginBottom: 16 }}>{error}</div>}

      {!result && (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center' }}>
          {scoring ? (
            <>
              <Spinner size={22} />
              <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
                {serpAnalysis ? 'Scoring page…' : 'Analyzing competitors & scoring… (usually 1–3 minutes)'}
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
                  <div style={{ display: 'flex', alignItems: 'center' }}>
                    {eng.score < 80 && (
                      <label style={{ paddingLeft: 16, display: 'flex', alignItems: 'center', cursor: 'pointer' }} title="Select to fix">
                        <input type="checkbox" checked={selected.has(key)} onChange={() => toggleSelect(key)} />
                      </label>
                    )}
                    <button
                      onClick={() => hasDetails && toggleExpand(key)}
                      style={{
                        flex: 1, display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
                        paddingLeft: eng.score >= 80 ? 20 : 12, background: 'none', border: 'none',
                        cursor: hasDetails ? 'pointer' : 'default', textAlign: 'left',
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
                  </div>
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
            {result.deficiencies.length > 0 ? (
              <>
                <div>
                  <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Improve this page</p>
                  <p style={{ fontSize: 13, color: '#64748b', margin: '2px 0 0' }}>
                    Select engines above to fix, or fix everything. The reoptimized page is saved as a new version.
                  </p>
                </div>
                <button
                  style={{ ...primaryBtn, width: '100%', opacity: reoptimizing ? 0.6 : 1 }}
                  disabled={reoptimizing}
                  onClick={() => runReoptimize(result.deficiencies)}
                >
                  {reoptimizing ? <><Spinner size={16} color="#fff" /> Rewriting page… (1–4 min)</> : 'Fix all issues'}
                </button>
                {selected.size > 0 && selected.size < result.deficiencies.length && (
                  <button
                    style={{ ...outlineBtn, width: '100%' }}
                    disabled={reoptimizing}
                    onClick={() => runReoptimize(result.deficiencies.filter(d => selected.has(d.engine_key)))}
                  >
                    Fix selected ({selected.size})
                  </button>
                )}
                {reoptimizing && onLeaveBackground ? (
                  <button style={{ ...outlineBtn, width: '100%' }} onClick={leaveBackground}>
                    Leave & finish in the background
                  </button>
                ) : (
                  <button style={{ ...outlineBtn, width: '100%' }} disabled={reoptimizing} onClick={onCreateNew}>
                    Create a new page instead
                  </button>
                )}
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
