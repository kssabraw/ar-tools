import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  ArrowRight, CheckCircle2, MinusCircle, Search, Sparkles, XCircle,
} from 'lucide-react'
import { ecommerceApi } from './api'
import type { DiscoverItem, EcommercePageType, ReoptimizeUrlResult } from './types'
import { Spinner } from '../localseo/Spinner'
import { card, errorBox, input, label, outlineBtn, primaryBtn, scoreColor } from '../localseo/shared'

// Pages scoring at/above this are skipped server-side. Surfaced here only as copy.
const SCORE_THRESHOLD = 75

// One reoptimization line, ready to dispatch. Either just a URL (uses the shared
// keyword + the page-type switch) or `URL | keyword`.
interface Target {
  url: string
  keyword: string
  pageType: EcommercePageType
  raw: string
  error?: string
}

type RowState =
  | { phase: 'pending' }
  | { phase: 'running' }
  | { phase: 'done'; result: ReoptimizeUrlResult }
  | { phase: 'failed'; error: string }
  | { phase: 'detached' }

function normalizeUrl(u: string): string {
  const t = u.trim()
  if (!t) return ''
  if (!/^https?:\/\//i.test(t)) return `https://${t}`
  return t
}
function looksLikeUrl(u: string): boolean {
  return /^https?:\/\/.+\..+/.test(u)
}

interface Props {
  clientId: string
  clientName?: string
  pageType: EcommercePageType
  onOpenSaved: () => void
}

export function ReoptimizeView({ clientId, clientName, pageType, onOpenSaved }: Props) {
  const [mode, setMode] = useState<'urls' | 'discover'>('urls')
  const [keyword, setKeyword] = useState('')
  const [bulkText, setBulkText] = useState('')
  const [publishToDoc, setPublishToDoc] = useState(false)

  // Discover-from-site state.
  const [discovering, setDiscovering] = useState(false)
  const [discoverItems, setDiscoverItems] = useState<DiscoverItem[] | null>(null)
  const [discoverNote, setDiscoverNote] = useState<string | null>(null)
  const [discoverError, setDiscoverError] = useState('')
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set())

  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [detached, setDetached] = useState(false)
  const [rows, setRows] = useState<Array<{ target: Target; state: RowState }>>([])
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)

  const detachedRef = useRef(false)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { detachedRef.current = true; if (pollRef.current) clearTimeout(pollRef.current) }, [])

  // Parse the pasted textarea into dispatchable targets (URL, optional keyword).
  const parseBulk = (): Target[] =>
    bulkText
      .split('\n')
      .map(l => l.trim())
      .filter(Boolean)
      .map(raw => {
        const parts = raw.split('|').map(p => p.trim())
        const url = normalizeUrl(parts[0] ?? '')
        const kw = parts[1] || keyword.trim()
        const err = !parts[0] ? 'Missing URL' : !looksLikeUrl(url) ? 'Invalid URL' : undefined
        return { url, keyword: kw, pageType, raw, error: err }
      })

  // Discover targets are the selected found pages (each carries its own page_type).
  const discoverTargets = (): Target[] =>
    (discoverItems ?? [])
      .filter(it => selectedUrls.has(it.url))
      .map(it => ({ url: it.url, keyword: keyword.trim(), pageType: it.page_type, raw: it.url }))

  const targets = mode === 'urls' ? parseBulk() : discoverTargets()
  const validTargets = targets.filter(t => !t.error)
  const canRun = !running && validTargets.length > 0

  const runDiscover = async () => {
    setDiscovering(true)
    setDiscoverError('')
    setDiscoverItems(null)
    setDiscoverNote(null)
    setSelectedUrls(new Set())
    try {
      const res = await ecommerceApi.discover(clientId, pageType)
      setDiscoverItems(res.items ?? [])
      setDiscoverNote(res.note ?? null)
    } catch (e) {
      setDiscoverError(e instanceof Error ? e.message : 'Could not scan the site')
    } finally {
      setDiscovering(false)
    }
  }

  const toggleUrl = (url: string) => setSelectedUrls(prev => {
    const next = new Set(prev)
    if (next.has(url)) next.delete(url); else next.add(url)
    return next
  })

  const run = async () => {
    const valid = targets.filter(t => !t.error)
    if (!valid.length || running) return
    setError('')
    detachedRef.current = false
    setDetached(false)
    setRunning(true)
    setRows(valid.map(target => ({ target, state: { phase: 'pending' } as RowState })))
    if (pollRef.current) clearTimeout(pollRef.current)

    let handles: Array<{ job_id: string; page_url: string }> = []
    try {
      const res = await ecommerceApi.reoptimizeBulk(clientId, {
        targets: valid.map(t => ({ page_url: t.url, keyword: t.keyword || null, page_type: t.pageType })),
        score_threshold: SCORE_THRESHOLD,
        publish_to_doc: publishToDoc,
      })
      handles = res.jobs ?? []
    } catch (e) {
      setRunning(false)
      setRows([])
      setError(e instanceof Error ? e.message : 'Could not start reoptimization')
      return
    }
    if (detachedRef.current) return
    if (!handles.length) { setRunning(false); return }
    if (handles.length < valid.length) {
      setRows(prev => prev.map((r, idx) => (
        idx < handles.length ? r : { ...r, state: { phase: 'failed', error: 'Could not enqueue this page.' } }
      )))
    }
    const jobIds = handles.map(h => h.job_id)
    setProgress({ current: 0, total: jobIds.length })

    const poll = async () => {
      if (detachedRef.current) return
      try {
        const statuses = await ecommerceApi.jobsStatus(clientId, jobIds)
        if (detachedRef.current) return
        const byId = new Map(statuses.map(s => [s.job_id, s]))
        setRows(prev => prev.map((r, idx) => {
          const st = handles[idx] && byId.get(handles[idx].job_id)
          if (!st) return r
          if (st.status === 'complete' && st.result) {
            return { ...r, state: { phase: 'done', result: st.result as unknown as ReoptimizeUrlResult } }
          }
          if (st.status === 'failed') {
            return { ...r, state: { phase: 'failed', error: st.error || 'Reoptimization failed' } }
          }
          if (st.status === 'running') return { ...r, state: { phase: 'running' } }
          return r
        }))
        const terminal = statuses.filter(s => s.status === 'complete' || s.status === 'failed').length
        setProgress({ current: terminal, total: jobIds.length })
        if (terminal >= jobIds.length) {
          setRunning(false)
          setProgress(null)
          return
        }
      } catch {
        // transient poll error — keep trying
      }
      pollRef.current = setTimeout(poll, 4000)
    }
    pollRef.current = setTimeout(poll, 4000)
  }

  const leave = () => {
    detachedRef.current = true
    if (pollRef.current) clearTimeout(pollRef.current)
    setRunning(false)
    setDetached(true)
    setProgress(null)
    setRows(prev => prev.map(r =>
      r.state.phase === 'running' || r.state.phase === 'pending'
        ? { ...r, state: { phase: 'detached' } }
        : r,
    ))
  }

  const reoptimizedCount = rows.filter(r => r.state.phase === 'done' && r.state.result.status === 'reoptimized').length
  const allDiscoverSelected = Boolean(discoverItems && discoverItems.length > 0 && discoverItems.every(it => selectedUrls.has(it.url)))

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Reoptimize existing pages</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          Paste live {pageType} URLs (or discover them from the client's site). Each page is scored against the 8 engines
          first — only pages scoring <strong>below {SCORE_THRESHOLD}/100</strong> are rewritten. Stronger pages are
          skipped automatically, with a note explaining why.
        </p>
      </div>

      {/* Mode toggle */}
      <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4, alignSelf: 'flex-start' }}>
        {(['urls', 'discover'] as const).map(m => (
          <button
            key={m}
            onClick={() => !running && setMode(m)}
            disabled={running}
            style={{
              padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: running ? 'not-allowed' : 'pointer', border: 'none',
              background: mode === m ? '#fff' : 'transparent', color: mode === m ? '#0f172a' : '#64748b',
              boxShadow: mode === m ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{m === 'urls' ? 'Paste URLs' : 'Discover from site'}</button>
        ))}
      </div>

      {/* Shared keyword (optional default for lines / discovered pages) */}
      <div>
        <label style={label}>Target keyword <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional — default for every page)</span></label>
        <input style={input} value={keyword} disabled={running} onChange={e => setKeyword(e.target.value)} placeholder="e.g. wireless noise-cancelling headphones" />
      </div>

      {/* URL input(s) */}
      {mode === 'urls' ? (
        <div>
          <label style={label}>Page URLs — one per line</label>
          <textarea
            style={{ ...input, minHeight: 130, fontFamily: 'inherit', resize: 'vertical' }}
            value={bulkText}
            disabled={running}
            onChange={e => setBulkText(e.target.value)}
            placeholder={'https://shop.example.com/products/headphones\nhttps://shop.example.com/products/earbuds | wireless earbuds\nhttps://shop.example.com/collections/audio'}
          />
          <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
            Each line is a page. Use just a URL to apply the keyword above, or
            {' '}<code style={{ background: '#f1f5f9', padding: '1px 5px', borderRadius: 4 }}>URL | keyword</code> to override per line.
            All are treated as <b style={{ textTransform: 'capitalize' }}>{pageType}</b> pages (use the switch above to change).
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <button
            style={{ ...outlineBtn, alignSelf: 'flex-start', opacity: discovering || running ? 0.6 : 1 }}
            onClick={runDiscover}
            disabled={discovering || running}
          >
            {discovering ? <Spinner size={14} /> : <Search size={14} />} {discovering ? 'Scanning site…' : `Discover ${pageType} pages`}
          </button>

          {discoverError && <div style={errorBox}>{discoverError}</div>}
          {discoverNote && <p style={{ fontSize: 12, color: '#92400e', margin: 0 }}>{discoverNote}</p>}

          {discoverItems && discoverItems.length === 0 && !discovering && (
            <p style={{ fontSize: 13, color: '#64748b', textAlign: 'center', padding: 16 }}>
              No {pageType} pages found on this client's site.
            </p>
          )}

          {discoverItems && discoverItems.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8' }}>
                <span>{discoverItems.length} page{discoverItems.length === 1 ? '' : 's'} found. Tick the ones to reoptimize.</span>
                <button
                  onClick={() => setSelectedUrls(allDiscoverSelected ? new Set() : new Set(discoverItems.map(it => it.url)))}
                  disabled={running}
                  style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}
                >
                  {allDiscoverSelected ? 'Deselect all' : 'Select all'}
                </button>
              </div>
              <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', maxHeight: 320, overflowY: 'auto' }}>
                {discoverItems.map((it, i) => (
                  <label key={it.url} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', cursor: 'pointer', borderTop: i ? '1px solid #f1f5f9' : 'none', background: selectedUrls.has(it.url) ? '#f5f7ff' : '#fff' }}>
                    <input
                      type="checkbox"
                      checked={selectedUrls.has(it.url)}
                      onChange={() => toggleUrl(it.url)}
                      disabled={running}
                      style={{ width: 16, height: 16, cursor: 'pointer', flexShrink: 0, accentColor: '#6366f1' }}
                    />
                    <span style={{ fontSize: 13, color: '#0f172a', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.url}>
                      {it.url.replace(/^https?:\/\//, '')}
                    </span>
                    <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: '#eef2ff', color: '#4f46e5', textTransform: 'capitalize', flexShrink: 0 }}>{it.page_type}</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Publish-to-Doc option */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
        <input type="checkbox" checked={publishToDoc} disabled={running} onChange={e => setPublishToDoc(e.target.checked)} />
        Publish each reoptimized page to a Google Doc in {clientName ?? 'the client'}'s Drive folder
      </label>

      {error && <div style={errorBox}>{error}</div>}

      {/* Invalid-line warnings (urls mode) */}
      {mode === 'urls' && targets.some(t => t.error) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
          <span style={{ fontWeight: 600 }}>{targets.filter(t => t.error).length} line(s) will be skipped:</span>
          {targets.filter(t => t.error).slice(0, 5).map((t, i) => (
            <span key={i} style={{ wordBreak: 'break-all' }}>“{t.raw.slice(0, 60)}” — {t.error}</span>
          ))}
        </div>
      )}

      {/* Run / progress */}
      {!running ? (
        <button
          style={{ ...primaryBtn, width: '100%', opacity: canRun ? 1 : 0.5, cursor: canRun ? 'pointer' : 'not-allowed' }}
          disabled={!canRun}
          onClick={run}
        >
          <Sparkles size={16} /> Score &amp; reoptimize {validTargets.length || ''} page{validTargets.length === 1 ? '' : 's'}
        </button>
      ) : (
        <div style={{ ...card, background: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={16} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
              Scoring &amp; reoptimizing in the background… {progress ? `${progress.current} / ${progress.total} done` : ''}
            </span>
            <button onClick={leave} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}>
              Leave &amp; finish in the background
            </button>
          </div>
          {progress && (
            <div style={{ display: 'flex', gap: 4 }}>
              {Array.from({ length: progress.total }).map((_, idx) => (
                <div key={idx} style={{
                  height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                  background: idx < progress.current ? '#16a34a' : '#e2e8f0',
                }} />
              ))}
            </div>
          )}
          <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
            Each page is scored, then rewritten only if it scores below {SCORE_THRESHOLD}. This runs in the background — you can leave; reoptimized pages land in Saved Pages.
          </p>
        </div>
      )}

      {/* Results */}
      {rows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {detached && (
            <p style={{ fontSize: 13, color: '#6366f1', fontWeight: 600, margin: 0 }}>
              Reoptimizing in the background — finished pages appear in Saved Pages. You can work on other clients.
            </p>
          )}
          {!running && reoptimizedCount > 0 && (
            <p style={{ fontSize: 13, color: '#16a34a', fontWeight: 600, margin: 0 }}>
              {reoptimizedCount} page{reoptimizedCount === 1 ? '' : 's'} reoptimized and saved — {' '}
              <button onClick={onOpenSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#16a34a', fontWeight: 600, textDecoration: 'underline' }}>
                view in Saved Pages
              </button>.
            </p>
          )}
          {rows.map((r, i) => <ResultRow key={i} target={r.target} state={r.state} onOpenSaved={onOpenSaved} />)}
        </div>
      )}
    </div>
  )
}

function ResultRow({ target, state, onOpenSaved }: { target: Target; state: RowState; onOpenSaved: () => void }) {
  const urlLabel = target.url.replace(/^https?:\/\//, '')
  let badge: ReactNode
  let detail: ReactNode = null

  if (state.phase === 'pending') {
    badge = <span style={chip('#f1f5f9', '#64748b')}>Queued</span>
  } else if (state.phase === 'running') {
    badge = <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Spinner size={13} /> <span style={{ fontSize: 12, color: '#6366f1', fontWeight: 600 }}>Working…</span></span>
  } else if (state.phase === 'failed') {
    badge = <span style={chip('#fef2f2', '#dc2626')}><XCircle size={12} /> Failed</span>
    detail = <span style={{ fontSize: 12, color: '#dc2626' }}>{state.error}</span>
  } else if (state.phase === 'detached') {
    badge = <span style={chip('#eef2ff', '#6366f1')}>In background</span>
    detail = <span style={{ fontSize: 12, color: '#94a3b8' }}>Still finishing in the background — it’ll appear in Saved Pages when done.</span>
  } else {
    const r = state.result
    if (r.status === 'skipped') {
      badge = <span style={chip('#eff6ff', '#2563eb')}><MinusCircle size={12} /> Skipped</span>
      detail = <span style={{ fontSize: 12, color: '#64748b' }}>{r.reason}</span>
    } else {
      badge = <span style={chip('#f0fdf4', '#16a34a')}><CheckCircle2 size={12} /> Reoptimized</span>
      detail = (
        <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#64748b', flexWrap: 'wrap' }}>
          <span>
            Score{' '}
            {r.prev_score != null && <span style={{ color: scoreColor(r.prev_score), fontWeight: 600 }}>{Math.round(r.prev_score)}</span>}
            {r.prev_score != null && r.new_score != null && <ArrowRight size={11} style={{ margin: '0 2px', verticalAlign: 'middle' }} />}
            {r.new_score != null && <span style={{ color: scoreColor(r.new_score), fontWeight: 700 }}>{Math.round(r.new_score)}</span>}
            /100
          </span>
          {r.published?.doc_url && (
            <a href={r.published.doc_url} target="_blank" rel="noreferrer" style={{ color: '#6366f1', fontWeight: 600 }}>Open Google Doc ↗</a>
          )}
          {r.publish_error && <span style={{ color: '#d97706' }}>Saved, but publish failed: {r.publish_error}</span>}
          <button onClick={onOpenSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#6366f1', fontWeight: 600 }}>
            View saved page
          </button>
        </span>
      )
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 14px', border: '1px solid #e2e8f0', borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13, color: '#0f172a', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={target.url}>
          {urlLabel}
        </span>
        {badge}
      </div>
      {detail}
    </div>
  )
}

function chip(bg: string, color: string): CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
    fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5, background: bg, color,
  }
}
