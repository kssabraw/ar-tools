import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, Building2, CheckCircle2, FilePlus, FileSearch, MapPin, Search, Sparkles, Trash2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { localSeoApi } from '../components/localseo/api'
import type { AnalysisResult, LocalSeoPageDetail, LocalSeoPageListItem } from '../components/localseo/types'
import { GeneratedPageView } from '../components/localseo/GeneratedPageView'
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

  const [tab, setTab] = useState<'new' | 'saved'>('new')
  const [view, setView] = useState<View>({ kind: 'form' })
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [runAnalysis, setRunAnalysis] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const [check, setCheck] = useState<CheckState>({ status: 'idle' })
  const [scanning, setScanning] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [manualUrl, setManualUrl] = useState('')

  // Creating-progress ticker (the generate POST blocks until done, so progress
  // is time-based rather than streamed).
  const [elapsed, setElapsed] = useState(0)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const hasGbp = Boolean(client?.gbp?.business_name)
  const canGenerate = Boolean(keyword.trim() && location.trim() && runAnalysis !== null)

  // Reset transient form state when the service/area inputs change (called from
  // the input handlers — avoids a setState-in-effect cascade).
  const resetTransient = () => {
    setCheck({ status: 'idle' })
    setManualUrl('')
    setError('')
  }

  const startTicker = () => {
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
  }
  const stopTicker = () => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
  }
  useEffect(() => () => stopTicker(), [])

  const refreshSaved = () => queryClient.invalidateQueries({ queryKey: ['local-seo-pages', clientId] })

  // ── Actions ────────────────────────────────────────────────────────────────

  const handleGenerate = async (kwOverride?: string) => {
    const kw = (typeof kwOverride === 'string' ? kwOverride : keyword).trim()
    if (!kw || !location.trim() || runAnalysis === null) return
    setError('')
    setView({ kind: 'creating' })
    startTicker()
    try {
      const page = await localSeoApi.generate(clientId, { keyword: kw, location: location.trim(), run_analysis: runAnalysis })
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

  const handlePreviewAnalysis = async () => {
    if (!keyword.trim() || !location.trim()) return
    setError('')
    setAnalyzing(true)
    try {
      const result = await localSeoApi.analyze(clientId, { keyword: keyword.trim(), location: location.trim() })
      setView({ kind: 'analysis', result })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setAnalyzing(false)
    }
  }

  const openSaved = async (pageId: string) => {
    setView({ kind: 'loading' }) // quick GET — not the multi-minute generate flow
    try {
      const page = await localSeoApi.getPage(pageId)
      setKeyword(page.keyword)
      setLocation(page.location)
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
        {(['new', 'saved'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '7px 16px', fontSize: 14, fontWeight: 600, borderRadius: 7, cursor: 'pointer', border: 'none',
              background: tab === t ? '#fff' : 'transparent', color: tab === t ? '#0f172a' : '#64748b',
              boxShadow: tab === t ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{t === 'new' ? 'New Page' : 'Saved Pages'}</button>
        ))}
      </div>

      {tab === 'saved' ? (
        <SavedPagesList
          pages={savedPages ?? []}
          loading={loadingSaved}
          onOpen={openSaved}
          onDelete={async (pid) => { await localSeoApi.deletePage(pid); refreshSaved() }}
        />
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
            <div style={{ position: 'relative' }}>
              <MapPin size={16} color="#94a3b8" style={{ position: 'absolute', left: 12, top: 12 }} />
              <input style={{ ...input, paddingLeft: 36 }} value={location} onChange={e => { setLocation(e.target.value); resetTransient() }} placeholder="e.g. Anaheim, California, United States" />
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
          </div>

          {error && <div style={errorBox}>{error}</div>}

          {/* Optional pre-checks */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button style={outlineBtn} onClick={handleCheckSite} disabled={scanning || !keyword.trim() || !location.trim()}>
              {scanning ? <Spinner size={14} /> : <FileSearch size={14} />} Check site for existing page
            </button>
            <button style={outlineBtn} onClick={handlePreviewAnalysis} disabled={analyzing || !keyword.trim() || !location.trim()}>
              {analyzing ? <Spinner size={14} /> : <Search size={14} />} Preview competitor analysis
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
