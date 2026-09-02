import { Sparkles } from 'lucide-react'
import { Spinner } from '../Spinner'
import { input, label } from '../shared'
import { splitLines } from './types'
import type { MatrixSuggestion } from './types'

const textarea: React.CSSProperties = { ...input, minHeight: 120, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }

export type MatrixAxis = 'services' | 'locations'

export interface AxesSuggest {
  onSuggest: (axis: MatrixAxis) => void
  suggesting: MatrixAxis | null
  services: MatrixSuggestion[]
  locations: MatrixSuggestion[]
  notes: string[]
}

interface Props {
  services: string
  locations: string
  onChange: (services: string, locations: string) => void
  disabled?: boolean
  // When given, each axis gains a "Suggest" button and the returned suggestions
  // render as click-to-add chips under its textarea (accepted ones disappear).
  suggest?: AxesSuggest
}

// The two axes of a service × location matrix, one entry per line. Shared by
// the one-shot "Upload your own → Matrix" panel and the saved-matrix builder /
// axes editor, so keyword composition and Suggest reach both.
export function MatrixAxesEditor({ services, locations, onChange, disabled, suggest }: Props) {
  const have = (text: string) => new Set(splitLines(text).map(x => x.toLowerCase()))
  const accept = (axis: MatrixAxis, value: string) => {
    const current = axis === 'services' ? services : locations
    if (have(current).has(value.toLowerCase())) return
    const next = current.trim() ? `${current.replace(/\s+$/, '')}\n${value}` : value
    onChange(axis === 'services' ? next : services, axis === 'locations' ? next : locations)
  }
  const acceptAll = (axis: MatrixAxis, items: MatrixSuggestion[]) => {
    const current = axis === 'services' ? services : locations
    const had = have(current)
    const fresh = items.map(s => s.label).filter(l => !had.has(l.toLowerCase()))
    if (!fresh.length) return
    const next = [current.replace(/\s+$/, ''), ...fresh].filter(Boolean).join('\n')
    onChange(axis === 'services' ? next : services, axis === 'locations' ? next : locations)
  }

  const axisBlock = (axis: MatrixAxis, title: string, value: string, placeholder: string) => {
    const pending = suggest ? suggest[axis].filter(s => !have(value).has(s.label.toLowerCase())) : []
    const busy = suggest?.suggesting === axis
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <label style={label}>{title} <span style={{ fontWeight: 400, color: '#94a3b8' }}>· {splitLines(value).length}</span></label>
          {suggest && (
            <button
              type="button"
              onClick={() => suggest.onSuggest(axis)}
              disabled={disabled || Boolean(suggest.suggesting)}
              title={axis === 'services' ? 'Expand the first service into its variations (Sonnet, ICP-grounded)' : 'Target cities + suburbs of the metro (geocode-verified)'}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: 'none', border: 'none', padding: 0, cursor: busy ? 'wait' : 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1', opacity: disabled || suggest.suggesting ? 0.5 : 1 }}
            >
              {busy ? <Spinner size={12} /> : <Sparkles size={13} />} {busy ? 'Suggesting…' : 'Suggest'}
            </button>
          )}
        </div>
        <textarea
          style={textarea}
          value={value}
          disabled={disabled}
          onChange={e => onChange(axis === 'services' ? e.target.value : services, axis === 'locations' ? e.target.value : locations)}
          placeholder={placeholder}
        />
        {pending.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {pending.map(s => (
              <button
                key={s.label}
                type="button"
                onClick={() => accept(axis, s.label)}
                disabled={disabled}
                title={s.group ? `From: ${s.group}` : undefined}
                style={{ fontSize: 12, padding: '3px 10px', borderRadius: 999, border: '1px dashed #c7d2fe', background: '#eef2ff', color: '#4338ca', cursor: 'pointer' }}
              >+ {s.label}</button>
            ))}
            <button
              type="button"
              onClick={() => acceptAll(axis, pending)}
              disabled={disabled}
              style={{ fontSize: 12, fontWeight: 600, background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', padding: '3px 6px' }}
            >Add all</button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {axisBlock('services', 'Services (one per line)', services, 'Roof restoration\nTile roof restoration\nColorbond roof restoration')}
        {axisBlock('locations', 'Locations (one per line)', locations, 'Melbourne\nCaulfield\nHawthorn\nMoorabbin')}
      </div>
      {suggest && suggest.notes.length > 0 && (
        <p style={{ fontSize: 12, color: '#92400e', margin: 0 }}>{suggest.notes.join(' · ')}</p>
      )}
    </div>
  )
}
