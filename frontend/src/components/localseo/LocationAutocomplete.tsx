import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { MapPin } from 'lucide-react'
import { localSeoApi } from './api'
import type { LocationSuggestion } from './types'
import { input } from './shared'

interface Props {
  clientId: string
  value: string
  // Reports the chosen text and the DataForSEO location_code (null when the
  // user is free-typing and hasn't picked a suggestion).
  onChange: (location: string, locationCode: number | null) => void
  placeholder?: string
  disabled?: boolean
}

/**
 * Area / location typeahead backed by DataForSEO's location list. Picking a
 * suggestion sets a validated location_code so the SERP lookup can't fail to
 * resolve; free-typing leaves the code null (the backend then validates it).
 */
export function LocationAutocomplete({ clientId, value, onChange, placeholder, disabled }: Props) {
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const boxRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Debounced search, driven by typing (not a value effect) — so a programmatic
  // value change from the parent (e.g. opening a saved page) never pops the
  // dropdown, and we avoid setState-in-effect cascades.
  const scheduleSearch = (q: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (q.trim().length < 2) {
      setSuggestions([])
      setOpen(false)
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await localSeoApi.searchLocations(clientId, q.trim())
        setSuggestions(res)
        setOpen(res.length > 0)
        setActive(-1)
      } catch {
        setSuggestions([])
        setOpen(false)
      }
    }, 250)
  }

  useEffect(() => () => { if (debounceRef.current) clearTimeout(debounceRef.current) }, [])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const handleType = (text: string) => {
    onChange(text, null)
    scheduleSearch(text)
  }

  const select = (s: LocationSuggestion) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    onChange(s.location_name, s.location_code)
    setSuggestions([])
    setOpen(false)
    setActive(-1)
  }

  return (
    <div ref={boxRef} style={{ position: 'relative' }}>
      <MapPin size={16} color="#94a3b8" style={{ position: 'absolute', left: 12, top: 12 }} />
      <input
        style={{ ...input, paddingLeft: 36 }}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        onChange={e => handleType(e.target.value)}
        onFocus={() => { if (suggestions.length) setOpen(true) }}
        onKeyDown={e => {
          if (!open || !suggestions.length) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setActive(a => Math.min(a + 1, suggestions.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setActive(a => Math.max(a - 1, 0))
          } else if (e.key === 'Enter' && active >= 0) {
            e.preventDefault()
            select(suggestions[active])
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && (
        <ul role="listbox" style={listStyle}>
          {suggestions.map((s, i) => (
            <li
              key={s.location_code}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={e => { e.preventDefault(); select(s) }}
              style={{ ...itemStyle, background: i === active ? '#eef2ff' : '#fff' }}
            >
              {s.location_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const listStyle: CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 4px)',
  left: 0,
  right: 0,
  zIndex: 20,
  margin: 0,
  padding: 4,
  listStyle: 'none',
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 8,
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.12)',
  maxHeight: 240,
  overflowY: 'auto',
}

const itemStyle: CSSProperties = {
  padding: '8px 10px',
  borderRadius: 6,
  fontSize: 13,
  color: '#0f172a',
  cursor: 'pointer',
}
