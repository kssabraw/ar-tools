import type { CSSProperties } from 'react'

// A compact "Content writing model" selector — chooses which LLM writes the DRAFT
// prose for the content writers (blog, service/location, Local SEO, Ecommerce,
// Fanout mass posts). "Sonnet" (Claude Sonnet) is the default; "Luna" routes the
// draft to OpenAI (gpt-5.6-luna). The post-draft quality gates (voice scoring,
// ICP/banned-term/QA judges) always stay on Claude, so grading is unaffected.
//
// The user-facing labels are MODEL names (Sonnet / Luna); the stored value is the
// PROVIDER ('anthropic' | 'openai') — the concrete OpenAI model id lives in config.
//
// Two modes:
//   - Client Setup default: value is a concrete provider, no inherit option.
//   - Per-run / per-page / per-batch override: pass `allowInherit` to add a "Use
//     client default" choice (value null = inherit the client's default).

export type ContentWriterProvider = 'anthropic' | 'openai'

const PROVIDER_OPTIONS: Array<{ id: ContentWriterProvider; label: string }> = [
  { id: 'anthropic', label: 'Sonnet' },
  { id: 'openai', label: 'Luna' },
]

interface Props {
  // null means "inherit the client default" (only valid when allowInherit).
  value: ContentWriterProvider | null
  onChange: (value: ContentWriterProvider | null) => void
  allowInherit?: boolean
  disabled?: boolean
  hideLabel?: boolean
  label?: string
  help?: string
}

export function ContentWriterSelect({
  value,
  onChange,
  allowInherit,
  disabled,
  hideLabel,
  label = 'Content writing model',
  help,
}: Props) {
  const options: Array<{ id: ContentWriterProvider | null; label: string }> = allowInherit
    ? [{ id: null, label: 'Use client default' }, ...PROVIDER_OPTIONS]
    : [...PROVIDER_OPTIONS]

  const helpText =
    help ??
    'Which model writes the draft. Quality checks (brand voice, QA) always run on Claude.'

  return (
    <div>
      {!hideLabel && <label style={labelStyle}>{label}</label>}
      <div style={pillGroup}>
        {options.map(opt => (
          <button
            key={opt.id ?? 'inherit'}
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
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }}>{helpText}</p>
      )}
    </div>
  )
}

const labelStyle: CSSProperties = {
  fontSize: 13, fontWeight: 600, color: '#0f172a', display: 'block', marginBottom: 6,
}
const pillGroup: CSSProperties = {
  display: 'inline-flex', gap: 4, background: '#f1f5f9', borderRadius: 8, padding: 4,
  flexWrap: 'wrap',
}
function pill(active: boolean, disabled: boolean): CSSProperties {
  return {
    padding: '6px 14px', fontSize: 13, fontWeight: 600, borderRadius: 6,
    cursor: disabled ? 'not-allowed' : 'pointer', border: 'none',
    background: active ? '#fff' : 'transparent', color: active ? '#0f172a' : '#64748b',
    boxShadow: active ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
  }
}
