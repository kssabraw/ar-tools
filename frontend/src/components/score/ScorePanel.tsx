import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Gauge, RotateCcw } from 'lucide-react'
import { useResumableJob } from '../../lib/useResumableJob'
import { EntityProviderSelect, type EntityProvider } from '../EntityProviderSelect'
import { LocationAutocomplete } from '../localseo/LocationAutocomplete'
import { Spinner } from '../localseo/Spinner'
import { card, input, label, outlineBtn, primaryBtn } from '../localseo/shared'
import { ErrorDetails } from '../ErrorDetails'
import { PasteEditor } from '../reoptimize/PasteEditor'
import type { ScoreResult } from '../localseo/types'
import type { ScoreAdapter } from './types'
import { ScoreResultView } from './ScoreResultView'

// The shared "Score only" panel: point at one live page (or paste its content),
// check it against the engines, and read the score + entity usage/gaps — nothing
// is rewritten. Driven by a per-tool ScoreAdapter (which knows the endpoints +
// engine labels). The score runs as a resumable background job, so navigating
// away and back reconnects.

type Mode = 'url' | 'paste'

function normalizeUrl(u: string): string {
  const t = u.trim()
  if (!t) return ''
  return /^https?:\/\//i.test(t) ? t : `https://${t}`
}
function looksLikeUrl(u: string): boolean {
  return /^https?:\/\/.+\..+/.test(u)
}

export function ScorePanel({ adapter }: { adapter: ScoreAdapter }) {
  const noun = adapter.itemNoun ?? 'page'
  const [mode, setMode] = useState<Mode>('url')
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [locationCode, setLocationCode] = useState<number | null>(null)
  const [url, setUrl] = useState('')
  const [pasteHtml, setPasteHtml] = useState('')
  const [entityProvider, setEntityProvider] = useState<EntityProvider>('textrazor')
  const [pageType, setPageType] = useState(adapter.defaultPageType ?? adapter.pageTypeOptions?.[0]?.id ?? '')
  const [result, setResult] = useState<ScoreResult | null>(null)
  const [error, setError] = useState('')
  // One score at a time (inputs are disabled while a run is in flight), so a
  // fixed key per tool lets a navigate-away-and-back remount reconnect to the
  // in-flight job and show its result — the typed inputs don't survive the remount.
  const job = useResumableJob<ScoreResult, null>({
    storageKey: adapter.storageKeyBase,
    poll: async (jobId) => {
      const st = await adapter.poll(jobId)
      return { status: st.status, result: st.result ?? null, error: st.error }
    },
    onComplete: (data) => {
      if (!data) { setError('Scoring returned no result.'); return }
      setResult(data)
    },
    onError: (err) => setError(err || 'Scoring failed'),
  })
  const scoring = job.running

  const canRun = !scoring
    && (!adapter.requiresKeyword || keyword.trim().length > 0)
    && (!adapter.requiresLocation || location.trim().length > 0)
    && (mode === 'url' ? looksLikeUrl(normalizeUrl(url)) : pasteHtml.trim().length > 0)

  const runScore = async () => {
    setError('')
    setResult(null)
    await job.start(async () => adapter.start({
      keyword: keyword.trim(),
      url: mode === 'url' ? normalizeUrl(url) : null,
      html: mode === 'paste' ? pasteHtml : null,
      location: adapter.supportsLocation ? location.trim() || null : null,
      locationCode: adapter.supportsLocation ? locationCode : null,
      pageType: pageType || undefined,
      entityProvider: adapter.supportsEntityProvider ? entityProvider : undefined,
    }), null)
  }

  const reset = () => { setResult(null); setError(''); job.reset() }

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', margin: 0 }}>Score an existing {noun}</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
          {adapter.introText
            ?? <>Point at a live {noun} (or paste its content) and check it against the engines — composite score, per-engine breakdown, and entity usage &amp; gaps. Nothing is rewritten.</>}
        </p>
      </div>

      {/* Page-type switch */}
      {adapter.ownsPageTypeSwitch && adapter.pageTypeOptions && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#475569' }}>Page type</span>
          <div style={pillGroup}>
            {adapter.pageTypeOptions.map(pt => (
              <button key={pt.id} onClick={() => !scoring && setPageType(pt.id)} disabled={scoring} style={pill(pageType === pt.id, scoring)}>
                {pt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Keyword (+ location) */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 240px' }}>
          <label style={label}>{adapter.keywordLabel ?? 'Keyword'}</label>
          <input
            style={input}
            value={keyword}
            disabled={scoring}
            onChange={e => setKeyword(e.target.value)}
            placeholder={adapter.keywordPlaceholder ?? 'e.g. emergency plumber'}
          />
        </div>
        {adapter.supportsLocation && (
          <div style={{ flex: '1 1 240px' }}>
            <label style={label}>Area / Location</label>
            <LocationAutocomplete
              clientId={adapter.clientId}
              value={location}
              onChange={(loc, code) => { setLocation(loc); setLocationCode(code) }}
              placeholder="Start typing a city, e.g. Melbourne…"
              disabled={scoring}
            />
          </div>
        )}
      </div>

      {/* Mode toggle */}
      {adapter.supportsPaste && (
        <div style={pillGroup}>
          {(['url', 'paste'] as const).map(m => (
            <button key={m} onClick={() => !scoring && setMode(m)} disabled={scoring} style={pill(mode === m, scoring)}>
              {m === 'url' ? 'Live URL' : 'Paste content'}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      {mode === 'url' ? (
        <div>
          <label style={label}>Page URL</label>
          <input
            style={input}
            value={url}
            disabled={scoring}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://example.com/services/emergency-plumber-melbourne"
          />
        </div>
      ) : (
        <div>
          <label style={label}>Page content</label>
          <PasteEditor value={pasteHtml} onChange={setPasteHtml} disabled={scoring} placeholder="Paste the existing page content…" />
        </div>
      )}

      {/* Entity engine */}
      {adapter.supportsEntityProvider && (
        <EntityProviderSelect value={entityProvider} onChange={setEntityProvider} disabled={scoring} />
      )}

      {error && <ErrorDetails message={error} />}

      {/* Run / progress */}
      {scoring ? (
        <div style={{ ...card, background: '#f8fafc', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Spinner size={16} />
          <span style={{ fontSize: 13, color: '#64748b' }}>Analyzing competitors &amp; scoring… (usually 1–3 minutes; runs in the background)</span>
        </div>
      ) : (
        <button
          style={{ ...primaryBtn, width: '100%', opacity: canRun ? 1 : 0.5, cursor: canRun ? 'pointer' : 'not-allowed' }}
          disabled={!canRun}
          onClick={runScore}
        >
          <Gauge size={16} /> Score this {noun}
        </button>
      )}

      {/* Result */}
      {result && !scoring && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ScoreResultView result={result} engineLabels={adapter.engineLabels} />
          <button style={{ ...outlineBtn, alignSelf: 'flex-start' }} onClick={reset}>
            <RotateCcw size={14} /> Score another {noun}
          </button>
        </div>
      )}
    </div>
  )
}

const pillGroup: CSSProperties = { display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4, alignSelf: 'flex-start' }
function pill(active: boolean, disabled: boolean): CSSProperties {
  return {
    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer', border: 'none',
    background: active ? '#fff' : 'transparent', color: active ? '#0f172a' : '#64748b',
    boxShadow: active ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
  }
}
