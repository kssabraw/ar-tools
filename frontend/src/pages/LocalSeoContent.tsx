import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, Building2, CheckCircle2, FilePlus, FileSearch, Search, Sparkles, Trash2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { localSeoApi } from '../components/localseo/api'
import { LocationAutocomplete } from '../components/localseo/LocationAutocomplete'
import type { AnalysisResult, LocalSeoPageDetail, LocalSeoPageListItem, RelatedPageItem } from '../components/localseo/types'
import { GeneratedPageView } from '../components/localseo/GeneratedPageView'
import { RelatedPagesList } from '../components/localseo/RelatedPagesList'
import { PageScoreView } from '../components/localseo/PageScoreView'
import { AnalysisResultsView } from '../components/localseo/AnalysisResultsView'
import { Spinner } from '../components/localseo/Spinner'
import {
  backLink, card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime, scoreColor,
} from '../components/localseo/shared'

type View =
  | { kind: 'form' }
  | { kind: 'creating' }
  | { kind: 'loading' }
  | { kind: 'generated'; page: LocalSeoPageDetail; isNew: boolean; prevScore: number | null }
  | { kind: 'score'; pageUrl?: string; pageHtml?: string; serpAnalysis?: AnalysisResult | null }
  | { kind: 'analysis'; result: AnalysisResult }

type CheckState =
  | { status: 'idle' }
  | { status: 'scanning' }
  | { status: 'found'; page: { url: string; title: string; h1?: string }; isBlogPost: boolean }
  | { status: 'not_found' }

