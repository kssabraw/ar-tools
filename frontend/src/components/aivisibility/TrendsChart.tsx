import { useId, useState } from 'react'

// Generic multi-series area chart for the AI Visibility trends (LABS'
// Recharts AreaChart re-created in the suite's dependency-free SVG style —
// same conventions as components/rankings/PositionChart: fixed viewBox,
// preserveAspectRatio none, gap-aware segments, hover guide + tooltip).
// Series are toggleable via the legend (color swatch + optional icon).

export interface ChartSeries {
  key: string
  label: string
  color: string
  points: (number | null)[]   // aligned to `labels`; null = gap
  icon?: React.ReactNode      // legend icon (e.g. EngineIcon)
  suffix?: string             // legend suffix (e.g. "(You)")
  emphasize?: boolean         // thicker stroke (the brand line)
}

export function TrendsChart({ labels, series, height = 240 }: {
  labels: string[]
  series: ChartSeries[]
  height?: number
}) {
  const gradPrefix = useId().replace(/[^a-zA-Z0-9]/g, '')
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hover, setHover] = useState<number | null>(null)

  const width = 720
  const padL = 38, padR = 12, padT = 12, padB = 22
  const n = labels.length
  const x = (i: number) => padL + (n > 1 ? (i / (n - 1)) * (width - padL - padR) : 0)
  const y = (v: number) => padT + (1 - Math.max(0, Math.min(100, v)) / 100) * (height - padT - padB)
  const baseline = y(0)

  const visible = series.filter(s => !hidden.has(s.key))
  // Gradient ids must be CSS-identifier-safe — series keys can contain spaces
  // (competitor names), so key the defs on the series' index instead.
  const gradId = (s: ChartSeries) => `${gradPrefix}-s${series.indexOf(s)}`

  // Gap-aware contiguous segments: [{ startIdx, pts: [i, v][] }]
  const segmentsOf = (pts: (number | null)[]) => {
    const segs: { i: number; v: number }[][] = []
    let cur: { i: number; v: number }[] = []
    pts.forEach((v, i) => {
      if (v == null) { if (cur.length) segs.push(cur); cur = [] }
      else cur.push({ i, v })
    })
    if (cur.length) segs.push(cur)
    return segs
  }
  const linePath = (seg: { i: number; v: number }[]) =>
    seg.map((p, k) => `${k ? 'L' : 'M'}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const areaPath = (seg: { i: number; v: number }[]) =>
    `${linePath(seg)} L${x(seg[seg.length - 1].i).toFixed(1)},${baseline.toFixed(1)} L${x(seg[0].i).toFixed(1)},${baseline.toFixed(1)} Z`

  const toggle = (key: string) => {
    setHidden(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const ticks = [0, 25, 50, 75, 100]
  // ~5 x labels, always incl. first + last
  const xLabelIdx = new Set<number>()
  if (n > 0) {
    const step = Math.max(1, Math.ceil((n - 1) / 4))
    for (let i = 0; i < n; i += step) xLabelIdx.add(i)
    xLabelIdx.add(n - 1)
  }

  const hoverRows = hover == null ? [] : visible
    .map(s => ({ s, v: s.points[hover] }))
    .filter((r): r is { s: ChartSeries; v: number } => r.v != null)

  return (
    <div>
      <div style={{ position: 'relative' }}>
        {n < 2 ? (
          <div style={emptyStyle}>Not enough scans in this range — run more scans to see the trend.</div>
        ) : (
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
            <defs>
              {visible.map(s => (
                <linearGradient key={s.key} id={gradId(s)} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={s.color} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={s.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            {ticks.map(t => (
              <g key={t}>
                <line x1={padL} y1={y(t)} x2={width - padR} y2={y(t)} stroke="#f1f5f9" strokeWidth={1} strokeDasharray={t === 0 ? undefined : '3 3'} />
                <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="#94a3b8">{t}%</text>
              </g>
            ))}
            {visible.map(s => segmentsOf(s.points).map((seg, k) => (
              <g key={`${s.key}-${k}`}>
                {seg.length > 1 && <path d={areaPath(seg)} fill={`url(#${gradId(s)})`} stroke="none" />}
                <path d={linePath(seg)} fill="none" stroke={s.color} strokeWidth={s.emphasize ? 3 : 2}
                  strokeLinejoin="round" strokeLinecap="round" />
                {seg.length === 1 && <circle cx={x(seg[0].i)} cy={y(seg[0].v)} r={2.5} fill={s.color} />}
              </g>
            )))}
            {hover != null && (
              <>
                <line x1={x(hover)} y1={padT} x2={x(hover)} y2={height - padB} stroke="#cbd5e1" strokeWidth={1} />
                {hoverRows.map(({ s, v }) => (
                  <circle key={s.key} cx={x(hover)} cy={y(v)} r={3.5} fill={s.color} stroke="#fff" strokeWidth={1} />
                ))}
              </>
            )}
            {[...xLabelIdx].map(i => (
              <text
                key={i} x={x(i)} y={height - 6} fontSize={10} fill="#94a3b8"
                textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
              >
                {labels[i]}
              </text>
            ))}
          </svg>
        )}
        {hover != null && hoverRows.length > 0 && (
          <div style={tipStyle}>
            <div style={{ fontWeight: 700, color: '#0f172a', marginBottom: 4 }}>{labels[hover]}</div>
            {hoverRows.map(({ s, v }) => (
              <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <span style={{ width: 8, height: 8, borderRadius: 999, background: s.color, flexShrink: 0 }} />
                <span style={{ color: '#475569', flex: 1 }}>{s.label}</span>
                <span style={{ fontWeight: 700, color: s.color }}>{v}%</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Interactive legend — toggle series on/off */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
        {series.map(s => {
          const off = hidden.has(s.key)
          return (
            <button
              key={s.key}
              onClick={() => toggle(s.key)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 10px',
                background: '#fff', border: '1px solid', borderColor: off ? '#e2e8f0' : s.color,
                borderRadius: 999, fontSize: 12, fontWeight: 600, color: '#334155',
                cursor: 'pointer', opacity: off ? 0.45 : 1,
              }}
              title={off ? `Show ${s.label}` : `Hide ${s.label}`}
            >
              <span style={{ width: 9, height: 9, borderRadius: 999, background: s.color }} />
              {s.icon}
              {s.label}
              {s.suffix && <span style={{ color: '#94a3b8', fontWeight: 400 }}>{s.suffix}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

const emptyStyle: React.CSSProperties = {
  height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#94a3b8', fontSize: 13, background: '#f8fafc', borderRadius: 8,
}
const tipStyle: React.CSSProperties = {
  position: 'absolute', top: 6, right: 8, fontSize: 11, minWidth: 150,
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px',
  pointerEvents: 'none', boxShadow: '0 4px 14px rgba(15,23,42,0.08)', zIndex: 5,
}
