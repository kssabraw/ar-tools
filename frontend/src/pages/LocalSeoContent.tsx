import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, Building2, CheckCircle2, ChevronDown, ChevronRight, MapPin, RotateCcw, Search, Sparkles, Trash2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { localSeoApi } from '../components/localseo/api'
import { LocationAutocomplete } from '../components/localseo/LocationAutocomplete'
import type { AnalysisResult, ExistingMatch, LocalSeoPageDetail, LocalSeoPageListItem, PrecheckResult, RankabilityResult, RelatedPageItem } from '../components/localseo/types'
import { GeneratedPageView } from '../components/localseo/GeneratedPageView'
import { RelatedPagesList } from '../components/localseo/RelatedPagesList'
import { BulkCreateBar } from '../components/localseo/BulkCreateBar'
import { useSiloPlan } from '../components/localseo/useSiloPlan'
import { useBulkCreate } from '../components/localseo/useBulkCreate'
import { useBulkPublish, type PublishItem } from '../components/publish/useBulkPublish'
import { BulkPublishBar } from '../components/publish/BulkPublishBar'
import { PageScoreView } from '../components/localseo/PageScoreView'
import { ReoptimizeView } from '../components/localseo/ReoptimizeView'
import { RankabilityReport } from '../components/localseo/RankabilityReport'
import { Spinner } from '../components/localseo/Spinner'
import {
  backLink, card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime, scoreColor,
} from '../components/localseo/shared'