export function LocalSeoContent() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: savedPages, isLoading: loadingSaved } = useQuery<LocalSeoPageListItem[]>({
    queryKey: ['local-seo-pages', clientId],
    queryFn: () => localSeoApi.listPages(clientId),
    enabled: Boolean(clientId),
  })

  const [tab, setTab] = useState<'new' | 'plan' | 'saved'>(
    // Deep-link support: /clients/:id/local-seo?tab=saved (or ?tab=plan).
    searchParams.get('tab') === 'saved' ? 'saved'
      : searchParams.get('tab') === 'plan' ? 'plan'
      : 'new',
  )
  const [view, setView] = useState<View>({ kind: 'form' })
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  // DataForSEO location_code from a picked suggestion; null while free-typing.
  const [locationCode, setLocationCode] = useState<number | null>(null)
  const [runAnalysis, setRunAnalysis] = useState<boolean | null>(null)
  // Bypass the 14-day shared SERP-analysis cache and re-scrape competitors.
  const [forceRefresh, setForceRefresh] = useState(false)
  // Phase 3 — mirror an existing page's structure. Blank → the client's saved default.
  const [pageTemplateUrl, setPageTemplateUrl] = useState('')
  const [savingTemplateDefault, setSavingTemplateDefault] = useState(false)
  const [error, setError] = useState('')
  const [check, setCheck] = useState<CheckState>({ status: 'idle' })
  const [scanning, setScanning] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [manualUrl, setManualUrl] = useState('')

  // Plan Silo tab — research a topic's parent/sibling/neighbourhood silo up front.
  const [planScanning, setPlanScanning] = useState(false)
  const [planResults, setPlanResults] = useState<RelatedPageItem[] | null>(null)
  const [planError, setPlanError] = useState('')

  // Bulk creation — generate the selected missing silo pages sequentially.
  const [selectedForCreate, setSelectedForCreate] = useState<Set<string>>(new Set())
  const [bulkRunAnalysis, setBulkRunAnalysis] = useState(false)
  const [bulkCreating, setBulkCreating] = useState(false)
  const [bulkProgress, setBulkProgress] = useState<{ current: number; total: number; currentKw: string } | null>(null)
  const [bulkElapsed, setBulkElapsed] = useState(0)
  const [bulkDone, setBulkDone] = useState(0)
  const [bulkFailed, setBulkFailed] = useState(0)
  const bulkTickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const bulkCancelledRef = useRef(false)
  const bulkAbortRef = useRef<AbortController | null>(null)

  // Creating-progress ticker (the generate POST blocks until done, so progress
  // is time-based rather than streamed).
  const [elapsed, setElapsed] = useState(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const hasGbp = Boolean(client?.gbp?.business_name)
  const hasWebsite = Boolean(client?.website_url || client?.gbp?.website)
  const canGenerate = Boolean(keyword.trim() && location.trim() && runAnalysis !== null)

  // Reset transient form state when the service/area inputs change (called from
  // the input handlers — avoids a setState-in-effect cascade).
  const resetTransient = () => {
    setCheck({ status: 'idle' })
    setManualUrl('')
    setError('')
  }

  const stopTicker = () => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
  }
  const startTicker = () => {
    stopTicker() // clear any prior interval so a rapid re-submit can't leak one
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
  }
  useEffect(() => () => stopTicker(), [])
  // Stop the bulk timer and abort any in-flight generate if the page unmounts mid-run.
  useEffect(() => () => {
    if (bulkTickRef.current) clearInterval(bulkTickRef.current)
    bulkAbortRef.current?.abort()
  }, [])

  const refreshSaved = () => queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] })

  // ── Actions ────────────────────────────────────────────────────────────────

  const handleGenerate = async (kwOverride?: string) => {
    const kw = (typeof kwOverride === 'string' ? kwOverride : keyword).trim()
    if (!kw || !location.trim() || runAnalysis === null) return
    setError('')
    setView({ kind: 'creating' })
    startTicker()
    try {
      const page = await localSeoApi.generate(clientId, { keyword: kw, location: location.trim(), location_code: locationCode, run_analysis: runAnalysis, force_refresh: forceRefresh, page_template_url: pageTemplateUrl.trim() || null })
      refreshSaved()
      setView({ kind: 'generated', page, isNew: true, prevScore: null })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Generation failed')
      setView({ kind: 'form' })
    } finally {
      stopTicker()
    }
  }

  const handleCheckSite = async () => {
    if (!keyword.trim() || !location.trim()) return
    if (!client?.website_url && !client?.gbp?.website) {
      setError('This client has no website on file. Add one to scan for existing pages.')
      return
    }
    setError('')
    setScanning(true)
    setCheck({ status: 'scanning' })
    try {
      const data = await localSeoApi.findPage(clientId, { keyword: keyword.trim(), location: location.trim() })
      if (data.found && data.page) {
        setCheck({ status: 'found', page: data.page, isBlogPost: data.is_blog_post })
      } else {
        setCheck({ status: 'not_found' })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Site scan failed')
      setCheck({ status: 'idle' })
    } finally {
      setScanning(false)
    }
  }

  const handleScanSilo = async () => {
    if (!keyword.trim() || !location.trim()) return
    setPlanError('')
    setPlanScanning(true)
    setPlanResults(null)
    setSelectedForCreate(new Set())
    setBulkDone(0)
    setBulkFailed(0)
    try {
      const data = await localSeoApi.relatedPages(clientId, { keyword: keyword.trim(), location: location.trim() })
      setPlanResults(data.items ?? [])
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setPlanScanning(false)
    }
  }

  // Hand a single found silo page off to the writer's score/reoptimize view.
  // (Missing items are selected via checkboxes and created in bulk instead.)
  const handlePlanAction = (item: RelatedPageItem) => {
    if (item.status === 'found' && item.url) {
      setKeyword(item.keyword)
      setView({ kind: 'score', pageUrl: item.url })
    }
  }

  const toggleSelect = (kw: string, checked: boolean) => setSelectedForCreate(prev => {
    const next = new Set(prev)
    if (checked) next.add(kw); else next.delete(kw)
    return next
  })

  // Generate each selected missing page in turn via the existing generate flow
  // (which saves server-side). Sequential by design: one long generation at a
  // time keeps progress honest and isolates per-page failures. No new backend.
  const handleBulkCreate = async () => {
    const queue = (planResults ?? [])
      .filter(r => r.status === 'missing' && selectedForCreate.has(r.keyword))
      .map(r => r.keyword)
    if (!queue.length || bulkCreating) return
    bulkCancelledRef.current = false
    bulkAbortRef.current = new AbortController()
    setBulkCreating(true)
    setBulkDone(0)
    setBulkFailed(0)
    setBulkElapsed(0)
    if (bulkTickRef.current) clearInterval(bulkTickRef.current)
    bulkTickRef.current = setInterval(() => setBulkElapsed(s => s + 1), 1000)

    let done = 0
    let failed = 0
    for (let i = 0; i < queue.length; i++) {
      if (bulkCancelledRef.current) break
      setBulkProgress({ current: i + 1, total: queue.length, currentKw: queue[i] })
      try {
        await localSeoApi.generate(
          clientId,
          { keyword: queue[i], location: location.trim(), location_code: locationCode, run_analysis: bulkRunAnalysis, force_refresh: false, page_template_url: null },
          bulkAbortRef.current?.signal,
        )
        if (bulkCancelledRef.current) break
        done++; setBulkDone(done)
      } catch {
        if (bulkCancelledRef.current) break
        failed++; setBulkFailed(failed)
      }
    }

    if (bulkTickRef.current) { clearInterval(bulkTickRef.current); bulkTickRef.current = null }
    bulkAbortRef.current = null
    setBulkCreating(false)
    setBulkProgress(null)
    // Drop the keywords we handled (kept the failed ones deselected too — they
    // can be re-selected for a retry); refresh the Saved Pages list.
    setSelectedForCreate(new Set())
    refreshSaved()
  }

  const cancelBulk = () => {
    bulkCancelledRef.current = true
    bulkAbortRef.current?.abort()
    bulkAbortRef.current = null
    if (bulkTickRef.current) { clearInterval(bulkTickRef.current); bulkTickRef.current = null }
  }

  const handlePreviewAnalysis = async () => {
    if (!keyword.trim() || !location.trim()) return
    setError('')
    setAnalyzing(true)
    try {
      const result = await localSeoApi.analyze(clientId, { keyword: keyword.trim(), location: location.trim(), location_code: locationCode, force_refresh: forceRefresh })
      setView({ kind: 'analysis', result })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleSaveTemplateDefault = async () => {
    setSavingTemplateDefault(true)
    setError('')
    try {
      await localSeoApi.setPageTemplateDefault(clientId, pageTemplateUrl.trim() || null)
      await queryClient.invalidateQueries({ queryKey: ['client', clientId] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save default')
    } finally {
      setSavingTemplateDefault(false)
    }
  }

  const openSaved = async (pageId: string) => {
    setView({ kind: 'loading' }) // quick GET — not the multi-minute generate flow
    try {
      const page = await localSeoApi.getPage(pageId)
      setKeyword(page.keyword)
      setLocation(page.location)
      setLocationCode(null)
      setView({ kind: 'generated', page, isNew: false, prevScore: null })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open page')
      setView({ kind: 'form' })
    }
  }

  // ── Sub-view routing ─────────────────────────────────────────────────────

  if (view.kind === 'creating') return <CreatingView elapsed={elapsed} runAnalysis={runAnalysis ?? false} />

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
        <GeneratedPageView
          clientId={clientId}
          page={view.page}
          isNew={view.isNew}
          prevScore={view.prevScore}
          onBack={() => setView({ kind: 'form' })}
          onScoreAndImprove={(page) => setView({ kind: 'score', pageHtml: page.content_html })}
          onRelatedAction={({ mode, keyword: kw, existingUrl }) => {
            setKeyword(kw)
            if (mode === 'reoptimize' && existingUrl) setView({ kind: 'score', pageUrl: existingUrl })
            else handleGenerate(kw)
          }}
          onNewPage={() => { setView({ kind: 'form' }); setKeyword(''); setCheck({ status: 'idle' }) }}
        />
      </div>
    )
  }

  if (view.kind === 'score') {
    return (
      <div style={{ padding: 32 }}>
        <PageScoreView
          clientId={clientId}
          keyword={keyword}
          location={location}
          pageUrl={view.pageUrl}
          pageHtml={view.pageHtml}
          serpAnalysis={view.serpAnalysis}
          onBack={() => setView({ kind: 'form' })}
          onReoptimized={(page, prevScore) => { refreshSaved(); setView({ kind: 'generated', page, isNew: true, prevScore }) }}
          onCreateNew={() => handleGenerate()}
        />
      </div>
    )
  }

  if (view.kind === 'analysis') {
    return (
      <div style={{ padding: 32 }}>
        <AnalysisResultsView result={view.result} onBack={() => setView({ kind: 'form' })} />
      </div>
    )
  }

  // ── Main form ──────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 32, maxWidth: 720 }}>
      <Link to={`/clients/${clientId}`} style={{ ...backLink, textDecoration: 'none' }}>
        <ArrowLeft size={14} /> Back to workspace
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '8px 0 2px' }}>Local SEO Content</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 24px' }}>
        Generate location-specific service pages for {client?.name ?? 'this client'}.
      </p>

      {/* Tabs */}
      <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 10, padding: 4, marginBottom: 20 }}>
        {(['new', 'plan', 'saved'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '7px 16px', fontSize: 14, fontWeight: 600, borderRadius: 7, cursor: 'pointer', border: 'none',
              background: tab === t ? '#fff' : 'transparent', color: tab === t ? '#0f172a' : '#64748b',
              boxShadow: tab === t ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{t === 'new' ? 'New Page' : t === 'plan' ? 'Plan Silo' : 'Saved Pages'}</button>
        ))}
      </div>

      {tab === 'saved' ? (
        <SavedPagesList
          pages={savedPages ?? []}
          loading={loadingSaved}
          onOpen={openSaved}
          onDelete={async (pid) => { await localSeoApi.deletePage(pid); refreshSaved() }}
        />
      ) : tab === 'plan' ? (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Research the silo for a topic</h2>
            <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
              Enter a seed service and area. We'll derive the parent / sibling / neighbourhood pages that topic should
              link to and check {client?.name ?? 'this client'}'s site for which already exist — then you can create the
              missing ones in one click.
            </p>
          </div>

          {!hasWebsite && (
            <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 13, color: '#92400e' }}>
              <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                No website is on file for this client, so every page will show as “missing”. <Link to={`/clients/${clientId}/edit`} style={{ color: '#92400e', fontWeight: 600 }}>Add one →</Link> to detect existing pages.
              </span>
            </div>
          )}

          {/* Service */}
          <div>
            <label style={label}>Seed service</label>
            <input style={input} value={keyword} disabled={bulkCreating} onChange={e => { setKeyword(e.target.value); setPlanResults(null); setPlanError(''); setSelectedForCreate(new Set()) }} placeholder="e.g. emergency plumber" />
          </div>

          {/* Area */}
          <div>
            <label style={label}>Area / Location</label>
            <LocationAutocomplete
              clientId={clientId}
              value={location}
              onChange={(loc, code) => { setLocation(loc); setLocationCode(code); setPlanResults(null); setPlanError(''); setSelectedForCreate(new Set()) }}
              placeholder="Start typing a city, e.g. Melbourne…"
              disabled={bulkCreating}
            />
          </div>

          {planError && <div style={errorBox}>{planError}</div>}

          <button
            style={{ ...primaryBtn, width: '100%', opacity: (planScanning || bulkCreating || !keyword.trim() || !location.trim()) ? 0.5 : 1, cursor: (planScanning || bulkCreating || !keyword.trim() || !location.trim()) ? 'not-allowed' : 'pointer' }}
            disabled={planScanning || bulkCreating || !keyword.trim() || !location.trim()}
            onClick={handleScanSilo}
          >
            {planScanning ? <Spinner size={16} /> : <Search size={16} />} {planScanning ? 'Scanning site…' : 'Scan site'}
          </button>

          {planScanning && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 32, color: '#64748b' }}>
              <Spinner size={22} />
              <p style={{ fontSize: 14, margin: 0 }}>Deriving related keywords and checking the site…</p>
              <p style={{ fontSize: 12, opacity: 0.7, margin: 0 }}>This usually takes 30–60 seconds.</p>
            </div>
          )}

          {!planScanning && planResults && planResults.length === 0 && (
            <p style={{ fontSize: 14, color: '#64748b', textAlign: 'center', padding: 24 }}>No related pages found for this topic.</p>
          )}

          {!planScanning && planResults && planResults.length > 0 && (() => {
            const found = planResults.filter(r => r.status === 'found').length
            const missingKws = planResults.filter(r => r.status === 'missing').map(r => r.keyword)
            const allMissingSelected = missingKws.length > 0 && missingKws.every(kw => selectedForCreate.has(kw))
            const selectedCount = selectedForCreate.size
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#64748b', flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{planResults.length} related keywords checked</span>
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#dcfce7', color: '#166534' }}>{found} exist</span>
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#fef3c7', color: '#92400e' }}>{missingKws.length} missing</span>
                  {missingKws.length > 0 && !bulkCreating && (
                    <button
                      onClick={() => setSelectedForCreate(allMissingSelected ? new Set() : new Set(missingKws))}
                      style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}
                    >
                      {allMissingSelected ? 'Deselect all' : 'Select all missing'}
                    </button>
                  )}
                </div>

                {missingKws.length > 0 && (
                  <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>
                    Tick the missing pages you want, then create them in one batch. Found pages can be reoptimized individually.
                  </p>
                )}

                <RelatedPagesList
                  items={planResults}
                  onAction={handlePlanAction}
                  selection={{ selected: selectedForCreate, onToggle: toggleSelect, disabled: bulkCreating }}
                />

                {/* Bulk creation: action bar → progress → summary */}
                {bulkCreating && bulkProgress ? (
                  <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, background: '#f8fafc' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <Spinner size={16} />
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        Creating “{bulkProgress.currentKw}”…
                      </span>
                      <span style={{ marginLeft: 'auto', fontSize: 12, color: '#64748b', flexShrink: 0 }}>
                        {bulkProgress.current} / {bulkProgress.total}{(() => {
                          if (bulkProgress.current <= 1 || bulkElapsed <= 0) return ''
                          const avg = bulkElapsed / (bulkProgress.current - 1)
                          const remaining = Math.round(avg * (bulkProgress.total - bulkProgress.current + 1))
                          if (remaining <= 0) return ''
                          return ` · ~${remaining >= 60 ? `${Math.round(remaining / 60)}m` : `${remaining}s`} left`
                        })()}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {Array.from({ length: bulkProgress.total }).map((_, idx) => (
                        <div key={idx} style={{
                          height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                          background: idx < bulkProgress.current - 1 ? '#16a34a' : idx === bulkProgress.current - 1 ? '#6366f1' : '#e2e8f0',
                        }} />
                      ))}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#64748b' }}>
                      <span>{bulkDone} done{bulkFailed > 0 ? ` · ${bulkFailed} failed` : ''}</span>
                      <button onClick={cancelBulk} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
                        Cancel
                      </button>
                    </div>
                    <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
                      Keep this tab open — pages generate one at a time and each is saved as it finishes.
                    </p>
                  </div>
                ) : (
                  <>
                    {(bulkDone > 0 || bulkFailed > 0) && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {bulkDone > 0 && (
                          <p style={{ fontSize: 13, color: '#16a34a', fontWeight: 600, margin: 0 }}>
                            {bulkDone} page{bulkDone === 1 ? '' : 's'} created and saved — <button onClick={() => setTab('saved')} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#16a34a', fontWeight: 600, textDecoration: 'underline' }}>view in Saved Pages</button>.
                          </p>
                        )}
                        {bulkFailed > 0 && (
                          <p style={{ fontSize: 13, color: '#dc2626', fontWeight: 600, margin: 0 }}>
                            {bulkFailed} page{bulkFailed === 1 ? '' : 's'} failed to generate. Re-select to retry.
                          </p>
                        )}
                      </div>
                    )}

                    {selectedCount > 0 && (
                      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, background: '#f8fafc' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
                          <input type="checkbox" checked={bulkRunAnalysis} onChange={e => setBulkRunAnalysis(e.target.checked)} />
                          Run competitor SERP analysis for each page (stronger pages, but much slower)
                        </label>
                        <button style={{ ...primaryBtn, width: '100%' }} onClick={handleBulkCreate}>
                          <Sparkles size={16} /> Create {selectedCount} selected page{selectedCount === 1 ? '' : 's'}
                        </button>
                        <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, textAlign: 'center' }}>
                          Each page takes ~2–4 minutes{bulkRunAnalysis ? ' (longer with analysis)' : ''}. They’re created one at a time.
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })()}
        </div>
      ) : (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>What service and area do you want to rank for?</h2>

          {!hasGbp && (
            <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 13, color: '#92400e' }}>
              <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                No Google Business Profile is attached to this client. Pages will still generate from available data, but
                attaching a GBP greatly improves results. <Link to={`/clients/${clientId}/edit#gbp`} style={{ color: '#92400e', fontWeight: 600 }}>Set one up →</Link>
              </span>
            </div>
          )}

          {/* Service */}
          <div>
            <label style={label}>Service</label>
            <input style={input} value={keyword} onChange={e => { setKeyword(e.target.value); resetTransient() }} placeholder="e.g. emergency plumber" />
          </div>

          {/* Area */}
          <div>
            <label style={label}>Area / Location</label>
            <LocationAutocomplete
              clientId={clientId}
              value={location}
              onChange={(loc, code) => { setLocation(loc); setLocationCode(code); resetTransient() }}
              placeholder="Start typing a city, e.g. Melbourne…"
            />
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
              Pick a suggestion so the location is recognized — free-typed areas that don’t match will be rejected.
            </p>
          </div>

          {/* Page template (Phase 3) — mirror an existing page's structure */}
          <div>
            <label style={label}>Mirror an existing page’s structure (optional)</label>
            <input
              style={input}
              value={pageTemplateUrl}
              onChange={e => setPageTemplateUrl(e.target.value)}
              placeholder={client?.local_seo_page_template_url || 'https://example.com/a-page-to-mirror'}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                {client?.local_seo_page_template_url
                  ? <>Client default: {client.local_seo_page_template_url} — leave blank to use it.</>
                  : 'The new page will follow this page’s section layout. Leave blank for the standard structure.'}
              </span>
              <button
                type="button"
                onClick={handleSaveTemplateDefault}
                disabled={savingTemplateDefault}
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}
              >
                {savingTemplateDefault ? 'Saving…' : 'Save as client default'}
              </button>
            </div>
          </div>

          {/* Required analysis choice */}
          <div>
            <label style={label}>Competitor SERP analysis</label>
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 8px' }}>
              Analyze top-ranking competitor pages to target the right terms, entities, and phrases. Slower and uses more
              API credit, but produces a stronger page. Required choice.
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <ChoiceCard
                active={runAnalysis === true}
                onClick={() => setRunAnalysis(true)}
                title="Run analysis"
                desc="Scrape & analyze competitors (recommended)"
              />
              <ChoiceCard
                active={runAnalysis === false}
                onClick={() => setRunAnalysis(false)}
                title="Skip analysis"
                desc="Generate faster from client data only"
              />
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
              <input type="checkbox" checked={forceRefresh} onChange={e => setForceRefresh(e.target.checked)} />
              Refresh competitor data (ignore the 14-day cache — slower, re-scrapes)
            </label>
          </div>

          {error && <div style={errorBox}>{error}</div>}

          {/* Optional pre-checks */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button style={outlineBtn} onClick={handleCheckSite} disabled={scanning || !keyword.trim() || !location.trim()}>
              {scanning ? <Spinner size={14} /> : <FileSearch size={14} />} {scanning ? 'Checking site…' : 'Check site for existing page'}
            </button>
            <button style={outlineBtn} onClick={handlePreviewAnalysis} disabled={analyzing || !keyword.trim() || !location.trim()}>
              {analyzing ? <Spinner size={14} /> : <Search size={14} />} {analyzing ? 'Analyzing competitors…' : 'Preview competitor analysis'}
            </button>
          </div>

          {/* Site-scan results */}
          {check.status === 'scanning' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, fontSize: 13, color: '#64748b' }}>
              <Spinner size={14} /> Scanning the client site for a "{keyword}" page…
            </div>
          )}

          {check.status === 'found' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
                <FileSearch size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                <div style={{ minWidth: 0 }}>
                  <p style={{ margin: 0, fontWeight: 600 }}>Existing page found:</p>
                  <a href={check.page.url} target="_blank" rel="noreferrer" style={{ color: '#92400e', wordBreak: 'break-all' }}>{check.page.url}</a>
                  {check.isBlogPost && <p style={{ margin: '4px 0 0' }}>⚠ This looks like a blog post, not a dedicated service page.</p>}
                </div>
              </div>
              <button style={{ ...primaryBtn, width: '100%' }} onClick={() => setView({ kind: 'score', pageUrl: check.page.url })}>
                View &amp; score this page
              </button>
              <div style={{ display: 'flex', gap: 8 }}>
                <input style={{ ...input, flex: 1 }} placeholder="Or score a different URL…" value={manualUrl}
                  onChange={e => setManualUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && manualUrl.trim()) setView({ kind: 'score', pageUrl: normalizeUrl(manualUrl) }) }} />
                <button style={outlineBtn} disabled={!manualUrl.trim()} onClick={() => setView({ kind: 'score', pageUrl: normalizeUrl(manualUrl) })}>Score</button>
              </div>
              <button style={{ ...backLink, alignSelf: 'center', marginBottom: 0 }} onClick={() => setCheck({ status: 'not_found' })}>
                No suitable page — create a new one instead
              </button>
            </div>
          )}

          {check.status === 'not_found' && (
            <div style={{ display: 'flex', gap: 8, padding: '10px 14px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, fontSize: 13, color: '#166534' }}>
              <FilePlus size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>No existing page found for "{keyword}" — creating a new page is recommended.</span>
            </div>
          )}

          {/* Primary action */}
          <button
            style={{ ...primaryBtn, width: '100%', opacity: canGenerate ? 1 : 0.5, cursor: canGenerate ? 'pointer' : 'not-allowed' }}
            disabled={!canGenerate}
            onClick={() => handleGenerate()}
          >
            <Sparkles size={16} /> Create new page
          </button>
          {!canGenerate && (
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '-8px 0 0', textAlign: 'center' }}>
              Enter a service, an area, and choose whether to run analysis.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function normalizeUrl(u: string): string {
  const t = u.trim()
  if (!/^https?:\/\//i.test(t)) return `https://${t}`
  return t
}

function ChoiceCard({ active, onClick, title, desc }: { active: boolean; onClick: () => void; title: string; desc: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1, textAlign: 'left', cursor: 'pointer', borderRadius: 10, padding: '12px 14px',
        background: active ? '#eef2ff' : '#fff',
        border: `1.5px solid ${active ? '#6366f1' : '#e2e8f0'}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 600, color: active ? '#4338ca' : '#0f172a' }}>
        {active && <CheckCircle2 size={15} color="#6366f1" />}{title}
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{desc}</div>
    </button>
  )
}

function SavedPagesList({ pages, loading, onOpen, onDelete }: {
  pages: LocalSeoPageListItem[]
  loading: boolean
  onOpen: (id: string) => void
  onDelete: (id: string) => Promise<void>
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

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
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
      {pages.map((p, i) => (
        <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.page_title || p.keyword}</span>
              <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: p.mode === 'reoptimize' ? '#eff6ff' : '#f0fdf4', color: p.mode === 'reoptimize' ? '#2563eb' : '#16a34a' }}>
                {p.mode === 'reoptimize' ? 'Reoptimized' : 'Generated'}
              </span>
              {p.composite_score != null && (
                <span style={{ fontSize: 11, fontWeight: 700, color: scoreColor(p.composite_score) }}>{Math.round(p.composite_score)}/100</span>
              )}
            </div>
            <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
              {p.keyword} · {p.location.split(',')[0]} <span style={{ marginLeft: 6, opacity: 0.7 }}>{relativeTime(p.created_at)}</span>
            </p>
          </div>
          <button style={outlineBtn} onClick={() => onOpen(p.id)}>View <ArrowRight size={13} /></button>
          {confirmId === p.id ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748b' }}>
              Delete?
              <button onClick={() => handleDelete(p.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#dc2626', fontWeight: 600 }}>Yes</button>
              <button onClick={() => setConfirmId(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}>No</button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmId(p.id)}
              disabled={deletingId === p.id}
              title="Delete"
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', display: 'inline-flex', alignItems: 'center' }}
            >
              {deletingId === p.id ? <Spinner size={14} /> : <Trash2 size={15} />}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function CreatingView({ elapsed, runAnalysis }: { elapsed: number; runAnalysis: boolean }) {
  const pct = Math.min(95, Math.round((elapsed / 180) * 100))
  const steps = runAnalysis
    ? [
        { label: 'Fetching top search results', done: pct >= 35, active: pct < 35 },
        { label: 'Scraping & analyzing competitor pages', done: pct >= 65, active: pct >= 35 && pct < 65 },
        { label: 'Generating & scoring your page', done: pct >= 95, active: pct >= 65 },
      ]
    : [
        { label: 'Building your page', done: pct >= 60, active: pct < 60 },
        { label: 'Scoring & finalizing', done: pct >= 95, active: pct >= 60 },
      ]
  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60
  const elapsedLabel = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`

  return (
    <div style={{ padding: 32, maxWidth: 640, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 2px' }}>Creating your page</h1>
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
    </div>
  )
}
