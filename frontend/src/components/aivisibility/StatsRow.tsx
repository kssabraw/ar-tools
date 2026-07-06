import { Eye, TrendingUp, Search, BarChart3 } from 'lucide-react'
import { HealthScoreGauge } from './HealthScoreGauge'
import { ENGINE_ORDER, ENGINES, EngineIcon } from './engines'
import './animations.css'

// LABS-style dashboard stats row: Global Health Score (arc gauge), Visibility
// Share, Keywords Tracked, Engines Monitored. The engines card keeps AR Tools'
// per-engine visibility % under each logo (info the old EngineStat strip
// carried — LABS shows logos only).

function pctColor(pct: number | null): string {
  if (pct == null) return '#94a3b8'
  if (pct >= 60) return '#15803d'
  if (pct >= 25) return '#b45309'
  return '#b91c1c'
}

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16,
  display: 'flex', flexDirection: 'column', minWidth: 0,
}

function CardHeader({ title, icon }: { title: string; icon: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>{title}</span>
      <span style={{ color: '#94a3b8', display: 'inline-flex' }}>{icon}</span>
    </div>
  )
}

export function StatsRow(props: {
  healthScore: number | null
  visibilityPct: number | null
  scansCount: number            // completed cells in the latest scan
  activeKeywordCount: number
  enginePcts: Record<string, number | null>  // latest per-engine visibility %
  onKeywordsClick: () => void
}) {
  const { healthScore, visibilityPct, scansCount, activeKeywordCount, enginePcts, onKeywordsClick } = props
  return (
    <div
      style={{
        display: 'grid', gap: 14, marginBottom: 22,
        gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
      }}
    >
      <div className="aiv-card-enter aiv-stagger-1" style={cardStyle}>
        <CardHeader title="Global Health Score" icon={<Eye size={15} />} />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <HealthScoreGauge score={healthScore} size="md" />
        </div>
      </div>

      <div className="aiv-card-enter aiv-stagger-2" style={cardStyle}>
        <CardHeader title="Visibility Share" icon={<TrendingUp size={15} />} />
        <div style={{ fontSize: 26, fontWeight: 700, color: pctColor(visibilityPct) }}>
          {visibilityPct == null ? '—' : `${visibilityPct}%`}
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
          {visibilityPct == null
            ? 'Run a scan to measure visibility'
            : `Based on ${scansCount} scanned answer${scansCount === 1 ? '' : 's'}`}
        </div>
      </div>

      <div
        className="aiv-card-enter aiv-stagger-3"
        style={{ ...cardStyle, cursor: 'pointer' }}
        onClick={onKeywordsClick}
        title="Manage keywords"
      >
        <CardHeader title="Keywords Tracked" icon={<Search size={15} />} />
        <div style={{ fontSize: 26, fontWeight: 700, color: '#0f172a' }}>{activeKeywordCount}</div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>Active search queries</div>
      </div>

      <div className="aiv-card-enter aiv-stagger-4" style={cardStyle}>
        <CardHeader title="Engines Monitored" icon={<BarChart3 size={15} />} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px 10px' }}>
          {ENGINE_ORDER.map(key => {
            const pct = enginePcts[key] ?? null
            return (
              <div key={key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                <EngineIcon engine={key} size={22} />
                <span style={{ fontSize: 10, color: '#94a3b8', whiteSpace: 'nowrap' }}>{ENGINES[key].label}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: pctColor(pct) }}>
                  {pct == null ? '—' : `${pct}%`}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
