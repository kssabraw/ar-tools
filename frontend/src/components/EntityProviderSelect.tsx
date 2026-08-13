import type { CSSProperties } from 'react'

// A compact "Entity engine" selector — chooses which entity-extraction provider
// the private nlp service uses for its competitor SERP analysis. Threaded from
// the Local SEO + Ecommerce generate / reoptimize / score forms down to the nlp
// payload's `entity_provider` field. "textrazor" is the nlp default (+ Wikipedia
// / Wikidata linking); "google" uses Google Cloud NLP.

export type EntityProvider = 'textrazor' | 'google'

const OPTIONS: Array<{ id: EntityProvider; label: string }> = [
  { id: 'textrazor', label: 'TextRazor (default)' },
  { id: 'google', label: 'Google NLP' },
]

interface Props {
  value: EntityProvider
  onChange: (value: EntityProvider) => void
  disabled?: boolean
  // Hides the label text for tight inline placements (Reoptimize panel).
  hideLabel?: boolean
}

export function EntityProviderSelect({ value, onChange, disabled, hideLabel }: Props) {
  return (
    <div>
      {!hideLabel && <label style={labelStyle}>Entity engine</label>}
      <div style={pillGroup}>
        {OPTIONS.map(opt => (
          <button
            key={opt.id}
            type="button"
            onClick={() => !disabled && onChange(opt.id)}
            disabled={disabled}
            style={pill(value === opt.id, Boolean(disabled))}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {!hideLabel && (
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>
          Which engine extracts entities from the competitor SERP analysis.
        </p>
      )}
    </div>
  )
}

const labelStyle: CSSProperties = {
  fontSize: 13, fontWeight: 600, color: '#0f172a', display: 'block', marginBottom: 6,
}
const pillGroup: CSSProperties = {
  display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4,
}
function pill(active: boolean, disabled: boolean): CSSProperties {
  return {
    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none',
    background: active ? '#fff' : 'transparent', color: active ? '#0f172a' : '#64748b',
    boxShadow: active ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
  }
}
