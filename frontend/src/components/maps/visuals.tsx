import { useState } from 'react'
import type { MapsKeywordTrend, MapsTrendPoint } from '../../lib/types'
import { rankColor, TREND_METRICS } from './rank'

// Shared Maps geo-grid visuals: the rank-color scale, the geo-grid map (numbered
// pins on a Google Static Map, with a dependency-free circular fallback), and the
// per-keyword trend chart. Used by both the in-app module and the printable report.

const GMAPS_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined
const MAP_SIZE = 480 // logical px of the square static map (requested at scale=2 for sharpness)
const muted: React.CSSProperties = { fontSize: 13, color: '#94a3b8' }

// Lat/lng of an in-circle grid cell: pins are spaced 1 mile, row 0 = north.
function cellLatLng(row: number, col: number, n: number, centerLat: number, centerLng: number) {
  const c = (n - 1) / 2
  const lat = centerLat + (c - row) * (1 / 69)
  const lng = centerLng + (col - c) * (1 / (69 * Math.cos((centerLat * Math.PI) / 180)))
  return { lat, lng }
}

// Largest integer Google zoom that fits the ~n-mile-wide grid into ~90% of the
// image (floored so edge pins never spill outside the map and get clipped).
function fitZoom(centerLat: number, n: number): number {
  const target = (n * 1609.34) / (MAP_SIZE * 0.9) // meters per logical px wanted
  const z = Math.log2((156543.03392 * Math.cos((centerLat * Math.PI) / 180)) / target)
  return Math.max(1, Math.min(16, Math.floor(z)))
}

// Web-Mercator projection of a lat/lng to a pixel within a MAP_SIZE square map
// centered on (centerLat, centerLng) at the given zoom.
function projectToPixel(lat: number, lng: number, centerLat: number, centerLng: number, zoom: number) {
  const worldSize = 256 * 2 ** zoom
  const px = (lo: number) => ((lo + 180) / 360) * worldSize
  const py = (la: number) => {
    const s = Math.max(-0.9999, Math.min(0.9999, Math.sin((la * Math.PI) / 180)))
    return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * worldSize
  }
  return { x: px(lng) - px(centerLng) + MAP_SIZE / 2, y: py(lat) - py(centerLat) + MAP_SIZE / 2 }
}

// The base (marker-less) Google Static Map centered on the scan, at a zoom that
// frames the grid. Null when no API key is configured (→ circular fallback).
function buildBaseMapUrl(centerLat: number | null, centerLng: number | null, zoom: number): string | null {
  if (!GMAPS_KEY || centerLat == null || centerLng == null) return null
  return `https://maps.googleapis.com/maps/api/staticmap?center=${centerLat},${centerLng}&zoom=${zoom}` +
    `&size=${MAP_SIZE}x${MAP_SIZE}&scale=2&maptype=roadmap&key=${GMAPS_KEY}`
}

