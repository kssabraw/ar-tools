import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'
import { parseError, looksLikeErrorCode } from '../lib/errorGuidance'

interface Palette {
  bg: string
  border: string
  headline: string
  body: string
  chipText: string
  chipBorder: string
  overrideText: string
  overrideBorder: string
}

// The suite's red-box palette (hardcoded hex) and the fanout palette, which
// tracks fanout's `--danger` theme token so the accordion looks native inside
// the `.fanout-app` subtree (its `.form-error` uses the same box + `--danger`).
const PALETTES: Record<'default' | 'fanout', Palette> = {
  default: {
    bg: '#fef2f2', border: '#fecaca', headline: '#991b1b', body: '#7f1d1d',
    chipText: '#b91c1c', chipBorder: '#fecaca', overrideText: '#b91c1c', overrideBorder: '#fca5a5',
  },
  fanout: {
    bg: '#fef2f2', border: '#fecaca', headline: 'var(--danger, #dc2626)', body: 'var(--danger, #dc2626)',
    chipText: 'var(--danger, #dc2626)', chipBorder: '#fecaca', overrideText: 'var(--danger, #dc2626)', overrideBorder: '#fca5a5',
  },
}

interface ErrorDetailsProps {
  /** The raw error message / code from the failed request. */
  message: string | null | undefined
  /**
   * Optional override handler (e.g. re-publish with `force_voice`). Only shown
   * when the matched error actually defines an override, so passing this on a
   * surface where no error needs it is harmless.
   */
  onOverride?: () => void
  /** True while the override action is running (disables + relabels the button). */
  overriding?: boolean
  /**
   * Visual theme. `default` is the suite's inline-styled red box; `fanout`
   * themes off fanout's `--danger` token so it matches that subtree's own
   * error styling. Only the palette changes — the accordion behaviour is one.
   */
  variant?: 'default' | 'fanout'
  /** Extra styles for the outer container. */
  style?: React.CSSProperties
}

/**
 * An expandable, actionable error box.
 *
 * Collapsed, it reads like the old red error line — a headline the reader
 * understands, not a raw code. Expanded, it explains what the error means and
 * gives a numbered plan of action, plus (where one exists) a one-click override.
 * The guidance itself lives in `lib/errorGuidance`, so this component is generic
 * across every surface that surfaces a backend error.
 */
export function ErrorDetails({ message, onOverride, overriding, variant = 'default', style }: ErrorDetailsProps) {
  const [open, setOpen] = useState(false)
  if (!message) return null

  const c = PALETTES[variant]
  const { code, raw, terms, guidance } = parseError(message)
  const showOverride = Boolean(guidance.override && onOverride)

  // An already-friendly sentence (a message, not a code we can map) has no plan
  // of action to add — render it as a plain error line so ErrorDetails is a
  // safe drop-in anywhere, upgrading only the messages it actually recognizes.
  if (code === 'unknown' && !looksLikeErrorCode(raw)) {
    return (
      <div
        style={{
          marginBottom: 12,
          padding: '10px 12px',
          background: c.bg,
          border: `1px solid ${c.border}`,
          borderRadius: 8,
          color: c.headline,
          fontSize: 12,
          lineHeight: 1.5,
          ...style,
        }}
      >
        {raw}
      </div>
    )
  }

  return (
    <div
      style={{
        marginBottom: 12,
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 8,
        color: c.headline,
        fontSize: 12,
        overflow: 'hidden',
        ...style,
      }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          padding: '10px 12px',
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          font: 'inherit',
          fontWeight: 600,
          textAlign: 'left',
          cursor: 'pointer',
        }}
        aria-expanded={open}
      >
        <AlertTriangle size={14} style={{ flexShrink: 0 }} />
        <span style={{ flex: 1 }}>{guidance.title}</span>
        <span style={{ fontWeight: 500, opacity: 0.75, display: 'flex', alignItems: 'center', gap: 2 }}>
          {open ? 'Hide' : 'What to do'}
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {open && (
        <div style={{ padding: '0 12px 12px 34px' }}>
          {terms.length > 0 && (
            <div style={{ margin: '2px 0 10px', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <span style={{ fontWeight: 600 }}>Flagged:</span>
              {terms.map(t => (
                <code
                  key={t}
                  style={{
                    background: '#fff',
                    border: `1px solid ${c.chipBorder}`,
                    borderRadius: 4,
                    padding: '1px 6px',
                    fontSize: 12,
                    color: c.chipText,
                  }}
                >
                  {t}
                </code>
              ))}
            </div>
          )}

          <div style={{ fontWeight: 600, marginBottom: 4 }}>What this means</div>
          <p style={{ margin: '0 0 10px', lineHeight: 1.5, color: c.body }}>{guidance.meaning}</p>

          <div style={{ fontWeight: 600, marginBottom: 4 }}>How to fix it</div>
          <ol style={{ margin: '0 0 4px', paddingLeft: 18, lineHeight: 1.6, color: c.body }}>
            {guidance.steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>

          {showOverride && (
            <button
              onClick={onOverride}
              disabled={overriding}
              style={{
                marginTop: 10,
                padding: '6px 12px',
                background: '#fff',
                border: `1px solid ${c.overrideBorder}`,
                borderRadius: 6,
                color: c.overrideText,
                fontSize: 12,
                fontWeight: 600,
                cursor: overriding ? 'default' : 'pointer',
                opacity: overriding ? 0.6 : 1,
              }}
            >
              {overriding ? 'Working…' : guidance.override}
            </button>
          )}

          {code !== 'unknown' && (
            <div style={{ marginTop: 10, fontSize: 11, opacity: 0.6 }}>
              Error code: <code>{raw}</code>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
