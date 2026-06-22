import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Printer, TrendingUp, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, GeneratedReport, KeywordSummary, RankLocation, RankOverview as Overview } from '../lib/types'
import { STATUS_META, statusRank } from '../components/rankings/status'
import { Sparkline } from '../components/rankings/Sparkline'
import { PositionChart } from '../components/rankings/PositionChart'
import { MetricsChart } from '../components/rankings/MetricsChart'

// Printable, client-facing organic-rankings report. Uses the data the tracker
// already serves; "Print / Save as PDF" uses the browser print dialog. A scoped
// print stylesheet isolates the report from the app chrome.
const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })

export function RankReport() {
  const { id, reportId } = useParams<{ id: string; reportId?: string }>()
  const clientId = id as string
  const archived = Boolean(reportId)

  // Archived report: render the stored snapshot. Live report: pull current data.
  const { data: archivedReport } = useQuery<GeneratedReport>({
    queryKey: ['rank-report', reportId],
    queryFn: () => api.get<GeneratedReport>(`/rank-reports/${reportId}`),
    enabled: archived,
  })
  const { data: clientLive } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: !archived,
  })
  const { data: ovLive } = useQuery<Overview>({
    queryKey: ['rank-overview', clientId],
    queryFn: () => api.get<Overview>(`/clients/${clientId}/rank/overview`),
    enabled: !archived,
  })
  const { data: keywordsLive } = useQuery<KeywordSummary[]>({
    queryKey: ['rank-keywords', clientId],
    queryFn: () => api.get<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`),
    enabled: !archived,
  })
  const { data: locLive } = useQuery<RankLocation>({
    queryKey: ['rank-location', clientId],
    queryFn: () => api.get<RankLocation>(`/clients/${clientId}/rank/location`),
    enabled: !archived,
  })

  const snap = archivedReport?.snapshot
  const client = archived
    ? { name: snap?.client.name ?? null, logo_url: snap?.client.logo_url ?? null }
    : { name: clientLive?.name ?? null, logo_url: clientLive?.logo_url ?? null }
  const ov: Overview | undefined = archived ? snap?.overview : ovLive
  const kws = (archived ? snap?.keywords : keywordsLive) ?? []
  const locationName = archived ? (snap?.location ?? null) : (locLive?.location ?? null)
  const gsc = (archived ? snap?.gsc_connected : ovLive?.gsc_connected) ?? false
  const today = archived ? fmtDate(new Date(archivedReport?.created_at ?? Date.now())) : fmtDate(new Date())

  const movement = (k: KeywordSummary) =>
    k.avg_90 != null && k.avg_7 != null ? k.avg_90 - k.avg_7 : 0 // positive = improved

  const improving = [...kws]
    .filter(k => k.direction === 'up' || k.status === 'climbing')
    .sort((a, b) => movement(b) - movement(a))
    .slice(0, 6)
  const declining = [...kws]
    .filter(k => k.status === 'dropping' || k.status === 'deindex_risk' || k.direction === 'down')
    .sort((a, b) => statusRank(a.status) - statusRank(b.status))
    .slice(0, 6)
  const byValue = [...kws]
    .filter(k => k.est_monthly_value != null)
    .sort((a, b) => (b.est_monthly_value ?? 0) - (a.est_monthly_value ?? 0))
    .slice(0, 10)
  const totalValue = kws.reduce((s, k) => s + (k.est_monthly_value ?? 0), 0)
  const sortedAll = [...kws].sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.keyword.localeCompare(b.keyword))

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <style>{PRINT_CSS}</style>

      {/* Controls (hidden in print) */}
      <div className="no-print" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Link to={`/clients/${clientId}/rankings`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }}>
          <ArrowLeft size={14} /> Back to tracker
        </Link>
        <button onClick={() => window.print()}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '10px 16px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
          <Printer size={15} /> Print / Save as PDF
        </button>
      </div>

      <div id="rank-report">
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, borderBottom: '2px solid #6366f1', paddingBottom: 16, marginBottom: 22 }}>
          {client.logo_url && (
            <img src={client.logo_url} alt="" style={{ width: 48, height: 48, borderRadius: 10, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0' }} />
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a' }}>{client.name ?? 'Client'}</div>
            <div style={{ fontSize: 14, color: '#6366f1', fontWeight: 600 }}>Organic Rankings Report</div>
          </div>
          <div style={{ textAlign: 'right', fontSize: 12, color: '#64748b' }}>
            <div>{today}</div>
            <div>{gsc ? 'Search Console + DataForSEO' : 'DataForSEO'}{locationName ? ` · ${locationName}` : ''}</div>
          </div>
        </div>

        {/* KPI summary */}
        <SectionTitle>Summary</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10, marginBottom: 8 }}>
          <Kpi label="Keywords" value={(ov?.keyword_count ?? 0).toLocaleString()} />
          <Kpi label="At risk" value={(ov?.at_risk ?? 0).toLocaleString()} alert={(ov?.at_risk ?? 0) > 0} />
          {gsc && <Kpi label="Avg position (30d)" value={ov?.avg_position_30d != null ? ov.avg_position_30d.toFixed(1) : '—'} />}
          {gsc && <Kpi label="Clicks (30d)" value={(ov?.clicks_30d ?? 0).toLocaleString()} />}
          {gsc && <Kpi label="Impressions (30d)" value={(ov?.impressions_30d ?? 0).toLocaleString()} />}
          <Kpi label="Est. monthly value" value={`$${Math.round(totalValue).toLocaleString()}`} accent />
        </div>

        {/* Status rollup */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
          {(Object.keys(STATUS_META) as (keyof typeof STATUS_META)[])
            .filter(s => ov?.status_counts[s])
            .sort((a, b) => statusRank(a) - statusRank(b))
            .map(s => (
              <span key={s} style={{ fontSize: 12, color: STATUS_META[s].color, background: STATUS_META[s].bg, borderRadius: 999, padding: '3px 11px', fontWeight: 600 }}>
                {STATUS_META[s].label} · {ov?.status_counts[s]}
              </span>
            ))}
        </div>

        {/* Trend charts (GSC only) */}
        {gsc && ov && (
          <div className="avoid-break" style={{ marginBottom: 22 }}>
            <SectionTitle>Average position</SectionTitle>
            <PositionChart points={ov.hero.map(h => ({ date: h.date, value: h.avg_position }))} height={180} />
            <div style={{ height: 12 }} />
            <SectionTitle>Clicks &amp; impressions</SectionTitle>
            <MetricsChart points={ov.hero.map(h => ({ date: h.date, clicks: h.clicks, impressions: h.impressions }))} height={140} />
          </div>
        )}

        {/* Highlights */}
        <div className="avoid-break" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 22 }}>
          <Movers title="Improving" icon={<TrendingUp size={14} color="#15803d" />} rows={improving} empty="No clear gainers this period." />
          <Movers title="Needs attention" icon={<AlertTriangle size={14} color="#b91c1c" />} rows={declining} empty="Nothing flagged — all holding." />
        </div>

        {/* Top by estimated value */}
        {byValue.length > 0 && (
          <div className="avoid-break" style={{ marginBottom: 22 }}>
            <SectionTitle>Top opportunities by estimated monthly value</SectionTitle>
            <table style={tableStyle}>
              <thead><tr><Th left>Keyword</Th><Th>Best position</Th><Th>Volume</Th><Th>CPC</Th><Th>Est. value</Th></tr></thead>
              <tbody>
                {byValue.map(k => (
                  <tr key={k.id} style={trStyle}>
                    <Td left>{k.keyword}</Td>
                    <Td>{bestPos(k)}</Td>
                    <Td>{k.search_volume != null ? k.search_volume.toLocaleString() : '—'}</Td>
                    <Td>{k.cpc != null ? `$${k.cpc.toFixed(2)}` : '—'}</Td>
                    <Td><strong style={{ color: '#15803d' }}>${Math.round(k.est_monthly_value ?? 0).toLocaleString()}</strong></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Full tracked keywords */}
        <SectionTitle>All tracked keywords</SectionTitle>
        <table style={tableStyle}>
          <thead><tr>
            <Th left>Keyword</Th><Th>Status</Th><Th>Trend</Th><Th>Today</Th>
            {gsc && <><Th>30d</Th><Th>90d</Th><Th>Clicks</Th></>}
          </tr></thead>
          <tbody>
            {sortedAll.map(k => {
              const meta = STATUS_META[k.status]
              return (
                <tr key={k.id} style={trStyle}>
                  <Td left>{k.keyword}</Td>
                  <Td><span style={{ color: meta.color, background: meta.bg, borderRadius: 999, padding: '1px 8px', fontSize: 11, fontWeight: 600 }}>{meta.label}</span></Td>
                  <Td><Sparkline values={k.sparkline} color={meta.color} width={72} height={20} /></Td>
                  <Td>{k.today_rank ?? '—'}</Td>
                  {gsc && <><Td>{k.avg_30 != null ? k.avg_30.toFixed(1) : '—'}</Td>
                    <Td>{k.avg_90 != null ? k.avg_90.toFixed(1) : '—'}</Td>
                    <Td>{k.clicks_30d.toLocaleString()}</Td></>}
                </tr>
              )
            })}
          </tbody>
        </table>

        <div style={{ marginTop: 24, paddingTop: 12, borderTop: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8', textAlign: 'center' }}>
          Generated by AR Tools · {today}{gsc ? '' : ' · Ranks from DataForSEO live SERP checks'}
        </div>
      </div>
    </div>
  )
}

function bestPos(k: KeywordSummary): string {
  const p = k.primary_source === 'dataforseo' ? k.today_rank : k.avg_30
  return p != null ? (typeof p === 'number' ? p.toFixed(p % 1 === 0 ? 0 : 1) : `${p}`) : '—'
}

function Movers({ title, icon, rows, empty }: { title: string; icon: React.ReactNode; rows: KeywordSummary[]; empty: string }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>{icon} {title}</div>
      {rows.length === 0 ? <div style={{ fontSize: 12, color: '#94a3b8' }}>{empty}</div> : rows.map((k, i) => {
        const meta = STATUS_META[k.status]
        return (
          <div key={k.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
            <span style={{ flex: 1, fontSize: 12, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.keyword}</span>
            <Sparkline values={k.sparkline} color={meta.color} width={64} height={18} />
            <span style={{ fontSize: 11, color: meta.color, fontWeight: 600, width: 64, textAlign: 'right' }}>{meta.label}</span>
          </div>
        )
      })}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>{children}</h3>
}
function Kpi({ label, value, alert, accent }: { label: string; value: string; alert?: boolean; accent?: boolean }) {
  return (
    <div style={{ border: `1px solid ${alert ? '#fecaca' : '#e2e8f0'}`, background: alert ? '#fef2f2' : '#fff', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 11, color: alert ? '#b91c1c' : '#94a3b8', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700, color: accent ? '#15803d' : alert ? '#b91c1c' : '#0f172a' }}>{value}</div>
    </div>
  )
}
function Th({ children, left }: { children?: React.ReactNode; left?: boolean }) {
  return <th style={{ padding: '6px 8px', textAlign: left ? 'left' : 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', borderBottom: '1px solid #e2e8f0' }}>{children}</th>
}
function Td({ children, left }: { children?: React.ReactNode; left?: boolean }) {
  return <td style={{ padding: '6px 8px', textAlign: left ? 'left' : 'right', fontSize: 12, color: '#334155' }}>{children}</td>
}

const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse' }
const trStyle: React.CSSProperties = { borderBottom: '1px solid #f1f5f9' }

const PRINT_CSS = `
@media print {
  body * { visibility: hidden !important; }
  #rank-report, #rank-report * { visibility: visible !important; }
  #rank-report { position: absolute; left: 0; top: 0; width: 100%; }
  .no-print { display: none !important; }
  .avoid-break { break-inside: avoid; }
  @page { margin: 14mm; }
}
`
