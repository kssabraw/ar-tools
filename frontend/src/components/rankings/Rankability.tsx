import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, ArrowDownRight, Camera, Zap } from 'lucide-react'
import { api } from '../../lib/api'
import type { RankabilityItem, RankabilityResponse } from '../../lib/types'
import { card } from '../localseo/shared'

type Sort = 'quickwins' | 'rankability' | 'value'

// Rankability (rank tracker §14.5) — how realistically the client can win each
// tracked keyword, from its latest SERP snapshot. Score 0–100 + band (higher =
// more winnable), the driving factors, and a Quick-wins sort (rankability ×
// potential value). Keywords without a snapshot yet prompt a capture.
export function Rankability({ clientId }: { clientId: string }) {
  const { data, isLoading } = useQuery<RankabilityResponse>({
    queryKey: ['rankability', clientId],
    queryFn: () => api.get<RankabilityResponse>(`/clients/${clientId}/rank/rankability`),
  })
  const [sort, setSort] = useState<Sort>('quickwins')

  const { scored, unscored } = useMemo(() => {
    const items = data?.items ?? []
    const scored = items.filter(i => i.has_snapshot && i.score != null)
    const unscored = items.filter(i => !i.has_snapshot || i.score == null)
    const cmp: Record<Sort, (a: RankabilityItem, b: RankabilityItem) => number> = {
      quickwins: (a, b) => (b.priority ?? 0) - (a.priority ?? 0),
      rankability: (a, b) => (b.score ?? 0) - (a.score ?? 0),
      value: (a, b) => (b.est_value ?? 0) - (a.est_value ?? 0),
    }
    return { scored: [...scored].sort(cmp[sort]), unscored }
  }, [data, sort])

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading rankability…</p>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ fontSize: 13, color: '#64748b', margin: 0, lineHeight: 1.6 }}>
        How realistically this client can win each keyword — scored 0–100 (higher = more winnable)
        from the latest SERP snapshot: incumbent backlink authority (RD &gt; UR &gt; DR), how many
        top results are written for the keyword, the client's own authority, and SERP crowding.
        <strong> Quick wins</strong> sorts by rankability × potential value.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 600 }}>Sort:</span>
        <SortChip active={sort === 'quickwins'} onClick={() => setSort('quickwins')} label="Quick wins" icon={<Zap size={12} />} />
        <SortChip active={sort === 'rankability'} onClick={() => setSort('rankability')} label="Rankability" />
        <SortChip active={sort === 'value'} onClick={() => setSort('value')} label="Potential value" />
      </div>

      {scored.length === 0 && unscored.length === 0 ? (
        <div style={{ ...card, color: '#64748b', fontSize: 13 }}>No tracked keywords yet.</div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={thLeft}>Keyword</th>
                <th style={th}>Rankability</th>
                <th style={thLeft}>Why</th>
                <th style={th} title="Monthly search volume">Vol.</th>
                <th style={th} title="Potential monthly value if won (top-3)">Potential</th>
                <th style={th} title="Rankability × potential value">Priority</th>
              </tr>
            </thead>
            <tbody>
              {scored.map(i => <Row key={i.keyword_id} item={i} />)}
            </tbody>
          </table>
        </div>
      )}

      {unscored.length > 0 && (
        <div style={{ ...card }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>
            Not scored yet ({unscored.length})
          </div>
          <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 10px', lineHeight: 1.5 }}>
            Rankability needs a SERP snapshot. Capture one from the Keywords tab (the
            <Camera size={11} style={{ verticalAlign: 'middle', margin: '0 3px' }} /> button on a keyword) — the weekly
            auto-capture will also fill these in over time.
          </p>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {unscored.map(i => (
              <span key={i.keyword_id} style={unscoredChip}>{i.keyword}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Row({ item }: { item: RankabilityItem }) {
  const meta = bandMeta(item.band)
  return (
    <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
      <td style={tdLeft}>
        <div style={{ fontWeight: 600, color: '#0f172a' }}>{item.keyword}</div>
        {item.client_rank != null && (
          <div style={{ fontSize: 11, color: '#94a3b8' }}>currently #{item.client_rank}</div>
        )}
      </td>
      <td style={td}>
        <span style={{ ...bandChip, color: meta.color, background: meta.bg }}>
          {meta.label} · {item.score}
        </span>
      </td>
      <td style={tdLeft}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {item.factors.map((f, i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#475569' }}>
              {f.direction === 'up'
                ? <ArrowUpRight size={11} color="#15803d" />
                : <ArrowDownRight size={11} color="#c2410c" />}
              {f.text}
            </span>
          ))}
        </div>
      </td>
      <td style={td}>{item.search_volume != null ? item.search_volume.toLocaleString() : <Dash />}</td>
      <td style={td}>{item.est_value != null
        ? <span style={{ color: '#15803d', fontWeight: 600 }}>${Math.round(item.est_value).toLocaleString()}</span>
        : <Dash />}</td>
      <td style={td}>{item.priority != null ? Math.round(item.priority).toLocaleString() : <Dash />}</td>
    </tr>
  )
}

function bandMeta(band: string | null): { label: string; color: string; bg: string } {
  switch (band) {
    case 'Easy': return { label: 'Easy', color: '#15803d', bg: '#dcfce7' }
    case 'Moderate': return { label: 'Moderate', color: '#0369a1', bg: '#e0f2fe' }
    case 'Hard': return { label: 'Hard', color: '#b45309', bg: '#fffbeb' }
    case 'Very hard': return { label: 'Very hard', color: '#b91c1c', bg: '#fef2f2' }
    default: return { label: band ?? '—', color: '#475569', bg: '#f1f5f9' }
  }
}

function SortChip({ active, onClick, label, icon }: { active: boolean; onClick: () => void; label: string; icon?: React.ReactNode }) {
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      border: active ? '1px solid #6366f1' : '1px solid #e2e8f0',
      background: active ? '#eef2ff' : '#fff', color: active ? '#4338ca' : '#64748b',
      borderRadius: 999, padding: '4px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
    }}>{icon}{label}</button>
  )
}

function Dash() { return <span style={{ color: '#cbd5e1' }}>—</span> }

const th: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const td: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', whiteSpace: 'nowrap', verticalAlign: 'top' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left', whiteSpace: 'normal' }
const bandChip: React.CSSProperties = { display: 'inline-block', borderRadius: 999, padding: '3px 10px', fontSize: 12, fontWeight: 700 }
const unscoredChip: React.CSSProperties = { fontSize: 12, color: '#64748b', background: '#f1f5f9', borderRadius: 6, padding: '3px 9px' }
