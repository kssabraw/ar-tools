import './animations.css'

// Health-score arc gauge for the AI Visibility dashboard. A 270° SVG arc that
// fills to `score` (0–100) on mount, colored by band. Ported in shape from the
// LABS HealthScoreGauge but using the suite's health palette (green/amber/red)
// instead of LABS' teal/amber/red. Sizes sm/md/lg.

type Size = 'sm' | 'md' | 'lg'

interface SizeConfig {
  dimension: number
  strokeWidth: number
  radius: number
  scoreFont: number
  labelFont: number
}

const SIZE_CONFIG: Record<Size, SizeConfig> = {
  sm: { dimension: 80,  strokeWidth: 6, radius: 33, scoreFont: 18, labelFont: 10 },
  md: { dimension: 112, strokeWidth: 7, radius: 46, scoreFont: 26, labelFont: 12 },
  lg: { dimension: 144, strokeWidth: 8, radius: 60, scoreFont: 32, labelFont: 14 },
}

// Suite health bands (match components/rankings + EngineStat coloring).
function scoreColor(score: number): string {
  if (score >= 70) return '#15803d' // healthy — green
  if (score >= 40) return '#b45309' // partial — amber
  return '#b91c1c'                  // invisible — red
}
function scoreLabel(score: number): string {
  if (score >= 70) return 'Healthy'
  if (score >= 40) return 'Partial'
  return 'Invisible'
}

const TRACK_COLOR = '#e2e8f0' // slate-200

export function HealthScoreGauge({ score, size = 'md' }: { score: number | null; size?: Size }) {
  const cfg = SIZE_CONFIG[size]
  const { dimension, strokeWidth, radius } = cfg
  const center = dimension / 2
  const circumference = 2 * Math.PI * radius
  const arcLength = circumference * 0.75 // 270° sweep
  const dashArray = `${arcLength} ${circumference}`

  const hasScore = score != null && !Number.isNaN(score)
  const clamped = hasScore ? Math.max(0, Math.min(100, score)) : 0
  const filled = arcLength * (clamped / 100)
  const offset = arcLength - filled
  const color = hasScore ? scoreColor(clamped) : '#94a3b8'

  // The 270° gap sits at the bottom: rotate so it opens downward.
  const rotation = 135

  return (
    <div style={{ position: 'relative', width: dimension, height: dimension }}>
      <svg
        width={dimension}
        height={dimension}
        style={{ transform: `rotate(${rotation}deg)` }}
        role="img"
        aria-label={hasScore ? `Health score: ${Math.round(clamped)}%` : 'Health score: no data'}
      >
        {/* Background track */}
        <circle
          cx={center} cy={center} r={radius}
          fill="none" stroke={TRACK_COLOR} strokeWidth={strokeWidth}
          strokeLinecap="round" strokeDasharray={dashArray}
        />
        {/* Filled arc */}
        {hasScore && (
          <circle
            cx={center} cy={center} r={radius}
            fill="none" stroke={color} strokeWidth={strokeWidth}
            strokeLinecap="round" strokeDasharray={dashArray}
            className="aiv-gauge-fill"
            style={{
              // custom props consumed by the aiv-gauge-fill keyframes
              '--aiv-gauge-circumference': `${arcLength}`,
              '--aiv-gauge-offset': `${offset}`,
              strokeDashoffset: offset,
              filter: `drop-shadow(0 0 4px ${color}80)`,
            } as React.CSSProperties}
          />
        )}
      </svg>
      {/* Center overlay */}
      <div
        style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}
      >
        <span style={{ fontSize: cfg.scoreFont, fontWeight: 700, color, lineHeight: 1 }}>
          {hasScore ? Math.round(clamped) : '—'}
        </span>
        <span style={{ fontSize: cfg.labelFont, fontWeight: 500, color: '#94a3b8', marginTop: 2 }}>
          {hasScore ? scoreLabel(clamped) : 'No data'}
        </span>
      </div>
    </div>
  )
}
