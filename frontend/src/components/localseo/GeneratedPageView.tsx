import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, Check, Copy, Download, ExternalLink, TrendingUp, Wand2, Megaphone, RefreshCw,
} from 'lucide-react'
import { GbpWorkspace } from '../../pages/GbpPosts'
import { localSeoApi } from './api'
import { useResumableJob } from '../../lib/useResumableJob'
import type { LocalSeoPageDetail, SocialPostsResult, EngineScore } from './types'
import { RelatedPagesList } from './RelatedPagesList'
import { VoiceCompliancePanel } from './VoiceCompliancePanel'
import { BulkCreateBar } from './BulkCreateBar'
import { useSiloPlan } from './useSiloPlan'
import { useBulkCreate } from './useBulkCreate'
import { Spinner } from './Spinner'
import { FeaturedImagePicker } from '../FeaturedImagePicker'
import { ErrorDetails } from '../ErrorDetails'
import {
  backLink, card, downloadFile, errorBox, formatHtml, htmlToText, outlineBtn,
  primaryBtn, relativeTime, scoreBg, scoreBorder, scoreColor, statusLabel, wordCount,
} from './shared'

// Scoped article styling for the rendered page HTML. Class-prefixed so it can't
// leak past the preview; hoisted to a module const (matches e.g. MapsReport's
// PRINT_CSS) so it isn't re-created on every render. Tables get display:block +
// overflow-x so a wide table scrolls inside the card instead of overflowing it.
const PREVIEW_CSS = `
  .seo-preview { line-height: 1.7; color: #1e293b; font-size: 15px; }
  .seo-preview h1 { font-size: 24px; font-weight: 700; color: #0f172a; margin: 0 0 16px; line-height: 1.25; }
  .seo-preview h2 { font-size: 19px; font-weight: 700; color: #0f172a; margin: 32px 0 12px; line-height: 1.3; }
  .seo-preview h3 { font-size: 16px; font-weight: 600; color: #0f172a; margin: 24px 0 10px; }
  .seo-preview p { margin: 0 0 18px; }
  .seo-preview ul, .seo-preview ol { margin: 0 0 18px; padding-left: 22px; }
  .seo-preview li { margin: 0 0 8px; }
  .seo-preview table { display: block; overflow-x: auto; border-collapse: collapse; width: 100%; margin: 8px 0 22px; font-size: 14px; }
  .seo-preview th, .seo-preview td { border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; vertical-align: top; }
  .seo-preview th { background: #f8fafc; font-weight: 600; color: #0f172a; }
  .seo-preview a { color: #6366f1; }
`

