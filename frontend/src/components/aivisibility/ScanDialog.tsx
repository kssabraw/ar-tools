import { useState } from 'react'
import { X, Users, Zap } from 'lucide-react'
import { ENGINE_ORDER, ENGINES, EngineIcon, type EngineKey } from './engines'
import type { ScanStatus } from './types'
import './animations.css'

// LABS-style "Run AI Visibility Scan" dialog: per-engine checkboxes (the scan
// API accepts an engines list), competitor toggle, and a scan-count summary box
// (credit-free — this is an internal tool; LABS' credit math becomes a plain
// "N answers will be scanned"). While a scan runs it shows live progress; the
// dialog can be closed and the scan keeps running server-side.

const ENGINE_DESCRIPTIONS: Record<EngineKey, string> = {
  chatgpt: 'OpenAI + web search',
  claude: 'Anthropic + web search',
  gemini: 'Google Search grounding',
  perplexity: 'Perplexity Sonar',
  google_ai_overview: 'Google SERP via DataForSEO',
  google_ai_mode: 'Google SERP via DataForSEO',
}

export function ScanDialog(props: {
  activeKeywordCount: number
  competitorCount: number
  running: boolean
  jobStatus: ScanStatus | undefined
  onRun: (engines: string[], includeCompetitors: boolean) => void
  onClose: () => void
}) {
  const { activeKeywordCount, competitorCount, running, jobStatus, onRun, onClose } = props
  // Internal-tool default: all six engines on (LABS defaults to ChatGPT-only
  // because each engine costs a credit; here the full sweep is the norm).
  const [selected, setSelected] = useState<Set<EngineKey>>(new Set(ENGINE_ORDER))
  const [includeCompetitors, setIncludeCompetitors] = useState(false)

  const toggle = (key: EngineKey) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const totalCells = activeKeywordCount * selected.size
  const done = jobStatus ? jobStatus.completed + jobStatus.failed : 0
  const progressPct = jobStatus && jobStatus.total > 0 ? Math.round((done / jobStatus.total) * 100) : 0

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <strong style={{ fontSize: 16, color: '#0f172a' }}>Run AI Visibility Scan</strong>
          <button style={closeBtn} onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px' }}>
          Check whether this brand appears when each AI engine answers your {activeKeywordCount} active keyword{activeKeywordCount === 1 ? '' : 's'}.
        </p>

        {/* Engine checkboxes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
          {ENGINE_ORDER.map(key => (
            <label
              key={key}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
                border: '1px solid', borderColor: selected.has(key) ? '#c7d2fe' : '#e2e8f0',
                background: selected.has(key) ? '#eef2ff' : '#fff',
                borderRadius: 10, cursor: running ? 'default' : 'pointer', userSelect: 'none',
              }}
            >
              <input
                type="checkbox"
                checked={selected.has(key)}
                disabled={running}
                onChange={() => toggle(key)}
              />
              <EngineIcon engine={key} size={18} />
              <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', flex: 1 }}>{ENGINES[key].label}</span>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>{ENGINE_DESCRIPTIONS[key]}</span>
            </label>
          ))}
        </div>

        {/* Competitor toggle */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#475569', marginBottom: 14, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={includeCompetitors}
            disabled={running}
            onChange={e => setIncludeCompetitors(e.target.checked)}
          />
          <Users size={14} /> Include competitors
          <span style={{ fontSize: 11, color: '#94a3b8' }}>
            {competitorCount > 0
              ? `${competitorCount} tracked — checked against the same answers, no extra calls`
              : 'none tracked yet'}
          </span>
        </label>

        {/* Scan summary box */}
        <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '10px 14px', marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: '#334155' }}>
            <strong>{activeKeywordCount}</strong> keyword{activeKeywordCount === 1 ? '' : 's'} × <strong>{selected.size}</strong> engine{selected.size === 1 ? '' : 's'} = <strong>{totalCells}</strong> answers scanned
          </div>
          {includeCompetitors && competitorCount > 0 && (
            <div style={{ fontSize: 12, color: '#15803d', marginTop: 3 }}>
              Competitors re-use the same answers — free.
            </div>
          )}
        </div>

        {/* Progress (while running) */}
        {running && jobStatus && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b', marginBottom: 5 }}>
              <span>Scanning…</span>
              <span>
                {done}/{jobStatus.total || '…'} done
                {jobStatus.failed > 0 && <span style={{ color: '#b91c1c' }}> · {jobStatus.failed} failed</span>}
              </span>
            </div>
            <div style={{ width: '100%', height: 8, background: '#f1f5f9', borderRadius: 999, overflow: 'hidden' }}>
              <div
                className="aiv-confidence-seg"
                style={{ width: `${progressPct}%`, height: '100%', background: '#6366f1', borderRadius: 999 }}
              />
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
              You can close this — the scan keeps running in the background.
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button style={ghostBtn} onClick={onClose}>{running ? 'Close' : 'Cancel'}</button>
          {!running && (
            <button
              style={{ ...primaryBtn, opacity: selected.size === 0 || activeKeywordCount === 0 ? 0.5 : 1 }}
              disabled={selected.size === 0 || activeKeywordCount === 0}
              onClick={() => onRun([...selected], includeCompetitors)}
            >
              <Zap size={14} /> Run scan
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 50,
}
const modal: React.CSSProperties = {
  background: '#fff', borderRadius: 14, padding: 22, maxWidth: 480, width: '100%',
  maxHeight: '85vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(15,23,42,0.2)',
}
const closeBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 2 }
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: '#6366f1', color: '#fff',
  border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: '#fff', color: '#475569',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '9px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
