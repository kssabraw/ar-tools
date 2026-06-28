import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowDownRight, ArrowUpRight, Minus, PlusCircle, MinusCircle } from 'lucide-react'
import { api } from '../../lib/api'
import type {
  KeywordSummary, SerpTimelineResponse, SerpTrendsResponse,
} from '../../lib/types'
import { card } from '../localseo/shared'
import { Sparkline } from './Sparkline'
import { SIGNAL_META, SignalChip } from './SerpSnapshots'

// SERP Landscape Trends (rank tracker §14) — how Google's SERP composition
// changes over time, from the dated snapshot archive. Three sections:
//  1) client-level per-signal prevalence (as-of weekly series),
//  2) a "what changed since last capture" digest,
//  3) a per-keyword timeline of dated snapshots with deltas.
export function SerpTrends({ clientId }: { clientId: string }) {
  const { data: trends, isLoading } = useQuery<SerpTrendsResponse>({
    queryKey: ['serp-trends', clientId],
    queryFn: () => api.get<SerpTrendsResponse>(`/clients/${clientId}/serp-trends?weeks=12`),
  })

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading SERP trends…</p>

  const hasData = (trends?.series.length ?? 0) > 0
  const lastWeek = trends?.week_ends.at(-1)
  const firstWeek = trends?.week_ends[0]
  const latestKwCount = trends?.keyword_counts.at(-1) ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <p style={{ fontSize: 13, color: '#64748b', margin: 0, lineHeight: 1.6 }}>
        How the SERP landscape for this client's tracked keywords shifts over time — built from the
        dated SERP snapshots (captured weekly + on demand). Read it to spot Google changing intent
        signals and enhancements across the board.
      </p>

      {!hasData ? (
        <div style={{ ...card, color: '#64748b', fontSize: 13, lineHeight: 1.6 }}>
          No SERP snapshots yet for this client's keywords. Capture snapshots from the Keywords tab
          (the camera button on a keyword) — once a few are stored, prevalence trends and a
          change digest appear here. The weekly auto-capture also feeds this over time.
        </div>
      ) : (
        <>
          {/* 1) Client-level prevalence over time */}
          <section style={card}>
            <div style={sectionHead}>
              <h3 style={h3}>Signal & enhancement prevalence</h3>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                {firstWeek} → {lastWeek} · {latestKwCount} keyword{latestKwCount === 1 ? '' : 's'} with data
              </span>
            </div>
            <p style={subtle}>
              Share of the client's keywords whose SERP shows each signal, week over week (as-of
              the latest snapshot per keyword). Hover a name for what it implies.
            </p>
            <div style={{ overflowX: 'auto' }}>
              <table style={table}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <th style={thLeft}>Signal</th>
                    <th style={th}>Trend (12 wks)</th>
                    <th style={th}>Now</th>
                    <th style={th}>Δ vs start</th>
                  </tr>
                </thead>
                <tbody>
                  {trends!.series.map(s => {
                    const meta = SIGNAL_META[s.signal]
                    const latest = s.pct.at(-1)
                    const first = s.pct.find(v => v != null) ?? null
                    const delta = latest != null && first != null ? latest - first : null
                    return (
                      <tr key={s.signal} style={{ borderBottom: '1px solid #f1f5f9' }}>
                        <td style={tdLeft}>
                          <span style={{ fontWeight: 600, color: '#0f172a', cursor: 'help' }} title={meta?.tip ?? s.signal}>
                            {meta?.label ?? s.signal}
                          </span>
                        </td>
                        <td style={td}>
                          {/* Sparkline is inverted-Y (smaller = top); negate so higher % reads higher. */}
                          <Sparkline values={s.pct.map(v => (v == null ? null : -v))} color="#6366f1" />
                        </td>
                        <td style={td}>{latest != null ? `${Math.round(latest * 100)}%` : <Dash />}</td>
                        <td style={td}><Delta value={delta} unit="pp" /></td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          {/* 2) What changed since last capture */}
          <section style={card}>
            <div style={sectionHead}><h3 style={h3}>What changed since last capture</h3></div>
            {trends!.changes.length === 0 ? (
              <p style={{ ...subtle, marginBottom: 0 }}>
                No signal changes between the two most recent captures of any keyword.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {trends!.changes.map(c => (
                  <div key={c.keyword_id} style={changeRow}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 13 }}>{c.keyword}</div>
                      <div style={{ fontSize: 11, color: '#94a3b8' }}>{new Date(c.captured_at).toLocaleDateString()}</div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      {c.added.map(s => (
                        <span key={`a-${s}`} style={addedChip} title="Appeared"><PlusCircle size={11} /> {SIGNAL_META[s]?.label ?? s}</span>
                      ))}
                      {c.removed.map(s => (
                        <span key={`r-${s}`} style={removedChip} title="Disappeared"><MinusCircle size={11} /> {SIGNAL_META[s]?.label ?? s}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* 3) Per-keyword timeline */}
      <KeywordTimeline clientId={clientId} />
    </div>
  )
}

function KeywordTimeline({ clientId }: { clientId: string }) {
  const { data: keywords } = useQuery<KeywordSummary[]>({
    queryKey: ['rank-keywords', clientId],
    queryFn: () => api.get<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`),
  })
  const [keywordId, setKeywordId] = useState<string>('')

  const { data: timeline } = useQuery<SerpTimelineResponse>({
    queryKey: ['serp-timeline', keywordId],
    queryFn: () => api.get<SerpTimelineResponse>(`/tracked-keywords/${keywordId}/serp-timeline`),
    enabled: Boolean(keywordId),
  })

  const sorted = useMemo(
    () => [...(keywords ?? [])].sort((a, b) => a.keyword.localeCompare(b.keyword)),
    [keywords],
  )
  // Newest first for reading "what's the latest, and what changed".
  const points = useMemo(() => [...(timeline?.points ?? [])].reverse(), [timeline])

  return (
    <section style={card}>
      <div style={sectionHead}>
        <h3 style={h3}>Per-keyword timeline</h3>
        <select value={keywordId} onChange={e => setKeywordId(e.target.value)} style={select}>
          <option value="">Select a keyword…</option>
          {sorted.map(k => <option key={k.id} value={k.id}>{k.keyword}</option>)}
        </select>
      </div>

      {!keywordId ? (
        <p style={{ ...subtle, marginBottom: 0 }}>Pick a keyword to see how its SERP evolved capture by capture.</p>
      ) : points.length === 0 ? (
        <p style={{ ...subtle, marginBottom: 0 }}>No snapshots stored for this keyword yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {points.map((p, i) => (
            <div key={p.snapshot_id} style={{ display: 'flex', gap: 12, padding: '12px 0', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
              <div style={{ width: 92, flexShrink: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 12, color: '#0f172a' }}>{new Date(p.captured_at).toLocaleDateString()}</div>
                <div style={{ fontSize: 11, color: '#94a3b8' }}>{new Date(p.captured_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                {/* Authority + rank line */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: 12, color: '#475569', marginBottom: 6 }}>
                  <span title="Client's organic position">Rank <strong style={{ color: '#0f172a' }}>{p.client_rank ?? '—'}</strong>{' '}
                    {p.client_rank_delta != null && p.client_rank_delta !== 0 && <RankArrow delta={p.client_rank_delta} />}</span>
                  <span title="Client page URL Rating">UR <strong style={{ color: '#0f172a' }}>{p.client_ur ?? '—'}</strong></span>
                  <span title="Client domain Domain Rating">DR <strong style={{ color: '#0f172a' }}>{p.client_dr ?? '—'}</strong>{' '}
                    {p.client_dr_delta != null && p.client_dr_delta !== 0 && <Delta value={p.client_dr_delta} unit="" higherBetter />}</span>
                  {p.query_intent && <span style={{ color: '#7c3aed', textTransform: 'capitalize' }}>{p.query_intent}</span>}
                </div>
                {/* Signal chips */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  {[...(p.aio_present ? ['aio'] : []), ...(p.local_intent ? ['local'] : []), ...p.intent_signals]
                    .map(s => <SignalChip key={s} signal={s} />)}
                  {p.intent_signals.length === 0 && !p.aio_present && !p.local_intent && (
                    <span style={{ fontSize: 11, color: '#cbd5e1' }}>no signals</span>
                  )}
                </div>
                {/* Deltas */}
                {(p.signals_added.length > 0 || p.signals_removed.length > 0) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {p.signals_added.map(s => (
                      <span key={`a-${s}`} style={addedChip}><PlusCircle size={11} /> {SIGNAL_META[s]?.label ?? s}</span>
                    ))}
                    {p.signals_removed.map(s => (
                      <span key={`r-${s}`} style={removedChip}><MinusCircle size={11} /> {SIGNAL_META[s]?.label ?? s}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

// A drop in rank number is an improvement (closer to #1) → green up-arrow.
function RankArrow({ delta }: { delta: number }) {
  const improved = delta < 0
  const Icon = improved ? ArrowUpRight : ArrowDownRight
  const color = improved ? '#15803d' : '#c2410c'
  return <span style={{ display: 'inline-flex', alignItems: 'center', color, fontWeight: 600 }}><Icon size={12} />{Math.abs(delta)}</span>
}

function Delta({ value, unit, higherBetter = true }: { value: number | null; unit: string; higherBetter?: boolean }) {
  if (value == null || value === 0) return <Dash />
  const pretty = unit === 'pp' ? `${value > 0 ? '+' : ''}${Math.round(value * 100)}pp` : `${value > 0 ? '+' : ''}${value}`
  const good = higherBetter ? value > 0 : value < 0
  const color = good ? '#15803d' : '#c2410c'
  const Icon = value > 0 ? ArrowUpRight : ArrowDownRight
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, color, fontWeight: 600 }}><Icon size={12} />{pretty}</span>
}

function Dash() { return <span style={{ color: '#cbd5e1' }}><Minus size={12} /></span> }

const sectionHead: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 4, flexWrap: 'wrap' }
const h3: React.CSSProperties = { fontSize: 14, fontWeight: 700, color: '#0f172a', margin: 0 }
const subtle: React.CSSProperties = { fontSize: 12, color: '#64748b', margin: '4px 0 12px', lineHeight: 1.5 }
const table: React.CSSProperties = { borderCollapse: 'collapse', width: '100%', fontSize: 13 }
const th: React.CSSProperties = { padding: '8px 12px', textAlign: 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const td: React.CSSProperties = { padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left' }
const changeRow: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 12, padding: '8px 10px', background: '#fafbfc', border: '1px solid #f1f5f9', borderRadius: 8 }
const addedChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10, fontWeight: 600, color: '#15803d', background: '#dcfce7', borderRadius: 999, padding: '2px 8px' }
const removedChip: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10, fontWeight: 600, color: '#b91c1c', background: '#fef2f2', borderRadius: 999, padding: '2px 8px' }
const select: React.CSSProperties = { padding: '6px 10px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, fontFamily: 'inherit', maxWidth: 260 }