// SERP-signal coverage: how well the page covers the entities, keywords and
// competitor phrases mined from the SERP. Rendered between the Brand Voice panel
// and the "How to reach 100" gaps. Degrades gracefully — older saved pages carry
// only the coverage percentages (no entities_used / zones), and a page scored
// without a SERP analysis carries none of it, so the panel simply hides.
function SearchCoveragePanel({ coverage }: { coverage?: EngineScore }) {
  if (!coverage || coverage.entity_coverage == null) return null
  const pct = (n?: number) => (n == null ? '—' : `${Math.round(n)}%`)
  const used = coverage.entities_used ?? []
  const missing = coverage.entities_missing ?? []
  const zones = coverage.zones ?? []
  const recs = coverage.recommendations ?? []
  const entityDetail = coverage.entity_detail ?? []
  const totalShortfall = coverage.total_entity_shortfall ?? 0
  const chip = (text: string, bg: string, color: string) => (
    <span key={text} style={{ fontSize: 12, fontWeight: 600, padding: '3px 9px', borderRadius: 999, background: bg, color }}>{text}</span>
  )
  const th: CSSProperties = { textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#64748b', padding: '6px 12px', textTransform: 'uppercase', letterSpacing: 0.3 }
  const td: CSSProperties = { fontSize: 13, color: '#0f172a', padding: '6px 12px', borderTop: '1px solid #f1f5f9' }
  const cell = (found?: number, target?: number) =>
    found == null || target == null ? '—' : `${found}/${target}${found >= target ? ' ✓' : ''}`
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ background: '#f8fafc', padding: '16px 20px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>Search coverage</p>
          <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>How well this page covers the entities, keywords and competitor phrases from the SERP.</p>
        </div>
        <span style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', whiteSpace: 'nowrap' }}>{pct(coverage.score)}</span>
      </div>
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Total coverage */}
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          {[
            ['Entities', coverage.entity_coverage],
            ['Keywords', coverage.keyword_coverage],
            ['Competitor phrases', coverage.quadgram_coverage],
          ].map(([label, val]) => (
            <div key={label as string}>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', lineHeight: 1.1 }}>{pct(val as number | undefined)}</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>{label}</div>
            </div>
          ))}
        </div>

        {/* Entities used / missing */}
        {(used.length > 0 || missing.length > 0) && (
          <div>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>
              Entities used {used.length > 0 && `(${used.length})`}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {used.map((e) => chip(e, '#ecfdf5', '#047857'))}
              {missing.map((e) => chip(e, '#fef2f2', '#b91c1c'))}
            </div>
            {missing.length > 0 && (
              <p style={{ fontSize: 11, color: '#94a3b8', margin: '6px 0 0' }}>Red = target entities not yet on the page.</p>
            )}
          </div>
        )}

        {/* Entity targets — Cora-style: current vs recommended mentions per entity */}
        {entityDetail.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>
              Entity targets{totalShortfall > 0 && ` — ${totalShortfall} mention${totalShortfall > 1 ? 's' : ''} to add`}
            </p>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 360 }}>
              <thead>
                <tr>
                  <th style={th}>Entity</th>
                  <th style={{ ...th, textAlign: 'right' }}>On page</th>
                  <th style={{ ...th, textAlign: 'right' }}>Target</th>
                  <th style={{ ...th, textAlign: 'right' }}>Needed</th>
                </tr>
              </thead>
              <tbody>
                {entityDetail.map((e) => {
                  const short = e.shortfall > 0
                  return (
                    <tr key={e.name} style={short ? { background: '#fef2f2' } : undefined}>
                      <td style={{ ...td, fontWeight: short ? 600 : 400 }}>{e.name}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{e.current}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{e.recommended}</td>
                      <td style={{ ...td, textAlign: 'right', color: short ? '#b91c1c' : '#94a3b8', fontWeight: short ? 700 : 400 }}>
                        {short ? `+${e.shortfall}` : '✓'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: '#94a3b8', margin: '6px 0 0' }}>
              Target = average mentions across the top-ranking competitor pages. "Needed" is how many more times to use the entity on this page.
            </p>
          </div>
        )}

        {/* Coverage by zone */}
        {zones.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>Coverage by zone</p>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 360 }}>
              <thead>
                <tr>
                  <th style={th}>Zone</th>
                  <th style={th}>Keywords</th>
                  <th style={th}>Entities</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((z) => (
                  <tr key={z.zone}>
                    <td style={td}>{z.zone}</td>
                    <td style={td}>{cell(z.keyword_found, z.keyword_target)}</td>
                    <td style={td}>{cell(z.entity_found, z.entity_target)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Recommendations */}
        {recs.length > 0 && (
          <div>
            <p style={{ fontSize: 12, fontWeight: 600, color: '#475569', margin: '0 0 6px' }}>Recommendations</p>
            <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {recs.map((r, i) => (
                <li key={i} style={{ fontSize: 12, color: '#475569' }}>{r}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

interface Props {
  clientId: string
  page: LocalSeoPageDetail
  isNew?: boolean
  prevScore?: number | null
  onBack: () => void
  onScoreAndImprove: (page: LocalSeoPageDetail) => void
  onRelatedAction: (action: { mode: 'reoptimize' | 'new'; keyword: string; existingUrl?: string }) => void
  onNewPage: () => void
}

type Tab = 'preview' | 'html' | 'social' | 'related'

export function GeneratedPageView({
  clientId, page, isNew, prevScore, onBack, onScoreAndImprove, onRelatedAction, onNewPage,
}: Props) {
  const { keyword, location, content_html, schema_json, page_title, content_gaps, voice_violations, engine_scores, mode } = page
  const score = page.composite_score
  const status = page.composite_status

  const [tab, setTab] = useState<Tab>('preview')
  const [copiedHtml, setCopiedHtml] = useState(false)
  const [copiedSchema, setCopiedSchema] = useState(false)

  // Publish to Google Doc (client's Drive folder) or WordPress (client's site).
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState('')
  const [publishedUrl, setPublishedUrl] = useState<string | null>(page.published_doc_url)
  const [wpPublishing, setWpPublishing] = useState(false)
  const [wpStatus, setWpStatus] = useState<'draft' | 'publish'>('draft')
  const [wpUrl, setWpUrl] = useState<string | null>(page.published_url ?? null)
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(page.featured_image_url ?? null)

  const handleFeaturedImage = async (url: string | null) => {
    await localSeoApi.setFeaturedImage(page.id, url)
    setFeaturedImageUrl(url)
  }

  // Re-runs whichever publish destination was blocked, with force_voice — wired
  // to the error accordion's "Publish anyway" override so a brand-guide block
  // (an LLM-distilled never-use list can misfire) isn't a dead end. The raw
  // error code is stored as-is; ErrorDetails turns it into guidance.
  const forceRetry = useRef<(() => void) | null>(null)

  const handlePublish = async (forceVoice = false) => {
    setPublishing(true)
    setPublishError('')
    try {
      const res = await localSeoApi.publishPage(
        page.id, forceVoice ? { force_voice: true } : {},
      )
      setPublishedUrl(res.doc_url ?? null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Publish failed'
      forceRetry.current = () => handlePublish(true)
      setPublishError(msg)
    } finally {
      setPublishing(false)
    }
  }

  const handleWpPublish = async (forceVoice = false) => {
    setWpPublishing(true)
    setPublishError('')
    try {
      const res = await localSeoApi.publishPage(page.id, {
        destination: 'wordpress', status: wpStatus, ...(forceVoice ? { force_voice: true } : {}),
      })
      const link = res.edit_url || res.url || null
      setWpUrl(link)
      if (link) window.open(link, '_blank')
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Publish failed'
      forceRetry.current = () => handleWpPublish(true)
      setPublishError(msg)
    } finally {
      setWpPublishing(false)
    }
  }

  const queryClient = useQueryClient()
  // Social posts — generated ONCE and saved on the page (page.social_posts), so
  // re-opening the tab re-reads them instead of paying for a fresh generation.
  // Seeded from the saved set; an explicit Regenerate overwrites it.
  const [social, setSocial] = useState<SocialPostsResult | null>(page.social_posts ?? null)
  const [socialError, setSocialError] = useState('')
  const [copiedPost, setCopiedPost] = useState<string | null>(null)
  const [gbpSeed, setGbpSeed] = useState<{ text: string; nonce: number } | undefined>(undefined)
  const socialRequested = useRef(false)
  const socialJob = useResumableJob<SocialPostsResult, null>({
    storageKey: `localseo:social:${clientId}:${page.id}`,
    poll: async (jobId) => {
      const [st] = await localSeoApi.jobsStatus(clientId, [jobId])
      return st
        ? { status: st.status, result: (st.result as SocialPostsResult | null) ?? null, error: st.error }
        : { status: 'running' }
    },
    onComplete: (data) => {
      if (data) { setSocial(data); queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] }) }
      else setSocialError('No posts returned.')
    },
    onError: (err) => setSocialError(err || 'Could not generate posts'),
  })
  const socialLoading = socialJob.running

  // Related pages — the Fanout-powered silo plan (same engine as the Plan Silo
  // tab), seeded from this page's keyword + area. Lazily kicked off when the tab
  // is first opened; it runs as an async job, so we poll via the shared hook.
  const relatedPlan = useSiloPlan(clientId)
  const relatedRequested = useRef(false)
  // Multi-select bulk creation of the missing related pages (same flow as the
  // Plan Silo tab). Refresh the saved-pages list as pages land.
  const bulk = useBulkCreate(clientId, () =>
    queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] }),
  )

  const fetchSocial = async () => {
    setSocialError('')
    await socialJob.start(async () => {
      const { job_id } = await localSeoApi.socialPosts(clientId, {
        keyword, location, page_content: htmlToText(content_html), page_id: page.id,
      })
      return job_id
    }, null)
  }

  const fetchRelated = () => { bulk.reset(); void relatedPlan.run(keyword, location) }

  useEffect(() => {
    if (tab === 'social' && !socialRequested.current) {
      socialRequested.current = true
      // Skip if a prior job is already reconnecting or posts are already in hand.
      if (socialJob.phase === 'idle' && !social) void fetchSocial()
    }
    if (tab === 'related' && !relatedRequested.current) {
      relatedRequested.current = true
      fetchRelated()
    }
  }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const fullHtml = (page_title ? `<title>${page_title}</title>\n\n` : '') + formatHtml(content_html)

  const copyHtml = async () => {
    await navigator.clipboard.writeText(fullHtml)
    setCopiedHtml(true)
    setTimeout(() => setCopiedHtml(false), 2000)
  }
  const copySchema = async () => {
    await navigator.clipboard.writeText(schema_json)
    setCopiedSchema(true)
    setTimeout(() => setCopiedSchema(false), 2000)
  }
  const downloadHtml = () => {
    const slug = keyword.replace(/\s+/g, '-').toLowerCase()
    downloadFile(fullHtml, `${slug}.html`, 'text/html')
  }
  const copyPost = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text)
    setCopiedPost(id)
    setTimeout(() => setCopiedPost(null), 2000)
  }
  const downloadSocial = () => {
    if (!social) return
    const text = `GBP POSTS\n${'-'.repeat(40)}\n${social.gbp.map((p, i) => `${i + 1}. ${p}`).join('\n\n')}`
    downloadFile(text, `${keyword.replace(/\s+/g, '-')}-gbp-posts.txt`, 'text/plain')
  }

  const TABS: Array<{ key: Tab; label: string; busy?: boolean }> = [
    { key: 'preview', label: 'Preview' },
    { key: 'html', label: 'HTML' },
    { key: 'social', label: 'GBP Posts', busy: socialLoading },
    { key: 'related', label: 'Related Pages', busy: relatedPlan.loading },
  ]

  return (
    <div style={{ maxWidth: 920, margin: '0 auto' }}>
      <button onClick={onBack} style={backLink}><ArrowLeft size={14} /> Back</button>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>
            {mode === 'reoptimize' ? 'Reoptimized Page' : 'Generated Page'}
          </h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
            <span style={{ fontWeight: 600 }}>{keyword}</span> · {location.split(',')[0]} · ~{wordCount(content_html)} words
            <span style={{ marginLeft: 8, opacity: 0.7 }}>{relativeTime(page.created_at)}</span>
          </p>
        </div>
      </div>

      {/* Score banner */}
      {score != null && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 16, padding: '14px 18px', borderRadius: 12,
          background: scoreBg(score), border: `1px solid ${scoreBorder(score)}`, marginBottom: 16,
        }}>
          <TrendingUp size={20} color={scoreColor(score)} style={{ flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <p style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 2px' }}>SEO Score</p>
            {mode === 'reoptimize' && prevScore != null ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: '#94a3b8' }}>{Math.round(prevScore)}</span>
                <ArrowRight size={16} color="#94a3b8" />
                <span style={{ fontSize: 20, fontWeight: 700, color: scoreColor(score) }}>{Math.round(score)}</span>
                <span style={{ fontSize: 13, color: '#64748b' }}>/ 100</span>
                {score > prevScore && (
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#16a34a', background: '#f0fdf4', borderRadius: 999, padding: '2px 8px' }}>
                    +{Math.round(score - prevScore)} pts
                  </span>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: scoreColor(score) }}>{Math.round(score)}</span>
                <span style={{ fontSize: 13, color: '#64748b' }}>/ 100</span>
              </div>
            )}
          </div>
          {status && <p style={{ fontSize: 12, color: '#64748b', textTransform: 'capitalize', margin: 0 }}>{statusLabel(status)}</p>}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '9px 14px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
              background: 'none', border: 'none', borderBottom: '2px solid',
              borderBottomColor: tab === t.key ? '#6366f1' : 'transparent',
              color: tab === t.key ? '#0f172a' : '#94a3b8', marginBottom: -1,
            }}
          >
            {t.label}{t.busy && <Spinner size={12} />}
          </button>
        ))}
      </div>

      {/* Preview */}
      {tab === 'preview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {page_title && (
            <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8 }}>
              <span style={{ fontSize: 12, fontFamily: 'monospace', color: '#94a3b8' }}>&lt;title&gt;</span>
              <span style={{ fontSize: 14, color: '#0f172a' }}>{page_title}</span>
            </div>
          )}
          <div style={{ ...card, padding: 28 }}>
            <style>{PREVIEW_CSS}</style>
            <div className="seo-preview" dangerouslySetInnerHTML={{ __html: content_html }} />
          </div>
          <VoiceCompliancePanel compliance={voice_violations} />
          <SearchCoveragePanel coverage={engine_scores?.serp_signal_coverage} />
          {content_gaps && content_gaps.length > 0 && (
            <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ background: '#f8fafc', padding: '16px 20px', borderBottom: '1px solid #e2e8f0' }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>How to reach 100/100</p>
                <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>
                  These facts would improve the score but couldn't be included because they weren't verified from the
                  client's business data. Add them to the Google Business Profile or website, then regenerate.
                </p>
              </div>
              <div>
                {content_gaps.map((gap, i) => (
                  <div key={i} style={{ padding: '14px 20px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
                        background: gap.score_impact === 'high' ? '#fef2f2' : gap.score_impact === 'medium' ? '#fffbeb' : '#f1f5f9',
                        color: gap.score_impact === 'high' ? '#dc2626' : gap.score_impact === 'medium' ? '#d97706' : '#64748b',
                      }}>
                        {gap.score_impact === 'high' ? 'High impact' : gap.score_impact === 'medium' ? 'Medium impact' : 'Low impact'}
                      </span>
                      <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{gap.category}</span>
                    </div>
                    <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 2px' }}>{gap.missing}</p>
                    <p style={{ fontSize: 12, color: '#475569', margin: '0 0 2px' }}><b>Why it matters:</b> {gap.why_important}</p>
                    <p style={{ fontSize: 12, color: '#475569', margin: 0 }}><b>How to add it:</b> {gap.how_to_add}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* HTML */}
      {tab === 'html' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            {schema_json && (
              <button style={outlineBtn} onClick={copySchema}>
                {copiedSchema ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy schema</>}
              </button>
            )}
            <button style={outlineBtn} onClick={copyHtml}>
              {copiedHtml ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy HTML</>}
            </button>
          </div>
          <pre style={{
            background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16,
            fontSize: 12, overflowX: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
            color: '#0f172a', maxHeight: 600, overflowY: 'auto', margin: 0,
          }}>{fullHtml}</pre>
        </div>
      )}

      {/* GBP Posts */}
      {tab === 'social' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {socialLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 48, color: '#64748b' }}>
              <Spinner size={22} /><p style={{ fontSize: 14, margin: 0 }}>Generating GBP posts…</p>
            </div>
          )}
          {!socialLoading && socialError && (
            <div style={errorBox}>{socialError} <button onClick={fetchSocial} style={{ ...backLink, marginBottom: 0, marginLeft: 8 }}>Retry</button></div>
          )}
          {!socialLoading && social && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
                <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>Suggested posts for this page — send one to the composer below to add an image, schedule, or publish it.</p>
                <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                  <button style={outlineBtn} onClick={fetchSocial} title="Generate a fresh set of suggestions"><RefreshCw size={14} /> Regenerate</button>
                  <button style={outlineBtn} onClick={downloadSocial}><Download size={14} /> Download all</button>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {social.gbp.map((post, i) => {
                  const id = `gbp-${i}`
                  return (
                    <div key={id} style={{ ...card, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', width: 16, flexShrink: 0, marginTop: 2 }}>{i + 1}</span>
                      <p style={{ fontSize: 14, color: '#0f172a', flex: 1, whiteSpace: 'pre-wrap', margin: 0 }}>{post}</p>
                      <button onClick={() => setGbpSeed({ text: post, nonce: Date.now() })} title="Send to the composer below"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: '#eef2ff', border: '1px solid #c7d2fe', color: '#4f46e5', fontSize: 12, fontWeight: 600, cursor: 'pointer', borderRadius: 8, padding: '5px 10px', flexShrink: 0, whiteSpace: 'nowrap' }}>
                        <Megaphone size={13} /> Use in composer
                      </button>
                      <button onClick={() => copyPost(post, id)} title="Copy" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', flexShrink: 0, marginTop: 2 }}>
                        {copiedPost === id ? <Check size={16} color="#16a34a" /> : <Copy size={16} />}
                      </button>
                    </div>
                  )
                })}
              </div>
            </>
          )}

          {/* Full GBP Posts toolkit — compose (seedable from a suggestion above),
              add images, schedule, and publish to the client's Business Profile. */}
          <div style={{ marginTop: 8, paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <Megaphone size={18} color="#6366f1" />
              <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: 0 }}>Post to Google Business Profile</h3>
            </div>
            <GbpWorkspace clientId={clientId} seed={gbpSeed} />
          </div>
        </div>
      )}

      {/* Related Pages */}
      {tab === 'related' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {relatedPlan.loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 48, color: '#64748b' }}>
              <Spinner size={22} />
              <p style={{ fontSize: 14, margin: 0 }}>Discovering silos, expanding keywords, and clustering demand…</p>
              <p style={{ fontSize: 12, opacity: 0.7, margin: 0 }}>This usually takes 1–3 minutes.</p>
            </div>
          )}
          {!relatedPlan.loading && relatedPlan.notes.length > 0 && (
            <p style={{ fontSize: 12, color: '#92400e', margin: 0 }}>Some steps ran in degraded mode — results may be partial: {relatedPlan.notes.join(' · ')}</p>
          )}
          {relatedPlan.error && (
            <div style={errorBox}>{relatedPlan.error} <button onClick={fetchRelated} style={{ ...backLink, marginBottom: 0, marginLeft: 8 }}>Retry</button></div>
          )}
          {relatedPlan.items && relatedPlan.items.length === 0 && (
            <p style={{ fontSize: 14, color: '#64748b', textAlign: 'center', padding: 32 }}>No related pages found.</p>
          )}
          {relatedPlan.items && relatedPlan.items.length > 0 && (
            <>
              <RelatedPagesList
                items={relatedPlan.items}
                onAction={(item) => onRelatedAction(
                  item.status === 'found'
                    ? { mode: 'reoptimize', keyword: item.keyword, existingUrl: item.url ?? undefined }
                    : { mode: 'new', keyword: item.keyword },
                )}
                selection={{ selected: bulk.selected, onToggle: bulk.toggle, disabled: bulk.creating }}
              />
              <BulkCreateBar items={relatedPlan.items} bulk={bulk} location={location} locationCode={null} />
              <p style={{ fontSize: 12, color: '#94a3b8', margin: 0, textAlign: 'center' }}>
                Tick missing pages to create them in one batch, or reoptimize a found page individually (that opens it).
              </p>
            </>
          )}
        </div>
      )}

      {/* Footer actions */}
      <div style={{ ...card, marginTop: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {isNew && (
          <p style={{ fontSize: 12, color: '#16a34a', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Check size={14} /> Saved to this client's Local SEO pages.
          </p>
        )}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button style={{ ...primaryBtn, flex: 1 }} onClick={() => onScoreAndImprove(page)}>
            <Wand2 size={16} /> Score &amp; Improve
          </button>
          <button style={{ ...outlineBtn, flex: 1 }} onClick={copyHtml}>
            {copiedHtml ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy HTML</>}
          </button>
          <button style={{ ...outlineBtn, flex: 1 }} onClick={downloadHtml}><Download size={14} /> Download</button>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>Featured image</span>
          <FeaturedImagePicker value={featuredImageUrl} onChange={handleFeaturedImage} />
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <button style={outlineBtn} onClick={() => handlePublish()} disabled={publishing}>
            <ExternalLink size={14} /> {publishing ? 'Publishing…' : publishedUrl ? 'Re-publish to Google Doc' : 'Publish to Google Doc'}
          </button>
          {publishedUrl && (
            <a href={publishedUrl} target="_blank" rel="noreferrer"
              style={{ fontSize: 13, fontWeight: 600, color: '#16a34a', display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'none' }}>
              <Check size={14} /> View Google Doc
            </a>
          )}
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'inline-flex', border: '1px solid #cbd5e1', borderRadius: 8, overflow: 'hidden' }}>
            <select
              value={wpStatus}
              onChange={e => setWpStatus(e.target.value as 'draft' | 'publish')}
              style={{ border: 'none', background: '#fff', color: '#334155', fontSize: 13, fontWeight: 600, padding: '0 8px', cursor: 'pointer' }}
              title="Draft saves to WordPress unpublished; Publish goes live"
            >
              <option value="draft">Draft</option>
              <option value="publish">Publish</option>
            </select>
            <button
              style={{ ...outlineBtn, border: 'none', borderLeft: '1px solid #cbd5e1', borderRadius: 0 }}
              onClick={() => handleWpPublish()}
              disabled={wpPublishing}
            >
              <ExternalLink size={14} /> {wpPublishing ? 'Publishing…' : wpUrl ? 'Re-publish to WordPress' : 'Publish to WordPress'}
            </button>
          </div>
          {wpUrl && (
            <a href={wpUrl} target="_blank" rel="noreferrer"
              style={{ fontSize: 13, fontWeight: 600, color: '#16a34a', display: 'inline-flex', alignItems: 'center', gap: 4, textDecoration: 'none' }}>
              <Check size={14} /> Open in WordPress
            </a>
          )}
        </div>
        {publishError && (
          <ErrorDetails
            message={publishError}
            overriding={publishing || wpPublishing}
            onOverride={() => forceRetry.current?.()}
          />
        )}
        <button onClick={onNewPage} style={{ ...backLink, alignSelf: 'center', marginBottom: 0 }}>← Start a new page</button>
      </div>
    </div>
  )
}
