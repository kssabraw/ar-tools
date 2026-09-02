import { MapPin, X } from 'lucide-react'
import { LocationAutocomplete } from '../LocationAutocomplete'
import { label } from '../shared'
import { pinKey, type LocationPins } from './locationPins'
import { splitLines } from './types'

interface Props {
  clientId: string
  locationsText: string
  pins: LocationPins
  onChange: (pins: LocationPins) => void
  disabled?: boolean
}

// One row per location on the axis: pinned rows show the DataForSEO area they
// resolve to (with an unpin); unpinned rows offer the typeahead. Only a PICKED
// suggestion pins — free text never does, so a typo can't silently anchor a
// suburb's SERP to the wrong place.
export function MatrixLocationPins({ clientId, locationsText, pins, onChange, disabled }: Props) {
  const names = splitLines(locationsText)
  if (!names.length) return null
  const pinnedCount = names.filter(n => pins[pinKey(n)]).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div>
        <label style={label}>
          Pin a location to its own search area <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional · {pinnedCount} pinned)</span>
        </label>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '2px 0 0' }}>
          By default every cell is generated against the metro with the suburb in the keyword — the live-verified path.
          Pin a row only when a location is really a different market (another metro, a distant town) and should have
          its own competitor SERP.
        </p>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {names.map(name => {
          const pin = pins[pinKey(name)]
          return (
            <div key={pinKey(name)} style={{ display: 'grid', gridTemplateColumns: '180px 1fr', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: '#0f172a', display: 'inline-flex', alignItems: 'center', gap: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {pin ? <MapPin size={13} color="#6366f1" /> : <span style={{ width: 13 }} />}{name}
              </span>
              {pin ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#4338ca', background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 8, padding: '6px 10px' }}>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{pin.canonical}</span>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => { const next = { ...pins }; delete next[pinKey(name)]; onChange(next) }}
                    title="Unpin — generate against the metro again"
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#4338ca', display: 'inline-flex' }}
                  ><X size={13} /></button>
                </div>
              ) : (
                <LocationAutocomplete
                  clientId={clientId}
                  value=""
                  onChange={(loc, code) => { if (code != null) onChange({ ...pins, [pinKey(name)]: { location_code: code, canonical: loc } }) }}
                  placeholder={`Search a DataForSEO area for ${name}…`}
                  disabled={disabled}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
