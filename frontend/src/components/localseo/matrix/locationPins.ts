import { splitLines } from './types'

// A pinned location generates its cells at its OWN DataForSEO area instead of
// the matrix's metro anchor (plan §3.2). Keyed by the location's lower-cased
// name, so a pin survives re-ordering the axis and is dropped with its line.
export type LocationPins = Record<string, { location_code: number; canonical: string }>

export function pinKey(name: string): string {
  return name.trim().toLowerCase()
}

// Seed pins from a saved matrix's location rows.
export function pinsFromRows(rows: { name: string; location_code?: number | null; canonical?: string | null }[]): LocationPins {
  const out: LocationPins = {}
  for (const r of rows) {
    if (r.location_code) out[pinKey(r.name)] = { location_code: r.location_code, canonical: r.canonical ?? r.name }
  }
  return out
}

// The `locations` body the API takes: a plain name, or the name + its pin.
export function composeLocations(text: string, pins: LocationPins): ({ name: string; location_code: number; canonical: string } | string)[] {
  return splitLines(text).map(name => {
    const pin = pins[pinKey(name)]
    return pin ? { name, location_code: pin.location_code, canonical: pin.canonical } : name
  })
}
