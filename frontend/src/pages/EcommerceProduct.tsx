import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, CheckCircle2, RotateCcw, Sparkles, Trash2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { ecommerceApi } from '../components/ecommerce/api'
import type { EcommercePageDetail, EcommercePageListItem, EcommercePageType } from '../components/ecommerce/types'
import { GeneratedProductView } from '../components/ecommerce/GeneratedProductView'
import { ProductScoreView } from '../components/ecommerce/ProductScoreView'
import { ReoptimizeView } from '../components/ecommerce/ReoptimizeView'
import { useBulkGenerate } from '../components/ecommerce/useBulkGenerate'
import { Spinner } from '../components/localseo/Spinner'
import { useBulkPublish, type PublishItem } from '../components/publish/useBulkPublish'
import { BulkPublishBar } from '../components/publish/BulkPublishBar'
import { usePagedPublish, PublishTabs, Pager, PublishBadges } from '../components/publish/PublishFilter'
import {
  backLink, card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime, scoreColor,
} from '../components/localseo/shared'

type View =
  | { kind: 'form' }
  | { kind: 'creating' }
  | { kind: 'loading' }
  | { kind: 'generated'; page: EcommercePageDetail; isNew: boolean; prevScore: number | null }
  | { kind: 'score'; pageUrl?: string; pageHtml?: string }

type Tab = 'new' | 'reopt' | 'saved' | 'drafts'

