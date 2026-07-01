import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, Check, Download, ExternalLink, Ban, CheckCircle, XCircle, Loader, Gauge, Sparkles } from 'lucide-react'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType, ServiceWriterOutput } from '../lib/types'
import type { ScoreResult } from './localseo/types'

function scoreColor(s: number) {
  return s >= 90 ? '#16a34a' : s >= 70 ? '#ca8a04' : '#dc2626'
}

const TERMINAL = ['complete', 'failed', 'cancelled']

type Fmt = 'markdown' | 'html' | 'wordpress'

function download(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      style={btnStyle}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function StageChip({ label, status }: { label: string; status?: string | null }) {
  const s = status ?? 'pending'
  const color = s === 'complete' ? '#16a34a' : s === 'failed' ? '#dc2626' : s === 'running' ? '#6366f1' : '#94a3b8'
  const Icon = s === 'complete' ? CheckCircle : s === 'failed' ? XCircle : s === 'running' ? Loader : Loader
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color, padding: '4px 10px', border: `1px solid ${color}33`, borderRadius: 8, background: `${color}11` }}>
      <Icon size={14} /> {label}: {s}
    </span>
  )
}

export function ServicePageRunView({ run }: { run: RunDetailType }) {
  const queryClient = useQueryClient()
  const [fmt, setFmt] = useState<Fmt>('wordpress')
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)
  const [wpStatus, setWpStatus] = useState<'draft' | 'publish'>('draft')
  const [wpUrl, setWpUrl] = useState<string | null>(null)

  // A location page is the multi-service hub variant — same pipeline + view,
  // only the labels + scoring mode differ (local engines, incl. geo).
  const isLocation = run.content_type === 'location_page'
  const kindLabel = isLocation ? 'Location Page' : 'Service Page'
  const backPath = isLocation
    ? `/clients/${run.client_id}/location-pages`
    : `/clients/${run.client_id}/service-pages`
  const scoreNote = isLocation ? 'local engines, incl. geo' : 'location-agnostic'

  const publishMutation = useMutation({
    mutationFn: () => api.post<{ doc_url: string }>(`/runs/${run.id}/publish`, {}),
    onSuccess: (data) => {
      setPublishedUrl(data.doc_url)
      window.open(data.doc_url, '_blank')
    },
  })
  // Publish straight to the client's WordPress site (as a Page), draft or live.
  const wpPublishMutation = useMutation({
    mutationFn: () => api.post<{ url: string; edit_url: string }>(
      `/runs/${run.id}/publish`, { destination: 'wordpress', status: wpStatus },
    ),
    onSuccess: (data) => {
      const link = data.edit_url || data.url
      setWpUrl(link)
      if (link) window.open(link, '_blank')
    },
  })
  const cancelMutation = useMutation({
    mutationFn: () => api.post(`/runs/${run.id}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', run.id] }),
  })

  // Score / reoptimize (nlp-api national mode, via the service writer).
  const persistedScore = (run.module_outputs?.service_score?.output_payload ?? null) as unknown as ScoreResult | null
  const [score, setScore] = useState<ScoreResult | null>(persistedScore)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Seed from the auto-score once it arrives (without clobbering a manual re-score).
  useEffect(() => {
    if (!score && persistedScore) setScore(persistedScore)
  }, [persistedScore, score])

  const scoreMutation = useMutation({
    mutationFn: () => api.stream<ScoreResult>(`/runs/${run.id}/score`, {}),
    onSuccess: (data) => { setScore(data); setSelected(new Set()) },
  })
  const reoptMutation = useMutation({
    mutationFn: () => {
      const defs = (score?.deficiencies ?? []).filter(
        (d) => selected.size === 0 || selected.has(d.engine_key),
      )
      return api.stream<{ score: ScoreResult }>(`/runs/${run.id}/reoptimize`, { deficiencies: defs })
    },
    onSuccess: (data) => {
      if (data?.score) setScore(data.score)
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ['run', run.id] })
    },
  })

  const sw = (run.module_outputs?.service_writer?.output_payload ?? null) as unknown as ServiceWriterOutput | null
  const isLive = !TERMINAL.includes(run.status)
  const rendering = sw ? sw.renderings?.[fmt] ?? '' : ''
  const ext = fmt === 'markdown' ? 'md' : fmt === 'html' ? 'html' : 'html'

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={backPath} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {isLocation ? 'Location Pages' : 'Service Pages'}
      </Link>

      <div style={{ marginTop: 16, marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#6366f1', textTransform: 'uppercase', letterSpacing: 0.5 }}>{kindLabel}</span>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '4px 0 0' }}>
          {sw?.title || run.title || run.keyword}
        </h1>
        {sw?.meta_description && <p style={{ color: '#64748b', margin: '6px 0 0', fontSize: 14 }}>{sw.meta_description}</p>}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '16px 0' }}>
        <StageChip label="Brief" status={run.module_outputs?.service_brief?.status} />
        <StageChip label="Writer" status={run.module_outputs?.service_writer?.status} />
        {isLive && (
          <button type="button" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending} style={btnStyle}>
            <Ban size={14} /> Cancel
          </button>
        )}
      </div>

      {run.status === 'failed' && (
        <div style={{ padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
          {run.error_message || 'Generation failed.'}
        </div>
      )}

      {isLive && <div style={{ color: '#64748b', fontSize: 14 }}>Generating… this page refreshes automatically.</div>}

      {sw && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '8px 0 12px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4, border: '1px solid #e2e8f0', borderRadius: 8, padding: 3 }}>
              {(['wordpress', 'html', 'markdown'] as Fmt[]).map((f) => (
                <button key={f} type="button" onClick={() => setFmt(f)}
                  style={{ ...tabStyle, ...(fmt === f ? tabActiveStyle : {}) }}>
                  {f === 'wordpress' ? 'WordPress' : f === 'html' ? 'HTML' : 'Markdown'}
                </button>
              ))}
            </div>
            <CopyButton text={rendering} />
            <button type="button" onClick={() => download(rendering, `${run.keyword}.${ext}`, 'text/plain')} style={btnStyle}>
              <Download size={14} /> Download
            </button>
            <button type="button" onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending} style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1' }}>
              {publishMutation.isPending ? 'Publishing…' : 'Publish to Google Doc'}
            </button>
            {publishedUrl && (
              <a href={publishedUrl} target="_blank" rel="noreferrer" style={{ ...btnStyle, textDecoration: 'none' }}>
                <ExternalLink size={14} /> Open Doc
              </a>
            )}
            {wpUrl ? (
              <a href={wpUrl} target="_blank" rel="noreferrer" style={{ ...btnStyle, textDecoration: 'none', color: '#16a34a', borderColor: '#bbf7d0' }}>
                <ExternalLink size={14} /> Open in WP
              </a>
            ) : (
              <div style={{ display: 'inline-flex', border: '1px solid #c7d2fe', borderRadius: 8, overflow: 'hidden' }}>
                <select
                  value={wpStatus}
                  onChange={(e) => setWpStatus(e.target.value as 'draft' | 'publish')}
                  style={{ border: 'none', background: '#fff', color: '#6366f1', fontSize: 13, fontWeight: 600, padding: '0 6px', cursor: 'pointer' }}
                  title="Draft saves to WordPress unpublished; Publish goes live"
                >
                  <option value="draft">Draft</option>
                  <option value="publish">Publish</option>
                </select>
                <button
                  type="button"
                  onClick={() => wpPublishMutation.mutate()}
                  disabled={wpPublishMutation.isPending}
                  style={{ ...btnStyle, border: 'none', borderLeft: '1px solid #c7d2fe', borderRadius: 0, color: '#6366f1' }}
                  title="Publish directly to the client's WordPress site"
                >
                  <ExternalLink size={14} /> {wpPublishMutation.isPending ? 'Publishing…' : 'Publish to Website'}
                </button>
              </div>
            )}
          </div>
          {(publishMutation.error || wpPublishMutation.error) && (
            <div style={errStyle}>
              {((publishMutation.error || wpPublishMutation.error) as Error).message}
            </div>
          )}
          {fmt === 'wordpress' && (
            <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 8px' }}>
              Gutenberg block markup — paste into the WordPress block editor (Code editor) and it converts to native blocks.
            </p>
          )}
          <pre style={preStyle}>{rendering}</pre>

          {sw.schema_jsonld && (
            <details style={{ marginTop: 16 }}>
              <summary style={{ cursor: 'pointer', fontSize: 14, fontWeight: 600, color: '#334155' }}>
                JSON-LD structured data (Service + FAQPage)
              </summary>
              <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '8px 0' }}>
                <CopyButton text={sw.schema_jsonld} />
              </div>
              <pre style={preStyle}>{sw.schema_jsonld}</pre>
            </details>
          )}

          {/* Score + reoptimize ({scoreNote} engines) */}
          <div style={{ marginTop: 28, borderTop: '1px solid #e2e8f0', paddingTop: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }}>Page score</h3>
              <button type="button" onClick={() => scoreMutation.mutate()}
                disabled={scoreMutation.isPending || reoptMutation.isPending} style={btnStyle}>
                <Gauge size={14} /> {scoreMutation.isPending ? 'Scoring…' : score ? 'Re-score' : 'Score'}
              </button>
              {score && (
                <button type="button" onClick={() => reoptMutation.mutate()}
                  disabled={reoptMutation.isPending || scoreMutation.isPending}
                  style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1' }}>
                  <Sparkles size={14} /> {reoptMutation.isPending ? 'Reoptimizing…' : selected.size ? `Reoptimize (${selected.size})` : 'Reoptimize'}
                </button>
              )}
            </div>
            {scoreMutation.isError && <div style={errStyle}>Could not score the page. {(scoreMutation.error as Error)?.message}</div>}
            {reoptMutation.isError && <div style={errStyle}>Could not reoptimize. {(reoptMutation.error as Error)?.message}</div>}
            {reoptMutation.isPending && (
              <div style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
                Rewriting the page to fix the selected issues — this can take a minute, then it re-scores.
              </div>
            )}
            {score ? (
              <div style={{ marginTop: 12 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontSize: 34, fontWeight: 800, color: scoreColor(score.composite_score) }}>
                    {Math.round(score.composite_score)}
                  </span>
                  <span style={{ fontSize: 13, color: '#64748b' }}>/ 100 · {score.composite_status}</span>
                </div>
                {score.deficiencies?.length ? (
                  <>
                    <p style={{ fontSize: 13, color: '#475569', margin: '12px 0 6px' }}>
                      Select issues to fix, then Reoptimize (none selected = fix all):
                    </p>
                    {score.deficiencies.map((d) => (
                      <label key={d.engine_key} style={{ display: 'block', border: '1px solid #e2e8f0', borderRadius: 8, padding: 10, marginBottom: 8, cursor: 'pointer' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <input type="checkbox" checked={selected.has(d.engine_key)}
                            onChange={(e) => setSelected((prev) => {
                              const n = new Set(prev)
                              if (e.target.checked) n.add(d.engine_key); else n.delete(d.engine_key)
                              return n
                            })} />
                          <span style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{d.engine}</span>
                          <span style={{ fontSize: 12, color: scoreColor(d.score ?? 0) }}>{d.score ?? 0}/100</span>
                        </div>
                        {!!d.issues?.length && <ul style={defListStyle}>{d.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>}
                        {!!d.recommendations?.length && (
                          <ul style={{ ...defListStyle, color: '#16a34a' }}>{d.recommendations.map((r, k) => <li key={k}>{r}</li>)}</ul>
                        )}
                      </label>
                    ))}
                  </>
                ) : (
                  <p style={{ fontSize: 13, color: '#16a34a', marginTop: 10 }}>No deficiencies — this page scores well across all engines.</p>
                )}
              </div>
            ) : (
              !scoreMutation.isPending && (
                <p style={{ fontSize: 13, color: '#64748b', marginTop: 10 }}>
                  Score this page against the SEO/AEO engines ({scoreNote}) to see per-engine deficiencies, then reoptimize.
                </p>
              )
            )}
          </div>
        </>
      )}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }
const btnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '6px 12px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer' }
const tabStyle: React.CSSProperties = { fontSize: 13, padding: '5px 12px', border: 'none', borderRadius: 6, background: 'transparent', color: '#64748b', cursor: 'pointer' }
const tabActiveStyle: React.CSSProperties = { background: '#eef2ff', color: '#6366f1', fontWeight: 600 }
const preStyle: React.CSSProperties = { background: '#0f172a', color: '#e2e8f0', padding: 16, borderRadius: 10, overflow: 'auto', maxHeight: 480, fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }
const errStyle: React.CSSProperties = { color: '#dc2626', fontSize: 13, marginTop: 8 }
const defListStyle: React.CSSProperties = { margin: '6px 0 0 26px', padding: 0, fontSize: 12.5, color: '#64748b', lineHeight: 1.5 }
