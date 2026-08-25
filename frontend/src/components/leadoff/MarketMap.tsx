import { useState } from 'react'
import { MapPin } from 'lucide-react'
import { buildBaseMapUrl, projectToPixel, fitZoom, MAP_SIZE } from '../maps/visuals'

// The LeadOff market map: competitor pins (from public.competitor_locations),
// the market centre, suggested GBP placement zones, and an optional pasted GBP
// reference pin, plotted over a Google Static Map. Reuses the geo-grid's
// static-map + CSS-pin precedent (no map JS dependency); degrades to a note
// when no Maps key is configured — the octant bars carry the same field.

export interface MarketMapPin {
  name: string | null
  lat: number
  lng: number
  reviews: number
  rank?: number | null
  rating?: number | null
  miles?: number
}
export interface MarketMapPlacement {
  octant: string
  lat: number
  lng: number
  locality?: string | null
}
export interface MarketMapGbp {
  name: string | null
  lat: number
  lng: number
}

// Local great-circle distance (miles) — just for framing the GBP reference pin.
function haversineMiles(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const r = 3958.8
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLng = toRad(lng2 - lng1)
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2
  return 2 * r * Math.asin(Math.sqrt(a))
}

export function MarketMap({ center, pins, placement = [], gbp = null, radiusMiles }: {
  center: { lat: number; lng: number }
  pins: MarketMapPin[]
  placement?: MarketMapPlacement[]
  gbp?: MarketMapGbp | null
  radiusMiles: number
}) {
  const [imgError, setImgError] = useState(false)

  // Frame the ~2×radius-mile-wide market. A pasted GBP can sit outside the
  // market, so widen the frame to include it — but only when it's reasonably
  // close (≤3× radius); a far/mis-pasted GBP keeps the market readable and gets
  // an out-of-view caption instead.
  const gbpMiles = gbp ? haversineMiles(center.lat, center.lng, gbp.lat, gbp.lng) : 0
  const includeGbp = gbpMiles > 0 && gbpMiles <= radiusMiles * 3
  const spanMiles = includeGbp ? Math.max(radiusMiles * 2, gbpMiles * 2 + 2) : radiusMiles * 2
  const zoom = fitZoom(center.lat, spanMiles)
  const mapUrl = buildBaseMapUrl(center.lat, center.lng, zoom)

  if (!mapUrl || imgError) {
    return (
      <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 8px' }}>
        Map preview needs a Google Maps key (VITE_GOOGLE_MAPS_API_KEY). The octant
        read below covers the same competitor field.
      </p>
    )
  }

  const project = (lat: number, lng: number) => {
    const { x, y } = projectToPixel(lat, lng, center.lat, center.lng, zoom)
    return {
      left: `${(x / MAP_SIZE) * 100}%`,
      top: `${(y / MAP_SIZE) * 100}%`,
      inView: x >= 0 && x <= MAP_SIZE && y >= 0 && y <= MAP_SIZE,
    }
  }

  // Competitor dot scales with review count (prominence), bounded.
  const dotSize = (reviews: number) =>
    Math.max(10, Math.min(22, 10 + Math.round(Math.sqrt(Math.max(reviews, 0)))))

  const gbpPos = gbp ? project(gbp.lat, gbp.lng) : null

  return (
    <div>
      <div style={mapBox}>
        <img src={mapUrl} alt="Market map" onError={() => setImgError(true)}
          style={{ width: '100%', height: '100%', display: 'block' }} />

        {/* Competitor pins — teal, sized by reviews, ranked ones show the rank */}
        {pins.map((p, i) => {
          const pos = project(p.lat, p.lng)
          if (!pos.inView) return null
          const d = dotSize(p.reviews)
          return (
            <div key={i} title={pinTitle(p)}
              style={{ ...pinBase, left: pos.left, top: pos.top, width: d, height: d,
                background: '#0e7d6f', color: '#fff', fontSize: 9, fontWeight: 700, zIndex: 1 }}>
              {p.rank != null ? p.rank : ''}
            </div>
          )
        })}

        {/* Suggested GBP placement zones — amber diamonds along weak bearings */}
        {placement.map((p, i) => {
          const pos = project(p.lat, p.lng)
          if (!pos.inView) return null
          return (
            <div key={`pl-${i}`}
              title={`Suggested zone: ${p.octant}${p.locality ? ` — near ${p.locality}` : ''}`}
              style={{ ...pinBase, left: pos.left, top: pos.top, width: 16, height: 16,
                background: '#f59e0b', color: '#fff', fontSize: 9, fontWeight: 700, zIndex: 2,
                borderRadius: 3, transform: 'translate(-50%, -50%) rotate(45deg)' }}>
              <span style={{ transform: 'rotate(-45deg)' }}>{p.octant[0]}</span>
            </div>
          )
        })}

        {/* Market centre (city) */}
        <div title="Market centre (city)"
          style={{ ...pinBase, left: '50%', top: '50%', width: 14, height: 14,
            background: '#fff', border: '2px solid #475569', zIndex: 3 }}>
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#475569' }} />
        </div>

        {/* GBP reference pin */}
        {gbp && gbpPos?.inView && (
          <div title={`GBP: ${gbp.name ?? 'business'}`}
            style={{ ...pinBase, left: gbpPos.left, top: gbpPos.top, width: 22, height: 22,
              background: '#4f46e5', color: '#fff', zIndex: 4, border: '2px solid #fff',
              boxShadow: '0 0 0 3px rgba(99,102,241,.35), 0 1px 4px rgba(0,0,0,.4)' }}>
            <MapPin size={12} />
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={legend}>
        <LegendDot color="#0e7d6f" label="Competitor (size = reviews)" />
        <LegendDot color="#475569" label="Market centre" ring />
        {placement.length > 0 && <LegendDot color="#f59e0b" label="Suggested zone" diamond />}
        {gbp && <LegendDot color="#4f46e5" label={gbp.name ? `GBP: ${gbp.name}` : 'Your GBP'} />}
      </div>

      {gbp && gbpPos && !gbpPos.inView && (
        <p style={{ fontSize: 11, color: '#b45309', margin: '4px 0 0' }}>
          {gbp.name ?? 'The GBP'} is {gbpMiles.toFixed(1)} mi from the market centre — outside the map view.
        </p>
      )}
    </div>
  )
}

function pinTitle(p: MarketMapPin): string {
  const bits = [p.name || 'Competitor']
  if (p.rank != null) bits.push(`rank ${p.rank}`)
  if (p.rating != null) bits.push(`★ ${p.rating}`)
  bits.push(`${p.reviews} review${p.reviews === 1 ? '' : 's'}`)
  if (p.miles != null) bits.push(`${p.miles} mi`)
  return bits.join(' · ')
}

function LegendDot({ color, label, ring, diamond }: {
  color: string; label: string; ring?: boolean; diamond?: boolean
}) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#64748b' }}>
      <span style={{
        width: 10, height: 10, borderRadius: diamond ? 2 : '50%',
        background: ring ? '#fff' : color, border: ring ? `2px solid ${color}` : undefined,
        transform: diamond ? 'rotate(45deg)' : undefined, flexShrink: 0,
      }} />
      {label}
    </span>
  )
}

const mapBox: React.CSSProperties = {
  position: 'relative', width: '100%', maxWidth: MAP_SIZE, aspectRatio: '1 / 1',
  borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden',
}
const pinBase: React.CSSProperties = {
  position: 'absolute', transform: 'translate(-50%, -50%)', borderRadius: '50%',
  display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1,
  boxSizing: 'border-box',
}
const legend: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 8,
}
