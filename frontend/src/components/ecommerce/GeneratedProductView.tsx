import { useState } from 'react'
import {
  ArrowLeft, ArrowRight, Check, Copy, Download, ExternalLink, TrendingUp, Wand2,
} from 'lucide-react'
import { ecommerceApi } from './api'
import type { ContentGap, EcommercePageDetail } from './types'
import { FeaturedImagePicker } from '../FeaturedImagePicker'
import {
  backLink, card, downloadFile, errorBox, formatHtml, outlineBtn,
  primaryBtn, relativeTime, scoreBg, scoreBorder, scoreColor, statusLabel, wordCount,
} from '../localseo/shared'

// Scoped article styling for the rendered page HTML — class-prefixed so it can't
// leak past the preview.
const PREVIEW_CSS = `
  .ec-preview { line-height: 1.7; color: #1e293b; font-size: 15px; }
  .ec-preview h1 { font-size: 24px; font-weight: 700; color: #0f172a; margin: 0 0 16px; line-height: 1.25; }
  .ec-preview h2 { font-size: 19px; font-weight: 700; color: #0f172a; margin: 32px 0 12px; line-height: 1.3; }
  .ec-preview h3 { font-size: 16px; font-weight: 600; color: #0f172a; margin: 24px 0 10px; }
  .ec-preview p { margin: 0 0 18px; }
  .ec-preview ul, .ec-preview ol { margin: 0 0 18px; padding-left: 22px; }
  .ec-preview li { margin: 0 0 8px; }
  .ec-preview table { display: block; overflow-x: auto; border-collapse: collapse; width: 100%; margin: 8px 0 22px; font-size: 14px; }
  .ec-preview th, .ec-preview td { border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; vertical-align: top; }
  .ec-preview th { background: #f8fafc; font-weight: 600; color: #0f172a; }
  .ec-preview a { color: #6366f1; }
`

interface Props {
  page: EcommercePageDetail
  isNew?: boolean
  prevScore?: number | null
  onBack: () => void
  onScoreAndImprove: (page: EcommercePageDetail) => void
  onNewPage: () => void
}

type Tab = 'preview' | 'html' | 'schema'

