import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  ArrowRight, CheckCircle2, ExternalLink, MinusCircle, Search, Sparkles, XCircle,
} from 'lucide-react'
import { useResumableBatch, type BatchJobRow } from '../../lib/useResumableBatch'
import { EntityProviderSelect, type EntityProvider } from '../EntityProviderSelect'
import { LocationAutocomplete } from '../localseo/LocationAutocomplete'
import { Spinner } from '../localseo/Spinner'
import { card, input, label, outlineBtn, primaryBtn, scoreColor } from '../localseo/shared'
import { ErrorDetails } from '../ErrorDetails'
import { PasteEditor } from './PasteEditor'
import type {
  ReoptAdapter,
  ReoptDiscoverItem,
  ReoptExistingItem,
  ReoptHandle,
  ReoptItem,
  ReoptResult,
  ReoptResultStatus,
} from './types'

// The one shared Reoptimize UI, driven by a tool-specific ReoptAdapter. It owns
// the input modes (Live URL / Paste content / Discover / Pick existing), the
// shared keyword/location/page-type/notes/destination controls, the run button,
// the "leave & finish in the background" affordance (via useResumableBatch, so
// navigating away and back reconnects), and the per-target result rows. Every
// behavioural difference between the four tools lives in the adapter, not here.

type PanelMode = 'url' | 'discover' | 'paste' | 'existing'

interface Meta {
  handles: ReoptHandle[]
}

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
  adapter: ReoptAdapter
  // Ecommerce drives page type from the parent page; the panel reads it here.
  pageType?: string
}