export function EcommerceProduct() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: savedPages, isLoading: loadingSaved } = useQuery<EcommercePageListItem[]>({
    queryKey: ['ecommerce-pages', clientId],
    queryFn: () => ecommerceApi.listPages(clientId),
    enabled: Boolean(clientId),
  })

  const { data: draftPages, isLoading: loadingDrafts } = useQuery<EcommercePageListItem[]>({
    queryKey: ['ecommerce-drafts', clientId],
    queryFn: () => ecommerceApi.listDrafts(clientId),
    enabled: Boolean(clientId),
  })

  const [tab, setTab] = useState<Tab>(
    // Deep-link support: /clients/:id/ecommerce?tab=saved (or reopt / drafts).
    searchParams.get('tab') === 'saved' ? 'saved'
      : searchParams.get('tab') === 'reopt' ? 'reopt'
        : searchParams.get('tab') === 'drafts' ? 'drafts'
          : 'new',
  )
  const [view, setView] = useState<View>({ kind: 'form' })

  // Page-type switch — applies to New + Reoptimize.
  const [pageType, setPageType] = useState<EcommercePageType>('product')

  // New-page form inputs.
  const [genMode, setGenMode] = useState<'single' | 'bulk'>('single')
  const [keyword, setKeyword] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [productInput, setProductInput] = useState('')
  const [bulkKeywords, setBulkKeywords] = useState('')
  const [error, setError] = useState('')

  // Creating-progress ticker + background-generation poll (same pattern as the
  // Local SEO writer): cancelling stops polling only — the job keeps running
  // server-side, so the page still lands in Saved Pages.
  const [elapsed, setElapsed] = useState(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const genPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const genCancelledRef = useRef(false)
  const genDetachedRef = useRef(false)

  const stopTicker = () => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
  }
  const startTicker = () => {
    stopTicker()
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
  }
  useEffect(() => () => stopTicker(), [])
  useEffect(() => () => {
    genCancelledRef.current = true
    if (genPollRef.current) clearTimeout(genPollRef.current)
  }, [])

  const refreshSaved = () => {
    queryClient.invalidateQueries({ queryKey: ['ecommerce-pages', clientId] })
    queryClient.invalidateQueries({ queryKey: ['ecommerce-drafts', clientId] })
  }

  // Bulk generation from a keyword list (background jobs via the shared hook).
  const bulkGen = useBulkGenerate(clientId, refreshSaved)

  const canGenerate = Boolean(keyword.trim())

  // ── Single-page generation ────────────────────────────────────────────────
  const runGenerate = async () => {
    const kw = keyword.trim()
    if (!kw) return
    setError('')
    setView({ kind: 'creating' })
    startTicker()
    genCancelledRef.current = false
    genDetachedRef.current = false
    if (genPollRef.current) clearTimeout(genPollRef.current)
    try {
      const { job_id } = await ecommerceApi.generateAsync(clientId, {
        keyword: kw,
        page_type: pageType,
        source_url: sourceUrl.trim() || null,
        product_input: productInput.trim() || null,
      })
      const poll = async () => {
        if (genCancelledRef.current) return
        try {
          const res = await ecommerceApi.getGenerateJob(clientId, job_id)
          if (genCancelledRef.current) return
          if (res.status === 'complete' && res.page_id) {
            stopTicker()
            refreshSaved()
            if (!genDetachedRef.current) {
              const page = await ecommerceApi.getPage(res.page_id)
              if (!genCancelledRef.current && !genDetachedRef.current) {
                setView({ kind: 'generated', page, isNew: true, prevScore: null })
              }
            }
            return
          }
          if (res.status === 'failed') {
            stopTicker()
            if (!genDetachedRef.current) {
              setError(res.error || 'Generation failed')
              setView({ kind: 'form' })
            }
            return
          }
        } catch {
          // transient poll error — keep trying
        }
        genPollRef.current = setTimeout(poll, 3000)
      }
      genPollRef.current = setTimeout(poll, 3000)
    } catch (e) {
      stopTicker()
      setError(e instanceof Error ? e.message : 'Could not start generation')
      setView({ kind: 'form' })
    }
  }

  // Leave the creating screen without cancelling the job. The poll keeps running
  // (detached) so the finished page drops into Saved Pages live.
  const leaveGenerating = () => {
    genDetachedRef.current = true
    stopTicker()
    setView({ kind: 'form' })
    setTab('saved')
  }

  const openSaved = async (pageId: string) => {
    setView({ kind: 'loading' })
    try {
      const page = await ecommerceApi.getPage(pageId)
      setKeyword(page.keyword)
      setPageType(page.page_type)
      setView({ kind: 'generated', page, isNew: false, prevScore: null })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open page')
      setView({ kind: 'form' })
    }
  }

  const startBulkGenerate = () => {
    const keywords = bulkKeywords.split('\n').map(k => k.trim()).filter(Boolean)
    if (!keywords.length) return
    bulkGen.reset()
    void bulkGen.start(keywords, pageType)
  }

  // ── Sub-view routing ───────────────────────────────────────────────────────
  if (view.kind === 'creating') return <CreatingView elapsed={elapsed} pageType={pageType} onLeave={leaveGenerating} />

  if (view.kind === 'loading') {
    return (
      <div style={{ padding: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: '#64748b', minHeight: 240 }}>
        <Spinner size={20} /> <span style={{ fontSize: 14 }}>Loading page…</span>
      </div>
    )
  }

  if (view.kind === 'generated') {
    return (
      <div style={{ padding: 32 }}>
        <GeneratedProductView
          page={view.page}
          isNew={view.isNew}
          prevScore={view.prevScore}
          onBack={() => setView({ kind: 'form' })}
          onScoreAndImprove={(page) => setView({ kind: 'score', pageUrl: page.source_url ?? undefined, pageHtml: page.content_html })}
          onNewPage={() => { setView({ kind: 'form' }); setKeyword(''); setSourceUrl(''); setProductInput('') }}
        />
      </div>
    )
  }

  if (view.kind === 'score') {
    return (
      <div style={{ padding: 32 }}>
        <ProductScoreView
          clientId={clientId}
          keyword={keyword}
          pageType={pageType}
          pageUrl={view.pageUrl}
          pageHtml={view.pageHtml}
          onBack={() => setView({ kind: 'form' })}
          onReoptimized={(page, prevScore) => { refreshSaved(); setView({ kind: 'generated', page, isNew: true, prevScore }) }}
          onCreateNew={() => setView({ kind: 'form' })}
          onLeaveBackground={() => { refreshSaved(); setView({ kind: 'form' }); setTab('saved') }}
        />
      </div>
    )
  }

  // ── Main form ──────────────────────────────────────────────────────────────
  const showPageTypeSwitch = tab === 'new' || tab === 'reopt'

  return (
    <div style={{ padding: 32, maxWidth: 720 }}>
      <Link to={`/clients/${clientId}`} style={{ ...backLink, textDecoration: 'none' }}>
        <ArrowLeft size={14} /> Back to workspace
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '8px 0 2px' }}>Ecommerce Writer</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 24px' }}>
        Generate & reoptimize product and collection pages for {client?.name ?? 'this client'}.
      </p>

      {/* Tabs */}
      <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 10, padding: 4, marginBottom: 20 }}>
        {(['new', 'reopt', 'saved', 'drafts'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '7px 16px', fontSize: 14, fontWeight: 600, borderRadius: 7, cursor: 'pointer', border: 'none',
              background: tab === t ? '#fff' : 'transparent', color: tab === t ? '#0f172a' : '#64748b',
              boxShadow: tab === t ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{t === 'new' ? 'New Page' : t === 'reopt' ? 'Reoptimize' : t === 'saved' ? 'Saved Pages' : `Drafts${draftPages && draftPages.length ? ` (${draftPages.length})` : ''}`}</button>
        ))}
      </div>

      {/* Page-type switch — applies to New + Reoptimize */}
      {showPageTypeSwitch && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>Page type</span>
          <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4 }}>
            {(['product', 'collection'] as const).map(pt => (
              <button
                key={pt}
                onClick={() => setPageType(pt)}
                style={{
                  padding: '6px 16px', fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: 'pointer', border: 'none', textTransform: 'capitalize',
                  background: pageType === pt ? '#fff' : 'transparent', color: pageType === pt ? '#0f172a' : '#64748b',
                  boxShadow: pageType === pt ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
                }}
              >{pt}</button>
            ))}
          </div>
        </div>
      )}

      {tab === 'saved' ? (
        <SavedPagesList
          pages={savedPages ?? []}
          loading={loadingSaved}
          onOpen={openSaved}
          onDelete={async (pid) => { await ecommerceApi.deletePage(pid); refreshSaved() }}
          wordpressConfigured={Boolean(client?.wordpress_site_url && client?.wordpress_app_password_set)}
        />
      ) : tab === 'drafts' ? (
        <DraftsList
          pages={draftPages ?? []}
          loading={loadingDrafts}
          onOpen={openSaved}
          onRestore={async (pid) => { await ecommerceApi.restorePage(pid); refreshSaved() }}
          onPurge={async (pid) => { await ecommerceApi.purgePage(pid); refreshSaved() }}
          onPurgeAll={async () => { await ecommerceApi.purgeDrafts(clientId); refreshSaved() }}
        />
      ) : tab === 'reopt' ? (
        <ReoptimizeView
          clientId={clientId}
          clientName={client?.name}
          pageType={pageType}
          onOpenSaved={() => { refreshSaved(); setTab('saved') }}
        />
      ) : genMode === 'bulk' ? (
        <BulkGenerateForm
          keywords={bulkKeywords}
          setKeywords={setBulkKeywords}
          pageType={pageType}
          bulk={bulkGen}
          onSwitchSingle={() => setGenMode('single')}
          onStart={startBulkGenerate}
          onViewSaved={() => setTab('saved')}
        />
      ) : (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>
              Write a new {pageType} page
            </h2>
            <button
              type="button"
              onClick={() => setGenMode('bulk')}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#6366f1' }}
            >
              Bulk from a keyword list →
            </button>
          </div>

          {/* House PDP template (products only) — every product mirrors this structure */}
          {pageType === 'product' && <HouseTemplatePanel clientId={clientId} />}

          {/* Keyword */}
          <div>
            <label style={label}>Target keyword</label>
            <input style={input} value={keyword} onChange={e => { setKeyword(e.target.value); setError('') }} placeholder={pageType === 'collection' ? 'e.g. running shoes' : 'e.g. wireless noise-cancelling headphones'} />
          </div>

          {/* Source URL (optional) */}
          <div>
            <label style={label}>Source URL <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional)</span></label>
            <input style={input} value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="https://shop.example.com/products/…" />
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
              We'll scrape it for product facts (specs, price, variants) to ground the copy.
            </p>
          </div>

          {/* Product details (optional) */}
          <div>
            <label style={label}>Product details <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional)</span></label>
            <textarea
              style={{ ...input, minHeight: 110, fontFamily: 'inherit', resize: 'vertical' }}
              value={productInput}
              onChange={e => setProductInput(e.target.value)}
              placeholder={'Paste specs, price, variants, materials, dimensions, key features…'}
            />
          </div>

          {error && <div style={errorBox}>{error}</div>}

          <button
            style={{ ...primaryBtn, width: '100%', opacity: canGenerate ? 1 : 0.5, cursor: canGenerate ? 'pointer' : 'not-allowed' }}
            disabled={!canGenerate}
            onClick={runGenerate}
          >
            <Sparkles size={16} /> Create {pageType} page
          </button>
          {!canGenerate && (
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '-8px 0 0', textAlign: 'center' }}>
              Enter a target keyword to continue.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// Bulk-generate a list of keywords into pages of the current page type.
