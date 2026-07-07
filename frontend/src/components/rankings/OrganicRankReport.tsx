import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BarChart3, ExternalLink, FileText, TrendingDown, TrendingUp, Minus, X } from 'lucide-react'
import { api } from '../../lib/api'
import { Markdown } from '../Markdown'
import { card, errorBox, primaryBtn } from '../localseo/shared'

// Organic Rank Analysis report viewer — the per-keyword deep-dive (the organic
// analogue of the Maps Local Rank Analysis report). Opened per tracked keyword:
// generates an on-demand report (reusing the latest SERP snapshot — prompts to
// capture one first when none exists), polls while it renders, and shows the
// trajectory verdict + winnability at-a-glance, the Sonnet narrative, the
// deterministic gap-to-close work order, and the published Google Doc link.

interface WorkOrderItem {
  type: string
  headline: string
  detail: string
  severity: number
  leverage: number
  cta: string
}

interface RankReportRow {
  id: string
  status: 'pending' | 'complete' | 'failed'
  trigger?: string
  error?: string | null
  report_md?: string | null
  report_headline?: string | null
  report_analytics?: Record<string, any> | null
  report_work_order?: WorkOrderItem[] | null
  priority?: number | null
  doc_url?: string | null
  generated_at?: string | null
  created_at?: string
}

interface HistoryRow {
  id: string
  status: string
  trigger?: string
  priority?: number | null
  report_headline?: string | null
  generated_at?: string | null
  created_at?: string
  doc_url?: string | null
}

type GenerateResponse =
  | { status: 'needs_snapshot'; detail: string }
  | { status: 'pending'; report_id: string | null; already_running?: boolean }

const CTA_LABELS: Record<string, string> = {
  link_building: 'Build links (Recipe Engine)',
  create_page: 'Create a page (Local SEO / Content)',
  reoptimize_page: 'Reoptimize the ranking page',
  consolidate: 'Consolidate competing pages (GSC Research)',
}