// The business's Maps rank per pin: numbered, color-coded badges projected onto a
// Google Static Map at their real lat/lng (ranked pins show the rank; not-ranked
// pins are small grey dots). Falls back to the circular heatmap with no Maps key.
export function GeoGridMap({ grid, centerLat, centerLng, size = MAP_SIZE }: {
  grid: Array<Array<number | null>> | null
  centerLat: number | null
  centerLng: number | null
  size?: number
}) {
  const [imgError, setImgError] = useState(false)
  const n = grid && grid.length ? Math.max(...grid.map(row => row.length)) : 0
  const zoom = centerLat != null && n ? fitZoom(centerLat, n) : 12
  const mapUrl = n ? buildBaseMapUrl(centerLat, centerLng, zoom) : null

  if (!mapUrl || imgError) return <CircleHeatmap grid={grid} />

  const pins: Array<{ x: number; y: number; rank: number | null; ranked: boolean }> = []
  if (grid && centerLat != null && centerLng != null) {
    const c = (n - 1) / 2
    const radiusSq = (n / 2) ** 2
    for (let row = 0; row < n; row++) {
      for (let col = 0; col < n; col++) {
        if ((row - c) ** 2 + (col - c) ** 2 > radiusSq) continue
        const { lat, lng } = cellLatLng(row, col, n, centerLat, centerLng)
        const { x, y } = projectToPixel(lat, lng, centerLat, centerLng, zoom)
        const cell = grid[row] && grid[row][col] != null ? grid[row][col] : null
        pins.push({ x, y, rank: cell, ranked: typeof cell === 'number' && cell >= 1 })
      }
    }
  }

  return (
    <div style={{ position: 'relative', width: '100%', maxWidth: size, aspectRatio: '1 / 1', borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
      <img src={mapUrl} alt="Geo-grid map" onError={() => setImgError(true)}
        style={{ width: '100%', height: '100%', display: 'block' }} />
      {pins.map((p, i) => (
        <div key={i} title={p.ranked ? `Rank ${p.rank}` : 'Not ranked here'}
          style={{
            position: 'absolute', left: `${(p.x / MAP_SIZE) * 100}%`, top: `${(p.y / MAP_SIZE) * 100}%`,
            transform: 'translate(-50%, -50%)',
            width: p.ranked ? 22 : 12, height: p.ranked ? 22 : 12, borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: rankColor(p.rank), color: '#fff', fontSize: 11, fontWeight: 700, lineHeight: 1,
            border: '1.5px solid #fff', boxShadow: '0 1px 2px rgba(0,0,0,.35)', boxSizing: 'border-box',
          }}>
          {p.ranked ? p.rank : ''}
        </div>
      ))}
    </div>
  )
}

// Circular pin heatmap: small color-coded dots laid out in a circle (cells
// outside the scan circle are omitted so the shape reads as a circle).
function CircleHeatmap({ grid }: { grid: Array<Array<number | null>> | null }) {
  if (!grid || grid.length === 0) return <p style={muted}>No grid data.</p>
  const n = Math.max(...grid.map(r => r.length))
  const center = (n - 1) / 2
  const radiusSq = (n / 2) ** 2
  const inCircle = (r: number, c: number) => (r - center) ** 2 + (c - center) ** 2 <= radiusSq
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${n}, 1fr)`, gap: 3, maxWidth: n * 28 }}>
      {Array.from({ length: n }).flatMap((_, ri) =>
        Array.from({ length: n }).map((__, ci) => {
          if (!inCircle(ri, ci)) return <div key={`${ri}-${ci}`} />
          const cell = (grid[ri] && grid[ri][ci] != null) ? grid[ri][ci] : null
          const ranked = typeof cell === 'number' && cell >= 1
          return (
            <div key={`${ri}-${ci}`} title={ranked ? `Rank ${cell}` : 'Not ranked here'}
              style={{
                aspectRatio: '1', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 9, fontWeight: 700, background: rankColor(cell), color: ranked ? '#fff' : '#cbd5e1',
              }}>
              {ranked ? cell : ''}
            </div>
          )
        }),
      )}
    </div>
  )
}

const SERIES_COLORS = ['#6366f1', '#16a34a', '#ea580c', '#0ea5e9', '#db2777', '#ca8a04', '#7c3aed', '#0d9488']

// Coverage/rank trend over time, one line per keyword. Avg rank is drawn inverted
// so "up = improving" holds for every metric. Each keyword's latest value shows
// in the legend.
export function TrendChart({ keywords, metric }: { keywords: MapsKeywordTrend[]; metric: typeof TREND_METRICS[number] }) {
  const W = 600, H = 240, padL = 38, padR = 12, padT = 12, padB = 26
  const plotW = W - padL - padR, plotH = H - padT - padB

  const val = (p: MapsTrendPoint): number | null => p[metric.key] as number | null
  const times = keywords.flatMap(k => k.points.map(p => Date.parse(p.completed_at || '') || 0))
  const tMin = Math.min(...times), tMax = Math.max(...times)
  const vals = keywords.flatMap(k => k.points.map(val).filter((v): v is number => v != null))
  const yLo = metric.lowerIsBetter ? 1 : 0
  const yHi = metric.fixedMax ?? Math.max(yLo + 1, Math.ceil((Math.max(...vals, yLo) + 1)))

  const x = (t: number) => padL + (tMax === tMin ? plotW / 2 : ((t - tMin) / (tMax - tMin)) * plotW)
  const y = (v: number) => {
    const frac = (v - yLo) / (yHi - yLo || 1)
    return padT + (metric.lowerIsBetter ? frac : 1 - frac) * plotH
  }
  const ticks = Array.from({ length: 5 }, (_, i) => yLo + ((yHi - yLo) * i) / 4)
  const fmt = (v: number | null) => (v == null ? '—' : `${metric.lowerIsBetter ? (Math.round(v * 10) / 10) : Math.round(v)}${metric.unit}`)

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxWidth: W, display: 'block' }} role="img" aria-label={`${metric.label} trend`}>
        {ticks.map((tk, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(tk)} y2={y(tk)} stroke="#eef2f7" strokeWidth={1} />
            <text x={padL - 6} y={y(tk) + 3} textAnchor="end" fontSize={9} fill="#94a3b8">{Math.round(tk)}{metric.unit}</text>
          </g>
        ))}
        {keywords.map((k, ki) => {
          const color = SERIES_COLORS[ki % SERIES_COLORS.length]
          const pts = k.points.filter(p => val(p) != null)
          const line = pts.map(p => `${x(Date.parse(p.completed_at || '') || 0)},${y(val(p) as number)}`).join(' ')
          return (
            <g key={k.keyword}>
              {pts.length > 1 && <polyline points={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
              {pts.map((p, i) => (
                <circle key={i} cx={x(Date.parse(p.completed_at || '') || 0)} cy={y(val(p) as number)} r={2.8} fill={color}>
                  <title>{`${k.keyword} · ${fmt(val(p))} · ${p.completed_at ? new Date(p.completed_at).toLocaleDateString() : ''}`}</title>
                </circle>
              ))}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 8 }}>
        {keywords.map((k, ki) => {
          const last = [...k.points].reverse().find(p => val(p) != null)
          return (
            <span key={k.keyword} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569' }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: SERIES_COLORS[ki % SERIES_COLORS.length] }} />
              {k.keyword}<strong style={{ color: '#0f172a' }}>{fmt(last ? val(last) : null)}</strong>
            </span>
          )
        })}
      </div>
      {metric.lowerIsBetter && <p style={{ ...muted, marginBottom: 0, marginTop: 8 }}>Lower is better — the line is drawn so up = improving.</p>}
    </div>
  )
}
