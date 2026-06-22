// Tiny inverted rank sparkline. Lower position = higher on the chart (rank 1 on
// top), matching GSC. Renders gaps: stretches of null are NOT connected
// (spanGaps:false), so a disappearance reads as a break, not a gradual slip.
export function Sparkline({
  values, color, width = 96, height = 24,
}: {
  values: (number | null)[]
  color: string
  width?: number
  height?: number
}) {
  const present = values.filter((v): v is number => v != null)
  if (present.length === 0) {
    return (
      <svg width={width} height={height} role="img" aria-label="no data">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2}
          stroke="#e2e8f0" strokeDasharray="2 3" strokeWidth={1} />
      </svg>
    )
  }

  const min = Math.min(...present)
  const max = Math.max(...present)
  const span = max - min || 1
  const n = values.length
  const dx = n > 1 ? width / (n - 1) : 0
  const pad = 2

  // Inverted Y: smaller position → smaller y (top).
  const y = (v: number) => pad + ((v - min) / span) * (height - pad * 2)
  const x = (i: number) => i * dx

  // Build segments split on nulls so gaps aren't bridged.
  const segments: string[] = []
  let cur: string[] = []
  values.forEach((v, i) => {
    if (v == null) {
      if (cur.length) segments.push(cur.join(' '))
      cur = []
    } else {
      cur.push(`${cur.length ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
    }
  })
  if (cur.length) segments.push(cur.join(' '))

  const last = values[n - 1]
  return (
    <svg width={width} height={height} role="img" aria-label="rank trend">
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke={color} strokeWidth={1.5}
          strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {last != null && (
        <circle cx={x(n - 1)} cy={y(last)} r={2} fill={color} />
      )}
    </svg>
  )
}
