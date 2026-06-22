import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Pin, PinOff, Plus, RefreshCw, Trash2, TrendingDown, TrendingUp, Minus, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import type { KeywordStatus, KeywordSummary, KeywordTrendline, KeywordPagesResponse } from '../../lib/types'
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
                <th style={th} title="Cost per click (DataForSEO)">CPC</th>
                <th style={th} title="Monthly search volume (DataForSEO)">Vol.</th>
                <th style={th} title="Est. monthly value = volume × CTR-at-position × CPC">Est. value</th>
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
  const { data: pages } = useQuery<KeywordPagesResponse>({
    queryKey: ['rank-kw-pages', k.id],
    queryFn: () => api.get<KeywordPagesResponse>(`/tracked-keywords/${k.id}/pages`),
    enabled: open && !isDf,
  })

  const deleteMut = useMutation({
    mutationFn: () => api.delete<void>(`/tracked-keywords/${k.id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
      queryClient.invalidateQueries({ queryKey: ['rank-overview', clientId] })
    },
  })
  const checkIndexMut = useMutation({
    mutationFn: () => api.post(`/tracked-keywords/${k.id}/check-index`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] }),
  })
  const pinMut = useMutation({
    mutationFn: (vars: { canonical_url?: string; canonical_url_locked: boolean }) =>
      api.patch(`/tracked-keywords/${k.id}`, vars),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rank-keywords', clientId] })
      queryClient.invalidateQueries({ queryKey: ['rank-kw-pages', k.id] })
    },
  })

  const colSpan = 7 + (showGsc ? 7 : 0) + (isAdmin ? 1 : 0)
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
              {(k.canonical_url || k.page_count > 1) && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, maxWidth: 320 }}>
                  {k.canonical_url && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: '#94a3b8', overflow: 'hidden', minWidth: 0 }}>
                      {k.canonical_url_locked && <Pin size={10} color="#7c3aed" />}
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{k.canonical_url}</span>
                    </span>
                  )}
                  {k.page_count > 1 && (
                    <span style={pagesChip} title="Surfaces across multiple pages — expand for the breakdown">
                      +{k.page_count - 1} {k.page_count - 1 === 1 ? 'page' : 'pages'}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </td>
        <td style={td}><Sparkline values={k.sparkline} color={meta.color} /></td>
        <td style={td}><span style={{ ...badge, color: meta.color, background: meta.bg }}>{meta.label}</span></td>
        <td style={td}>{k.today_rank != null ? <span style={todayBox}>{k.today_rank}</span> : <Dash />}</td>
        <td style={td}>{k.cpc != null ? `$${k.cpc.toFixed(2)}` : <Dash />}</td>
        <td style={td}>{k.search_volume != null ? k.search_volume.toLocaleString() : <Dash />}</td>
        <td style={td}>{k.est_monthly_value != null
          ? <span style={{ color: '#15803d', fontWeight: 600 }}>${Math.round(k.est_monthly_value).toLocaleString()}</span>
          : <Dash />}</td>
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
            {k.status === 'deindex_risk' && <DeindexBanner k={k} isAdmin={isAdmin}
              checking={checkIndexMut.isPending} onCheck={() => checkIndexMut.mutate()} />}
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
              {isDf
                ? 'DataForSEO live SERP rank — weekly checks (lower is better; inverted axis)'
                : 'GSC average position — full tracked range (gaps = days the keyword returned no data)'}
            </div>
            <PositionChart points={trendValues} />
            {pages && pages.pages.length > 0 && (
              <PageBreakdown
                pages={pages.pages}
                locked={k.canonical_url_locked}
                isAdmin={isAdmin}
                pinning={pinMut.isPending}
                onPin={(page) => pinMut.mutate({ canonical_url: page, canonical_url_locked: true })}
                onUnpin={() => pinMut.mutate({ canonical_url_locked: false })}
              />
            )}
          </td>
        </tr>
      )}
    </>
  )
}

// Which landing pages a keyword surfaces for — flags the canonical page,
// surfaces "split across pages" conflicts (PRD §8.5), and lets an admin pin the
// canonical page so the most-clicks heuristic can't reassign it (§5).
function PageBreakdown({ pages, locked, isAdmin, pinning, onPin, onUnpin }: {
  pages: KeywordPagesResponse['pages']
  locked: boolean
  isAdmin: boolean
  pinning: boolean
  onPin: (page: string) => void
  onUnpin: () => void
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: '#64748b' }}>Landing pages this keyword surfaces for</span>
        {locked && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#7c3aed' }}>
            <Pin size={11} /> canonical pinned
            {isAdmin && (
              <button style={{ ...outlineBtn, padding: '2px 8px', fontSize: 11, marginLeft: 6 }}
                onClick={onUnpin} disabled={pinning}>
                <PinOff size={11} /> Unpin
              </button>
            )}
          </span>
        )}
      </div>
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
        {pages.map((p, i) => (
          <div key={p.page} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#fff', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
            <a href={p.page} target="_blank" rel="noreferrer"
              style={{ flex: 1, color: '#6366f1', textDecoration: 'none', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>
              {p.page}
            </a>
            {p.is_canonical && <span style={canonChip}>{locked ? 'pinned' : 'canonical'}</span>}
            <span style={{ fontSize: 12, color: '#64748b', width: 60, textAlign: 'right' }}>{p.clicks.toLocaleString()} clk</span>
            <span style={{ fontSize: 12, color: '#94a3b8', width: 70, textAlign: 'right' }}>{p.impressions.toLocaleString()} impr</span>
            <span style={{ fontSize: 12, color: '#64748b', width: 40, textAlign: 'right' }}>{p.avg_position != null ? p.avg_position.toFixed(1) : '—'}</span>
            {isAdmin && !(p.is_canonical && locked) && (
              <button style={{ ...outlineBtn, padding: '3px 8px', fontSize: 11 }}
                onClick={() => onPin(p.page)} disabled={pinning} title="Pin this page as the canonical landing page">
                <Pin size={11} /> Pin
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// For a deindex_risk keyword, surface the URL-Inspection verdict so the message
// becomes "this page is deindexed" rather than just "rankings look low".
function DeindexBanner({ k, isAdmin, checking, onCheck }: {
  k: KeywordSummary; isAdmin: boolean; checking: boolean; onCheck: () => void
}) {
  const confirmed = k.index_status === 'not_indexed'
  const indexed = k.index_status === 'indexed'
  const bg = confirmed ? '#fef2f2' : indexed ? '#f0fdf4' : '#fffbeb'
  const border = confirmed ? '#fecaca' : indexed ? '#bbf7d0' : '#fde68a'
  const color = confirmed ? '#b91c1c' : indexed ? '#15803d' : '#b45309'
  return (
    <div style={{ background: bg, border: `1px solid ${border}`, borderRadius: 8, padding: '10px 12px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
      {confirmed ? <ShieldAlert size={16} color={color} /> : indexed ? <ShieldCheck size={16} color={color} /> : <ShieldAlert size={16} color={color} />}
      <div style={{ flex: 1, fontSize: 12, color, lineHeight: 1.5 }}>
        {confirmed
          ? <>Confirmed: Google reports this page is <strong>not indexed</strong>{k.index_checked_at ? ` (checked ${new Date(k.index_checked_at).toLocaleDateString()})` : ''}. This is a deindexing, not just a ranking dip.</>
          : indexed
            ? <>URL Inspection says the page is <strong>indexed</strong> — the disappearance is a ranking drop, not deindexing.</>
            : <>Sustained disappearance after an established baseline — possible deindexing. Run a URL Inspection to confirm.</>}
      </div>
      {isAdmin && k.canonical_url && (
        <button style={{ ...outlineBtn, padding: '5px 10px', fontSize: 12 }} onClick={onCheck} disabled={checking}>
          {checking ? 'Checking…' : 'Check index'}
        </button>
      )}
    </div>
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
const pagesChip: React.CSSProperties = { flexShrink: 0, fontSize: 10, fontWeight: 600, color: '#7c3aed', background: '#f3e8ff', borderRadius: 4, padding: '1px 5px', whiteSpace: 'nowrap' }
const canonChip: React.CSSProperties = { fontSize: 10, fontWeight: 600, color: '#15803d', background: '#dcfce7', borderRadius: 4, padding: '1px 6px' }
const todayBox: React.CSSProperties = { display: 'inline-block', minWidth: 22, border: '1px solid #e2e8f0', borderRadius: 5, padding: '1px 6px', fontWeight: 700, color: '#0f172a' }
const emptyCard: React.CSSProperties = { ...card, color: '#64748b', fontSize: 13, lineHeight: 1.6 }
const dfBanner: React.CSSProperties = { background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '10px 14px', fontSize: 12, color: '#0369a1', marginBottom: 14, lineHeight: 1.5 }