function BulkGenerateForm({ keywords, setKeywords, pageType, bulk, onSwitchSingle, onStart, onViewSaved }: {
  keywords: string
  setKeywords: (v: string) => void
  pageType: EcommercePageType
  bulk: ReturnType<typeof useBulkGenerate>
  onSwitchSingle: () => void
  onStart: () => void
  onViewSaved: () => void
}) {
  const { creating, detached, total, done, failed, error, leave } = bulk
  const count = keywords.split('\n').map(k => k.trim()).filter(Boolean).length
  const finished = done + failed

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Bulk-create {pageType} pages</h2>
        <button
          type="button"
          onClick={onSwitchSingle}
          disabled={creating}
          style={{ background: 'none', border: 'none', padding: 0, cursor: creating ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600, color: '#6366f1' }}
        >
          ← Single page
        </button>
      </div>

      <div>
        <label style={label}>Keywords — one per line</label>
        <textarea
          style={{ ...input, minHeight: 150, fontFamily: 'inherit', resize: 'vertical' }}
          value={keywords}
          disabled={creating}
          onChange={e => setKeywords(e.target.value)}
          placeholder={'wireless headphones\nbluetooth speaker\nusb-c charger'}
        />
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
          Each keyword becomes its own <b style={{ textTransform: 'capitalize' }}>{pageType}</b> page. They generate in the background — you can leave once they start.
        </p>
      </div>

      {error && <div style={errorBox}>{error}</div>}

      {creating ? (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, background: '#f8fafc' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={16} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>Generating in the background…</span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#64748b', flexShrink: 0 }}>
              {finished} / {total} done{failed > 0 ? ` · ${failed} failed` : ''}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {Array.from({ length: total }).map((_, idx) => (
              <div key={idx} style={{
                height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                background: idx < done ? '#16a34a' : idx < finished ? '#dc2626' : '#e2e8f0',
              }} />
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, flex: 1 }}>
              Each page is saved to Saved Pages as it finishes — you don’t need to wait here.
            </p>
            <button onClick={leave} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1', flexShrink: 0 }}>
              Leave &amp; finish in the background
            </button>
          </div>
        </div>
      ) : (
        <>
          {detached && total > 0 && (
            <p style={{ fontSize: 13, color: '#6366f1', fontWeight: 600, margin: 0 }}>
              {total} page{total === 1 ? '' : 's'} generating in the background — they’ll appear in Saved Pages as they finish.
            </p>
          )}
          {!detached && (done > 0 || failed > 0) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {done > 0 && (
                <p style={{ fontSize: 13, color: '#16a34a', fontWeight: 600, margin: 0 }}>
                  {done} page{done === 1 ? '' : 's'} created and saved — <button onClick={onViewSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#16a34a', fontWeight: 600, textDecoration: 'underline' }}>view in Saved Pages</button>.
                </p>
              )}
              {failed > 0 && (
                <p style={{ fontSize: 13, color: '#dc2626', fontWeight: 600, margin: 0 }}>{failed} page{failed === 1 ? '' : 's'} failed to generate.</p>
              )}
            </div>
          )}
          <button
            style={{ ...primaryBtn, width: '100%', opacity: count ? 1 : 0.5, cursor: count ? 'pointer' : 'not-allowed' }}
            disabled={!count}
            onClick={onStart}
          >
            <Sparkles size={16} /> Create {count || ''} {pageType} page{count === 1 ? '' : 's'}
          </button>
        </>
      )}
    </div>
  )
}

