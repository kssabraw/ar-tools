import { useState } from 'react'
import { MapPin, ExternalLink } from 'lucide-react'
import { buildBaseMapUrl, projectToPixel, fitZoom, MAP_SIZE } from '../maps/visuals'

// The LeadOff market map: competitor pins (live GBPs from a scout/tryout),
// the market centre, suggested GBP placement zones, and an optional pasted GBP
// reference pin, plotted over a Google Static Map. Reuses the geo-grid's
// static-map + CSS-pin precedent (no map JS dependency); degrades to a note
// when no Maps key is configured — the octant bars carry the same field.
//
// Interactions: click the base map → opens an interactive Google Map at the same
// view in a new tab (a closer look). Hover a competitor pin → a card with its
// name / ★ rating / reviews / distance and a "View on Google" link; the pin
// itself also links straight to that GBP.

export interface MarketMapPin {
  name: string | null
  lat: number
  lng: number
  reviews: number
  rank?: number | null
  rating?: number | null
  miles?: number
  place_id?: string | null
}
export interface MarketMapPlacement {
  octant: string
  lat: number
  lng: number
  locality?: string | null
}
// A ranked GBP Placement Advisor zone (demand-aware). When zones are present
// they REPLACE the octant placement diamonds — the advisor has run, so the
// numbered, demand-scored zones are the answer (placement plan §5.1).
export interface MarketMapZone {
  rank: number
  score: number
  lat: number
  lng: number
  locality?: string | null
  is_top?: boolean
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

// The Google Maps URL that opens a competitor's GBP: by place_id when we have it
// (the canonical listing), else a name/coordinate search.
function gbpUrl(p: MarketMapPin): string {
  if (p.place_id) return `https://www.google.com/maps/place/?q=place_id:${encodeURIComponent(p.place_id)}`
  if (p.name) return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.name)}`
  return `https://www.google.com/maps/search/?api=1&query=${p.lat},${p.lng}`
}

