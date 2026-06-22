import { useMemo, useState } from 'react'

interface Pt { date: string; value: number | null }

// Average-position hero line. Inverted Y (position 1 at top) so improving rank
// trends UP. Gaps (null) render as visible breaks, not bridged lines.
export function PositionChart({ points, height = 220 }: { points: Pt[]; height?: number }) {
  const [hover, setHover] = useState<number | null>(null)
  const width = 720
  const padL = 34, padR = 12, padT = 12, padB = 22

  const { present, min, max } = useMemo(() => {
    const vals = points.map(p => p.value).filter((v): v is number => v != null)
    return { present: vals.length, min: Math.min(...vals), max: Math.max(...vals) }
  }, [points])

  if (present === 0) {
    return <div style={emptyStyle}>No position data in this range yet.</div>
  }

  // Pad the band a little so the line isn't flush against the edges.
  const lo = Math.max(1, Math.floor(min - 1))
  const hi = Math.ceil(max + 1)
  const span = hi - lo || 1
  const n = points.length
  const x = (i: number) => padL + (n > 1 ? (i / (n - 1)) * (width - padL - padR) : 0)
  // Inverted: position lo (best) near the top.
  const y = (v: number) => padT + ((v - lo) / span) * (height - padT - padB)

  const segments: string[] = []
  let cur: string[] = []
  points.forEach((p, i) => {
    if (p.value == null) {
      if (cur.length) segments.push(cur.join(' '))
      cur = []
    } else {
      cur.push(`${cur.length ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
    }
  })
  if (cur.length) segments.push(cur.join(' '))

  const ticks = [lo, Math.round((lo + hi) / 2), hi]
  const hp = hover != null ? points[hover] : null

  return (
    <div style={{ position: 'relative' }}>
      <svg
        width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none"
        style={{ display: 'block' }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const px = ((e.clientX - rect.left) / rect.width) * width
          const i = Math.round(((px - padL) / (width - padL - padR)) * (n - 1))
          setHover(Math.max(0, Math.min(n - 1, i)))
        }}
      >
        {ticks.map(t => (
          <g key={t}>
            <line x1={padL} y1={y(t)} x2={width - padR} y2={y(t)} stroke="#f1f5f9" strokeWidth={1} />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#94a3b8">{t}</text>
          </g>
        ))}
        {segments.map((d, i) => (
          <path key={i} d={d} fill="none" stroke="#6366f1" strokeWidth={2}
            strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hp && hp.value != null && (
          <>
            <line x1={x(hover!)} y1={padT} x2={x(hover!)} y2={height - padB} stroke="#cbd5e1" strokeWidth={1} />
            <circle cx={x(hover!)} cy={y(hp.value)} r={3} fill="#6366f1" />
          </>
        )}
        <text x={padL} y={height - 6} fontSize={10} fill="#94a3b8">{points[0]?.date}</text>
        <text x={width - padR} y={height - 6} textAnchor="end" fontSize={10} fill="#94a3b8">
          {points[n - 1]?.date}
        </text>
      </svg>
      {hp && (
        <div style={tipStyle}>
          <strong>{hp.date}</strong> · {hp.value != null ? `pos ${hp.value.toFixed(1)}` : 'no data'}
        </div>
      )}
    </div>
  )
}

const emptyStyle: React.CSSProperties = {
  height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#94a3b8', fontSize: 13, background: '#f8fafc', borderRadius: 8,
}
const tipStyle: React.CSSProperties = {
  position: 'absolute', top: 4, right: 8, fontSize: 11, color: '#475569',
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, padding: '2px 8px',
  pointerEvents: 'none',
}
