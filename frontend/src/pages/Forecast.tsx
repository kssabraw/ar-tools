import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowDownRight, ArrowUpRight, Minus, Sparkles, Target, TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client, ForecastResponse } from '../lib/types'

// Deterministic forecasting — where the campaign is heading and what winning
// is worth, computed on read from stored rank history + the market cache.
// Projections are linear trend extrapolations: direction & magnitude
// guidance, not promises (the caveat ships on every surface).

export function Forecast() {
  const { id } = useParams<{ id: string }>()
  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data, isLoading } = useQuery<ForecastResponse>({
    queryKey: ['forecast', id],
    queryFn: () => api.get<ForecastResponse>(`/clients/${id}/forecast`),
    enabled: Boolean(id),
    staleTime: 5 * 60_000,
  })

  const p = data?.portfolio
  const qw = data?.quick_wins
  const gsc = data?.gsc_clicks_trajectory

  return (
    <div style={{ padding: 32, maxWidth: 1000 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Forecast</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Where the campaign is heading at the current trend, and what winning is worth.
        Linear projections from tracked rank history — direction &amp; magnitude guidance, not promises.
      </p>

      {isLoading ? (
        <div style={emptyBox}>Computing…</div>
      ) : !data?.keyword_count ? (
        <div style={emptyBox}>
          No tracked keywords yet — the forecast builds from the rank tracker's history.
          Add keywords in Rankings first.
        </div>
      ) : (
        <>
          {/* ── Hero numbers ─────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10, marginBottom: 14 }}>
            <Hero
              label="Est. clicks / month from tracked keywords"
              now={p?.clicks_per_month_now}
              later={p?.clicks_per_month_90d}
              suffix=""
            />
            <Hero
              label="Est. traffic value / month"
              now={p?.value_per_month_now}
              later={p?.value_per_month_90d}
              prefix="$"
            />
            {gsc && (
              <Hero
                label="Site-wide GSC clicks (30d, actual)"
                now={gsc.clicks_last_30d}
                later={gsc.projected_90d_ahead}
                subtitle={`prev 30d: ${gsc.clicks_previous_30d.toLocaleString()}`}
              />
            )}
          </div>

          {/* ── Quick-win scenario ───────────────────────────────────── */}
          {qw && qw.keyword_count > 0 && (
            <section style={{ ...card, borderColor: '#c7d2fe', background: '#f8faff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Sparkles size={16} style={{ color: '#4f46e5' }} />
                <h2 style={{ ...cardTitle, margin: 0 }}>
                  Quick-win scenario — move {qw.keyword_count} striking-distance keyword{qw.keyword_count !== 1 ? 's' : ''} to top {qw.target_position}
                </h2>
              </div>
              <p style={{ fontSize: 13.5, color: '#334155', margin: '8px 0 10px' }}>
                Worth about <strong>+{qw.total_extra_clicks_per_month.toLocaleString()} clicks/mo</strong>
                {qw.total_extra_value_per_month > 0 && (
                  <> ≈ <strong>${qw.total_extra_value_per_month.toLocaleString()}/mo</strong> in equivalent ad spend</>
                )}
                . These are the keywords the Action Plan's quick wins target.
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {qw.keywords.slice(0, 10).map((k) => (
                  <span key={k.keyword} style={qwChip}>
                    {k.keyword} <span style={{ color: '#64748b' }}>#{k.current_position}</span>
                    {' '}→ +{k.extra_clicks_per_month}/mo{k.extra_value_per_month ? ` ($${k.extra_value_per_month})` : ''}
                  </span>
                ))}
              </div>
              {qw.skipped_no_volume > 0 && (
                <p style={{ fontSize: 11.5, color: '#94a3b8', margin: '8px 0 0' }}>
                  {qw.skipped_no_volume} striking-distance keyword{qw.skipped_no_volume !== 1 ? 's' : ''} skipped (no search-volume data cached yet).
                </p>
              )}
            </section>
          )}

          {/* ── Goal projections ─────────────────────────────────────── */}
          {(data.goal_projections?.length ?? 0) > 0 && (
            <section style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Target size={16} style={{ color: '#64748b' }} />
                <h2 style={{ ...cardTitle, margin: 0 }}>Goal trajectories</h2>
              </div>
              <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
                {data.goal_projections.map((g) => (
                  <div key={g.goal_label} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                    <span style={{
                      ...statusDot,
                      background: g.on_trajectory ? '#15803d' : '#b45309',
                    }} />
                    <span style={{ color: '#0f172a', fontWeight: 600 }}>{g.goal_label}</span>
                    <span style={{ color: '#64748b' }}>
                      at the current trend reaches ~{g.projected_value?.toLocaleString()} in {g.horizon_days} days
                      (target {g.target_value?.toLocaleString()}) — {g.on_trajectory ? 'on trajectory' : 'off trajectory without intervention'}
                      {' '}· {g.confidence} confidence
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── Per-keyword table ────────────────────────────────────── */}
          <section style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <TrendingUp size={16} style={{ color: '#64748b' }} />
              <h2 style={{ ...cardTitle, margin: 0 }}>Keyword trajectories</h2>
            </div>
            <div style={{ overflowX: 'auto', marginTop: 10 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr>
                    {['Keyword', 'Now', 'Trend/wk', '30d', '90d', 'Clicks/mo', 'In 90d', 'Value/mo', 'Confidence'].map((h) => (
                      <th key={h} style={th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.keywords.map((f) => (
                    <tr key={f.keyword} style={{ borderTop: '1px solid #f1f5f9' }}>
                      <td style={{ ...td, fontWeight: 600, color: '#0f172a' }}>{f.keyword}</td>
                      <td style={td}>{f.current_position ?? '—'}</td>
                      <td style={td}><TrendArrow value={f.trend_per_week} /></td>
                      <td style={td}>{f.projected_position_30d ?? '—'}</td>
                      <td style={td}>{f.projected_position_90d ?? '—'}</td>
                      <td style={td}>
                        {f.clicks_per_month_now != null ? f.clicks_per_month_now.toLocaleString() : '—'}
                        {f.clicks_source === 'ctr_model' && f.clicks_per_month_now != null && <span title="Modelled: volume × CTR curve" style={{ color: '#94a3b8' }}> est</span>}
                      </td>
                      <td style={td}>{f.clicks_per_month_90d != null ? f.clicks_per_month_90d.toLocaleString() : '—'}</td>
                      <td style={td}>{f.value_per_month_now != null ? `$${f.value_per_month_now.toLocaleString()}` : '—'}</td>
                      <td style={td}><span style={confChip(f.confidence)}>{f.confidence}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ fontSize: 11.5, color: '#94a3b8', margin: '10px 0 0' }}>
              "Clicks/mo" uses actual Search Console clicks where available; "est" rows are
              volume × a standard CTR curve. Trend/wk in positions (negative = improving).
            </p>
          </section>
        </>
      )}
    </div>
  )
}

function Hero({ label, now, later, prefix = '', suffix = '', subtitle }: {
  label: string; now?: number | null; later?: number | null; prefix?: string; suffix?: string; subtitle?: string
}) {
  if (now == null) return null
  const delta = later != null ? later - now : null
  return (
    <div style={card}>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: '#0f172a', marginTop: 4 }}>
        {prefix}{now.toLocaleString()}{suffix}
      </div>
      {later != null && (
        <div style={{ fontSize: 12.5, color: delta && delta > 0 ? '#15803d' : delta && delta < 0 ? '#b45309' : '#64748b', marginTop: 2 }}>
          → {prefix}{later.toLocaleString()}{suffix} in ~90 days at the current trend
        </div>
      )}
      {subtitle && <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 2 }}>{subtitle}</div>}
    </div>
  )
}

function TrendArrow({ value }: { value: number | null }) {
  if (value == null) return <Minus size={13} style={{ color: '#cbd5e1' }} />
  if (value < -0.05) return <span style={{ color: '#15803d', display: 'inline-flex', alignItems: 'center', gap: 2 }}><ArrowUpRight size={13} />{Math.abs(value)}</span>
  if (value > 0.05) return <span style={{ color: '#b91c1c', display: 'inline-flex', alignItems: 'center', gap: 2 }}><ArrowDownRight size={13} />{value}</span>
  return <span style={{ color: '#64748b' }}>flat</span>
}

const confChip = (c: string): React.CSSProperties => ({
  fontSize: 10.5, fontWeight: 700, padding: '2px 7px', borderRadius: 999, textTransform: 'uppercase',
  color: c === 'high' ? '#15803d' : c === 'medium' ? '#0369a1' : '#94a3b8',
  background: c === 'high' ? '#f0fdf4' : c === 'medium' ? '#f0f9ff' : '#f8fafc',
})

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b',
  textDecoration: 'none', marginBottom: 14,
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff', marginBottom: 10 }
const cardTitle: React.CSSProperties = { fontSize: 14, fontWeight: 600, color: '#0f172a' }
const th: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3 }
const td: React.CSSProperties = { padding: '7px 8px', color: '#334155', whiteSpace: 'nowrap' }
const qwChip: React.CSSProperties = {
  fontSize: 12, color: '#3730a3', background: '#eef2ff', border: '1px solid #e0e7ff',
  padding: '4px 10px', borderRadius: 999,
}
const statusDot: React.CSSProperties = { width: 8, height: 8, borderRadius: 999, flexShrink: 0 }
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
