import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, MousePointerClick, Eye, BarChart3, Hash } from 'lucide-react'
import { api } from '../../lib/api'
import type { KeywordSummary, RankOverview as Overview } from '../../lib/types'
import { card } from '../localseo/shared'
import { STATUS_META, statusRank } from './status'
import { Sparkline } from './Sparkline'
import { PositionChart } from './PositionChart'
import { MetricsChart } from './MetricsChart'

export function RankOverview({ propertyId }: { propertyId: string }) {
  const { data: ov } = useQuery<Overview>({
    queryKey: ['rank-overview', propertyId],
    queryFn: () => api.get<Overview>(`/gsc-properties/${propertyId}/overview`),
  })
  const { data: keywords } = useQuery<KeywordSummary[]>({
    queryKey: ['rank-keywords', propertyId],
    queryFn: () => api.get<KeywordSummary[]>(`/gsc-properties/${propertyId}/keywords`),
  })

  const triage = useMemo(() => {
    return [...(keywords ?? [])]
      .sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.keyword.localeCompare(b.keyword))
      .slice(0, 8)
  }, [keywords])

  if (!ov) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading overview…</p>

  if (ov.keyword_count === 0) {
    return (
      <div style={{ ...card, color: '#64748b', fontSize: 14, lineHeight: 1.6 }}>
        No keywords tracked yet. Head to the <strong>Keywords</strong> tab to add the terms this
        client wants to rank for — the Overview lights up once they have data.
      </div>
    )
  }

  return (
    <div>
      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 20 }}>
        <Kpi icon={<Hash size={16} />} label="Keywords" value={ov.keyword_count.toLocaleString()} />
        <Kpi icon={<AlertTriangle size={16} />} label="At risk" value={ov.at_risk.toLocaleString()}
          emphasis={ov.at_risk > 0} />
        <Kpi icon={<BarChart3 size={16} />} label="Avg position 30d"
          value={ov.avg_position_30d != null ? ov.avg_position_30d.toFixed(1) : '—'} />
        <Kpi icon={<MousePointerClick size={16} />} label="Clicks 30d" value={ov.clicks_30d.toLocaleString()} />
        <Kpi icon={<Eye size={16} />} label="Impressions 30d" value={ov.impressions_30d.toLocaleString()} />
      </div>

      {/* Status rollup */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
        {(Object.keys(STATUS_META) as (keyof typeof STATUS_META)[])
          .filter(s => ov.status_counts[s])
          .sort((a, b) => statusRank(a) - statusRank(b))
          .map(s => (
            <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: STATUS_META[s].color, background: STATUS_META[s].bg, borderRadius: 999, padding: '4px 12px', fontWeight: 600 }}>
              {STATUS_META[s].label} · {ov.status_counts[s]}
            </span>
          ))}
      </div>

      {/* Hero: average position */}
      <div style={{ ...card, marginBottom: 16 }}>
        <h3 style={chartTitle}>Average position</h3>
        <p style={chartHint}>GSC impression-weighted average — improving rank trends upward (inverted axis).</p>
        <PositionChart points={ov.hero.map(h => ({ date: h.date, value: h.avg_position }))} />
      </div>

      {/* Clicks & impressions */}
      <div style={{ ...card, marginBottom: 20 }}>
        <h3 style={chartTitle}>Clicks &amp; impressions</h3>
        <MetricsChart points={ov.hero.map(h => ({ date: h.date, clicks: h.clicks, impressions: h.impressions }))} />
      </div>

      {/* Triage list */}
      <h3 style={{ ...chartTitle, marginBottom: 10 }}>Needs attention</h3>
      <div style={{ ...card, padding: 0 }}>
        {triage.map((k, i) => {
          const meta = STATUS_META[k.status]
          return (
            <div key={k.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
              <span style={{ flex: 1, fontWeight: 600, color: '#0f172a', fontSize: 13, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.keyword}</span>
              <Sparkline values={k.sparkline} color={meta.color} width={84} height={22} />
              <span style={{ fontSize: 12, color: '#64748b', width: 60, textAlign: 'right' }}>
                {k.avg_30 != null ? `30d ${k.avg_30.toFixed(1)}` : '—'}
              </span>
              <span style={{ color: meta.color, background: meta.bg, borderRadius: 999, padding: '2px 9px', fontSize: 11, fontWeight: 600, width: 78, textAlign: 'center' }}>
                {meta.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Kpi({ icon, label, value, emphasis }: { icon: React.ReactNode; label: string; value: string; emphasis?: boolean }) {
  return (
    <div style={{ ...card, padding: 14, borderColor: emphasis ? '#fecaca' : '#e2e8f0', background: emphasis ? '#fef2f2' : '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: emphasis ? '#b91c1c' : '#94a3b8', fontSize: 12, fontWeight: 600 }}>
        {icon} {label}
      </div>
      <div style={{ marginTop: 6, fontSize: 22, fontWeight: 700, color: emphasis ? '#b91c1c' : '#0f172a' }}>{value}</div>
    </div>
  )
}

const chartTitle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: '#0f172a', margin: 0, textTransform: 'uppercase', letterSpacing: '0.04em' }
const chartHint: React.CSSProperties = { fontSize: 12, color: '#94a3b8', margin: '4px 0 12px' }