function SavedPagesList({ pages, loading, onOpen, onDelete, wordpressConfigured }: {
  pages: EcommercePageListItem[]
  loading: boolean
  onOpen: (id: string) => void
  onDelete: (id: string) => Promise<void>
  wordpressConfigured?: boolean
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const bulk = useBulkPublish()
  const pub = usePagedPublish(pages, p => Boolean(p.published_doc_url || p.published_url))

  const items: PublishItem[] = pages.map(p => ({
    key: `ecp:${p.id}`,
    type: 'ecommerce_page',
    id: p.id,
    label: p.page_title || p.keyword,
  }))

  const handleDelete = async (pid: string) => {
    setConfirmId(null)
    setDeletingId(pid)
    try { await onDelete(pid) } finally { setDeletingId(null) }
  }

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#64748b', fontSize: 14, padding: 16 }}><Spinner size={16} /> Loading saved pages…</div>
  }
  if (pages.length === 0) {
    return <p style={{ fontSize: 14, color: '#94a3b8', textAlign: 'center', padding: 32 }}>No saved pages yet. Generate one from the New Page tab.</p>
  }
  return (
    <>
      <BulkPublishBar items={items} bulk={bulk} wordpressConfigured={wordpressConfigured} placement="top" />
      <div style={{ margin: '4px 0 12px' }}>
        <PublishTabs counts={pub.counts} active={pub.filter} onPick={pub.pick} />
      </div>
      {pub.total === 0 ? (
        <p style={{ fontSize: 14, color: '#94a3b8', textAlign: 'center', padding: 24 }}>Nothing in this view.</p>
      ) : (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
          {pub.pageItems.map((p, i) => {
            const key = `ecp:${p.id}`
            const result = bulk.results[key]
            return (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: bulk.selected.has(key) ? '#f5f7ff' : '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
                <input
                  type="checkbox"
                  checked={bulk.selected.has(key)}
                  onChange={e => bulk.toggle(key, e.target.checked)}
                  disabled={bulk.publishing}
                  style={{ width: 16, height: 16, cursor: 'pointer', flexShrink: 0, accentColor: '#6366f1' }}
                  title="Select for bulk publish"
                />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.page_title || p.keyword}</span>
                    <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: '#eef2ff', color: '#4f46e5', textTransform: 'capitalize' }}>{p.page_type}</span>
                    <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: p.mode === 'reoptimize' ? '#eff6ff' : '#f0fdf4', color: p.mode === 'reoptimize' ? '#2563eb' : '#16a34a' }}>
                      {p.mode === 'reoptimize' ? 'Reoptimized' : 'Generated'}
                    </span>
                    {p.composite_score != null && (
                      <span style={{ fontSize: 11, fontWeight: 700, color: scoreColor(p.composite_score) }}>{Math.round(p.composite_score)}/100</span>
                    )}
                  </div>
                  <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
                    {p.keyword} <span style={{ marginLeft: 6, opacity: 0.7 }}>{relativeTime(p.created_at)}</span>
                  </p>
                </div>
                {result?.status === 'done' && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                    {result.docUrl && <a href={result.docUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12, fontWeight: 600, color: '#16a34a', textDecoration: 'none' }}>Open Doc ↗</a>}
                    {result.siteUrl && <a href={result.siteUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12, fontWeight: 600, color: '#2563eb', textDecoration: 'none' }}>Open page ↗</a>}
                    {!result.docUrl && !result.siteUrl && <span style={{ fontSize: 12, fontWeight: 600, color: '#16a34a' }}>Published</span>}
                  </span>
                )}
                {result?.status === 'failed' && <span style={{ fontSize: 12, color: '#dc2626', flexShrink: 0 }} title={result.error}>Failed</span>}
                {result?.status === 'publishing' && <Spinner size={14} />}
                {!result && <span style={{ flexShrink: 0 }}><PublishBadges docUrl={p.published_doc_url} siteUrl={p.published_url} /></span>}
                <button style={outlineBtn} onClick={() => onOpen(p.id)}>View <ArrowRight size={13} /></button>
                {confirmId === p.id ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748b' }}>
                    Move to Drafts?
                    <button onClick={() => handleDelete(p.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontWeight: 600 }}>Yes</button>
                    <button onClick={() => setConfirmId(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}>No</button>
                  </span>
                ) : (
                  <button
                    onClick={() => setConfirmId(p.id)}
                    disabled={deletingId === p.id}
                    title="Move to Drafts"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', display: 'inline-flex', alignItems: 'center' }}
                  >
                    {deletingId === p.id ? <Spinner size={14} /> : <Trash2 size={15} />}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
      <Pager page={pub.page} pageCount={pub.pageCount} total={pub.total} pageSize={pub.pageSize} onPage={pub.setPage} />
    </>
  )
}