export function MarketMap({ center, pins, placement = [], zones = [], gbp = null, radiusMiles, browseQuery }: {
  center: { lat: number; lng: number }
  pins: MarketMapPin[]
  placement?: MarketMapPlacement[]
  // Ranked demand-aware placement zones. When non-empty they replace the octant
  // placement diamonds (the advisor has run).
  zones?: MarketMapZone[]
  gbp?: MarketMapGbp | null
  radiusMiles: number
  // The market's category (e.g. "chimney sweep"). When set, a clearly-separate
  // "Browse all … on Google" link is offered BELOW the map — this opens Google's
  // full live directory (more businesses than the ranked field we plot), so it's
  // labelled as its own thing, never as "the same map".
  browseQuery?: string
}) {
  const [imgError, setImgError] = useState(false)
  const [hovered, setHovered] = useState<number | null>(null)
  const browse = (browseQuery || '').trim()

  // Frame the ~2×radius-mile-wide market. A pasted GBP can sit outside the
  // market, so widen the frame to include it — but only when it's reasonably
  // close (≤3× radius); a far/mis-pasted GBP keeps the market readable and gets
  // an out-of-view caption instead.
  const gbpMiles = gbp ? haversineMiles(center.lat, center.lng, gbp.lat, gbp.lng) : 0
  const includeGbp = gbpMiles > 0 && gbpMiles <= radiusMiles * 3
  const spanMiles = includeGbp ? Math.max(radiusMiles * 2, gbpMiles * 2 + 2) : radiusMiles * 2
  const zoom = fitZoom(center.lat, spanMiles)
  const mapUrl = buildBaseMapUrl(center.lat, center.lng, zoom)
  // The separate "browse Google's full directory" action (a live category search
  // at the market centre) — distinct from what the map plots.
  const browseUrl = browse
    ? `https://www.google.com/maps/search/${encodeURIComponent(browse)}/@${center.lat},${center.lng},${zoom}z`
    : null

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
      topPct: (y / MAP_SIZE) * 100,
      leftPct: (x / MAP_SIZE) * 100,
      inView: x >= 0 && x <= MAP_SIZE && y >= 0 && y <= MAP_SIZE,
    }
  }

  // Competitor dot scales with review count (prominence), bounded.
  const dotSize = (reviews: number) =>
    Math.max(10, Math.min(22, 10 + Math.round(Math.sqrt(Math.max(reviews, 0)))))

  const gbpPos = gbp ? project(gbp.lat, gbp.lng) : null

  return (
    <div>
      {/* Outer keeps overflow visible so a pin's hover card can spill past the
          map edges; the image frame gets the rounded/clipped border. The base
          map is a static snapshot (not a link) — a whole-map "open in Google
          Maps" would show Google's full live directory, which is a larger set
          than our captured competitors and reads as a mismatch. Instead, each
          competitor pin links to its exact Google listing. */}
      <div style={mapOuter}>
        <div style={mapFrame}>
          <img src={mapUrl} alt="Market map" onError={() => setImgError(true)}
            style={{ width: '100%', height: '100%', display: 'block' }} />
        </div>

        {/* Competitor pins — teal, sized by reviews, ranked ones show the rank.
            Each links to its GBP; hovering shows a details card with the link. */}
        {pins.map((p, i) => {
          const pos = project(p.lat, p.lng)
          if (!pos.inView) return null
          const d = dotSize(p.reviews)
          const below = pos.topPct < 32          // flip the card down for top-row pins
          const isHover = hovered === i
          const popStyle: React.CSSProperties = { ...popover }
          if (below) { popStyle.top = '100%'; popStyle.paddingTop = 9 }
          else { popStyle.bottom = '100%'; popStyle.paddingBottom = 9 }
          return (
            <div key={i}
              onMouseEnter={() => setHovered(i)} onMouseLeave={() => setHovered(h => (h === i ? null : h))}
              style={{ ...pinBase, left: pos.left, top: pos.top, width: d, height: d, zIndex: isHover ? 30 : 6 }}>
              <a href={gbpUrl(p)} target="_blank" rel="noreferrer"
                style={{ ...dotLink, width: d, height: d, background: '#0e7d6f',
                  fontSize: 9, fontWeight: 700 }}>
                {p.rank != null ? p.rank : ''}
              </a>
              {isHover && (
                <div style={popStyle}>
                  <div style={popoverCard}>
                    <div style={{ fontWeight: 700, color: '#0f172a', marginBottom: 2 }}>
                      {p.name || 'Competitor'}
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 5 }}>
                      {p.rating != null && (
                        <span style={{ color: '#d97706', fontWeight: 600 }}>★ {p.rating}</span>
                      )}
                      {p.rating != null && ' · '}
                      {p.reviews} review{p.reviews === 1 ? '' : 's'}
                      {p.rank != null && ` · rank ${p.rank}`}
                      {p.miles != null && ` · ${p.miles} mi`}
                    </div>
                    <a href={gbpUrl(p)} target="_blank" rel="noreferrer" style={popoverLink}>
                      <ExternalLink size={11} /> View on Google
                    </a>
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {/* Suggested GBP placement zones — amber diamonds along weak bearings.
            Decorative: pointer-events off so a click falls through to the map.
            Hidden once the demand-aware advisor has run (zones replace them). */}
        {zones.length === 0 && placement.map((p, i) => {
          const pos = project(p.lat, p.lng)
          if (!pos.inView) return null
          return (
            <div key={`pl-${i}`}
              title={`Suggested zone: ${p.octant}${p.locality ? ` — near ${p.locality}` : ''}`}
              style={{ ...pinBase, left: pos.left, top: pos.top, width: 16, height: 16,
                background: '#f59e0b', color: '#fff', fontSize: 9, fontWeight: 700, zIndex: 2,
                borderRadius: 3, transform: 'translate(-50%, -50%) rotate(45deg)', pointerEvents: 'none' }}>
              <span style={{ transform: 'rotate(-45deg)' }}>{p.octant[0]}</span>
            </div>
          )
        })}

        {/* Demand-aware placement zones — numbered, top zone highlighted. The
            answer to "where should the GBP live" (placement plan §5.1). */}
        {zones.map((z, i) => {
          const pos = project(z.lat, z.lng)
          if (!pos.inView) return null
          return (
            <div key={`zone-${i}`}
              title={`Zone ${z.rank}: scores ${z.score}/100${z.locality ? ` — near ${z.locality}` : ''}`}
              style={{ ...pinBase, left: pos.left, top: pos.top, width: 22, height: 22,
                background: z.is_top ? '#7c3aed' : '#a78bfa', color: '#fff',
                fontSize: 11, fontWeight: 800, zIndex: z.is_top ? 8 : 7,
                border: '2px solid #fff', pointerEvents: 'none',
                boxShadow: '0 1px 5px rgba(15,23,42,.4)' }}>
              {z.rank}
            </div>
          )
        })}

        {/* Market centre (city) */}
        <div title="Market centre (city)"
          style={{ ...pinBase, left: '50%', top: '50%', width: 14, height: 14,
            background: '#fff', border: '2px solid #475569', zIndex: 3, pointerEvents: 'none' }}>
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#475569' }} />
        </div>

        {/* GBP reference pin */}
        {gbp && gbpPos?.inView && (
          <div title={`GBP: ${gbp.name ?? 'business'}`}
            style={{ ...pinBase, left: gbpPos.left, top: gbpPos.top, width: 22, height: 22,
              background: '#4f46e5', color: '#fff', zIndex: 5, border: '2px solid #fff', pointerEvents: 'none',
              boxShadow: '0 0 0 3px rgba(99,102,241,.35), 0 1px 4px rgba(0,0,0,.4)' }}>
            <MapPin size={12} />
          </div>
        )}
      </div>

      {/* Legend */}
      <div style={legend}>
        <LegendDot color="#0e7d6f" label="Competitor (size = reviews)" />
        <LegendDot color="#475569" label="Market centre" ring />
        {zones.length > 0 && <LegendDot color="#7c3aed" label="Placement zone (ranked)" />}
        {zones.length === 0 && placement.length > 0 && <LegendDot color="#f59e0b" label="Suggested zone" diamond />}
        {gbp && <LegendDot color="#4f46e5" label={gbp.name ? `GBP: ${gbp.name}` : 'Your GBP'} />}
      </div>

      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
        Hover a competitor pin for its rating and reviews, or click it to open that business's Google listing.
      </div>

      {/* A clearly-separate escape hatch to Google's FULL directory — labelled as
          its own thing, since it returns more businesses than the ranked field
          plotted above (which is why it's not the base-map click). */}
      {browseUrl && (
        <div style={{ marginTop: 6 }}>
          <a href={browseUrl} target="_blank" rel="noreferrer" style={browseLink}>
            <ExternalLink size={12} /> Browse all "{browse}" businesses on Google Maps
          </a>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
            Opens Google's full live directory for this area — more listings than the ranked competitors shown above.
          </div>
        </div>
      )}

      {gbp && gbpPos && !gbpPos.inView && (
        <p style={{ fontSize: 11, color: '#b45309', margin: '4px 0 0' }}>
          {gbp.name ?? 'The GBP'} is {gbpMiles.toFixed(1)} mi from the market centre — outside the map view.
        </p>
      )}
    </div>
  )
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

const mapOuter: React.CSSProperties = {
  position: 'relative', width: '100%', maxWidth: MAP_SIZE, aspectRatio: '1 / 1',
}
const mapFrame: React.CSSProperties = {
  position: 'absolute', inset: 0, display: 'block',
  borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden',
}
const pinBase: React.CSSProperties = {
  position: 'absolute', transform: 'translate(-50%, -50%)', borderRadius: '50%',
  display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1,
  boxSizing: 'border-box',
}
const dotLink: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff',
  borderRadius: '50%', boxSizing: 'border-box', textDecoration: 'none', cursor: 'pointer',
  boxShadow: '0 0 0 1px rgba(255,255,255,.7)',
}
// The hover card wrapper. bottom/top + padding are set inline so the transparent
// padding bridges the gap to the dot, keeping the card open while the pointer
// crosses into it (the card is a descendant of the pin's hover container).
const popover: React.CSSProperties = {
  position: 'absolute', left: '50%', transform: 'translateX(-50%)',
  zIndex: 30, pointerEvents: 'auto',
}
const popoverCard: React.CSSProperties = {
  width: 200, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8,
  padding: '8px 10px', boxShadow: '0 6px 20px rgba(15,23,42,.18)', textAlign: 'left',
  fontSize: 12,
}
const popoverLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600,
  color: '#0e7d6f', textDecoration: 'none',
}
const legend: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 8,
}
const browseLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600,
  color: '#475569', textDecoration: 'none',
}