type View =
  | { kind: 'form' }
  | { kind: 'prechecking' }
  | { kind: 'choice'; result: PrecheckResult; kw: string }
  | { kind: 'creating' }
  | { kind: 'loading' }
  | { kind: 'generated'; page: LocalSeoPageDetail; isNew: boolean; prevScore: number | null }
  | { kind: 'score'; pageUrl?: string; pageHtml?: string; serpAnalysis?: AnalysisResult | null }

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

  const { data: draftPages, isLoading: loadingDrafts } = useQuery<LocalSeoPageListItem[]>({
    queryKey: ['local-seo-drafts', clientId],
    queryFn: () => localSeoApi.listDrafts(clientId),
    enabled: Boolean(clientId),
  })

  const [tab, setTab] = useState<'new' | 'plan' | 'reopt' | 'saved' | 'drafts'>(
    // Deep-link support: /clients/:id/local-seo?tab=saved (or plan / reopt / drafts).
    searchParams.get('tab') === 'saved' ? 'saved'
      : searchParams.get('tab') === 'plan' ? 'plan'
      : searchParams.get('tab') === 'reopt' ? 'reopt'
      : searchParams.get('tab') === 'drafts' ? 'drafts'
      : 'new',
  )
  const [view, setView] = useState<View>({ kind: 'form' })
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  // DataForSEO location_code from a picked suggestion; null while free-typing.
  const [locationCode, setLocationCode] = useState<number | null>(null)
  // Bypass the 14-day shared SERP-analysis cache and re-scrape competitors.
  const [forceRefresh, setForceRefresh] = useState(false)
  // Phase 3 — mirror an existing page's structure. Blank → the client's saved default.
  const [pageTemplateUrl, setPageTemplateUrl] = useState('')
  const [savingTemplateDefault, setSavingTemplateDefault] = useState(false)
  const [error, setError] = useState('')
  // Advanced options (page template + cache refresh) collapse, hidden by default.
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Map-pack rankability check (single point-in-time report).
  const [rankability, setRankability] = useState<RankabilityResult | null>(null)
  const [rankabilityLoading, setRankabilityLoading] = useState(false)
  // For a service-area business (no GBP address) the user supplies the city the
  // business is physically in, so distance to the target area can be measured.
  const [sabCity, setSabCity] = useState('')

  // Plan Silo tab — Fanout-powered silo discovery + keyword clustering, surfaced
  // as candidate page targets grouped by silo. Same async engine as the per-page
  // "Related Pages" tab, via the shared hook (kick off + poll). Aliased to the
  // local names the render uses.
  const siloPlan = useSiloPlan(clientId)
  const planScanning = siloPlan.loading
  const planResults = siloPlan.items
  const planNotes = siloPlan.notes
  const planError = siloPlan.error
  // Elapsed-time ticker for the planning spinner — restarts whenever a plan
  // begins and clears when it finishes (the run is a background job; this just
  // reassures the user it's still working).
  const [planElapsed, setPlanElapsed] = useState(0)
  useEffect(() => {
    if (!planScanning) return
    setPlanElapsed(0)
    const id = setInterval(() => setPlanElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [planScanning])


  // Creating-progress ticker. Generation runs as a background job; progress is
  // time-based and we poll the job for completion.
  const [elapsed, setElapsed] = useState(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Background-generation poll. Cancelling stops the polling only — the job keeps
  // running server-side, so the page still lands in Saved Pages.
  const genPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const genCancelledRef = useRef(false)
  // Detached = the user left the creating screen but the poll keeps running so
  // Saved Pages updates live when it finishes (without yanking them back).
  const genDetachedRef = useRef(false)

  const hasGbp = Boolean(client?.gbp?.business_name)
  const hasWebsite = Boolean(client?.website_url || client?.gbp?.website)
  const canGenerate = Boolean(keyword.trim() && location.trim())
  // A GBP with no street address is a service-area business — it hides its address.
  const isSab = hasGbp && !client?.gbp?.address?.trim()

  // Reset transient form state when the service/area inputs change (called from
  // the input handlers — avoids a setState-in-effect cascade).
  const resetTransient = () => {
    setError('')
    setRankability(null)
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
  // Stop the single-generate poll if the page unmounts mid-run. The background
  // job itself keeps running server-side. (Plan-silo bulk cleanup lives in the
  // useBulkCreate hook.)
  useEffect(() => () => {
    genCancelledRef.current = true
    if (genPollRef.current) clearTimeout(genPollRef.current)
  }, [])

  const refreshSaved = () => {
    queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] })
    queryClient.invalidateQueries({ queryKey: ['local-seo-drafts', clientId] })
  }

  // Plan Silo bulk creation — background jobs via the shared hook (same flow as
  // the per-page Related Pages tab); selection + progress live in the hook.
  const planBulk = useBulkCreate(clientId, refreshSaved)

  // ── Actions ────────────────────────────────────────────────────────────────

  // Actually write the page (no precheck). Used after the user opts past the
  // existing-page gate. Runs as a background job: we kick it off, then poll —
  // but the user can leave at any time (even switch clients) and it keeps going
  // server-side, landing in Saved Pages when done.
  const runGenerate = async (kwOverride?: string) => {
    const kw = (typeof kwOverride === 'string' ? kwOverride : keyword).trim()
    if (!kw || !location.trim()) return
    setError('')
    setView({ kind: 'creating' })
    startTicker()
    genCancelledRef.current = false
    genDetachedRef.current = false
    if (genPollRef.current) clearTimeout(genPollRef.current)
    try {
      const { job_id } = await localSeoApi.generateAsync(clientId, {
        keyword: kw, location: location.trim(), location_code: locationCode,
        force_refresh: forceRefresh, page_template_url: pageTemplateUrl.trim() || null,
      })
      const poll = async () => {
        if (genCancelledRef.current) return
        try {
          const res = await localSeoApi.getGenerateJob(clientId, job_id)
          if (genCancelledRef.current) return
          if (res.status === 'complete' && res.page_id) {
            stopTicker()
            refreshSaved() // page appears in Saved Pages even if the user left
            if (!genDetachedRef.current) {
              const page = await localSeoApi.getPage(res.page_id)
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
  // (detached), so the finished page drops into Saved Pages live; navigating to
  // another client unmounts the page and stops the poll, but the job still
  // completes server-side and the page is there on return.
  const leaveGenerating = () => {
    genDetachedRef.current = true
    stopTicker()
    setView({ kind: 'form' })
    setTab('saved')
  }

  // Primary "Create new page" action: gate on the existing-page precheck. If the
  // client already has (or ranks for) a page on this topic, pause and let the
  // user reoptimize it instead of writing a duplicate. No matches → write straight
  // away. A precheck failure is non-fatal — we fall through to generation so the
  // check can never block page creation.
  const handleGenerate = async (kwOverride?: string) => {
    const kw = (typeof kwOverride === 'string' ? kwOverride : keyword).trim()
    if (!kw || !location.trim()) return
    setError('')
    setView({ kind: 'prechecking' })
    try {
      const result = await localSeoApi.precheck(clientId, {
        keyword: kw, location: location.trim(), location_code: locationCode,
      })
      if (result.matches.length > 0) {
        setView({ kind: 'choice', result, kw })
        return
      }
    } catch {
      // best-effort — don't block page creation on a precheck failure
    }
    await runGenerate(kw)
  }

  // Reoptimize an existing match: an in-tool page opens in its detail view (with
  // Score & Improve); a live-site / ranking page goes straight to the score →
  // reoptimize pipeline by URL.
  const handleReoptimizeMatch = (match: ExistingMatch) => {
    if (match.matched_keyword) setKeyword(match.matched_keyword)
    if (match.page_id) {
      void openSaved(match.page_id)
    } else if (match.url) {
      setView({ kind: 'score', pageUrl: match.url })
    }
  }

  const handleCheckRankability = async () => {
    if (!keyword.trim() || !location.trim()) return
    if (!hasGbp) {
      setError('Attach a Google Business Profile to this client to run a map-pack check.')
      return
    }
    setError('')
    setRankabilityLoading(true)
    setRankability(null)
    try {
      const data = await localSeoApi.checkRankability(clientId, {
        keyword: keyword.trim(),
        location: location.trim(),
        location_code: locationCode,
        sab_city: isSab && sabCity.trim() ? sabCity.trim() : null,
      })
      setRankability(data)
    } catch (e) {
      // Graceful fallback — render just the error message in the report card.
      setRankability({
        score: 0, verdict: 'unknown', score_breakdown: {},
        has_map_pack: false, competitors: [], ranking_categories: [],
        category_match: 'none', distance_ok: true,
        keyword_in_competitor_names: 0, competitor_name_examples: [],
        in_maps_results: false, is_sab: false, sab_pack_mismatch: false,
        physical_competitors_in_pack: 0,
        message: e instanceof Error ? e.message : 'Could not retrieve map pack data.',
        match_count: 0, total_results: 0,
      })
    } finally {
      setRankabilityLoading(false)
    }
  }

  const handleScanSilo = () => {
    if (!keyword.trim() || !location.trim()) return
    planBulk.reset()
    void siloPlan.run(keyword, location, locationCode)
  }

  // Hand a single found silo page off to the writer's score/reoptimize view.
  // (Missing items are selected via checkboxes and created in bulk instead.)
  const handlePlanAction = (item: RelatedPageItem) => {
    if (item.status === 'found' && item.url) {
      setKeyword(item.keyword)
      setView({ kind: 'score', pageUrl: item.url })
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

  if (view.kind === 'creating') return <CreatingView elapsed={elapsed} onLeave={leaveGenerating} />

  if (view.kind === 'prechecking') {
    return (
      <div style={{ padding: 32, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#64748b', minHeight: 280 }}>
        <Spinner size={22} />
        <p style={{ fontSize: 14, margin: 0 }}>Checking for an existing or ranking page for “{keyword}”…</p>
        <p style={{ fontSize: 12, opacity: 0.7, margin: 0 }}>Scanning saved pages, the live site, and search rankings.</p>
      </div>
    )
  }

  if (view.kind === 'choice') {
    return (
      <div style={{ padding: 32 }}>
        <ExistingPageChoiceView
          result={view.result}
          keyword={view.kw}
          location={location}
          onReoptimize={handleReoptimizeMatch}
          onWriteNew={() => runGenerate(view.kw)}
          onBack={() => setView({ kind: 'form' })}
        />
      </div>
    )
  }

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
          onNewPage={() => { setView({ kind: 'form' }); setKeyword('') }}
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
          onCreateNew={() => runGenerate()}
          onLeaveBackground={() => { refreshSaved(); setView({ kind: 'form' }); setTab('saved') }}
        />
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
        {(['new', 'plan', 'reopt', 'saved', 'drafts'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '7px 16px', fontSize: 14, fontWeight: 600, borderRadius: 7, cursor: 'pointer', border: 'none',
              background: tab === t ? '#fff' : 'transparent', color: tab === t ? '#0f172a' : '#64748b',
              boxShadow: tab === t ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{t === 'new' ? 'New Page' : t === 'plan' ? 'Plan Silo' : t === 'reopt' ? 'Reoptimize' : t === 'saved' ? 'Saved Pages' : `Drafts${draftPages && draftPages.length ? ` (${draftPages.length})` : ''}`}</button>
        ))}
      </div>

      {tab === 'saved' ? (
        <SavedPagesList
          pages={savedPages ?? []}
          loading={loadingSaved}
          onOpen={openSaved}
          onDelete={async (pid) => { await localSeoApi.deletePage(pid); refreshSaved() }}
        />
      ) : tab === 'drafts' ? (
        <DraftsList
          pages={draftPages ?? []}
          loading={loadingDrafts}
          onOpen={openSaved}
          onRestore={async (pid) => { await localSeoApi.restorePage(pid); refreshSaved() }}
          onPurge={async (pid) => { await localSeoApi.purgePage(pid); refreshSaved() }}
          onPurgeAll={async () => { await localSeoApi.purgeDrafts(clientId); refreshSaved() }}
        />
      ) : tab === 'reopt' ? (
        <ReoptimizeView
          clientId={clientId}
          clientName={client?.name}
          onOpenSaved={() => { refreshSaved(); setTab('saved') }}
        />
      ) : tab === 'plan' ? (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Plan the silo for a service</h2>
            <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
              Enter a seed service and area. We research the topic, discover the service silos around it, then expand
              and cluster real search demand into candidate pages — grouped by silo. Each is checked against
              {' '}{client?.name ?? 'this client'}'s existing pages, so you can create the missing ones in one batch.
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
            <input style={input} value={keyword} disabled={planBulk.creating} onChange={e => { setKeyword(e.target.value); siloPlan.reset(); planBulk.reset() }} placeholder="e.g. emergency plumber" />
          </div>

          {/* Area */}
          <div>
            <label style={label}>Area / Location</label>
            <LocationAutocomplete
              clientId={clientId}
              value={location}
              onChange={(loc, code) => { setLocation(loc); setLocationCode(code); siloPlan.reset(); planBulk.reset() }}
              placeholder="Start typing a city, e.g. Melbourne…"
              disabled={planBulk.creating}
            />
          </div>

          {planError && <div style={errorBox}>{planError}</div>}

          <button
            style={{ ...primaryBtn, width: '100%', opacity: (planScanning || planBulk.creating || !keyword.trim() || !location.trim()) ? 0.5 : 1, cursor: (planScanning || planBulk.creating || !keyword.trim() || !location.trim()) ? 'not-allowed' : 'pointer' }}
            disabled={planScanning || planBulk.creating || !keyword.trim() || !location.trim()}
            onClick={handleScanSilo}
          >
            {planScanning ? <Spinner size={16} /> : <Search size={16} />} {planScanning ? 'Planning silo…' : 'Plan silo'}
          </button>

          {planScanning && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 32, color: '#64748b' }}>
              <Spinner size={22} />
              <p style={{ fontSize: 14, margin: 0 }}>Discovering silos, expanding keywords, and clustering demand…</p>
              <p style={{ fontSize: 15, fontWeight: 600, color: '#475569', fontVariantNumeric: 'tabular-nums', margin: 0 }}>
                {Math.floor(planElapsed / 60)}:{String(planElapsed % 60).padStart(2, '0')} elapsed
              </p>
              <p style={{ fontSize: 12, opacity: 0.7, margin: 0 }}>This usually takes 4–6 minutes. You can keep this tab open.</p>
            </div>
          )}

          {!planScanning && planResults && planResults.length === 0 && (
            <p style={{ fontSize: 14, color: '#64748b', textAlign: 'center', padding: 24 }}>No candidate pages found for this service / area. Try a broader service term.</p>
          )}

          {!planScanning && planNotes.length > 0 && (
            <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
              <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>Some steps ran in degraded mode — results may be partial: {planNotes.join(' · ')}</span>
            </div>
          )}

          {!planScanning && planResults && planResults.length > 0 && (() => {
            const found = planResults.filter(r => r.status === 'found').length
            const onSite = planResults.filter(r => r.status === 'on_site').length
            const missingCount = planResults.filter(r => r.status === 'missing').length
            const siloCount = new Set(planResults.map(r => r.group)).size
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#64748b', flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, color: '#0f172a' }}>{planResults.length} candidate pages across {siloCount} silo{siloCount === 1 ? '' : 's'}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#dcfce7', color: '#166534' }}>{found} exist</span>
                  {onSite > 0 && (
                    <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#dbeafe', color: '#1e40af' }} title="Generic location pages already on the client's site">{onSite} on site</span>
                  )}
                  <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: '#fef3c7', color: '#92400e' }}>{missingCount} missing</span>
                </div>

                <RelatedPagesList
                  items={planResults}
                  onAction={handlePlanAction}
                  selection={{ selected: planBulk.selected, onToggle: planBulk.toggle, disabled: planBulk.creating }}
                />

                <BulkCreateBar
                  items={planResults}
                  bulk={planBulk}
                  location={location}
                  locationCode={locationCode}
                  onViewSaved={() => setTab('saved')}
                />
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

          {/* Advanced options (optional) — page template + cache refresh. Competitor
              SERP analysis always runs at generation, so there's no choice to make here. */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced(v => !v)}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#6366f1', display: 'flex', alignItems: 'center', gap: 4 }}
            >
              {showAdvanced ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Advanced options
            </button>
            {showAdvanced && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 12 }}>
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

                {/* Competitor analysis runs automatically; this only bypasses the cache. */}
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
                  <input type="checkbox" checked={forceRefresh} onChange={e => setForceRefresh(e.target.checked)} />
                  Refresh competitor data (ignore the 14-day cache — slower, re-scrapes)
                </label>
              </div>
            )}
          </div>

          {error && <div style={errorBox}>{error}</div>}

          {/* SAB city — service-area businesses hide their address, so the user
              supplies the city they're physically in for the map-pack distance check. */}
          {isSab && (
            <div>
              <label style={label}>Your business's home city (for the map-pack check)</label>
              <input
                style={input}
                value={sabCity}
                onChange={e => setSabCity(e.target.value)}
                placeholder="e.g. Anaheim, CA"
              />
              <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
                This is a service-area business with no public address. We use this to measure distance to the target area.
              </p>
            </div>
          )}

          {/* Optional pre-check — the existing-page scan now runs automatically as
              part of "Create new page" (the precheck gate), so only the map-pack
              check remains here. */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button style={outlineBtn} onClick={handleCheckRankability} disabled={rankabilityLoading || !keyword.trim() || !location.trim()}>
              {rankabilityLoading ? <Spinner size={14} /> : <MapPin size={14} />} {rankabilityLoading ? 'Checking map pack…' : 'Check map pack'}
            </button>
          </div>

          {/* Map-pack rankability report */}
          {rankabilityLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#f8fafc', borderRadius: 8, fontSize: 13, color: '#64748b' }}>
              <Spinner size={14} /> Checking the Maps pack for "{keyword}"…
            </div>
          )}
          {!rankabilityLoading && rankability && <RankabilityReport result={rankability} />}

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
              Enter a service and an area to continue.
            </p>
          )}
        </div>
      )}
    </div>
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
  const bulk = useBulkPublish()

  const items: PublishItem[] = pages.map(p => ({
    key: `lsp:${p.id}`,
    type: 'local_seo_page',
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
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
      {pages.map((p, i) => {
        const key = `lsp:${p.id}`
        const result = bulk.results[key]
        return (
        <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', background: bulk.selected.has(key) ? '#f5f7ff' : '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
          <input
            type="checkbox"
            checked={bulk.selected.has(key)}
            onChange={e => bulk.toggle(key, e.target.checked)}
            disabled={bulk.publishing}
            style={{ width: 16, height: 16, cursor: 'pointer', flexShrink: 0, accentColor: '#6366f1' }}
            title="Select for bulk publish to Google Docs"
          />
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
          {result?.status === 'done' && (result.docUrl
            ? <a href={result.docUrl} target="_blank" rel="noreferrer" style={{ fontSize: 12, fontWeight: 600, color: '#16a34a', textDecoration: 'none', flexShrink: 0 }}>Open Doc ↗</a>
            : <span style={{ fontSize: 12, fontWeight: 600, color: '#16a34a', flexShrink: 0 }}>Published</span>)}
          {result?.status === 'failed' && <span style={{ fontSize: 12, color: '#dc2626', flexShrink: 0 }} title={result.error}>Failed</span>}
          {result?.status === 'publishing' && <Spinner size={14} />}
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
    <BulkPublishBar items={items} bulk={bulk} />
    </>
  )
}

// The Drafts (recycle bin) tab: soft-deleted pages, each restorable or
// permanently deletable, plus an "Empty drafts" action for the whole bin.
function DraftsList({ pages, loading, onOpen, onRestore, onPurge, onPurgeAll }: {
  pages: LocalSeoPageListItem[]
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
                {p.composite_score != null && (
                  <span style={{ fontSize: 11, fontWeight: 700, color: scoreColor(p.composite_score) }}>{Math.round(p.composite_score)}/100</span>
                )}
              </div>
              <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
                {p.keyword} · {p.location.split(',')[0]}
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

// The automatic gate: shown when the precheck finds the client already has — or
// ranks for — a page on this topic. The user reoptimizes one of the listed pages
// (picking among several when multiple rank) or writes a new page anyway.
function ExistingPageChoiceView({
  result, keyword, location, onReoptimize, onWriteNew, onBack,
}: {
  result: PrecheckResult
  keyword: string
  location: string
  onReoptimize: (m: ExistingMatch) => void
  onWriteNew: () => void
  onBack: () => void
}) {
  const { matches, degraded_notes } = result
  const rankingCount = matches.filter(m => m.signals.includes('ranking')).length
  const sourceLabel = (s?: string | null) =>
    s === 'gsc' ? 'Search Console' : s === 'dataforseo' ? 'Google SERP' : ''

  const signalChip = (m: ExistingMatch) => {
    if (m.signals.includes('ranking')) {
      const pos = m.rank_position
      return { text: pos != null ? `Ranking #${pos}` : 'Ranking', bg: '#fef3c7', color: '#92400e' }
    }
    if (m.signals.includes('in_tool')) return { text: 'Generated in tool', bg: '#f0fdf4', color: '#166534' }
    return { text: 'On live site', bg: '#dbeafe', color: '#1e40af' }
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <button onClick={onBack} style={backLink}><ArrowLeft size={14} /> Back</button>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
        A page for “{keyword}” may already exist
      </h1>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
        {rankingCount > 1
          ? `${rankingCount} of this client's pages are ranking for this keyword in ${location.split(',')[0]}. `
          : ''}
        Reoptimizing an existing page usually beats publishing a competing duplicate. Pick a page to improve, or write a new one.
      </p>

      {degraded_notes.length > 0 && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e', marginBottom: 16 }}>
          <Building2 size={16} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>Some checks ran in degraded mode — results may be partial: {degraded_notes.join(' · ')}</span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
        {matches.map((m, i) => {
          const chip = signalChip(m)
          return (
            <div key={m.page_id || m.url || i} style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5, background: chip.bg, color: chip.color }}>{chip.text}</span>
                {m.signals.includes('ranking') && sourceLabel(m.rank_source) && (
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>via {sourceLabel(m.rank_source)}</span>
                )}
                {m.is_blog_post && (
                  <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5, background: '#fef2f2', color: '#dc2626' }} title="Looks like a blog post, not a dedicated service page">Blog post</span>
                )}
              </div>
              {m.title && <p style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0 }}>{m.title}</p>}
              {m.url && (
                <a href={m.url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#6366f1', wordBreak: 'break-all' }}>
                  {m.url}
                </a>
              )}
              {!m.url && m.page_id && (
                <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>Saved in this client's Local SEO pages.</p>
              )}
              <button style={{ ...primaryBtn, alignSelf: 'flex-start' }} onClick={() => onReoptimize(m)}>
                <ArrowRight size={15} /> Reoptimize this page
              </button>
            </div>
          )
        })}
      </div>

      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 10, background: '#f8fafc' }}>
        <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
          None of these are the right page? Write a brand-new page for “{keyword}”.
        </p>
        <button style={{ ...outlineBtn, alignSelf: 'flex-start' }} onClick={onWriteNew}>
          <Sparkles size={15} /> Write a new page anyway
        </button>
      </div>
    </div>
  )
}

function CreatingView({ elapsed, onLeave }: { elapsed: number; onLeave?: () => void }) {
  const pct = Math.min(95, Math.round((elapsed / 180) * 100))
  // Analysis always runs first, so the progress steps always include it.
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

      {/* Generation runs server-side as a background job, so leaving is safe. */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, marginTop: 16 }}>
        <p style={{ fontSize: 12, color: '#64748b', textAlign: 'center', margin: 0 }}>
          You can leave this page — generation continues in the background and the finished page appears in <b>Saved Pages</b>. Feel free to work on other clients meanwhile.
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