export function OrganicRankReport({ keywordId, keyword, onClose }: {
  keywordId: string; keyword: string; onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [needsSnapshot, setNeedsSnapshot] = useState(false)
  const [polling, setPolling] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const pollCount = useRef(0)
  const MAX_POLLS = 90 // ~9 min at 6s — a report is one LLM call, well within this.

  // The latest (or explicitly selected) report for this keyword.
  const { data: latest } = useQuery<RankReportRow>({
    queryKey: ['rank-analysis-latest', keywordId],
    queryFn: () => api.get<RankReportRow>(`/tracked-keywords/${keywordId}/analysis`),
    refetchInterval: polling ? 6000 : false,
  })
  const { data: history } = useQuery<HistoryRow[]>({
    queryKey: ['rank-analysis-history', keywordId],
    queryFn: () => api.get<HistoryRow[]>(`/tracked-keywords/${keywordId}/analysis/history`),
  })

  // A report was requested — poll the latest until it lands (or times out).
  useEffect(() => {
    if (!polling) return
    const status = latest?.status
    if (status === 'complete' || status === 'failed') {
      setPolling(false)
      pollCount.current = 0
      setSelectedId(latest?.id ?? null)
      queryClient.invalidateQueries({ queryKey: ['rank-analysis-history', keywordId] })
      return
    }
    pollCount.current += 1
    if (pollCount.current >= MAX_POLLS) setPolling(false)
  }, [latest, polling, keywordId, queryClient])

  const genMut = useMutation({
    mutationFn: () => api.post<GenerateResponse>(`/tracked-keywords/${keywordId}/analysis`, {}),
    onSuccess: (res) => {
      if (res.status === 'needs_snapshot') {
        setNeedsSnapshot(true)
        return
      }
      setNeedsSnapshot(false)
      pollCount.current = 0
      setPolling(true)
      setSelectedId(null)
      queryClient.invalidateQueries({ queryKey: ['rank-analysis-latest', keywordId] })
    },
  })

  // The report shown in the detail pane: an explicitly-selected history row, else
  // the latest. A selected id fetches on demand; latest is already loaded.
  const showLatest = !selectedId || selectedId === latest?.id
  const detail = showLatest ? latest : undefined

  return (
    <div style={overlay} onClick={onClose}>
      <div style={panel} onClick={(e) => e.stopPropagation()}>
        <div style={header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <BarChart3 size={18} color="#6366f1" />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>Organic Rank Analysis</div>
              <div style={{ fontSize: 12, color: '#64748b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{keyword}</div>
            </div>
          </div>
          <button style={iconBtn} onClick={onClose} title="Close"><X size={16} /></button>
        </div>

        <div style={body}>
          {/* Left: generate + history */}
          <div style={sidebar}>
            <button style={{ ...primaryBtn, width: '100%', justifyContent: 'center' }}
              onClick={() => genMut.mutate()} disabled={polling || genMut.isPending}>
              <FileText size={14} /> {polling ? 'Generating…' : genMut.isPending ? 'Starting…' : 'Generate report'}
            </button>
            {genMut.error && <div style={{ ...errorBox, marginTop: 8 }}>{(genMut.error as Error).message}</div>}
            {needsSnapshot && (
              <div style={{ ...hint, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' }}>
                No SERP snapshot yet. This report analyzes the latest Competitive SERP Snapshot — capture
                one first with the camera button on this keyword, then generate the report.
              </div>
            )}
            {polling && (
              <div style={hint}>
                Assembling the trajectory + competitive landscape and writing the analysis (one LLM pass).
                This takes about a minute — it appears here when it lands.
              </div>
            )}
            {pollCount.current >= MAX_POLLS && !polling && detail?.status !== 'complete' && (
              <div style={{ ...hint, background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' }}>
                Still working — this is taking longer than expected. It keeps running in the background;
                reopen this panel later.
              </div>
            )}
            <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(history ?? []).length === 0 && !polling && (
                <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.5 }}>
                  No reports yet. Generate one to get a full per-keyword diagnosis — trajectory, the
                  competitive landscape, who's beating you and why, and a ranked work order.
                </div>
              )}
              {(history ?? []).map(h => (
                <button key={h.id} onClick={() => setSelectedId(h.id)}
                  style={{ ...snapItem, ...(((selectedId ?? latest?.id) === h.id) ? snapItemActive : {}) }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                    <span style={{ fontWeight: 600, color: '#0f172a' }}>
                      {new Date(h.generated_at || h.created_at || '').toLocaleDateString()}
                    </span>
                    <StatusPill status={h.status} />
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                    {h.trigger && h.trigger !== 'on_demand' ? `${h.trigger} · ` : ''}
                    {h.priority != null ? `priority ${Math.round(h.priority).toLocaleString()}` : '—'}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Right: report detail */}
          <div style={detailPane}>
            {selectedId && !showLatest
              ? <ReportDetail reportId={selectedId} />
              : <ReportBody report={detail} empty={!detail || detail.status === undefined} />}
          </div>
        </div>
      </div>
    </div>
  )
}

function ReportDetail({ reportId }: { reportId: string }) {
  const { data, isLoading } = useQuery<RankReportRow>({
    queryKey: ['rank-analysis-report', reportId],
    queryFn: () => api.get<RankReportRow>(`/rank-keyword-reports/${reportId}`),
  })
  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 13 }}>Loading report…</p>
  return <ReportBody report={data} empty={!data} />
}

function ReportBody({ report, empty }: { report?: RankReportRow; empty?: boolean }) {
  if (empty || !report || report.status === undefined) {
    return (
      <div style={{ color: '#94a3b8', fontSize: 13, padding: 24, textAlign: 'center' }}>
        Generate a report to see the full analysis.
      </div>
    )
  }
  if (report.status === 'pending') {
    return <p style={{ color: '#94a3b8', fontSize: 13 }}>Report is generating…</p>
  }
  if (report.status === 'failed') {
    return (
      <div style={errorBox}>
        This report failed{report.error ? `: ${report.error}` : '.'} Generate again to retry.
      </div>
    )
  }

  const a = report.report_analytics || {}
  const traj = a.trajectory || {}
  const win = a.winnability || {}
  const market = a.market || {}
  const gap = a.authority_gap || {}
  const workOrder = report.report_work_order || a.work_order || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Meta + Doc link */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          {report.generated_at ? new Date(report.generated_at).toLocaleString() : ''}
        </span>
        {report.doc_url && (
          <a href={report.doc_url} target="_blank" rel="noreferrer" style={sourceLink}>
            <ExternalLink size={12} /> View Google Doc
          </a>
        )}
      </div>

      {/* At a glance */}
      <div style={glanceGrid}>
        <Stat label="Position" value={fmtPos(traj.current_position)} sub={velocityLabel(traj.velocity)} dir={traj.velocity} />
        <Stat label="Projected 90d" value={fmtPos(traj.projected_position_90d)} sub={traj.confidence ? `${traj.confidence} confidence` : ''} />
        <Stat label="Winnability" value={win.score != null ? String(win.score) : '—'} sub={win.band || ''} />
        <Stat label="Priority" value={report.priority != null ? Math.round(report.priority).toLocaleString() : '—'}
          sub={market.est_value != null ? `$${Math.round(market.est_value).toLocaleString()}/mo value` : ''} />
      </div>

      {gap.rd_to_match != null && gap.rd_to_match > 0 && (
        <div style={{ fontSize: 12, color: '#334155', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 12px' }}>
          Authority gap: needs <strong>~{gap.rd_to_match}</strong> more referring domains to match the median
          top-10 page ({gap.median_competitor_rd ?? '—'} vs {gap.client_rd ?? 0}).
        </div>
      )}

      {/* Narrative */}
      {report.report_md && (
        <section style={{ ...card, fontSize: 13, lineHeight: 1.65, color: '#334155' }}>
          <Markdown>{report.report_md}</Markdown>
        </section>
      )}

      {/* Deterministic work order */}
      {workOrder.length > 0 && (
        <section style={{ ...card, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '12px 14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>Recommended focus</span>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>ranked by leverage</span>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {workOrder.map((w: WorkOrderItem, i: number) => (
              <div key={i} style={{ padding: '10px 14px', borderTop: '1px solid #f1f5f9', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <LeverageBadge value={w.leverage} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{w.headline}</div>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{w.detail}</div>
                  <div style={{ fontSize: 11, color: '#6366f1', marginTop: 4, fontWeight: 600 }}>
                    {CTA_LABELS[w.cta] || w.cta}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Stat({ label, value, sub, dir }: { label: string; value: string; sub?: string; dir?: string }) {
  const Icon = dir === 'improving' || dir === 'improving_fast' ? TrendingUp
    : dir === 'declining' || dir === 'declining_fast' ? TrendingDown
    : dir ? Minus : null
  const color = dir === 'improving' || dir === 'improving_fast' ? '#15803d'
    : dir === 'declining' || dir === 'declining_fast' ? '#dc2626' : '#64748b'
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px' }}>
      <div style={{ fontSize: 10, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', marginTop: 2 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 11, color, marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
          {Icon && <Icon size={11} />}{sub}
        </div>
      )}
    </div>
  )
}

function LeverageBadge({ value }: { value: number }) {
  const color = value >= 70 ? '#dc2626' : value >= 45 ? '#b45309' : '#64748b'
  const bg = value >= 70 ? '#fef2f2' : value >= 45 ? '#fffbeb' : '#f1f5f9'
  return (
    <span style={{ flexShrink: 0, fontSize: 11, fontWeight: 700, color, background: bg, borderRadius: 6, padding: '3px 8px', minWidth: 34, textAlign: 'center' }}>
      {value}
    </span>
  )
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    complete: { color: '#15803d', bg: '#dcfce7' },
    pending: { color: '#b45309', bg: '#fffbeb' },
    failed: { color: '#b91c1c', bg: '#fef2f2' },
  }
  const s = map[status] ?? { color: '#475569', bg: '#f1f5f9' }
  return <span style={miniBadge(s.color, s.bg)}>{status}</span>
}

function fmtPos(p: number | null | undefined): string {
  return p == null ? '—' : `#${Number(p).toFixed(p < 10 ? 1 : 0)}`
}

const VELOCITY_LABELS: Record<string, string> = {
  improving_fast: 'Improving fast', improving: 'Improving', holding: 'Holding',
  declining: 'Declining', declining_fast: 'Declining fast', flat: 'No trend',
}
function velocityLabel(v?: string): string {
  return v ? VELOCITY_LABELS[v] || '' : ''
}

const overlay: React.CSSProperties = { position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 24 }
const panel: React.CSSProperties = { background: '#fff', borderRadius: 14, width: '100%', maxWidth: 940, maxHeight: '90vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 60px rgba(0,0,0,0.25)' }
const header: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid #e2e8f0' }
const body: React.CSSProperties = { display: 'flex', minHeight: 0, flex: 1 }
const sidebar: React.CSSProperties = { width: 240, flexShrink: 0, borderRight: '1px solid #e2e8f0', padding: 14, overflowY: 'auto' }
const detailPane: React.CSSProperties = { flex: 1, minWidth: 0, padding: 16, overflowY: 'auto', background: '#fafbfc' }
const iconBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 4, display: 'inline-flex' }
const hint: React.CSSProperties = { marginTop: 10, fontSize: 11, color: '#64748b', lineHeight: 1.5, background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '8px 10px' }
const snapItem: React.CSSProperties = { textAlign: 'left', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', cursor: 'pointer', fontSize: 12 }
const snapItemActive: React.CSSProperties = { borderColor: '#6366f1', background: '#eef2ff' }
const glanceGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8 }
const sourceLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#6366f1', textDecoration: 'none' }
function miniBadge(color: string, bg: string): React.CSSProperties {
  return { fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px', color, background: bg }
}
