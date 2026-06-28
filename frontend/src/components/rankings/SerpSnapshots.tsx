import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, ExternalLink, MapPin, Sparkles, X } from 'lucide-react'
import { api } from '../../lib/api'
import type {
  SerpSnapshotCaptureResponse,
  SerpSnapshotDetail,
  SerpSnapshotListItem,
} from '../../lib/types'
import { card, errorBox, primaryBtn } from '../localseo/shared'

// Competitive SERP Snapshot viewer (rank tracker §14). Opened per tracked
// keyword: lists the dated archive, captures a new on-demand snapshot (~24
// DataForSEO lookups — polls the list until it lands), and renders one snapshot:
// AIO + sources, query intent, the top-10 organic landscape with per-page UR +
// referring domains, and per-domain Domain Rating. The client's row is
// highlighted throughout.
export function SerpSnapshots({ keywordId, keyword, onClose }: {
  keywordId: string; keyword: string; onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const [timedOut, setTimedOut] = useState(false)
  const baselineNewest = useRef<string | null>(null)
  const pollCount = useRef(0)
  // ~6 min at the 6s interval. A capture that never lands a row (e.g. the client
  // has no website, so the job inserts nothing) would otherwise poll forever.
  const MAX_POLLS = 60

  const { data: snapshots } = useQuery<SerpSnapshotListItem[]>({
    queryKey: ['serp-snapshots', keywordId],
    queryFn: () => api.get<SerpSnapshotListItem[]>(`/tracked-keywords/${keywordId}/serp-snapshots`),
    refetchInterval: capturing ? 6000 : false,
  })

  // While capturing, watch the list for a new snapshot row (the worker inserts it
  // when the capture finishes — or a 'failed' marker on a SERP error). When the
  // newest id changes from the pre-capture baseline, stop polling + auto-open it.
  // Bounded so a capture that never persists a row can't spin indefinitely.
  useEffect(() => {
    if (!capturing) return
    const newest = snapshots?.[0]?.id ?? null
    if (newest && newest !== baselineNewest.current) {
      setCapturing(false)
      pollCount.current = 0
      setSelectedId(newest)
      return
    }
    pollCount.current += 1
    if (pollCount.current >= MAX_POLLS) {
      setCapturing(false)
      setTimedOut(true)
    }
  }, [snapshots, capturing])

  const captureMut = useMutation({
    mutationFn: () =>
      api.post<SerpSnapshotCaptureResponse>(`/tracked-keywords/${keywordId}/serp-snapshot`, {}),
    onSuccess: () => {
      baselineNewest.current = snapshots?.[0]?.id ?? null
      pollCount.current = 0
      setTimedOut(false)
      setCapturing(true)
      queryClient.invalidateQueries({ queryKey: ['serp-snapshots', keywordId] })
    },
  })

  return (
    <div style={overlay} onClick={onClose}>
      <div style={panel} onClick={(e) => e.stopPropagation()}>
        <div style={header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <Camera size={18} color="#6366f1" />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>SERP Snapshot</div>
              <div style={{ fontSize: 12, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{keyword}</div>
            </div>
          </div>
          <button style={iconBtn} onClick={onClose} title="Close"><X size={16} /></button>
        </div>

        <div style={body}>
          {/* Left: dated archive + capture */}
          <div style={sidebar}>
            <button style={{ ...primaryBtn, width: '100%', justifyContent: 'center' }}
              onClick={() => captureMut.mutate()} disabled={capturing || captureMut.isPending}>
              <Camera size={14} /> {capturing ? 'Capturing…' : captureMut.isPending ? 'Starting…' : 'New snapshot'}
            </button>
            {captureMut.error && <div style={{ ...errorBox, marginTop: 8 }}>{(captureMut.error as Error).message}</div>}
            {capturing && (
              <div style={hint}>
                Capturing the live SERP + authority signals (~24 DataForSEO lookups). This can take a
                minute — the snapshot appears below when it lands.
              </div>
            )}
            {timedOut && (
              <div style={{ ...hint, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' }}>
                Still working — this capture is taking longer than expected. It keeps running in the
                background; reopen this panel later to see it, or try again.
              </div>
            )}
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(snapshots ?? []).length === 0 && !capturing && (
                <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.5 }}>
                  No snapshots yet. Capture one to record the current competitive landscape — they're
                  stored dated so you can compare over time.
                </div>
              )}
              {(snapshots ?? []).map(s => (
                <button key={s.id} onClick={() => setSelectedId(s.id)}
                  style={{ ...snapItem, ...(selectedId === s.id ? snapItemActive : {}) }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                    <span style={{ fontWeight: 600, color: '#0f172a' }}>{new Date(s.captured_at).toLocaleDateString()}</span>
                    <StatusPill status={s.status} />
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {new Date(s.captured_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    {s.client_rank != null ? ` · client #${s.client_rank}` : ''}
                    {s.result_count ? ` · ${s.result_count} pages` : ''}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Right: selected snapshot detail */}
          <div style={detailPane}>
            {selectedId ? (
              <SnapshotDetailView snapshotId={selectedId} />
            ) : (
              <div style={{ color: '#94a3b8', fontSize: 13, padding: 24, textAlign: 'center' }}>
                Select a snapshot to view the SERP landscape.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SnapshotDetailView({ snapshotId }: { snapshotId: string }) {
  const { data: snap, isLoading } = useQuery<SerpSnapshotDetail>({
    queryKey: ['serp-snapshot', snapshotId],
    queryFn: () => api.get<SerpSnapshotDetail>(`/serp-snapshots/${snapshotId}`),
  })

  const drByDomain = useMemo(() => {
    const m = new Map<string, number | null>()
    for (const d of snap?.domains ?? []) if (d.domain) m.set(d.domain, d.domain_rating)
    return m
  }, [snap])

  // The client's ranking page may surface on a www/subdomain host that isn't a
  // key in drByDomain (DR is keyed on the canonical client domain). Fall back to
  // the client domain row's DR for is_client result rows so the per-page DR column
  // isn't blank for the client.
  const clientDr = useMemo(
    () => snap?.domains?.find(d => d.is_client)?.domain_rating ?? null,
    [snap],
  )

  // Intent signals + targeting come straight from the API — it derives them for
  // pre-column snapshots too (single source of truth; no client-side heuristics).
  const signals = useMemo(() => snap?.intent_signals ?? [], [snap])

  const targeting = useMemo(() => {
    if (!snap) return { numerator: 0, denominator: 0 }
    const top = snap.results.filter(r => r.position != null && (r.position as number) <= 10)
    return { numerator: snap.targeted_count ?? 0, denominator: top.length }
  }, [snap])

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 13 }}>Loading snapshot…</p>
  if (!snap) return <p style={errorBox}>Snapshot not found.</p>

  if (snap.status === 'failed') {
    return (
      <div style={errorBox}>
        This capture failed{snap.error ? `: ${snap.error}` : '.'} The SERP couldn't be fetched —
        capture again to retry.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Meta strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          {new Date(snap.captured_at).toLocaleString()}
        </span>
        {snap.query_intent && <IntentBadge intent={snap.query_intent} />}
        {snap.local_intent && (
          <span style={{ ...miniBadge, color: '#0e7490', background: '#cffafe', display: 'inline-flex', alignItems: 'center', gap: 4 }}
            title="Google shows a local pack / map for this query — it carries local intent">
            <MapPin size={11} /> Local
          </span>
        )}
        {snap.status === 'partial' && (
          <span style={{ ...miniBadge, color: '#b45309', background: '#fffbeb' }}>partial — some authority lookups failed</span>
        )}
      </div>

      {/* Intent signals derived from the SERP composition + title patterns */}
      {signals.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em' }}>
            Signals
          </span>
          {signals.map(s => <SignalChip key={s} signal={s} />)}
        </div>
      )}

      {/* AI Overview */}
      <section style={card}>
        <SectionTitle icon={<Sparkles size={14} color="#7c3aed" />} title="AI Overview" />
        {snap.aio_present ? (
          <>
            {snap.aio_text && (
              <p style={{ fontSize: 13, color: '#334155', lineHeight: 1.6, margin: '4px 0 10px', whiteSpace: 'pre-wrap' }}>
                {snap.aio_text.length > 600 ? snap.aio_text.slice(0, 600) + '…' : snap.aio_text}
              </p>
            )}
            {(snap.aio_sources ?? []).length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', marginBottom: 6 }}>Cited sources</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(snap.aio_sources ?? []).map((s, i) => (
                    <a key={i} href={s.url ?? '#'} target="_blank" rel="noreferrer" style={sourceLink}>
                      <ExternalLink size={11} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.title || s.domain || s.url}
                      </span>
                      {s.domain && <span style={{ color: '#94a3b8', flexShrink: 0 }}>· {s.domain}</span>}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>No AI Overview appeared for this query.</p>
        )}
      </section>

      {/* Top organic results */}
      <section style={{ ...card, padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '12px 14px' }}>
          <SectionTitle title="Top organic results" />
          {targeting.denominator > 0 && (
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
              <strong style={{ color: '#0f172a' }}>{targeting.numerator} of {targeting.denominator}</strong> top results are written for this keyword
              {targeting.numerator < targeting.denominator && (
                <span style={{ color: '#15803d' }}> · the rest are loosely-relevant (an opening for a purpose-built page)</span>
              )}
            </div>
          )}
          {(snap.keyword_topic || snap.generalist_count != null) && (
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
              {snap.keyword_topic && <>Topic <strong style={{ color: '#0f172a' }}>{snap.keyword_topic}</strong> · </>}
              {snap.generalist_count != null && (
                <><strong style={{ color: '#0f172a' }}>{snap.generalist_count} of {targeting.denominator}</strong> incumbents are generalists</>
              )}
              {snap.client_topical_focus && snap.client_topical_focus !== 'unknown' && (
                <span style={{ color: snap.client_topical_focus === 'specialist' ? '#15803d' : '#64748b' }}>
                  {' '}· you're a <strong>{snap.client_topical_focus}</strong>
                  {snap.client_topical_focus === 'specialist' && snap.generalist_count ? ' (an edge here)' : ''}
                </span>
              )}
            </div>
          )}
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={table}>
            <thead>
              <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                <th style={thNum}>#</th>
                <th style={thLeft}>Page</th>
                <th style={th} title="Referring domains to this page (the strongest backlink signal)">RD</th>
                <th style={th} title="URL Rating — this page's authority, 0–100">UR</th>
                <th style={th} title="Domain Rating — the whole domain's authority, 0–100">DR</th>
              </tr>
            </thead>
            <tbody>
              {snap.results.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9', background: r.is_client ? '#eef2ff' : '#fff' }}>
                  <td style={tdNum}>{r.position ?? '—'}</td>
                  <td style={tdLeft}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {r.is_client && <span style={clientChip}>client</span>}
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontWeight: 600, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }}>
                            {r.title || r.domain || '—'}
                          </span>
                          {r.targeted === false && (
                            <span style={looseChip} title="Not written for this keyword — title/URL don't target it (a weaker, beatable result)">loose match</span>
                          )}
                          {!r.is_client && r.topical_focus === 'generalist' && (
                            <span style={generalistChip} title="A generalist site — the topic is one of many things it covers (beatable by a specialist)">generalist</span>
                          )}
                        </div>
                        {r.url && (
                          <a href={r.url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#6366f1', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block', maxWidth: 360 }}>
                            {r.url}
                          </a>
                        )}
                      </div>
                    </div>
                  </td>
                  <td style={td}>{numOrDash(r.referring_domains)}</td>
                  <td style={td}><Authority value={r.url_rating} status={r.backlinks_status} /></td>
                  <td style={td}><Authority value={r.is_client ? clientDr : (r.domain ? drByDomain.get(r.domain) ?? null : null)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Per-domain Domain Rating */}
      {(snap.domains ?? []).length > 0 && (
        <section style={{ ...card, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px' }}>
            <SectionTitle title="Domain authority (DR)" />
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={table}>
              <thead>
                <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <th style={thLeft}>Domain</th>
                  <th style={th} title="Referring domains to the whole domain">Ref. domains</th>
                  <th style={th} title="Domain Rating — the whole domain's authority, 0–100">DR</th>
                </tr>
              </thead>
              <tbody>
                {snap.domains.map((d, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #f1f5f9', background: d.is_client ? '#eef2ff' : '#fff' }}>
                    <td style={tdLeft}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                        {d.is_client && <span style={clientChip}>client</span>}
                        <span style={{ fontWeight: 600, color: '#0f172a' }}>{d.domain}</span>
                      </span>
                    </td>
                    <td style={td}>{numOrDash(d.referring_domains)}</td>
                    <td style={td}><Authority value={d.domain_rating} status={d.backlinks_status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

export const SIGNAL_META: Record<string, { label: string; tip: string }> = {
  aio: { label: 'AI Overview', tip: 'An AI Overview appears for this query.' },
  local: { label: 'Local pack', tip: 'A local pack / map appears — local intent.' },
  forums: { label: 'Forums', tip: 'Discussions & forums shown — users want opinions & real experiences (often pre-purchase research).' },
  video: { label: 'Video', tip: 'Video results present — how-to / demo / visual intent.' },
  news: { label: 'News', tip: 'Top stories present — news & freshness (QDF) intent.' },
  shopping: { label: 'Shopping', tip: 'Shopping units / ads present — commercial / transactional intent.' },
  featured_snippet: { label: 'Snippet', tip: 'Featured snippet — direct-answer informational intent.' },
  paa: { label: 'PAA', tip: 'People Also Ask — research depth / unresolved sub-questions.' },
  knowledge: { label: 'Knowledge', tip: 'Knowledge panel — entity or navigational intent.' },
  images: { label: 'Images', tip: 'Image pack — visual intent.' },
  recipes: { label: 'Recipes', tip: 'Recipe results — recipe intent.' },
  jobs: { label: 'Jobs', tip: 'Jobs pack — job-seeking intent.' },
  events: { label: 'Events', tip: 'Events pack — events intent.' },
  listicle: { label: 'Listicle', tip: 'Roundup titles ("10 best…", "top N") — comparison / commercial-investigation intent.' },
  comparison: { label: 'Comparison', tip: '"vs" / "alternatives" titles — comparison intent.' },
  how_to: { label: 'How-to', tip: '"How to" / guide / tutorial titles — instructional intent.' },
  freshness: { label: 'Freshness', tip: 'Year-stamped titles — query deserves freshness (QDF).' },
  definitional: { label: 'Definitional', tip: '"What is" titles — informational / definitional intent.' },
  navigational: { label: 'Navigational', tip: 'Homepages dominate the results — brand / navigational intent.' },
}

export function SignalChip({ signal }: { signal: string }) {
  const m = SIGNAL_META[signal]
  const label = m?.label ?? signal
  return <span style={signalChip} title={m?.tip ?? signal}>{label}</span>
}

// DataForSEO's UR/DR rank is 0–1000; display it on the familiar Ahrefs-style
// 0–100 scale (raw value is kept in the DB for the rankability calc). Referring
// domains (RD) are a real count and are NOT scaled.
export function ahrefsScale(value: number | null | undefined): number | null {
  return value == null ? null : Math.round(value / 10)
}

function Authority({ value, status }: { value: number | null; status?: string }) {
  if (value == null) {
    if (status === 'failed') return <span style={{ color: '#dc2626', fontSize: 11 }}>failed</span>
    return <span style={{ color: '#cbd5e1' }}>—</span>
  }
  // Colour off the raw 0–1000 value; show the 0–100-scaled number.
  const strong = value >= 400
  const mid = value >= 150
  const color = strong ? '#15803d' : mid ? '#b45309' : '#64748b'
  return <span style={{ fontWeight: 700, color }}>{ahrefsScale(value)}</span>
}

function IntentBadge({ intent }: { intent: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    informational: { color: '#0369a1', bg: '#e0f2fe' },
    commercial: { color: '#7c3aed', bg: '#f3e8ff' },
    transactional: { color: '#15803d', bg: '#dcfce7' },
    navigational: { color: '#b45309', bg: '#fffbeb' },
  }
  const s = map[intent] ?? { color: '#475569', bg: '#f1f5f9' }
  return <span style={{ ...miniBadge, color: s.color, background: s.bg, textTransform: 'capitalize' }}>{intent}</span>
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    complete: { color: '#15803d', bg: '#dcfce7' },
    partial: { color: '#b45309', bg: '#fffbeb' },
    failed: { color: '#b91c1c', bg: '#fef2f2' },
  }
  const s = map[status] ?? { color: '#475569', bg: '#f1f5f9' }
  return <span style={{ ...miniBadge, color: s.color, background: s.bg }}>{status}</span>
}

function SectionTitle({ icon, title }: { icon?: React.ReactNode; title: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
      {icon}
      <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{title}</span>
    </div>
  )
}

function numOrDash(n: number | null) {
  return n == null ? <span style={{ color: '#cbd5e1' }}>—</span> : n.toLocaleString()
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 24 }
const panel: React.CSSProperties = { background: '#fff', borderRadius: 14, width: '100%', maxWidth: 920, maxHeight: '88vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,0.25)' }
const header: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid #e2e8f0' }
const body: React.CSSProperties = { display: 'flex', minHeight: 0, flex: 1 }
const sidebar: React.CSSProperties = { width: 240, flexShrink: 0, borderRight: '1px solid #e2e8f0', padding: 14, overflowY: 'auto' }
const detailPane: React.CSSProperties = { flex: 1, minWidth: 0, padding: 16, overflowY: 'auto', background: '#fafbfc' }
const iconBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4, display: 'inline-flex' }
const hint: React.CSSProperties = { marginTop: 10, fontSize: 11, color: '#64748b', lineHeight: 1.5, background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '8px 10px' }
const snapItem: React.CSSProperties = { textAlign: 'left', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', cursor: 'pointer', fontSize: 12 }
const snapItemActive: React.CSSProperties = { borderColor: '#6366f1', background: '#eef2ff' }
const miniBadge: React.CSSProperties = { fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px' }
const signalChip: React.CSSProperties = { fontSize: 10, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: 999, padding: '2px 8px', cursor: 'help' }
const clientChip: React.CSSProperties = { fontSize: 9, fontWeight: 700, color: '#4338ca', background: '#e0e7ff', borderRadius: 4, padding: '1px 5px', flexShrink: 0 }
const looseChip: React.CSSProperties = { fontSize: 9, fontWeight: 600, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 4, padding: '1px 5px', flexShrink: 0, whiteSpace: 'nowrap', cursor: 'help' }
const generalistChip: React.CSSProperties = { fontSize: 9, fontWeight: 600, color: '#0e7490', background: '#ecfeff', border: '1px solid #a5f3fc', borderRadius: 4, padding: '1px 5px', flexShrink: 0, whiteSpace: 'nowrap', cursor: 'help' }
const sourceLink: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#6366f1', textDecoration: 'none' }
const table: React.CSSProperties = { borderCollapse: 'collapse', width: '100%', fontSize: 12 }
const th: React.CSSProperties = { padding: '8px 12px', textAlign: 'right', fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const thNum: React.CSSProperties = { ...th, textAlign: 'center', width: 32 }
const td: React.CSSProperties = { padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left' }
const tdNum: React.CSSProperties = { ...td, textAlign: 'center', color: '#64748b', fontWeight: 600 }
