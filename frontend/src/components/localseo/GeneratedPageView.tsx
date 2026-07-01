import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, Check, Copy, Download, ExternalLink, TrendingUp, Wand2,
} from 'lucide-react'
import { localSeoApi } from './api'
import type { LocalSeoPageDetail, SocialPostsResult } from './types'
import { RelatedPagesList } from './RelatedPagesList'
import { BulkCreateBar } from './BulkCreateBar'
import { useSiloPlan } from './useSiloPlan'
import { useBulkCreate } from './useBulkCreate'
import { Spinner } from './Spinner'
import { FeaturedImagePicker } from '../FeaturedImagePicker'
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
  const { keyword, location, content_html, schema_json, page_title, content_gaps, mode } = page
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

  const handlePublish = async () => {
    setPublishing(true)
    setPublishError('')
    try {
      const res = await localSeoApi.publishPage(page.id)
      setPublishedUrl(res.doc_url ?? null)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Publish failed'
      setPublishError(
        msg.includes('missing_google_drive_folder_id')
          ? 'Set this client’s Google Drive folder first (Client → Edit), then publish.'
          : msg.includes('publish_not_configured')
            ? 'Publishing isn’t configured on the server (no Apps Script URL).'
            : msg,
      )
    } finally {
      setPublishing(false)
    }
  }

  const handleWpPublish = async () => {
    setWpPublishing(true)
    setPublishError('')
    try {
      const res = await localSeoApi.publishPage(page.id, { destination: 'wordpress', status: wpStatus })
      const link = res.edit_url || res.url || null
      setWpUrl(link)
      if (link) window.open(link, '_blank')
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Publish failed'
      setPublishError(
        msg.includes('wordpress_not_configured')
          ? 'Add this client’s WordPress site + Application Password first (Client → Edit), then publish.'
          : msg.includes('wordpress_auth_failed')
            ? 'WordPress rejected the credentials — check the username and Application Password.'
            : msg,
      )
    } finally {
      setWpPublishing(false)
    }
  }

  // Social posts — lazily generated when the tab is first opened (each call
  // costs an LLM round-trip; suite doesn't persist them).
  const [social, setSocial] = useState<SocialPostsResult | null>(null)
  const [socialLoading, setSocialLoading] = useState(false)
  const [socialError, setSocialError] = useState('')
  const [copiedPost, setCopiedPost] = useState<string | null>(null)
  const socialRequested = useRef(false)

  // Related pages — the Fanout-powered silo plan (same engine as the Plan Silo
  // tab), seeded from this page's keyword + area. Lazily kicked off when the tab
  // is first opened; it runs as an async job, so we poll via the shared hook.
  const relatedPlan = useSiloPlan(clientId)
  const relatedRequested = useRef(false)
  // Multi-select bulk creation of the missing related pages (same flow as the
  // Plan Silo tab). Refresh the saved-pages list as pages land.
  const queryClient = useQueryClient()
  const bulk = useBulkCreate(clientId, () =>
    queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] }),
  )

  const fetchSocial = async () => {
    setSocialLoading(true)
    setSocialError('')
    try {
      const data = await localSeoApi.socialPosts(clientId, {
        keyword, location, page_content: htmlToText(content_html),
      })
      setSocial(data)
    } catch (e) {
      setSocialError(e instanceof Error ? e.message : 'Could not generate posts')
    } finally {
      setSocialLoading(false)
    }
  }

  const fetchRelated = () => { bulk.reset(); void relatedPlan.run(keyword, location) }

  useEffect(() => {
    if (tab === 'social' && !socialRequested.current) {
      socialRequested.current = true
      void fetchSocial()
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
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button style={outlineBtn} onClick={downloadSocial}><Download size={14} /> Download all</button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {social.gbp.map((post, i) => {
                  const id = `gbp-${i}`
                  return (
                    <div key={id} style={{ ...card, padding: 16, display: 'flex', gap: 12 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', width: 16, flexShrink: 0 }}>{i + 1}</span>
                      <p style={{ fontSize: 14, color: '#0f172a', flex: 1, whiteSpace: 'pre-wrap', margin: 0 }}>{post}</p>
                      <button onClick={() => copyPost(post, id)} title="Copy" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', flexShrink: 0 }}>
                        {copiedPost === id ? <Check size={16} color="#16a34a" /> : <Copy size={16} />}
                      </button>
                    </div>
                  )
                })}
              </div>
            </>
          )}
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
          <button style={outlineBtn} onClick={handlePublish} disabled={publishing}>
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
              onClick={handleWpPublish}
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
        {publishError && <div style={errorBox}>{publishError}</div>}
        <button onClick={onNewPage} style={{ ...backLink, alignSelf: 'center', marginBottom: 0 }}>← Start a new page</button>
      </div>
    </div>
  )
}