// The Drafts (recycle bin) tab: soft-deleted pages, each restorable or
// permanently deletable, plus an "Empty drafts" action for the whole bin.
function DraftsList({ pages, loading, onOpen, onRestore, onPurge, onPurgeAll }: {
  pages: EcommercePageListItem[]
  loading: boolean
  onOpen: (id: string) => void
  onRestore: (id: string) => Promise<void>
  onPurge: (id: string) => Promise<void>
  onPurgeAll: () => Promise<void>
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmAll, setConfirmAll] = useState(false)
  const [purgingAll, setPurgingAll] = useState(false)

  const run = async (pid: string, fn: (id: string) => Promise<void>) => {
    setConfirmId(null)
    setBusyId(pid)
    try { await fn(pid) } finally { setBusyId(null) }
  }
  const handlePurgeAll = async () => {
    setConfirmAll(false)
    setPurgingAll(true)
    try { await onPurgeAll() } finally { setPurgingAll(false) }
  }

  if (loading) {
    return <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#64748b', fontSize: 14, padding: 16 }}><Spinner size={16} /> Loading drafts…</div>
  }
  if (pages.length === 0) {
    return <p style={{ fontSize: 14, color: '#94a3b8', textAlign: 'center', padding: 32 }}>No drafts. Deleting a page from Saved Pages moves it here, where you can restore it or delete it for good.</p>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>
          {pages.length} draft{pages.length === 1 ? '' : 's'} — deleted pages you can restore or permanently remove.
        </p>
        {confirmAll ? (
          <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748b' }}>
            Permanently delete all {pages.length}?
            <button onClick={handlePurgeAll} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontWeight: 600 }}>Yes, delete all</button>
            <button onClick={() => setConfirmAll(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}>No</button>
          </span>
        ) : (
          <button
            onClick={() => setConfirmAll(true)}
            disabled={purgingAll}
            style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#dc2626', display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            {purgingAll ? <Spinner size={12} /> : <Trash2 size={13} />} Empty drafts
          </button>
        )}
      </div>

      <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
        {pages.map((p, i) => (
          <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.page_title || p.keyword}</span>
                <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: '#eef2ff', color: '#4f46e5', textTransform: 'capitalize' }}>{p.page_type}</span>
                {p.composite_score != null && (
                  <span style={{ fontSize: 11, fontWeight: 700, color: scoreColor(p.composite_score) }}>{Math.round(p.composite_score)}/100</span>
                )}
              </div>
              <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
                {p.keyword}
                <span style={{ marginLeft: 6, opacity: 0.7 }}>deleted {p.deleted_at ? relativeTime(p.deleted_at) : ''}</span>
              </p>
            </div>
            <button style={outlineBtn} onClick={() => onOpen(p.id)}>View <ArrowRight size={13} /></button>
            <button
              style={{ ...outlineBtn, color: '#16a34a', borderColor: '#bbf7d0' }}
              onClick={() => run(p.id, onRestore)}
              disabled={busyId === p.id}
            >
              {busyId === p.id ? <Spinner size={13} /> : <RotateCcw size={13} />} Restore
            </button>
            {confirmId === p.id ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748b' }}>
                Delete forever?
                <button onClick={() => run(p.id, onPurge)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontWeight: 600 }}>Yes</button>
                <button onClick={() => setConfirmId(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}>No</button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmId(p.id)}
                disabled={busyId === p.id}
                title="Delete permanently"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', display: 'inline-flex', alignItems: 'center' }}
              >
                <Trash2 size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// House PDP template (products only): set once per client — the reference product
// page whose structure every new product description mirrors. Persisted via the
// clients.ecommerce_page_template_url default; generation resolves it server-side.
function HouseTemplatePanel({ clientId }: { clientId: string }) {
  const [url, setUrl] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    ecommerceApi.getPageTemplate(clientId)
      .then(r => { if (alive) { setSaved(r.ecommerce_page_template_url); setUrl(r.ecommerce_page_template_url ?? '') } })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [clientId])

  const dirty = (url.trim() || null) !== (saved || null)

  const save = async () => {
    setSaving(true)
    try {
      const r = await ecommerceApi.setPageTemplate(clientId, url.trim() || null)
      setSaved(r.ecommerce_page_template_url)
      setUrl(r.ecommerce_page_template_url ?? '')
    } finally { setSaving(false) }
  }

  if (loading) return null

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, background: '#f8fafc', padding: '12px 14px' }}>
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
          House template{' '}
          {saved
            ? <span style={{ color: '#16a34a', fontWeight: 500 }}>· product pages mirror your reference layout</span>
            : <span style={{ color: '#94a3b8', fontWeight: 400 }}>· not set (using the default structure)</span>}
        </div>
        <span style={{ fontSize: 12, color: '#6366f1', fontWeight: 600 }}>{open ? 'Hide' : saved ? 'Change' : 'Set up'}</span>
      </div>
      {open && (
        <div style={{ marginTop: 10 }}>
          <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 8px' }}>
            Paste the URL of one existing product page whose layout you want every product to follow. The writer reproduces its
            section structure, order and blocks — adapting the copy to each product. Applies to product pages only.
          </p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={{ ...input, flex: 1 }}
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://yourstore.com/products/your-best-example"
            />
            <button
              style={{ ...outlineBtn, whiteSpace: 'nowrap', opacity: dirty && !saving ? 1 : 0.5, cursor: dirty && !saving ? 'pointer' : 'not-allowed' }}
              disabled={!dirty || saving}
              onClick={save}
            >
              {saving ? 'Saving…' : saved && !url.trim() ? 'Clear' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function CreatingView({ elapsed, pageType, onLeave }: { elapsed: number; pageType: EcommercePageType; onLeave?: () => void }) {
  const pct = Math.min(95, Math.round((elapsed / 180) * 100))
  const steps = [
    { label: 'Fetching top search results', done: pct >= 35, active: pct < 35 },
    { label: 'Scraping & analyzing competitor pages', done: pct >= 65, active: pct >= 35 && pct < 65 },
    { label: 'Generating & scoring your page', done: pct >= 95, active: pct >= 65 },
  ]
  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60
  const elapsedLabel = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`

  return (
    <div style={{ padding: 32, maxWidth: 640, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 2px' }}>Creating your {pageType} page</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>Hang tight — this usually takes 2–4 minutes.</p>
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b' }}>
          <span style={{ fontWeight: 600 }}>Building your page… {elapsedLabel}</span>
          <span style={{ opacity: 0.7 }}>Usually 2–4 minutes</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {steps.map((s, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {s.done
                ? <CheckCircle2 size={16} color="#16a34a" />
                : s.active ? <Spinner size={16} /> : <div style={{ width: 16, height: 16, borderRadius: 999, border: '1px solid #e2e8f0' }} />}
              <span style={{ fontSize: 14, color: s.active ? '#0f172a' : '#94a3b8', fontWeight: s.active ? 600 : 400, textDecoration: s.done ? 'line-through' : 'none' }}>{s.label}</span>
            </div>
          ))}
        </div>
        <div style={{ width: '100%', height: 6, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
          <div style={{ height: '100%', background: '#6366f1', borderRadius: 999, width: `${pct}%`, transition: 'width 0.5s' }} />
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, marginTop: 16 }}>
        <p style={{ fontSize: 12, color: '#64748b', textAlign: 'center', margin: 0 }}>
          You can leave this page — generation continues in the background and the finished page appears in <b>Saved Pages</b>.
        </p>
        {onLeave && (
          <button style={outlineBtn} onClick={onLeave}>
            Leave &amp; finish in the background
          </button>
        )}
      </div>
    </div>
  )
}
