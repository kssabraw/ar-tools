import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { GbpProfile } from '../lib/types'
import { Search, MapPin, Star, Loader2, X, Check, Link2 } from 'lucide-react'

interface GbpSuggestion {
  place_id: string
  name: string
  address: string
  description: string
}
interface GbpDetailsResponse {
  place_id: string
  gbp: GbpProfile
}

interface GbpPickerProps {
  placeId: string | null
  profile: GbpProfile | null
  onChange: (placeId: string | null, profile: GbpProfile | null) => void
}

export function GbpPicker({ placeId, profile, onChange }: GbpPickerProps) {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<GbpSuggestion[]>([])
  const [searching, setSearching] = useState(false)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Paste-a-link flow (URL / share link / place ID / CID).
  const [pasteInput, setPasteInput] = useState('')
  const [resolving, setResolving] = useState(false)
  // Each keystroke bumps this; stale responses are dropped.
  const reqSeq = useRef(0)

  // Debounced search on the query.
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) {
      setSuggestions([])
      setSearching(false)
      return
    }
    setSearching(true)
    const seq = ++reqSeq.current
    const handle = setTimeout(async () => {
      try {
        const res = await api.get<{ suggestions: GbpSuggestion[] }>(
          `/clients/gbp/search?q=${encodeURIComponent(q)}`,
        )
        if (seq === reqSeq.current) setSuggestions(res.suggestions ?? [])
      } catch (e) {
        if (seq === reqSeq.current) {
          setError((e as Error).message)
          setSuggestions([])
        }
      } finally {
        if (seq === reqSeq.current) setSearching(false)
      }
    }, 350)
    return () => clearTimeout(handle)
  }, [query])

  async function selectSuggestion(s: GbpSuggestion) {
    setError(null)
    setLoadingDetails(true)
    // Drop any in-flight search results.
    reqSeq.current++
    setSuggestions([])
    setQuery('')
    try {
      const res = await api.get<GbpDetailsResponse>(
        `/clients/gbp/details?place_id=${encodeURIComponent(s.place_id)}`,
      )
      onChange(res.place_id, res.gbp)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoadingDetails(false)
    }
  }

  async function resolvePasted() {
    const value = pasteInput.trim()
    if (!value) return
    setError(null)
    setResolving(true)
    // Drop any in-flight search results.
    reqSeq.current++
    setSuggestions([])
    try {
      const res = await api.get<GbpDetailsResponse>(
        `/clients/gbp/resolve?input=${encodeURIComponent(value)}`,
      )
      onChange(res.place_id, res.gbp)
      setPasteInput('')
      setQuery('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setResolving(false)
    }
  }

  function clearSelection() {
    onChange(null, null)
    setError(null)
  }

  // ── Selected state ────────────────────────────────────────────────
  if (profile) {
    return (
      <div>
        <div style={selectedCard}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
            <div style={iconBadge}>
              <Check size={16} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>
                {profile.business_name || 'Business'}
              </div>
              {profile.address && (
                <div style={metaRow}>
                  <MapPin size={12} /> {profile.address}
                </div>
              )}
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 4 }}>
                {profile.gbp_rating != null && (
                  <span style={metaRow}>
                    <Star size={12} /> {profile.gbp_rating}
                    {profile.gbp_review_count != null ? ` (${profile.gbp_review_count})` : ''}
                  </span>
                )}
                {profile.gbp_category && <span style={metaMuted}>{profile.gbp_category}</span>}
                {profile.phone && <span style={metaMuted}>{profile.phone}</span>}
              </div>
              {profile.reviews && profile.reviews.length > 0 && (
                <div style={{ fontSize: 12, color: '#16a34a', marginTop: 6 }}>
                  {profile.reviews.length} review{profile.reviews.length === 1 ? '' : 's'} captured
                </div>
              )}
            </div>
            <button type="button" onClick={clearSelection} style={removeBtn} title="Remove GBP">
              <X size={14} />
            </button>
          </div>
        </div>
        {error && <div style={errStyle}>{error}</div>}
      </div>
    )
  }

  // ── Search state ──────────────────────────────────────────────────
  return (
    <div>
      <div style={{ position: 'relative' }}>
        <Search size={15} style={searchIcon} />
        <input
          value={query}
          onChange={e => {
            setQuery(e.target.value)
            setError(null)
          }}
          placeholder="Search by business name + city…"
          style={searchInput}
        />
        {(searching || loadingDetails) && (
          <Loader2 size={15} style={spinnerIcon} className="gbp-spin" />
        )}
      </div>

      <div style={dividerRow}>
        <span style={dividerLine} />
        <span style={dividerText}>or paste a link</span>
        <span style={dividerLine} />
      </div>

      <div style={{ position: 'relative', display: 'flex', gap: 8 }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Link2 size={15} style={searchIcon} />
          <input
            value={pasteInput}
            onChange={e => {
              setPasteInput(e.target.value)
              setError(null)
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                resolvePasted()
              }
            }}
            placeholder="Google Maps URL, share link, or place ID…"
            style={searchInput}
          />
        </div>
        <button
          type="button"
          onClick={resolvePasted}
          disabled={resolving || pasteInput.trim().length === 0}
          style={resolveBtn}
        >
          {resolving ? <Loader2 size={14} className="gbp-spin" /> : 'Fetch'}
        </button>
      </div>

      {suggestions.length > 0 && (
        <div style={dropdown}>
          {suggestions.map(s => (
            <button
              key={s.place_id}
              type="button"
              onClick={() => selectSuggestion(s)}
              style={suggestionRow}
            >
              <MapPin size={14} color="#94a3b8" style={{ marginTop: 2, flexShrink: 0 }} />
              <span style={{ minWidth: 0 }}>
                <span style={{ display: 'block', fontWeight: 600, fontSize: 13, color: '#0f172a' }}>
                  {s.name}
                </span>
                <span style={{ display: 'block', fontSize: 12, color: '#94a3b8' }}>
                  {s.address}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}

      {loadingDetails && (
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>Loading business details…</div>
      )}
      {error && <div style={errStyle}>{error}</div>}
      {placeId && !profile && (
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
          Linked place: {placeId}
        </div>
      )}

      <style>{`@keyframes gbp-spin { to { transform: rotate(360deg) } } .gbp-spin { animation: gbp-spin 0.8s linear infinite }`}</style>
    </div>
  )
}

const searchInput: React.CSSProperties = {
  width: '100%', padding: '10px 36px', border: '1px solid #d1d5db', borderRadius: 8,
  fontSize: 14, color: '#0f172a', boxSizing: 'border-box',
}
const searchIcon: React.CSSProperties = {
  position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8',
}
const spinnerIcon: React.CSSProperties = {
  position: 'absolute', right: 11, top: '50%', transform: 'translateY(-50%)', color: '#6366f1',
}
const dropdown: React.CSSProperties = {
  marginTop: 6, border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff',
  overflow: 'hidden', boxShadow: '0 4px 12px rgba(15,23,42,0.06)',
}
const suggestionRow: React.CSSProperties = {
  display: 'flex', gap: 10, alignItems: 'flex-start', width: '100%', textAlign: 'left',
  padding: '10px 12px', background: '#fff', border: 'none', borderBottom: '1px solid #f1f5f9',
  cursor: 'pointer',
}
const selectedCard: React.CSSProperties = {
  border: '1px solid #c7d2fe', background: '#f8faff', borderRadius: 10, padding: 14,
}
const iconBadge: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 32, height: 32, borderRadius: 8, background: '#eef2ff', color: '#6366f1', flexShrink: 0,
}
const metaRow: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b',
}
const metaMuted: React.CSSProperties = { fontSize: 12, color: '#94a3b8' }
const removeBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', padding: 6, background: '#fff', color: '#64748b',
  border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', flexShrink: 0,
}
const errStyle: React.CSSProperties = { color: '#dc2626', fontSize: 12, marginTop: 8 }
const dividerRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0',
}
const dividerLine: React.CSSProperties = { flex: 1, height: 1, background: '#e2e8f0' }
const dividerText: React.CSSProperties = { fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }
const resolveBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', minWidth: 64,
  padding: '0 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
