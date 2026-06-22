import { useMemo } from 'react'

interface Pt { date: string; clicks: number; impressions: number }

// Clicks (left axis, solid) & impressions (right axis, dashed) on separate
// scales so impressions don't flatten the clicks line. Color + dash both encode
// the series for accessibility (PRD §8.2).
export function MetricsChart({ points, height = 160 }: { points: Pt[]; height?: number }) {
  const width = 720
  const padL = 34, padR = 38, padT = 12, padB = 22

  const { maxC, maxI } = useMemo(() => ({
    maxC: Math.max(1, ...points.map(p => p.clicks)),
    maxI: Math.max(1, ...points.map(p => p.impressions)),
  }), [points])

  if (points.length === 0) {
    return <div style={emptyStyle}>No clicks/impressions in this range yet.</div>
  }

  const n = points.length
  const x = (i: number) => padL + (n > 1 ? (i / (n - 1)) * (width - padL - padR) : 0)
  const yC = (v: number) => padT + (1 - v / maxC) * (height - padT - padB)
  const yI = (v: number) => padT + (1 - v / maxI) * (height - padT - padB)

  const line = (sel: (p: Pt) => number, scale: (v: number) => number) =>
    points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${scale(sel(p)).toFixed(1)}`).join(' ')

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <text x={2} y={padT + 4} fontSize={10} fill="#6366f1">clicks</text>
      <text x={width - 2} y={padT + 4} textAnchor="end" fontSize={10} fill="#0ea5e9">impr.</text>
      <path d={line(p => p.clicks, yC)} fill="none" stroke="#6366f1" strokeWidth={2} strokeLinejoin="round" />
      <path d={line(p => p.impressions, yI)} fill="none" stroke="#0ea5e9" strokeWidth={1.5}
        strokeDasharray="4 3" strokeLinejoin="round" />
      <text x={padL} y={height - 6} fontSize={10} fill="#94a3b8">{points[0]?.date}</text>
      <text x={width - padR} y={height - 6} textAnchor="end" fontSize={10} fill="#94a3b8">{points[n - 1]?.date}</text>
    </svg>
  )
}

const emptyStyle: React.CSSProperties = {
  height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#94a3b8', fontSize: 13, background: '#f8fafc', borderRadius: 8,
}
