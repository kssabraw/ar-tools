import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  ArrowRight, CheckCircle2, FileText, GitBranch, Globe, Link2, MinusCircle, Sparkles, XCircle,
} from 'lucide-react'
import { localSeoApi } from './api'
import { LocationAutocomplete } from './LocationAutocomplete'
import type { ReoptimizeUrlResult } from './types'
import { Spinner } from './Spinner'
import { card, errorBox, input, label, primaryBtn, scoreColor } from './shared'

// Pages scoring at/above this are skipped server-side (kept in sync with the
// backend REOPT_SCORE_THRESHOLD). Surfaced here only as copy.
const SCORE_THRESHOLD = 75

type Destination = 'app' | 'doc'

// One reoptimization line, ready to dispatch. For bulk runs each line is either
// just a URL (uses the shared service + area) or `URL | keyword | area`.
interface Target {
  url: string
  keyword: string
  location: string
  locationCode: number | null
  raw: string
  error?: string
}

// Per-target run state. 'pending' before it runs, 'running' while in flight,
// then the resolved ReoptimizeUrlResult — or a failure / cancellation.
type RowState =
  | { phase: 'pending' }
  | { phase: 'running' }
  | { phase: 'done'; result: ReoptimizeUrlResult }
  | { phase: 'failed'; error: string }
  | { phase: 'cancelled' }

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
  onOpenSaved: () => void
}