export function ReoptimizePanel({ adapter, pageType: pageTypeProp }: Props) {
  const noun = adapter.itemNoun ?? 'page'
  const threshold = adapter.scoreThreshold

  // ── Available input modes (in a stable order) ──
  const modes: PanelMode[] = []
  if (adapter.supportsUrl) modes.push('url')
  if (adapter.supportsDiscover) modes.push('discover')
  if (adapter.supportsPaste) modes.push('paste')
  if (adapter.supportsExisting) modes.push('existing')
  const [mode, setMode] = useState<PanelMode>(modes[0] ?? 'url')

  // ── Shared inputs ──
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [locationCode, setLocationCode] = useState<number | null>(null)
  const [notes, setNotes] = useState('')
  // Entity-extraction engine for the nlp SERP analysis (Local SEO + Ecommerce).
  const [entityProvider, setEntityProvider] = useState<EntityProvider>('textrazor')

  // Page type: owned by the panel (Service) or supplied by the parent (Ecommerce).
  const [internalPageType, setInternalPageType] = useState(
    adapter.defaultPageType ?? adapter.pageTypeOptions?.[0]?.id ?? '',
  )
  const pageType = adapter.ownsPageTypeSwitch ? internalPageType : (pageTypeProp ?? adapter.defaultPageType ?? '')

  // URL mode inputs.
  const [urlSub, setUrlSub] = useState<'single' | 'bulk'>('single')
  const [singleUrl, setSingleUrl] = useState('')
  const [bulkText, setBulkText] = useState('')

  // Paste mode.
  const [pasteHtml, setPasteHtml] = useState('')

  // Destination.
  const [destination, setDestination] = useState<string>(adapter.destinations?.[0]?.id ?? 'app')
  const [publishToDoc, setPublishToDoc] = useState(false)

  // Discover mode.
  const [discovering, setDiscovering] = useState(false)
  const [discoverItems, setDiscoverItems] = useState<ReoptDiscoverItem[] | null>(null)
  const [discoverNote, setDiscoverNote] = useState<string | null>(null)
  const [discoverError, setDiscoverError] = useState('')
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set())

  // Existing mode.
  const [existingItems, setExistingItems] = useState<ReoptExistingItem[] | null>(null)
  const [loadingExisting, setLoadingExisting] = useState(false)
  const [existingError, setExistingError] = useState('')
  const [selectedExisting, setSelectedExisting] = useState<Set<string>>(new Set())

  const [error, setError] = useState('')
  const [detached, setDetached] = useState(false)
  const [localHandles, setLocalHandles] = useState<ReoptHandle[]>([])

  // Handles the poll wrapper reads — assigned during render (never stale in the
  // hook's timer callbacks, which run after commit).
  const handlesRef = useRef<ReoptHandle[]>([])

  const batchState = useResumableBatch<Meta>({
    storageKey: adapter.storageKey,
    poll: async (): Promise<BatchJobRow[]> => {
      const handles = handlesRef.current
      const pollable = handles.filter(h => h.kind !== 'skipped')
      let results: ReoptResult[] = []
      if (pollable.length) {
        try {
          results = await adapter.poll(pollable)
        } catch {
          results = [] // transient — treat as no update this tick
        }
      }
      const byId = new Map(results.map(r => [r.id, r]))
      return handles.map(h => {
        if (h.kind === 'skipped') {
          const res: ReoptResult = { id: h.id, label: h.label, status: 'skipped', reason: h.reason }
          return { id: h.id, status: 'complete', result: res as unknown as Record<string, unknown> }
        }
        const r = byId.get(h.id) ?? { id: h.id, label: h.label, status: 'queued' as ReoptResultStatus }
        const status =
          r.status === 'done' || r.status === 'skipped' ? 'complete'
            : r.status === 'failed' ? 'failed'
              : r.status === 'working' ? 'running'
                : 'pending'
        return {
          id: h.id,
          status,
          error: r.status === 'failed' ? (r.reason ?? null) : null,
          result: r as unknown as Record<string, unknown>,
          progress: r.progress ?? null,
          progress_message: r.progressMessage ?? null,
        }
      })
    },
  })
  const { rows, meta, start: startBatch, clear, detach, running } = batchState

  // Prefer the persisted handles (survive a reconnect) over local state.
  const activeHandles: ReoptHandle[] = meta?.handles ?? localHandles
  handlesRef.current = activeHandles

  // On reconnect the handles arrive via the persisted meta — mirror them locally
  // so the rows keep rendering after a later detach clears `batch`.
  useEffect(() => {
    if (meta?.handles?.length) setLocalHandles(meta.handles)
  }, [meta])

  // Lazy-load the discover / existing lists when their mode is first opened.
  const runDiscover = async () => {
    if (!adapter.discover) return
    setDiscovering(true)
    setDiscoverError('')
    setDiscoverItems(null)
    setDiscoverNote(null)
    setSelectedUrls(new Set())
    try {
      const res = await adapter.discover(pageType)
      setDiscoverItems(res.items ?? [])
      setDiscoverNote(res.note ?? null)
    } catch (e) {
      setDiscoverError(e instanceof Error ? e.message : 'Could not scan the site')
    } finally {
      setDiscovering(false)
    }
  }
  const loadExisting = async () => {
    if (!adapter.listExisting) return
    setLoadingExisting(true)
    setExistingError('')
    try {
      const items = await adapter.listExisting()
      setExistingItems(items)
    } catch (e) {
      setExistingError(e instanceof Error ? e.message : 'Could not load existing pages')
    } finally {
      setLoadingExisting(false)
    }
  }
  useEffect(() => {
    if (mode === 'existing' && existingItems === null && !loadingExisting) void loadExisting()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  // ── Build dispatchable targets from the active mode ──
  // A URL line is `URL` or `URL | keyword` (+ ` | area` for location-scoped
  // tools). Missing fields fall back to the shared keyword/area above.
  const parseUrlLine = (raw: string): ReoptItem & { error?: string } => {
    const parts = raw.split('|').map(p => p.trim())
    const url = normalizeUrl(parts[0] ?? '')
    const kw = parts[1] || keyword.trim()
    const hasAreaOverride = Boolean(adapter.supportsLocation && parts[2])
    const loc = adapter.supportsLocation ? (parts[2] || location.trim()) : ''
    const error = !parts[0] ? 'Missing URL'
      : !looksLikeUrl(url) ? 'Invalid URL'
        : adapter.requiresKeyword && !kw ? 'No keyword — add one above, or as “URL | keyword”.'
          : adapter.supportsLocation && !loc ? 'No area — add one above, or as “URL | keyword | area”.'
            : undefined
    return {
      url, keyword: kw,
      location: loc || undefined,
      locationCode: hasAreaOverride ? null : locationCode,
      pageType: pageType || undefined,
      raw, label: url.replace(/^https?:\/\//, '') || raw,
      error,
    }
  }

  interface Built { items: ReoptItem[]; invalid: ReoptItem[]; blockReason?: string }
  // Non-URL modes only (URL mode is resolved via `parsedUrl` + `splitValid`).
  const build = (): Built => {
    if (mode === 'paste') {
      const kw = keyword.trim()
      if (adapter.requiresKeyword && !kw) return { items: [], invalid: [], blockReason: 'Enter the keyword this content targets.' }
      if (!pasteHtml.trim()) return { items: [], invalid: [], blockReason: 'Paste the page content to reoptimize.' }
      return {
        items: [{
          keyword: kw, html: pasteHtml,
          location: adapter.supportsLocation ? (location.trim() || undefined) : undefined,
          locationCode: adapter.supportsLocation ? locationCode : null,
          pageType: pageType || undefined,
          label: kw || 'Pasted content',
        }],
        invalid: [],
      }
    }
    if (mode === 'discover') {
      const items = (discoverItems ?? [])
        .filter(it => selectedUrls.has(it.url))
        .map(it => ({
          url: it.url, keyword: keyword.trim(),
          pageType: it.pageType ?? pageType ?? undefined,
          label: it.label || it.url.replace(/^https?:\/\//, ''),
        }))
      return { items, invalid: [] }
    }
    // existing
    const items = (existingItems ?? [])
      .filter(it => selectedExisting.has(it.id))
      .map(it => ({
        url: it.url ?? undefined,
        existingId: it.id,
        keyword: (it.keyword || keyword.trim()),
        pageType: pageType || undefined,
        label: it.label,
      }))
    return { items, invalid: [] }
  }

  // Partition a parsed URL list into valid targets + invalid lines (which carry
  // an `error` string set by parseUrlLine's validation).
  function splitValid(parsed: Array<ReoptItem & { error?: string }>): { items: ReoptItem[]; invalid: ReoptItem[] } {
    const items: ReoptItem[] = []
    const invalid: ReoptItem[] = []
    for (const t of parsed) {
      if ((t as ReoptItem & { error?: string }).error) invalid.push(t)
      else items.push(t)
    }
    return { items, invalid }
  }

  // URL-mode targets, each carrying a validation `error` (parseUrlLine).
  const parsedUrl: Array<ReoptItem & { error?: string }> = (() => {
    if (mode !== 'url') return []
    const lines = adapter.urlSingleToggle && urlSub === 'single'
      ? [singleUrl].filter(l => l.trim())
      : bulkText.split('\n').map(l => l.trim()).filter(Boolean)
    return lines.map(parseUrlLine)
  })()

  const built: Built = mode === 'url' ? splitValid(parsedUrl) : build()
  const validTargets = built.items
  const invalidTargets = built.invalid
  const canRun = !running && validTargets.length > 0

  // ── Run: enqueue via the adapter, then poll via useResumableBatch ──
  const run = async () => {
    if (!validTargets.length || running) return
    setError('')
    setDetached(false)
    let handles: ReoptHandle[] = []
    try {
      handles = await adapter.start(validTargets, {
        destination,
        publishToDoc,
        notes: notes.trim() || null,
        pageType,
        entityProvider: adapter.supportsEntityProvider ? entityProvider : undefined,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start reoptimization')
      return
    }
    if (!handles.length) {
      setError('Nothing could be started — check the input and try again.')
      return
    }
    setLocalHandles(handles)
    startBatch(handles.map(h => h.id), { handles })
  }

  // Leave the jobs running server-side; stop polling but keep the persisted ids
  // so a later mount reconnects.
  const leave = () => {
    detach()
    setDetached(true)
  }

  // Stop (adapter supports cancel): cancel queued work, drop the batch entirely.
  const stop = async () => {
    if (!window.confirm(`Stop all queued reoptimization jobs for this client? Jobs already running will finish.`)) return
    try {
      await adapter.cancel?.(activeHandles.filter(h => h.kind !== 'skipped'))
    } catch { /* best-effort — UI already resetting */ }
    clear()
    setLocalHandles([])
    setDetached(false)
    setError('Queued reoptimizations cancelled.')
  }

  // ── Derive rows for rendering ──
  const rowsById = new Map(rows.map(r => [r.id, r]))
  const displayRows = activeHandles.map(h => {
    const raw = rowsById.get(h.id)?.result as ReoptResult | undefined
    let res: ReoptResult = raw ?? { id: h.id, label: h.label, status: 'queued' }
    if (detached && (res.status === 'queued' || res.status === 'working')) {
      res = { ...res, status: 'detached' }
    }
    return res
  })
  const total = activeHandles.length
  const doneCount = displayRows.filter(r => r.status === 'done' || r.status === 'skipped' || r.status === 'failed').length
  const reoptimizedCount = displayRows.filter(r => r.status === 'done').length
  const isRunKind = activeHandles.some(h => h.kind === 'run')
  // Live progress (Local SEO / Ecommerce jobs report a per-stage percent + message).
  // Overall = finished items count as 100, the running item contributes its live
  // percent, pending count as 0 — so the bar moves within a single long item AND
  // across a batch. Absent for run-based tools → fall back to the segment bar.
  const hasLiveProgress = displayRows.some(r => r.status === 'working' && typeof r.progress === 'number')
  const stageMessage = displayRows.find(r => r.status === 'working' && r.progressMessage)?.progressMessage ?? null
  const overallPct = total > 0
    ? Math.round(displayRows.reduce((sum, r) => {
        if (r.status === 'done' || r.status === 'skipped' || r.status === 'failed') return sum + 100
        if (r.status === 'working' && typeof r.progress === 'number') return sum + r.progress
        return sum
      }, 0) / total)
    : 0

  const allDiscoverSelected = Boolean(
    discoverItems && discoverItems.length > 0 && discoverItems.every(it => selectedUrls.has(it.url)),
  )
  const allExistingSelected = Boolean(
    existingItems && existingItems.length > 0 && existingItems.every(it => selectedExisting.has(it.id)),
  )

  const verb = threshold != null ? 'Score & reoptimize' : 'Reoptimize'
  const runLabel = validTargets.length === 1
    ? `${verb} this ${noun}`
    : `${verb} ${validTargets.length || ''} ${noun}s`

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Reoptimize existing {noun}s</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          {adapter.introText ?? (threshold != null
            ? <>Paste a live page URL (or a list). Each page is scored against the engines first — only pages scoring <strong>below {threshold}/100</strong> are rewritten; stronger pages are skipped with a note.</>
            : <>Point at a live {noun} (or paste its content). Each is scored and rewritten to fix its deficiencies — the result is a new run you can review and publish.</>)}
        </p>
      </div>

      {/* Mode toggle (only when more than one mode is available) */}
      {modes.length > 1 && (
        <div style={pillGroup}>
          {modes.map(m => (
            <button
              key={m}
              onClick={() => !running && setMode(m)}
              disabled={running}
              style={pill(mode === m, running)}
            >{modeLabel(m)}</button>
          ))}
        </div>
      )}

      {/* Page-type switch (Service owns its own; Ecommerce's is in the parent) */}
      {adapter.ownsPageTypeSwitch && adapter.pageTypeOptions && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>Page type</span>
          <div style={{ display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4 }}>
            {adapter.pageTypeOptions.map(pt => (
              <button
                key={pt.id}
                onClick={() => !running && setInternalPageType(pt.id)}
                disabled={running}
                style={pill(pageType === pt.id, running)}
              >{pt.label}</button>
            ))}
          </div>
        </div>
      )}

      {/* Shared keyword (+ location) */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 240px' }}>
          <label style={label}>
            {adapter.keywordLabel ?? 'Keyword'}{' '}
            {adapter.keywordOptionalHint
              ? <span style={{ fontWeight: 400, color: '#94a3b8' }}>{adapter.keywordOptionalHint}</span>
              : (mode === 'url' && (!adapter.urlSingleToggle || urlSub === 'bulk'))
                ? <span style={{ fontWeight: 400, color: '#94a3b8' }}>(default for all lines)</span>
                : null}
          </label>
          <input
            style={input}
            value={keyword}
            disabled={running}
            onChange={e => setKeyword(e.target.value)}
            placeholder={adapter.keywordPlaceholder ?? 'e.g. emergency plumber'}
          />
        </div>
        {adapter.supportsLocation && (
          <div style={{ flex: '1 1 240px' }}>
            <label style={label}>
              Area / Location{' '}
              {mode === 'url' && (!adapter.urlSingleToggle || urlSub === 'bulk')
                ? <span style={{ fontWeight: 400, color: '#94a3b8' }}>(default for all lines)</span>
                : null}
            </label>
            <LocationAutocomplete
              clientId={adapter.clientId}
              value={location}
              onChange={(loc, code) => { setLocation(loc); setLocationCode(code) }}
              placeholder="Start typing a city, e.g. Melbourne…"
              disabled={running}
            />
          </div>
        )}
      </div>

      {/* Input area per mode */}
      {mode === 'url' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {adapter.urlSingleToggle && (
            <div style={pillGroup}>
              {(['single', 'bulk'] as const).map(s => (
                <button key={s} onClick={() => !running && setUrlSub(s)} disabled={running} style={pill(urlSub === s, running)}>
                  {s === 'single' ? 'Single URL' : 'Multiple URLs'}
                </button>
              ))}
            </div>
          )}
          {adapter.urlSingleToggle && urlSub === 'single' ? (
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
                placeholder={adapter.supportsLocation
                  ? 'https://example.com/emergency-plumber\nhttps://example.com/blocked-drains | blocked drains | Geelong VIC'
                  : 'https://example.com/products/headphones\nhttps://example.com/products/earbuds | wireless earbuds'}
              />
              <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
                Each line is a page. Use just a URL to apply the {adapter.keywordLabel?.toLowerCase() ?? 'keyword'}{adapter.supportsLocation ? ' + area' : ''} above, or{' '}
                <code style={codeStyle}>URL | {adapter.keywordLabel?.toLowerCase() ?? 'keyword'}{adapter.supportsLocation ? ' | area' : ''}</code> to override per line.
              </p>
            </div>
          )}
        </div>
      )}

      {mode === 'paste' && (
        <div>
          <label style={label}>Page content</label>
          <PasteEditor
            value={pasteHtml}
            onChange={setPasteHtml}
            disabled={running}
            placeholder="Paste the existing page content (rich formatting is preserved)…"
          />
          <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
            Paste from a doc or the live page — headings, lists and bold are kept. The reoptimizer rewrites it against the engines.
          </p>
        </div>
      )}

      {mode === 'discover' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <button
            style={{ ...outlineBtn, alignSelf: 'flex-start', opacity: discovering || running ? 0.6 : 1 }}
            onClick={runDiscover}
            disabled={discovering || running}
          >
            {discovering ? <Spinner size={14} /> : <Search size={14} />} {discovering ? 'Scanning site…' : `Discover ${pageType ? pageType + ' ' : ''}pages`}
          </button>
          {discoverError && <ErrorDetails message={discoverError} />}
          {discoverNote && <p style={{ fontSize: 12, color: '#92400e', margin: 0 }}>{discoverNote}</p>}
          {discoverItems && discoverItems.length === 0 && !discovering && (
            <p style={{ fontSize: 13, color: '#64748b', textAlign: 'center', padding: 16 }}>No pages found on this client's site.</p>
          )}
          {discoverItems && discoverItems.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8' }}>
                <span>{discoverItems.length} page{discoverItems.length === 1 ? '' : 's'} found. Tick the ones to reoptimize.</span>
                <button
                  onClick={() => setSelectedUrls(allDiscoverSelected ? new Set() : new Set(discoverItems.map(it => it.url)))}
                  disabled={running}
                  style={linkBtn}
                >{allDiscoverSelected ? 'Deselect all' : 'Select all'}</button>
              </div>
              <div style={pickList}>
                {discoverItems.map((it, i) => (
                  <label key={it.url} style={pickRow(i > 0, selectedUrls.has(it.url))}>
                    <input
                      type="checkbox"
                      checked={selectedUrls.has(it.url)}
                      onChange={() => setSelectedUrls(prev => toggle(prev, it.url))}
                      disabled={running}
                      style={checkbox}
                    />
                    <span style={rowUrl} title={it.url}>{it.label || it.url.replace(/^https?:\/\//, '')}</span>
                    {it.pageType && <span style={typeBadge}>{it.pageType}</span>}
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {mode === 'existing' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {loadingExisting && <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#64748b' }}><Spinner size={14} /> Loading pages…</div>}
          {existingError && <ErrorDetails message={existingError} />}
          {existingItems && existingItems.length === 0 && !loadingExisting && (
            <p style={{ fontSize: 13, color: '#64748b', textAlign: 'center', padding: 16 }}>No existing pages to reoptimize.</p>
          )}
          {existingItems && existingItems.length > 0 && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8' }}>
                <span>{existingItems.length} page{existingItems.length === 1 ? '' : 's'}. Tick the ones to reoptimize.</span>
                <button
                  onClick={() => setSelectedExisting(allExistingSelected ? new Set() : new Set(existingItems.map(it => it.id)))}
                  disabled={running}
                  style={linkBtn}
                >{allExistingSelected ? 'Deselect all' : 'Select all'}</button>
              </div>
              <div style={pickList}>
                {existingItems.map((it, i) => (
                  <label key={it.id} style={pickRow(i > 0, selectedExisting.has(it.id))}>
                    <input
                      type="checkbox"
                      checked={selectedExisting.has(it.id)}
                      onChange={() => setSelectedExisting(prev => toggle(prev, it.id))}
                      disabled={running}
                      style={checkbox}
                    />
                    <span style={rowUrl} title={it.url ?? it.label}>{it.label}</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Notes */}
      {adapter.supportsNotes && (
        <div>
          <label style={label}>
            {adapter.notesLabel ?? 'Notes'}{' '}
            <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional) — guidance for the writer, applied to every {noun} in this batch.</span>
          </label>
          <textarea
            style={{ ...input, minHeight: 80, fontFamily: 'inherit', resize: 'vertical' }}
            value={notes}
            disabled={running}
            onChange={e => setNotes(e.target.value)}
            placeholder={adapter.notesPlaceholder ?? 'e.g. emphasize fast shipping; write for clinics not individuals'}
          />
        </div>
      )}

      {/* Entity engine (Local SEO + Ecommerce) */}
      {adapter.supportsEntityProvider && (
        <EntityProviderSelect value={entityProvider} onChange={setEntityProvider} disabled={running} />
      )}

      {/* Destination — radio (Local SEO) or a single publish-to-Doc checkbox */}
      {adapter.destinations && adapter.destinations.length > 0 ? (
        <div>
          <label style={label}>Where should reoptimized {noun}s go?</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 2 }}>
            {adapter.destinations.map(d => (
              <DestOption
                key={d.id}
                active={!d.disabled && destination === d.id}
                disabled={running || d.disabled}
                onClick={() => setDestination(d.id)}
                icon={d.icon}
                title={d.title}
                subtitle={d.subtitle}
              />
            ))}
          </div>
        </div>
      ) : adapter.supportsPublishToDoc ? (
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
          <input type="checkbox" checked={publishToDoc} disabled={running} onChange={e => setPublishToDoc(e.target.checked)} />
          {adapter.publishToDocLabel ?? 'Publish each reoptimized page to a Google Doc in the client\'s Drive folder'}
        </label>
      ) : null}

      {error && <ErrorDetails message={error} />}
      {built.blockReason && !error && validTargets.length === 0 && (
        <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>{built.blockReason}</p>
      )}

      {/* Invalid-line warnings (URL mode) */}
      {mode === 'url' && invalidTargets.length > 0 && (
        <div style={warnBox}>
          <span style={{ fontWeight: 600 }}>{invalidTargets.length} line(s) will be skipped:</span>
          {invalidTargets.slice(0, 5).map((t, i) => (
            <span key={i} style={{ wordBreak: 'break-all' }}>“{(t.raw ?? '').slice(0, 60)}” — {(t as ReoptItem & { error?: string }).error}</span>
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
          <Sparkles size={16} /> {runLabel}
        </button>
      ) : (
        <div style={{ ...card, background: '#f8fafc', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={16} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
              {threshold != null ? 'Scoring & reoptimizing' : 'Reoptimizing'} in the background… {total ? `${doneCount} / ${total} done` : ''}
            </span>
            <button onClick={leave} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}>
              Leave &amp; finish in the background
            </button>
            {adapter.cancel && (
              <button onClick={stop} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
                Stop
              </button>
            )}
          </div>
          {hasLiveProgress ? (
            <div>
              <div style={{ height: 8, background: '#e2e8f0', borderRadius: 999, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${overallPct}%`, background: '#6366f1', borderRadius: 999, transition: 'width 0.4s ease' }} />
              </div>
              <p style={{ fontSize: 11, color: '#64748b', margin: '6px 0 0' }}>
                {stageMessage ? `${stageMessage} · ${overallPct}%` : `${overallPct}%`}
                {total > 1 ? ` · ${doneCount} / ${total} done` : ''}
              </p>
            </div>
          ) : total > 0 ? (
            <div style={{ display: 'flex', gap: 4 }}>
              {Array.from({ length: total }).map((_, idx) => (
                <div key={idx} style={{ height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s', background: idx < doneCount ? '#16a34a' : '#e2e8f0' }} />
              ))}
            </div>
          ) : null}
          <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
            This runs in the background — you can leave; the results {isRunKind ? 'appear in the run list' : 'land in Saved Pages'} when done.
          </p>
        </div>
      )}

      {/* Results */}
      {displayRows.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {detached && (
            <p style={{ fontSize: 13, color: '#6366f1', fontWeight: 600, margin: 0 }}>
              Reoptimizing in the background — finished {isRunKind ? 'runs appear in the run list' : 'pages appear in Saved Pages'}. You can work on other clients.
            </p>
          )}
          {!running && reoptimizedCount > 0 && (
            <p style={{ fontSize: 13, color: '#16a34a', fontWeight: 600, margin: 0 }}>
              {reoptimizedCount} {noun}{reoptimizedCount === 1 ? '' : 's'} {isRunKind ? (adapter.runVerb ?? 'reoptimizing') : 'reoptimized and saved'}
              {adapter.onOpenSaved && !isRunKind && (
                <>
                  {' '}—{' '}
                  <button onClick={adapter.onOpenSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#16a34a', fontWeight: 600, textDecoration: 'underline' }}>
                    {adapter.savedLinkLabel ?? 'view in Saved Pages'}
                  </button>
                </>
              )}.
            </p>
          )}
          {displayRows.map((r, i) => <ResultRow key={r.id ?? i} result={r} adapter={adapter} />)}
        </div>
      )}
    </div>
  )
}

// ── Sub-components + helpers ─────────────────────────────────────────────────

function modeLabel(m: PanelMode): string {
  switch (m) {
    case 'url': return 'Paste URLs'
    case 'paste': return 'Paste content'
    case 'discover': return 'Discover from site'
    case 'existing': return 'Pick existing'
  }
}

function toggle(prev: Set<string>, key: string): Set<string> {
  const next = new Set(prev)
  if (next.has(key)) next.delete(key); else next.add(key)
  return next
}

function DestOption({ active, disabled, onClick, icon, title, subtitle }: {
  active?: boolean; disabled?: boolean; onClick?: () => void; icon?: ReactNode; title: string; subtitle: string
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
      {icon && <span style={{ color: active ? '#6366f1' : '#64748b', marginTop: 1 }}>{icon}</span>}
      <span style={{ minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{title}</span>
        <span style={{ display: 'block', fontSize: 12, color: '#94a3b8' }}>{subtitle}</span>
      </span>
    </button>
  )
}

function ResultRow({ result, adapter }: { result: ReoptResult; adapter: ReoptAdapter }) {
  let badge: ReactNode
  let detail: ReactNode = null

  if (result.status === 'queued') {
    badge = <span style={chip('#f1f5f9', '#64748b')}>Queued</span>
  } else if (result.status === 'working') {
    badge = <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Spinner size={13} /> <span style={{ fontSize: 12, color: '#6366f1', fontWeight: 600 }}>Working…</span></span>
  } else if (result.status === 'failed') {
    badge = <span style={chip('#fef2f2', '#dc2626')}><XCircle size={12} /> Failed</span>
    detail = <span style={{ fontSize: 12, color: '#dc2626' }}>{result.reason ?? 'Reoptimization failed'}</span>
  } else if (result.status === 'detached') {
    badge = <span style={chip('#eef2ff', '#6366f1')}>In background</span>
    detail = <span style={{ fontSize: 12, color: '#94a3b8' }}>Still finishing — it’ll appear when done.</span>
  } else if (result.status === 'skipped') {
    badge = <span style={chip('#eff6ff', '#2563eb')}><MinusCircle size={12} /> Skipped</span>
    detail = <span style={{ fontSize: 12, color: '#64748b' }}>{result.reason}</span>
  } else {
    // done
    badge = <span style={chip('#f0fdf4', '#16a34a')}><CheckCircle2 size={12} /> Reoptimized</span>
    detail = (
      <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#64748b', flexWrap: 'wrap' }}>
        {(result.prevScore != null || result.newScore != null) && (
          <span>
            Score{' '}
            {result.prevScore != null && <span style={{ color: scoreColor(result.prevScore), fontWeight: 600 }}>{Math.round(result.prevScore)}</span>}
            {result.prevScore != null && result.newScore != null && <ArrowRight size={11} style={{ margin: '0 2px', verticalAlign: 'middle' }} />}
            {result.newScore != null && <span style={{ color: scoreColor(result.newScore), fontWeight: 700 }}>{Math.round(result.newScore)}</span>}
            /100
          </span>
        )}
        {result.docUrl && (
          <a href={result.docUrl} target="_blank" rel="noreferrer" style={{ color: '#6366f1', fontWeight: 600 }}>Open Google Doc ↗</a>
        )}
        {result.publishError && <span style={{ color: '#d97706' }}>Saved, but publish failed: {result.publishError}</span>}
        {result.runId && adapter.runLinkBase && (
          <a href={`${adapter.runLinkBase}/${result.runId}`} style={{ color: '#6366f1', fontWeight: 600, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            View run <ExternalLink size={11} />
          </a>
        )}
        {adapter.onOpenSaved && !result.runId && (
          <button onClick={adapter.onOpenSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#6366f1', fontWeight: 600 }}>
            View saved page
          </button>
        )}
      </span>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 14px', border: '1px solid #e2e8f0', borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={rowUrl} title={result.label}>{result.label}</span>
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

const pillGroup: CSSProperties = { display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4, alignSelf: 'flex-start' }
function pill(active: boolean, disabled: boolean): CSSProperties {
  return {
    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer', border: 'none',
    background: active ? '#fff' : 'transparent', color: active ? '#0f172a' : '#64748b',
    boxShadow: active ? '0 1px 2px rgba(0,0,0,0.06)' : 'none', textTransform: 'capitalize',
  }
}
const linkBtn: CSSProperties = { marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }
const pickList: CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', maxHeight: 320, overflowY: 'auto' }
function pickRow(border: boolean, selected: boolean): CSSProperties {
  return { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', cursor: 'pointer', borderTop: border ? '1px solid #f1f5f9' : 'none', background: selected ? '#f5f7ff' : '#fff' }
}
const checkbox: CSSProperties = { width: 16, height: 16, cursor: 'pointer', flexShrink: 0, accentColor: '#6366f1' }
const rowUrl: CSSProperties = { fontSize: 13, color: '#0f172a', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
const typeBadge: CSSProperties = { fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: '#eef2ff', color: '#4f46e5', textTransform: 'capitalize', flexShrink: 0 }
const codeStyle: CSSProperties = { background: '#f1f5f9', padding: '1px 5px', borderRadius: 4 }
const warnBox: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8, fontSize: 12, color: '#92400e' }
