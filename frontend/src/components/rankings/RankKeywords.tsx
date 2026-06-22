import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Plus, RefreshCw, Trash2, TrendingDown, TrendingUp, Minus } from 'lucide-react'
import { api } from '../../lib/api'
import type { KeywordStatus, KeywordSummary, KeywordTrendline } from '../../lib/types'
import { card, errorBox, outlineBtn, primaryBtn } from '../localseo/shared'
import { STATUS_META, statusRank } from './status'
import { Sparkline } from './Sparkline'
import { PositionChart } from './PositionChart'

// `gscConnected` controls whether the GSC-only columns (clicks, impressions,
// CTR, 7/30/60/90 average position) are shown at all. Without GSC the table
// falls back to the DataForSEO live rank ("Today") + trend.
export function RankKeywords({ clientId, isAdmin, gscConnected }: {
  clientId: string; isAdmin: boolean; gscConnected: boolean
}) {
  const queryClient = useQueryClient()
  const { data: keywords, isLoading } = useQuery<KeywordSummary[]>({
    queryKey: ['rank-keywords', clientId],
    queryFn: () => api.get<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`),
  })

  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<KeywordStatus | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
    queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
  }

  const addMut = useMutation({
    mutationFn: (text: string) =>
      api.post<KeywordSummary[]>(`/clients/${clientId}/rank/keywords`, { keywords: [text] }),
    onSuccess: () => { invalidate(); setDraft(''); setAdding(false) },
  })
  const refreshMut = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/rank/refresh-dataforseo`, {}),
    onSuccess: invalidate,
  })

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const k of keywords ?? []) c[k.status] = (c[k.status] ?? 0) + 1
    return c
  }, [keywords])

  const rows = useMemo(() => {
    const list = (keywords ?? []).filter(k => !filter || k.status === filter)
    return [...list].sort((a, b) => statusRank(a.status) - statusRank(b.status) || a.keyword.localeCompare(b.keyword))
  }, [keywords, filter])

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading keywords…</p>

  const showGsc = gscConnected

  return (
    <div>
      {/* Add keywords + DataForSEO refresh */}
      <div style={{ ...card, marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        {adding ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 280 }}>
            <textarea
              style={textarea} autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
              placeholder="One keyword per line (or comma-separated). e.g. emergency ac repair"
            />
            {addMut.error && <div style={errorBox}>{(addMut.error as Error).message}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={primaryBtn} disabled={!draft.trim() || addMut.isPending}
                onClick={() => addMut.mutate(draft.trim())}>
                {addMut.isPending ? 'Adding…' : 'Add keywords'}
              </button>
              <button style={outlineBtn} onClick={() => { setAdding(false); setDraft('') }}>Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <button style={primaryBtn} onClick={() => setAdding(true)} disabled={!isAdmin}>
              <Plus size={14} /> Track keywords
            </button>
            {isAdmin && (keywords?.length ?? 0) > 0 && (
              <button style={outlineBtn} onClick={() => refreshMut.mutate()} disabled={refreshMut.isPending}
                title="Fetch DataForSEO ranks now for keywords GSC doesn't cover">
                <RefreshCw size={14} /> {refreshMut.isPending ? 'Fetching…' : 'Refresh live ranks'}
              </button>
            )}
          </>
        )}
      </div>

      {!gscConnected && (keywords?.length ?? 0) > 0 && (
        <div style={dfBanner}>
          No Search Console connection for this client — ranks come from DataForSEO live SERP checks
          (refreshed weekly). Clicks, impressions and Search Console average position aren’t available
          in this mode.
        </div>
      )}

      {/* Status filter chips */}
      {keywords && keywords.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          <Chip active={filter === null} onClick={() => setFilter(null)} label={`All ${keywords.length}`} color="#475569" bg="#f1f5f9" />
          {(Object.keys(STATUS_META) as KeywordStatus[]).filter(s => counts[s])
            .sort((a, b) => statusRank(a) - statusRank(b))
            .map(s => (
              <Chip key={s} active={filter === s} onClick={() => setFilter(filter === s ? null : s)}
                label={`${STATUS_META[s].label} ${counts[s]}`} color={STATUS_META[s].color} bg={STATUS_META[s].bg} />
            ))}
        </div>
      )}

      {keywords && keywords.length === 0 ? (
        <div style={emptyCard}>
          No keywords tracked yet. Add the terms this client wants to rank for — including ones they
          don’t rank for yet (those are tracked via DataForSEO until a position appears).
        </div>
      ) : (
        <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={thLeft}>Keyword</th>
                <th style={th}>Trend</th>
                <th style={th}>Status</th>
                <th style={th} title="Live rank (DataForSEO)">Today</th>
                {showGsc && <><th style={th}>7d</th><th style={th}>30d</th><th style={th}>60d</th><th style={th}>90d</th>
                  <th style={th}>Clicks</th><th style={th}>Impr.</th><th style={th}>CTR</th></>}
                {isAdmin && <th style={th}></th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(k => (
                <KeywordRow key={k.id} k={k} isAdmin={isAdmin} clientId={clientId} showGsc={showGsc} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function KeywordRow({ k, isAdmin, clientId, showGsc }: {
  k: KeywordSummary; isAdmin: boolean; clientId: string; showGsc: boolean
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const meta = STATUS_META[k.status]
  const isDf = k.primary_source === 'dataforseo'

  const { data: trend } = useQuery<KeywordTrendline>({
    queryKey: ['rank-trendline', k.id],
    queryFn: () => api.get<KeywordTrendline>(`/tracked-keywords/${k.id}/trendline`),
    enabled: open,
  })

  const deleteMut = useMutation({
    mutationFn: () => api.delete<void>(`/tracked-keywords/${k.id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
      queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
    },
  })

  const colSpan = 4 + (showGsc ? 7 : 0) + (isAdmin ? 1 : 0)
  // DataForSEO keywords plot tracked_rank; GSC keywords plot gsc_position.
  const trendValues = (trend?.points ?? []).map(p => ({
    date: p.date, value: isDf ? (p.tracked_rank ?? null) : p.gsc_position,
  }))

  return (
    <>
      <tr style={{ borderBottom: '1px solid #f1f5f9', cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        <td style={tdLeft}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {open ? <ChevronDown size={14} color="#94a3b8" /> : <ChevronRight size={14} color="#94a3b8" />}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontWeight: 600, color: '#0f172a' }}>{k.keyword}</span>
                {isDf && <span style={srcBadge}>DataForSEO</span>}
              </div>
              {k.canonical_url && (
                <div style={{ fontSize: 11, color: '#94a3b8', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {k.canonical_url}
                </div>
              )}
            </div>
          </div>
        </td>
        <td style={td}><Sparkline values={k.sparkline} color={meta.color} /></td>
        <td style={td}><span style={{ ...badge, color: meta.color, background: meta.bg }}>{meta.label}</span></td>
        <td style={td}>{k.today_rank != null ? <span style={todayBox}>{k.today_rank}</span> : <Dash />}</td>
        {showGsc && <>
          <td style={td}><PosCell value={k.avg_7} direction={k.direction} /></td>
          <td style={td}><Pos value={k.avg_30} /></td>
          <td style={td}><Pos value={k.avg_60} /></td>
          <td style={td}><Pos value={k.avg_90} /></td>
          <td style={td}>{k.clicks_30d.toLocaleString()}</td>
          <td style={td}>{k.impressions_30d.toLocaleString()}</td>
          <td style={td}>{k.impressions_30d ? `${(k.ctr_30d * 100).toFixed(1)}%` : <Dash />}</td>
        </>}
        {isAdmin && (
          <td style={td} onClick={(e) => e.stopPropagation()}>
            <button style={{ ...outlineBtn, padding: '4px 7px', color: '#dc2626' }}
              onClick={() => deleteMut.mutate()} title="Stop tracking"><Trash2 size={13} /></button>
          </td>
        )}
      </tr>
      {open && (
        <tr>
          <td colSpan={colSpan} style={{ padding: 16, background: '#fafbfc', borderBottom: '1px solid #f1f5f9' }}>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
              {isDf
                ? 'DataForSEO live SERP rank — weekly checks (lower is better; inverted axis)'
                : 'GSC average position — full tracked range (gaps = days the keyword returned no data)'}
            </div>
            <PositionChart points={trendValues} />
          </td>
        </tr>
      )}
    </>
  )
}

function Pos({ value }: { value: number | null }) {
  return value == null ? <Dash /> : <span style={{ color: '#334155' }}>{value.toFixed(1)}</span>
}
function PosCell({ value, direction }: { value: number | null; direction: KeywordSummary['direction'] }) {
  if (value == null) return <Dash />
  const arrow = direction === 'up' ? <TrendingUp size={13} color="#15803d" />
    : direction === 'down' ? <TrendingDown size={13} color="#c2410c" /> : <Minus size={12} color="#94a3b8" />
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#0f172a', fontWeight: 600 }}>{value.toFixed(1)} {arrow}</span>
}
function Dash() { return <span style={{ color: '#cbd5e1' }}>—</span> }
function Chip({ active, onClick, label, color, bg }: { active: boolean; onClick: () => void; label: string; color: string; bg: string }) {
  return <button onClick={onClick} style={{ border: active ? `1px solid ${color}` : '1px solid transparent', background: bg, color, borderRadius: 999, padding: '4px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>{label}</button>
}

const textarea: React.CSSProperties = { width: '100%', minHeight: 80, padding: 10, borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 14, fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }
const th: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const td: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', whiteSpace: 'nowrap' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left' }
const badge: React.CSSProperties = { borderRadius: 999, padding: '2px 9px', fontSize: 11, fontWeight: 600 }
const srcBadge: React.CSSProperties = { fontSize: 10, fontWeight: 600, color: '#0369a1', background: '#e0f2fe', borderRadius: 4, padding: '1px 5px' }
const todayBox: React.CSSProperties = { display: 'inline-block', minWidth: 22, border: '1px solid #e2e8f0', borderRadius: 5, padding: '1px 6px', fontWeight: 700, color: '#0f172a' }
const emptyCard: React.CSSProperties = { ...card, color: '#64748b', fontSize: 13, lineHeight: 1.6 }
const dfBanner: React.CSSProperties = { background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#0369a1', marginBottom: 14, lineHeight: 1.5 }