export function ReoptimizeView({ clientId, clientName, onOpenSaved }: Props) {
  const [mode, setMode] = useState<'single' | 'bulk'>('single')
  const [destination, setDestination] = useState<Destination>('app')

  // Shared service + area (used as the default for bulk lines, and as the only
  // inputs in single mode).
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [locationCode, setLocationCode] = useState<number | null>(null)

  const [singleUrl, setSingleUrl] = useState('')
  const [bulkText, setBulkText] = useState('')

  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  // Keyed by target index → run state. Built when a run starts.
  const [rows, setRows] = useState<Array<{ target: Target; state: RowState }>>([])
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)

  const cancelledRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => abortRef.current?.abort(), [])

  // Parse a bulk textarea into dispatchable targets, applying the shared service
  // + area as the default for lines that don't override them.
  const parseBulk = (): Target[] =>
    bulkText
      .split('\n')
      .map(l => l.trim())
      .filter(Boolean)
      .map(raw => {
        const parts = raw.split('|').map(p => p.trim())
        const url = normalizeUrl(parts[0] ?? '')
        const kw = parts[1] || keyword.trim()
        // A per-line area override is free-typed (no location_code); a line that
        // falls back to the shared area reuses its picked code.
        const hasAreaOverride = Boolean(parts[2])
        const loc = parts[2] || location.trim()
        const error = !parts[0]
          ? 'Missing URL'
          : !looksLikeUrl(url)
            ? 'Invalid URL'
            : !kw
              ? 'No service keyword — add one above or as “URL | keyword | area”.'
              : !loc
                ? 'No area — add one above or as “URL | keyword | area”.'
                : undefined
        return { url, keyword: kw, location: loc, locationCode: hasAreaOverride ? null : locationCode, raw, error }
      })

  const buildTargets = (): Target[] => {
    if (mode === 'single') {
      const url = normalizeUrl(singleUrl)
      const error = !singleUrl.trim()
        ? 'Enter a page URL'
        : !looksLikeUrl(url)
          ? 'That doesn’t look like a valid URL'
          : !keyword.trim()
            ? 'Enter the service this page targets'
            : !location.trim()
              ? 'Enter the area this page targets'
              : undefined
      return [{ url, keyword: keyword.trim(), location: location.trim(), locationCode, raw: url, error }]
    }
    return parseBulk()
  }

  const targets = buildTargets()
  const validTargets = targets.filter(t => !t.error)
  const canRun = !running && validTargets.length > 0

  const run = async () => {
    const all = buildTargets()
    const valid = all.filter(t => !t.error)
    if (!valid.length || running) return
    setError('')
    cancelledRef.current = false
    abortRef.current = new AbortController()
    setRunning(true)
    setRows(valid.map(target => ({ target, state: { phase: 'pending' } as RowState })))

    for (let i = 0; i < valid.length; i++) {
      if (cancelledRef.current) break
      setProgress({ current: i + 1, total: valid.length })
      setRows(prev => prev.map((r, idx) => (idx === i ? { ...r, state: { phase: 'running' } } : r)))
      try {
        const result = await localSeoApi.reoptimizeUrl(
          clientId,
          {
            page_url: valid[i].url,
            keyword: valid[i].keyword,
            location: valid[i].location,
            location_code: valid[i].locationCode,
            score_threshold: SCORE_THRESHOLD,
            publish_to_doc: destination === 'doc',
          },
          abortRef.current?.signal,
        )
        if (cancelledRef.current) break
        setRows(prev => prev.map((r, idx) => (idx === i ? { ...r, state: { phase: 'done', result } } : r)))
      } catch (e) {
        if (cancelledRef.current) break
        const msg = e instanceof Error ? e.message : 'Reoptimization failed'
        setRows(prev => prev.map((r, idx) => (idx === i ? { ...r, state: { phase: 'failed', error: msg } } : r)))
      }
    }

    abortRef.current = null
    setRunning(false)
    setProgress(null)
  }

  const cancel = () => {
    cancelledRef.current = true
    abortRef.current?.abort()
    abortRef.current = null
    setRunning(false)
    setProgress(null)
    // Resolve any still-open rows so they don't hang on a stuck spinner / "Queued".
    // (The in-flight server task may still finish + save its page — that page shows
    // up in Saved Pages; the row here just reflects that we stopped watching it.)
    setRows(prev => prev.map(r =>
      r.state.phase === 'running' || r.state.phase === 'pending'
        ? { ...r, state: { phase: 'cancelled' } }
        : r,
    ))
  }

  const reoptimizedCount = rows.filter(r => r.state.phase === 'done' && r.state.result.status === 'reoptimized').length

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Reoptimize existing pages</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          Paste a live page URL (or a list of them). Each page is scored against the 8 engines first —
          only pages scoring <strong>below {SCORE_THRESHOLD}/100</strong> are rewritten. Stronger pages are
          skipped automatically, with a note explaining why.
        </p>
      </div>

      {/* Mode toggle */}
      <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4, alignSelf: 'flex-start' }}>
        {(['single', 'bulk'] as const).map(m => (
          <button
            key={m}
            onClick={() => !running && setMode(m)}
            disabled={running}
            style={{
              padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: running ? 'not-allowed' : 'pointer', border: 'none',
              background: mode === m ? '#fff' : 'transparent', color: mode === m ? '#0f172a' : '#64748b',
              boxShadow: mode === m ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >{m === 'single' ? 'Single URL' : 'Multiple URLs'}</button>
        ))}
      </div>

      {/* Service + area (defaults for bulk lines; the only target inputs in single mode) */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 240px' }}>
          <label style={label}>Service {mode === 'bulk' && <span style={{ fontWeight: 400, color: '#94a3b8' }}>(default for all lines)</span>}</label>
          <input style={input} value={keyword} disabled={running} onChange={e => setKeyword(e.target.value)} placeholder="e.g. emergency plumber" />
        </div>
        <div style={{ flex: '1 1 240px' }}>
          <label style={label}>Area / Location {mode === 'bulk' && <span style={{ fontWeight: 400, color: '#94a3b8' }}>(default for all lines)</span>}</label>
          <LocationAutocomplete
            clientId={clientId}
            value={location}
            onChange={(loc, code) => { setLocation(loc); setLocationCode(code) }}
            placeholder="Start typing a city, e.g. Melbourne…"
            disabled={running}
          />
        </div>
      </div>

      {/* URL input(s) */}
      {mode === 'single' ? (
        <div>
          <label style={label}>Page URL</label>
          <input
            style={input}
            value={singleUrl}
            disabled={running}
            onChange={e => setSingleUrl(e.target.value)}
            placeholder="https://example.com/services/emergency-plumber-melbourne"
          />
        </div>
      ) : (
        <div>
          <label style={label}>Page URLs — one per line</label>
          <textarea
            style={{ ...input, minHeight: 130, fontFamily: 'inherit', resize: 'vertical' }}
            value={bulkText}
            disabled={running}
            onChange={e => setBulkText(e.target.value)}
            placeholder={'https://example.com/emergency-plumber\nhttps://example.com/blocked-drains | blocked drains | Geelong VIC\nhttps://example.com/hot-water-repairs'}
          />
          <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
            Each line is a page. Use just a URL to apply the service + area above, or
            {' '}<code style={{ background: '#f1f5f9', padding: '1px 5px', borderRadius: 4 }}>URL | service | area</code> to override per line.
          </p>
        </div>
      )}

      {/* Destination */}
      <div>
        <label style={label}>Where should reoptimized pages go?</label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 2 }}>
          <DestOption
            active={destination === 'app'} disabled={running}
            onClick={() => setDestination('app')}
            icon={<Link2 size={15} />} title="Save in the app"
            subtitle="Stored as a reoptimized page in this client's workspace (always saved)."
          />
          <DestOption
            active={destination === 'doc'} disabled={running}
            onClick={() => setDestination('doc')}
            icon={<FileText size={15} />} title="Save in the app + publish to Google Doc"
            subtitle={`A Google Doc is created in ${clientName ?? 'the client'}'s Drive folder for each rewritten page.`}
          />
          {/* Deferred destinations — surfaced so the choice is visible, disabled
              until live-to-CMS / git publishing is unlocked for the suite. */}
          <DestOption disabled icon={<GitBranch size={15} />} title="Commit to a GitHub repo" subtitle="Coming soon." />
          <DestOption disabled icon={<Globe size={15} />} title="Publish to WordPress" subtitle="Coming soon." />
        </div>
      </div>

      {error && <div style={errorBox}>{error}</div>}

      {/* Invalid-line warnings (bulk) */}
      {mode === 'bulk' && targets.some(t => t.error) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
          <span style={{ fontWeight: 600 }}>{targets.filter(t => t.error).length} line(s) will be skipped:</span>
          {targets.filter(t => t.error).slice(0, 5).map((t, i) => (
            <span key={i} style={{ wordBreak: 'break-all' }}>“{t.raw.slice(0, 60)}” — {t.error}</span>
          ))}
        </div>
      )}

      {/* Run / cancel */}
      {!running ? (
        <button
          style={{ ...primaryBtn, width: '100%', opacity: canRun ? 1 : 0.5, cursor: canRun ? 'pointer' : 'not-allowed' }}
          disabled={!canRun}
          onClick={run}
        >
          <Sparkles size={16} /> {mode === 'single'
            ? 'Score & reoptimize this page'
            : `Score & reoptimize ${validTargets.length || ''} page${validTargets.length === 1 ? '' : 's'}`}
        </button>
      ) : (
        <div style={{ ...card, background: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={16} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
              Scoring &amp; reoptimizing… {progress ? `${progress.current} / ${progress.total}` : ''}
            </span>
            <button onClick={cancel} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
              Cancel
            </button>
          </div>
          {progress && (
            <div style={{ display: 'flex', gap: 4 }}>
              {Array.from({ length: progress.total }).map((_, idx) => (
                <div key={idx} style={{
                  height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                  background: idx < progress.current - 1 ? '#16a34a' : idx === progress.current - 1 ? '#6366f1' : '#e2e8f0',
                }} />
              ))}
            </div>
          )}
          <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
            Each page is scored, then rewritten only if it scores below {SCORE_THRESHOLD}. This takes ~1–4 minutes per rewritten page — keep this tab open.
          </p>
        </div>
      )}

      {/* Results */}
      {rows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
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

function DestOption({ active, disabled, onClick, icon, title, subtitle }: {
  active?: boolean
  disabled?: boolean
  onClick?: () => void
  icon: ReactNode
  title: string
  subtitle: string
}) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10, textAlign: 'left', width: '100%',
        padding: '10px 14px', borderRadius: 8, cursor: disabled ? 'not-allowed' : 'pointer',
        border: `1px solid ${active ? '#6366f1' : '#e2e8f0'}`,
        background: active ? '#eef2ff' : disabled ? '#f8fafc' : '#fff',
        opacity: disabled ? 0.6 : 1,
      }}
    >
      <span style={{ color: active ? '#6366f1' : '#64748b', marginTop: 1 }}>{icon}</span>
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{title}</span>
        <span style={{ display: 'block', fontSize: 12, color: '#94a3b8' }}>{subtitle}</span>
      </span>
    </button>
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
  } else if (state.phase === 'cancelled') {
    badge = <span style={chip('#f1f5f9', '#94a3b8')}>Cancelled</span>
    detail = <span style={{ fontSize: 12, color: '#94a3b8' }}>Stopped before completing — any page that finished saving will appear in Saved Pages.</span>
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
