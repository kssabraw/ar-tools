import { useEffect } from 'react'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Printer, MapPin } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, MapsScanDetail, MapsScanResultRow, MapsTrendsResponse } from '../lib/types'
import { GeoGridMap, TrendChart } from '../components/maps/visuals'
import { Markdown } from '../components/Markdown'
import { TREND_METRICS, rankColor } from '../components/maps/rank'

// Printable, client-facing Maps geo-grid report: branded header, coverage KPIs,
// Top-3 %/Top-10 % trend over time, and a per-keyword heatmap. Uses the data the
// module already serves; "Print / Save as PDF" uses the browser print dialog,
// with a scoped print stylesheet isolating the report from the app chrome.
const fmtDate = (d: Date) => d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
const kpct = (n: number, d: number): number | null => (d ? Math.round((n / d) * 100) : null)
const fmtPct = (v: number | null) => (v == null ? '—' : `${v}%`)

export function MapsReport() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  // Optional per-keyword focus + auto-print, driven by the "Download report"
  // button on a single keyword's analysis (opens this page filtered + printing).
  const [params] = useSearchParams()
  const focusKeyword = params.get('keyword')
  const autoPrint = params.get('print') === '1'
  const scanId = params.get('scan_id')  // a specific past scan, else the latest

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
  })
  const { data: latest, error } = useQuery<MapsScanDetail>({
    queryKey: scanId ? ['maps-scan', scanId] : ['maps-latest', clientId],
    queryFn: () => scanId
      ? api.get<MapsScanDetail>(`/maps-scans/${scanId}`)
      : api.get<MapsScanDetail>(`/clients/${clientId}/maps/latest`),
    retry: false,
  })
  const { data: trends } = useQuery<MapsTrendsResponse>({
    queryKey: ['maps-trends', clientId],
    queryFn: () => api.get<MapsTrendsResponse>(`/clients/${clientId}/maps/trends`),
  })

  const allResults: MapsScanResultRow[] = latest?.results ?? []
  // When focused on one keyword, the whole report (KPIs, competitors, detail)
  // narrows to that keyword so the PDF is a single-keyword deliverable.
  const results = focusKeyword ? allResults.filter(r => r.keyword === focusKeyword) : allResults

  // Auto-open the print dialog once the focused report has rendered.
  useEffect(() => {
    if (!autoPrint || !latest || results.length === 0) return
    const t = setTimeout(() => window.print(), 700)
    return () => clearTimeout(t)
  }, [autoPrint, latest, results.length])

  const withPins = results.filter(r => r.total_pins > 0)
  const meanPct = (sel: (r: MapsScanResultRow) => number) =>
    withPins.length ? Math.round(withPins.reduce((s, r) => s + (sel(r) / r.total_pins) * 100, 0) / withPins.length) : null
  const avgTop3 = meanPct(r => r.top3_pins)
  const avgTop10 = meanPct(r => r.top10_pins)
  const avgFound = meanPct(r => r.found_pins)
  const ranks = results.map(r => r.average_rank).filter((v): v is number => v != null)
  const avgRank = ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : null

  // Who outranks the client, and how often: tally — across every keyword's
  // per-pin "above us" list — the in-circle pins where each business beats us.
  const dir: Record<string, { name: string | null; rating: number | null; reviews: number | null }> = {}
  const beat = new Map<string, { pins: number; rankSum: number }>()
  let totalSlots = 0
  for (const r of results) {
    const ca = r.competitors_above
    if (!ca) continue
    Object.assign(dir, ca.directory)
    for (const row of ca.grid) {
      for (const cell of row) {
        if (cell == null) continue   // out-of-circle pin
        totalSlots += 1
        for (const [pid, rank] of cell) {
          const e = beat.get(pid) || { pins: 0, rankSum: 0 }
          e.pins += 1; e.rankSum += rank
          beat.set(pid, e)
        }
      }
    }
  }
  const slotPct = (n: number) => (totalSlots ? Math.round((n / totalSlots) * 100) : 0)
  const topCompetitors = [...beat.entries()]
    .map(([pid, e]) => ({
      pid, name: dir[pid]?.name ?? null, rating: dir[pid]?.rating ?? null, reviews: dir[pid]?.reviews ?? null,
      pins: e.pins, avgRank: e.pins ? e.rankSum / e.pins : null,
    }))
    .sort((a, b) => b.pins - a.pins)
    .slice(0, 10)

  const hasTrend = (trends?.keywords ?? []).some(k => k.points.length > 1)
  const source = latest?.resource_category === 'googleLocalFinder' ? 'Local Finder' : 'Google Maps'

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <style>{PRINT_CSS}</style>

      {/* Controls (hidden in print) */}
      <div className="no-print" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Link to={`/clients/${clientId}/maps`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }}>
          <ArrowLeft size={14} /> Back to Maps ranker
        </Link>
        <button onClick={() => window.print()}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '10px 16px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
          <Printer size={15} /> Print / Save as PDF
        </button>
      </div>

      {error || !latest ? (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, color: '#64748b', fontSize: 14 }}>
          No completed scans yet — run a scan in the Maps ranker first, then come back to generate the report.
        </div>
      ) : (
        <div id="maps-report">
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, borderBottom: '2px solid #6366f1', paddingBottom: 16, marginBottom: 22 }}>
            {client?.logo_url && (
              <img src={client.logo_url} alt="" style={{ width: 48, height: 48, borderRadius: 10, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0' }} />
            )}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#0f172a' }}>{client?.name ?? 'Client'}</div>
              <div style={{ fontSize: 14, color: '#6366f1', fontWeight: 600 }}>
                Local Maps Visibility Report{focusKeyword ? ` — “${focusKeyword}”` : ''}
              </div>
            </div>
            <div style={{ textAlign: 'right', fontSize: 12, color: '#64748b' }}>
              <div>{fmtDate(new Date())}</div>
              <div>{source}{latest.radius_miles ? ` · ${latest.radius_miles}-mile grid` : ''}{latest.grid_size ? ` · ${latest.grid_size}×${latest.grid_size}` : ''}</div>
            </div>
          </div>

          {/* KPI summary */}
          <SectionTitle>Summary {latest.completed_at && <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: '#94a3b8' }}>· latest scan {fmtDate(new Date(latest.completed_at))}</span>}</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10, marginBottom: 22 }}>
            <Kpi label="Keywords" value={String(results.length)} />
            <Kpi label="Avg Top 3 %" value={fmtPct(avgTop3)} accent />
            <Kpi label="Avg Top 10 %" value={fmtPct(avgTop10)} />
            <Kpi label="Avg Found %" value={fmtPct(avgFound)} />
            <Kpi label="Avg rank" value={avgRank != null ? avgRank.toFixed(1) : '—'} />
          </div>

          {/* Trend over time */}
          {hasTrend && (
            <div className="avoid-break" style={{ marginBottom: 22 }}>
              <SectionTitle>Local-pack visibility over time</SectionTitle>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 18 }}>
                {(['top3_pct', 'top10_pct'] as const).map(key => (
                  <div key={key}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 4 }}>{TREND_METRICS.find(m => m.key === key)!.label} per keyword</div>
                    <TrendChart keywords={trends!.keywords} metric={TREND_METRICS.find(m => m.key === key)!} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Competitors outranking the client */}
          {topCompetitors.length > 0 && (
            <div className="avoid-break" style={{ marginBottom: 22 }}>
              <SectionTitle>Competitors outranking you</SectionTitle>
              <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 8px' }}>
                Businesses ranking above {client?.name ?? 'the client'} on the grid — “Beats you on” is the % of tracked pins where they outrank you, across {results.length} keyword{results.length === 1 ? '' : 's'}.
              </p>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <CompTh left>Business</CompTh><CompTh>Rating</CompTh>
                    <CompTh>Beats you on</CompTh><CompTh>Pins</CompTh><CompTh>Avg rank</CompTh>
                  </tr>
                </thead>
                <tbody>
                  {topCompetitors.map((c) => (
                    <tr key={c.pid} style={{ borderTop: '1px solid #f1f5f9' }}>
                      <CompTd left>{c.name ?? '—'}</CompTd>
                      <CompTd>{c.rating != null && c.rating > 0 ? `${c.rating}★ (${c.reviews ?? 0})` : '—'}</CompTd>
                      <CompTd><strong>{slotPct(c.pins)}%</strong></CompTd>
                      <CompTd>{c.pins}</CompTd>
                      <CompTd>{c.avgRank != null ? c.avgRank.toFixed(1) : '—'}</CompTd>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Per-keyword detail */}
          <SectionTitle>Per-keyword coverage</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 18 }}>
            {results.map(r => (
              <div key={r.keyword} className="avoid-break" style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 8 }}>
                  <MapPin size={14} color="#6366f1" /> {r.keyword}
                </div>
                <GeoGridMap grid={r.rank_grid} centerLat={latest.center_lat} centerLng={latest.center_lng} size={320} />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                  <Stat label="Top 3" value={fmtPct(kpct(r.top3_pins, r.total_pins))} color="#16a34a" />
                  <Stat label="Top 10" value={fmtPct(kpct(r.top10_pins, r.total_pins))} color="#ca8a04" />
                  <Stat label="Found" value={`${r.found_pins}/${r.total_pins}`} />
                  <Stat label="Avg rank" value={r.average_rank != null ? r.average_rank.toFixed(1) : '—'} />
                </div>
                {r.report_md && (
                  <div style={{ marginTop: 12, borderTop: '1px solid #f1f5f9', paddingTop: 10 }}>
                    <Markdown>{r.report_md}</Markdown>
                  </div>
                )}
                {(r.report_weak_locations?.weak_areas?.length ?? 0) > 0 && (
                  <div style={{ marginTop: 10, borderTop: '1px solid #f1f5f9', paddingTop: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Weakest nearby areas</div>
                    <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: '#334155' }}>
                      {r.report_weak_locations!.weak_areas.map((a, ai) => (
                        <li key={ai}>
                          {a.city ?? '—'}{a.admin_area ? `, ${a.admin_area}` : ''} — {a.pins} weak pin{a.pins === 1 ? '' : 's'}
                          {a.not_ranked > 0 ? ` (${a.not_ranked} unranked)` : ''}{a.octants.length ? ` · ${a.octants.join(', ')}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Legend */}
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', fontSize: 11, color: '#64748b', marginTop: 18 }}>
            <span>Rank per pin:</span>
            {([['1–3', 2], ['4–7', 5], ['8–10', 9], ['11–15', 13], ['16–20', 18], ['Not ranked', null]] as Array<[string, number | null]>).map(([label, rk]) => (
              <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 11, height: 11, borderRadius: 3, background: rankColor(rk) }} />{label}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>{children}</h3>
}
function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ border: '1px solid #e2e8f0', background: '#fff', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700, color: accent ? '#15803d' : '#0f172a' }}>{value}</div>
    </div>
  )
}
function CompTh({ children, left }: { children?: React.ReactNode; left?: boolean }) {
  return <th style={{ padding: '6px 8px', textAlign: left ? 'left' : 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', borderBottom: '1px solid #e2e8f0' }}>{children}</th>
}
function CompTd({ children, left }: { children?: React.ReactNode; left?: boolean }) {
  return <td style={{ padding: '6px 8px', textAlign: left ? 'left' : 'right', fontSize: 12, color: '#334155' }}>{children}</td>
}
function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', minWidth: 56 }}>
      <span style={{ fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{label}</span>
      <span style={{ fontSize: 14, fontWeight: 700, color: color ?? '#0f172a' }}>{value}</span>
    </span>
  )
}

const PRINT_CSS = `
@media print {
  body * { visibility: hidden !important; }
  #maps-report, #maps-report * { visibility: visible !important; }
  #maps-report { position: absolute; left: 0; top: 0; width: 100%; }
  .no-print { display: none !important; }
  .avoid-break { break-inside: avoid; }
  @page { margin: 14mm; }
}
`