export function GeneratedProductView({ page, isNew, prevScore, onBack, onScoreAndImprove, onNewPage }: Props) {
  const { keyword, page_type, content_html, schema_json, page_title, content_gaps, researched_facts, mode } = page
  const score = page.composite_score
  const status = page.composite_status

  const [tab, setTab] = useState<Tab>('preview')
  const [copiedHtml, setCopiedHtml] = useState(false)
  const [copiedSchema, setCopiedSchema] = useState(false)

  // Publish to Google Doc (client's Drive folder) or WordPress (client's site).
  const [publishing, setPublishing] = useState(false)
  const [publishError, setPublishError] = useState('')
  const [publishedUrl, setPublishedUrl] = useState<string | null>(page.published_doc_url ?? null)
  const [wpPublishing, setWpPublishing] = useState(false)
  const [wpStatus, setWpStatus] = useState<'draft' | 'publish'>('draft')
  const [wpUrl, setWpUrl] = useState<string | null>(page.published_url ?? null)
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(page.featured_image_url ?? null)

  const handleFeaturedImage = async (url: string | null) => {
    await ecommerceApi.setFeaturedImage(page.id, url)
    setFeaturedImageUrl(url)
  }

  const handlePublish = async () => {
    setPublishing(true)
    setPublishError('')
    try {
      const res = await ecommerceApi.publishPage(page.id)
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
      const res = await ecommerceApi.publishPage(page.id, { destination: 'wordpress', status: wpStatus })
      const link = res.url ?? null
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

  const TABS: Array<{ key: Tab; label: string }> = [
    { key: 'preview', label: 'Preview' },
    { key: 'html', label: 'HTML' },
    { key: 'schema', label: 'JSON-LD Schema' },
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
            <span style={{ fontWeight: 600 }}>{keyword}</span>
            {' · '}
            <span style={{ textTransform: 'capitalize' }}>{page_type}</span>
            {' · '}~{wordCount(content_html)} words
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
            {t.label}
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
            <div className="ec-preview" dangerouslySetInnerHTML={{ __html: content_html }} />
          </div>
          {researched_facts && researched_facts.length > 0 && (
            <div style={{ border: '1px solid #bbf7d0', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ background: '#f0fdf4', padding: '16px 20px', borderBottom: '1px solid #bbf7d0' }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: '#166534', margin: 0 }}>Auto-sourced public specs — verify</p>
                <p style={{ fontSize: 12, color: '#15803d', margin: '4px 0 0' }}>
                  These are invariant, publicly-documented properties of the product, researched from the cited
                  sources and written into the page (not gated to you). Confirm each value against its source before publishing.
                </p>
              </div>
              <div>
                {researched_facts.map((f, i) => (
                  <div key={i} style={{ padding: '12px 20px', borderTop: i ? '1px solid #f0fdf4' : 'none', display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{f.field}:</span>
                    <span style={{ fontSize: 13, color: '#334155' }}>{f.value}{f.unit && !f.value.toLowerCase().includes(f.unit.toLowerCase()) ? ` ${f.unit}` : ''}</span>
                    {f.source_url && (
                      <a href={f.source_url} target="_blank" rel="noopener noreferrer"
                         style={{ fontSize: 12, color: '#6366f1', display: 'inline-flex', alignItems: 'center', gap: 3, marginLeft: 'auto' }}>
                        {f.source_name || 'source'} <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {content_gaps && content_gaps.length > 0 && (
            <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ background: '#f8fafc', padding: '16px 20px', borderBottom: '1px solid #e2e8f0' }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>How to reach 100/100</p>
                <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>
                  These facts would improve the score but couldn't be included because they weren't verified from the
                  product data. Add them to the product feed or source page, then regenerate.
                </p>
              </div>
              <div>
                {content_gaps.map((gap, i) => {
                  // Gaps may be rich objects or plain strings — normalise so a
                  // string gap still renders as a legible line.
                  const g: Partial<ContentGap> = typeof gap === 'string' ? { missing: gap } : gap
                  return (
                    <div key={i} style={{ padding: '14px 20px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
                      {(g.score_impact || g.category) && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          {g.score_impact && (
                            <span style={{
                              fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
                              background: g.score_impact === 'high' ? '#fef2f2' : g.score_impact === 'medium' ? '#fffbeb' : '#f1f5f9',
                              color: g.score_impact === 'high' ? '#dc2626' : g.score_impact === 'medium' ? '#d97706' : '#64748b',
                            }}>
                              {g.score_impact === 'high' ? 'High impact' : g.score_impact === 'medium' ? 'Medium impact' : 'Low impact'}
                            </span>
                          )}
                          {g.category && <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{g.category}</span>}
                        </div>
                      )}
                      {g.missing && <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 2px' }}>{g.missing}</p>}
                      {g.why_important && <p style={{ fontSize: 12, color: '#475569', margin: '0 0 2px' }}><b>Why it matters:</b> {g.why_important}</p>}
                      {g.how_to_add && <p style={{ fontSize: 12, color: '#475569', margin: 0 }}><b>How to add it:</b> {g.how_to_add}</p>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* HTML */}
      {tab === 'html' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
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

      {/* JSON-LD Schema */}
      {tab === 'schema' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {schema_json ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button style={outlineBtn} onClick={copySchema}>
                  {copiedSchema ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy schema</>}
                </button>
              </div>
              <pre style={{
                background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16,
                fontSize: 12, overflowX: 'auto', whiteSpace: 'pre-wrap', fontFamily: 'monospace',
                color: '#0f172a', maxHeight: 600, overflowY: 'auto', margin: 0,
              }}>{schema_json}</pre>
            </>
          ) : (
            <p style={{ fontSize: 14, color: '#94a3b8', textAlign: 'center', padding: 32 }}>No structured data was generated for this page.</p>
          )}
        </div>
      )}

      {/* Footer actions */}
      <div style={{ ...card, marginTop: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {isNew && (
          <p style={{ fontSize: 12, color: '#16a34a', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Check size={14} /> Saved to this client's Ecommerce pages.
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
