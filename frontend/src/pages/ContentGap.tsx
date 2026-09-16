import { Fragment, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Download, Radar, RefreshCw, Wand2,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { Client } from '../lib/types'

// ── Types (mirror models/content_gap.py + the run-detail jsonb payloads) ─────
interface RunSummary {
  id: string
  trigger: string
  status: 'pending' | 'running' | 'complete' | 'partial' | 'failed'
  keywords_analyzed: number | null
  wins: number | null
  gaps: number | null
  error: string | null
  created_at: string | null
  completed_at: string | null
}
interface StatusResponse {
  enabled: boolean
  auto_enabled: boolean
  budget_remaining: number
  runs: RunSummary[]
}
interface EstimateResponse {
  enabled: boolean
  keyword_count: number
  money_page_count: number
  scope: { keyword: string; page_url: string | null; keyword_id: string | null }[]
  estimated_max_calls: number
  budget_remaining: number
  max_competitors: number
  snapshot_max_age_days: number
}
type Verdict = 'win' | 'aio_gap' | 'organic_gap' | 'full_gap'
interface Competitor { domain: string; url?: string | null; position?: number | null; registered?: boolean }
interface AuthorityGap {
  client?: { page_rd?: number | null; page_ur?: number | null; domain_rd?: number | null; dr?: number | null } | null
  competitors?: { domain?: string; position?: number | null; page_rd?: number | null; domain_rd?: number | null; dr?: number | null }[]
  competitor_page_rd_median?: number | null
  competitor_domain_rd_median?: number | null
  competitor_dr_median?: number | null
  page_rd_gap?: number | null
  domain_rd_gap?: number | null
  dr_gap?: number | null
  caveat?: string
}
interface TrafficGap {
  basis?: string
  client?: number | null
  competitor_median?: number | null
  delta?: number | null
  competitors?: { domain?: string; url?: string | null; organic_traffic_est?: number | null; estimate?: number | null }[]
}
interface EntityGap {
  serp_entities?: { name?: string; type?: string; page_spread?: number | null; recommended_mentions?: number | null; wiki_link?: string | null }[]
  serp_entity_count?: number
  client_deficiencies?: { engine?: string; engine_key?: string; score?: number | null; issues?: string[]; recommendations?: string[] }[]
}
interface OnpageScore {
  composite_score?: number | null
  composite_status?: string | null
  deficiencies?: { engine?: string; score?: number | null; issues?: string[]; recommendations?: string[] }[]
}
interface Gap {
  authority?: AuthorityGap
  aio_citation?: { cited_sources_not_client?: { domain?: string; url?: string | null; title?: string | null }[] }
  entities?: EntityGap
  onpage_score?: OnpageScore
  site_traffic?: TrafficGap
  page_traffic?: TrafficGap
  dimensions_unavailable?: string[]
}
interface OnpageDiff {
  client_available?: boolean
  competitors_compared?: number
  competitors_unavailable?: number
  subtopic_gap?: { heading: string; covered_by: string[]; count: number }[]
  word_count?: { client?: number | null; competitor_median?: number | null; delta?: number | null }
  element_gap?: { element: string; label: string; covered_by: string[]; count: number }[]
  schema_gap?: { schema: string; covered_by: string[]; count: number }[]
  title?: { client?: string | null; competitors?: { domain?: string; title?: string | null }[] }
  meta_description?: { client?: string | null; client_present?: boolean | null; competitors_with_meta?: number }
}
interface KeywordRow {
  id: string
  keyword: string
  page_url: string | null
  client_position: number | null
  aio_present: boolean | null
  in_aio: boolean | null
  verdict: Verdict
  competitors: Competitor[] | null
  gap: Gap | null
  onpage_diff: OnpageDiff | null
  serp_snapshot_id: string | null
  captured_fresh: boolean
}
interface RunDetail { run: RunSummary; keywords: KeywordRow[] }

// ── Verdict presentation ─────────────────────────────────────────────────────
const VERDICT: Record<Verdict, { label: string; bg: string; fg: string }> = {
  win: { label: 'Winning', bg: '#f0fdf4', fg: '#16a34a' },
  aio_gap: { label: 'AIO gap', bg: '#fefce8', fg: '#ca8a04' },
  organic_gap: { label: 'Organic gap', bg: '#fff7ed', fg: '#ea580c' },
  full_gap: { label: 'Full gap', bg: '#fef2f2', fg: '#dc2626' },
}
function fmt(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits })
}
function gapArrow(delta: number | null | undefined): string {
  // Positive delta = competitors ahead (a gap to close).
  if (delta == null) return '—'
  if (delta > 0) return `behind by ${fmt(delta)}`
  if (delta < 0) return `ahead by ${fmt(Math.abs(delta))}`
  return 'even'
}

// Cap the deep-linked gap notes so the whole URL stays well within browser
// limits (the reopt panel + nlp also truncate defensively).
const GAP_NOTES_MAX_SUBTOPICS = 8

// Compact writer_notes-style guidance from the on-page diff's subtopic gap — the
// subtopics the top competitors cover that this page doesn't (§11.1: supplementary
// rewrite guidance, NOT a scored deficiency). Returns '' when there's nothing to add.
function gapNotesFor(row: KeywordRow): string {
  const subs = (row.onpage_diff?.subtopic_gap ?? [])
    .map(s => s.heading?.trim())
    .filter((h): h is string => Boolean(h))
    .slice(0, GAP_NOTES_MAX_SUBTOPICS)
  if (subs.length === 0) return ''
  return `Content-gap analysis — the top-ranking competitors cover these subtopics that this page doesn't. Add them where they fit naturally (don't invent facts): ${subs.join('; ')}.`
}

// The "Reoptimize this page" deep-link (§11.1). LocalSeoContent's reopt tab
// reads url + keyword and prefills the ReoptimizePanel's single-URL + keyword
// inputs, so the handoff arrives runnable (Local SEO reopt requires a keyword);
// gapnotes seeds the (editable) Notes field with the subtopic gaps.
function reoptLink(clientId: string, row: KeywordRow): string {
  const params = new URLSearchParams({ tab: 'reopt' })
  if (row.page_url) params.set('url', row.page_url)
  if (row.keyword) params.set('keyword', row.keyword)
  const gapNotes = gapNotesFor(row)
  if (gapNotes) params.set('gapnotes', gapNotes)
  return `/clients/${clientId}/local-seo?${params.toString()}`
}

// ── styles ───────────────────────────────────────────────────────────────────
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 16 }
const chip = (bg: string, fg: string): React.CSSProperties => ({
  fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: bg, color: fg, whiteSpace: 'nowrap',
})
const th: React.CSSProperties = { textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#6b7280', padding: '8px 10px', textTransform: 'uppercase', letterSpacing: 0.4 }
const td: React.CSSProperties = { fontSize: 13, padding: '8px 10px', borderTop: '1px solid #f1f5f9', verticalAlign: 'top' }
const primaryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const outlineBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#fff', color: '#374151', border: '1px solid #d1d5db', borderRadius: 8, padding: '7px 12px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const dimTitle: React.CSSProperties = { fontSize: 12, fontWeight: 700, color: '#374151', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.3 }
const unavailPill: React.CSSProperties = { fontSize: 11, color: '#9ca3af', fontStyle: 'italic' }

function scanError(err: string): string {
  const map: Record<string, string> = {
    content_gap_disabled: 'The Content Gap Analyzer is not enabled yet.',
    budget_exceeded: "Today's analysis budget is used up — try again tomorrow or raise the cap.",
    forbidden: 'Running a scan is staff-only.',
  }
  return map[err] || err || 'Could not start the scan.'
}

export function ContentGap() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isStaff } = useAuth()
  const [runId, setRunId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [clientView, setClientView] = useState(false) // internal (default) vs softened client summary
  const [error, setError] = useState('')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id], queryFn: () => api.get<Client>(`/clients/${id}`), enabled: Boolean(id),
  })
  const { data: status } = useQuery<StatusResponse>({
    queryKey: ['content-gap', id], queryFn: () => api.get<StatusResponse>(`/clients/${id}/content-gap`), enabled: Boolean(id),
  })
  const { data: estimate } = useQuery<EstimateResponse>({
    queryKey: ['content-gap-estimate', id],
    queryFn: () => api.get<EstimateResponse>(`/clients/${id}/content-gap/estimate`),
    enabled: Boolean(id && status?.enabled),
  })

  // Poll the selected run until it settles.
  const { data: detail } = useQuery<RunDetail>({
    queryKey: ['content-gap-run', id, runId],
    queryFn: () => api.get<RunDetail>(`/clients/${id}/content-gap/runs/${runId}`),
    enabled: Boolean(id && runId),
    refetchInterval: (q) => {
      const s = (q.state.data as RunDetail | undefined)?.run?.status
      return s === 'pending' || s === 'running' ? 2500 : false
    },
  })

  const scan = useMutation({
    mutationFn: () => api.post<{ run_id: string; status: string }>(`/clients/${id}/content-gap/scan`, {}),
    onSuccess: (r) => {
      setError('')
      setRunId(r.run_id)
      queryClient.invalidateQueries({ queryKey: ['content-gap', id] })
    },
    onError: (e: unknown) => setError(scanError(e instanceof Error ? e.message : '')),
  })

  const runBusy = scan.isPending || detail?.run.status === 'pending' || detail?.run.status === 'running'

  function toggle(k: string) {
    setExpanded((p) => ({ ...p, [k]: !p[k] }))
  }
  function exportCsv() {
    if (!runId) return
    void api.download(`/clients/${id}/content-gap/runs/${runId}/export`, `content-gap-${runId}.csv`)
  }

  const rows = useMemo(() => detail?.keywords ?? [], [detail])
  const gapCount = useMemo(() => rows.filter((r) => r.verdict !== 'win').length, [rows])

  if (status && !status.enabled) {
    return (
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 16px' }}>
        <BackLink id={id} client={client} navigate={navigate} />
        <div style={{ ...card, marginTop: 16, textAlign: 'center', color: '#6b7280' }}>
          <Radar size={26} style={{ color: '#9ca3af' }} />
          <h2 style={{ fontSize: 18, margin: '10px 0 6px' }}>Content Gap Analyzer</h2>
          <p style={{ fontSize: 14 }}>This module isn’t enabled for the workspace yet.</p>
        </div>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 16px 64px' }}>
      <BackLink id={id} client={client} navigate={navigate} />

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, margin: '12px 0 20px', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Radar size={24} style={{ color: '#4f46e5' }} /> Content Gap Analyzer
          </h1>
          <p style={{ color: '#6b7280', fontSize: 14, margin: '6px 0 0', maxWidth: 640 }}>
            For each tracked keyword × money page, are you winning the SERP — top-10 organic and cited in the AI
            Overview? Where not, exactly what the competitors above you have that you don’t.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {isStaff ? (
            <button style={{ ...primaryBtn, opacity: runBusy ? 0.6 : 1 }} disabled={runBusy} onClick={() => scan.mutate()}>
              <RefreshCw size={15} className={runBusy ? 'spin' : undefined} /> {runBusy ? 'Scanning…' : 'Run scan'}
            </button>
          ) : (
            <span style={unavailPill}>Staff can run a scan.</span>
          )}
        </div>
      </div>

      {error && <div style={{ ...card, marginBottom: 16, borderColor: '#fecaca', background: '#fef2f2', color: '#b91c1c', fontSize: 13 }}>{error}</div>}

      {/* Scope preview + budget */}
      {estimate && (
        <div style={{ ...card, marginBottom: 16, display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
          <Stat label="Keywords in scope" value={fmt(estimate.keyword_count)} />
          <Stat label="With a money page" value={fmt(estimate.money_page_count)} />
          <Stat label="Max analysis calls" value={fmt(estimate.estimated_max_calls)} hint="worst case — wins short-circuit" />
          <Stat label="Budget left today" value={fmt(estimate.budget_remaining)} />
          {status?.auto_enabled && <span style={chip('#eef2ff', '#4f46e5')}>Auto-runs monthly</span>}
        </div>
      )}

      {/* Run history */}
      {status && status.runs.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
          {status.runs.slice(0, 12).map((r) => {
            const active = r.id === runId
            return (
              <button
                key={r.id}
                onClick={() => setRunId(r.id)}
                style={{
                  ...outlineBtn, padding: '6px 10px', fontSize: 12,
                  borderColor: active ? '#4f46e5' : '#d1d5db', color: active ? '#4f46e5' : '#374151',
                  background: active ? '#eef2ff' : '#fff',
                }}
              >
                {r.created_at ? new Date(r.created_at).toLocaleDateString() : 'run'}
                {' · '}
                {r.status === 'complete' || r.status === 'partial'
                  ? `${r.gaps ?? 0} gap${(r.gaps ?? 0) === 1 ? '' : 's'}`
                  : r.status}
                {r.trigger === 'scheduled' && ' · auto'}
              </button>
            )
          })}
        </div>
      )}

      {/* Selected run */}
      {runId && detail && (
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 15 }}>
                {detail.run.status === 'pending' || detail.run.status === 'running'
                  ? 'Analyzing…'
                  : `${gapCount} gap${gapCount === 1 ? '' : 's'} of ${rows.length} keyword${rows.length === 1 ? '' : 's'}`}
              </strong>
              {detail.run.status === 'partial' && (
                <span style={chip('#fefce8', '#ca8a04')} title="Some keywords are pending a fresh SERP capture or hit the budget — re-run to finish.">Partial · re-run to finish</span>
              )}
              {detail.run.status === 'failed' && <span style={chip('#fef2f2', '#dc2626')}>Failed{detail.run.error ? `: ${detail.run.error}` : ''}</span>}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <label style={{ fontSize: 12, color: '#6b7280', display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="checkbox" checked={clientView} onChange={(e) => setClientView(e.target.checked)} />
                Client summary
              </label>
              {rows.length > 0 && (
                <button style={outlineBtn} onClick={exportCsv}><Download size={14} /> CSV</button>
              )}
            </div>
          </div>

          {rows.length === 0 && (detail.run.status === 'complete' || detail.run.status === 'partial') && (
            <p style={{ color: '#6b7280', fontSize: 13, margin: 0 }}>
              No keywords analyzed. A keyword needs a recent SERP snapshot; the scan enqueued fresh captures where missing —
              re-run once they finish.
            </p>
          )}

          {rows.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ ...th, width: 28 }} />
                    <th style={th}>Keyword</th>
                    <th style={th}>Verdict</th>
                    <th style={th}>Org. pos</th>
                    <th style={th}>AIO</th>
                    <th style={th}>Competitors</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const v = VERDICT[r.verdict]
                    const isOpen = !!expanded[r.id]
                    const hasDrill = r.verdict !== 'win' && (r.gap || r.onpage_diff || (r.competitors && r.competitors.length > 0))
                    return (
                      <Fragment key={r.id}>
                        <tr style={{ cursor: hasDrill ? 'pointer' : 'default' }} onClick={() => hasDrill && toggle(r.id)}>
                          <td style={td}>{hasDrill ? (isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />) : null}</td>
                          <td style={{ ...td, fontWeight: 600 }}>
                            {r.keyword}
                            {r.page_url && (
                              <div style={{ fontSize: 11, color: '#9ca3af', wordBreak: 'break-all' }}>{r.page_url}</div>
                            )}
                          </td>
                          <td style={td}><span style={chip(v.bg, v.fg)}>{v.label}</span></td>
                          <td style={td}>{r.client_position ?? <span style={{ color: '#dc2626' }}>not top-10</span>}</td>
                          <td style={td}>{r.aio_present == null ? '—' : !r.aio_present ? <span style={{ color: '#9ca3af' }}>N/A</span> : r.in_aio ? <span style={{ color: '#16a34a' }}>✓ cited</span> : <span style={{ color: '#dc2626' }}>✗ absent</span>}</td>
                          <td style={td}>{r.competitors?.length ?? 0}</td>
                        </tr>
                        {isOpen && hasDrill && (
                          <tr>
                            <td />
                            <td colSpan={5} style={{ padding: '4px 10px 16px' }}>
                              <Drill row={r} clientView={clientView} clientId={id!} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {!runId && status && status.runs.length === 0 && (
        <div style={{ ...card, textAlign: 'center', color: '#6b7280' }}>
          <p style={{ fontSize: 14, margin: 0 }}>No scans yet. {isStaff ? 'Run one to see where this client is winning or trailing on their money-page keywords.' : 'A staff member can run the first scan.'}</p>
        </div>
      )}
      <style>{`.spin{animation:cgspin 1s linear infinite}@keyframes cgspin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}

function BackLink({ id, client, navigate }: { id?: string; client?: Client; navigate: ReturnType<typeof useNavigate> }) {
  return (
    <button onClick={() => navigate(id ? `/clients/${id}` : '/clients')} style={{ ...outlineBtn, border: 'none', padding: 0, color: '#6b7280' }}>
      <ArrowLeft size={16} /> {client?.name ?? 'Workspace'}
    </button>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
      <div style={{ fontSize: 11, color: '#6b7280' }}>{label}</div>
      {hint && <div style={{ fontSize: 10, color: '#9ca3af' }}>{hint}</div>}
    </div>
  )
}

// ── Per-keyword drill-in ─────────────────────────────────────────────────────
function Drill({ row, clientView, clientId }: { row: KeywordRow; clientView: boolean; clientId: string }) {
  const gap = row.gap ?? {}
  const diff = row.onpage_diff ?? undefined
  const unavailable = new Set(gap.dimensions_unavailable ?? [])
  const comps = row.competitors ?? []

  return (
    <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 8, padding: 14, display: 'grid', gap: 14 }}>
      {/* Competitor set */}
      <Section title="Competitors ranking above you">
        {comps.length === 0 ? (
          <span style={unavailPill}>No competitors resolved for this keyword.</span>
        ) : (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {comps.map((c, i) => (
              <span key={i} style={chip('#eef2ff', '#4338ca')}>
                {c.position != null ? `#${c.position} ` : ''}{c.domain}{c.registered ? ' ★' : ''}
              </span>
            ))}
          </div>
        )}
      </Section>

      {clientView ? (
        <ClientSummary gap={gap} diff={diff} />
      ) : (
        <>
          <AuthorityDim gap={gap} unavailable={unavailable} />
          <TrafficDim gap={gap} unavailable={unavailable} />
          <EntityDim gap={gap} unavailable={unavailable} />
          <OnpageDim diff={diff} unavailable={unavailable} />
        </>
      )}

      {/* Reoptimize handoff (§11.1) */}
      {row.page_url && (
        <div style={{ borderTop: '1px dashed #e5e7eb', paddingTop: 12, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Link
            to={reoptLink(clientId, row)}
            style={{ ...primaryBtn, textDecoration: 'none' }}
            title="Opens the Reoptimize tool with this page's URL + keyword prefilled — scores it against the SERP and rewrites to threshold."
          >
            <Wand2 size={15} /> Reoptimize this page <ArrowRight size={14} />
          </Link>
          <span style={{ fontSize: 11, color: '#9ca3af', wordBreak: 'break-all' }}>{row.page_url}</span>
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={dimTitle}>{title}</div>
      {children}
    </div>
  )
}

function Unavailable({ what }: { what: string }) {
  return <span style={unavailPill}>{what} unavailable for this keyword (page couldn’t be measured).</span>
}

function AuthorityDim({ gap, unavailable }: { gap: Gap; unavailable: Set<string> }) {
  const a = gap.authority
  return (
    <Section title="Authority (referring domains / DR)">
      {unavailable.has('authority') || !a ? (
        <Unavailable what="Authority data" />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 12 }}>
            <Metric label="Page RD gap" value={gapArrow(a.page_rd_gap)} />
            <Metric label="Domain RD gap" value={gapArrow(a.domain_rd_gap)} />
            <Metric label="DR gap" value={gapArrow(a.dr_gap)} />
          </div>
          {a.caveat && <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 6 }}>{a.caveat}</div>}
        </>
      )}
    </Section>
  )
}

function TrafficDim({ gap, unavailable }: { gap: Gap; unavailable: Set<string> }) {
  const site = gap.site_traffic
  const page = gap.page_traffic
  if (!site && !page && !unavailable.has('site_traffic') && !unavailable.has('page_traffic')) return null
  return (
    <Section title="Traffic (estimated)">
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 12 }}>
        {unavailable.has('site_traffic') ? <Unavailable what="Site traffic" /> : site && (
          <Metric label="Site traffic gap" value={gapArrow(site.delta)} hint={`you ${fmt(site.client)} · median ${fmt(site.competitor_median)}`} />
        )}
        {unavailable.has('page_traffic') ? <Unavailable what="Page traffic" /> : page && (
          <Metric label="Page traffic gap (modeled)" value={gapArrow(page.delta)} hint={`you ${fmt(page.client)} · median ${fmt(page.competitor_median)}`} />
        )}
      </div>
    </Section>
  )
}

function EntityDim({ gap, unavailable }: { gap: Gap; unavailable: Set<string> }) {
  const e = gap.entities
  const score = gap.onpage_score
  if (!e && !score && !unavailable.has('serp_entities') && !unavailable.has('onpage_score')) return null
  return (
    <Section title="Entities & on-page score">
      {score?.composite_score != null && (
        <div style={{ fontSize: 12, marginBottom: 8 }}>
          Your page scores <strong>{fmt(score.composite_score)}</strong>{score.composite_status ? ` (${score.composite_status})` : ''} against this SERP.
        </div>
      )}
      {unavailable.has('serp_entities') || !e?.serp_entities?.length ? (
        <span style={unavailPill}>No SERP entity coverage available.</span>
      ) : (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {e.serp_entities.slice(0, 14).map((ent, i) => (
            <span key={i} style={chip('#f0fdf4', '#15803d')} title={ent.type ?? ''}>
              {ent.name}{ent.page_spread != null ? ` (${ent.page_spread})` : ''}
            </span>
          ))}
          {e.serp_entity_count != null && e.serp_entity_count > 14 && <span style={unavailPill}>+{e.serp_entity_count - 14} more</span>}
        </div>
      )}
      {(e?.client_deficiencies?.length ?? 0) > 0 && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 12, color: '#6b7280' }}>
          {e!.client_deficiencies!.slice(0, 4).map((d, i) => (
            <li key={i}>{d.engine}: {(d.issues ?? d.recommendations ?? []).slice(0, 1).join('') || 'below SERP coverage'}</li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function OnpageDim({ diff, unavailable }: { diff?: OnpageDiff; unavailable: Set<string> }) {
  if (unavailable.has('onpage_diff') || !diff) {
    return <Section title="On-page content"><Unavailable what="On-page diff" /></Section>
  }
  const wc = diff.word_count
  return (
    <Section title="On-page content">
      {!diff.client_available && (
        <div style={{ ...unavailPill, marginBottom: 8 }}>Your page couldn’t be scraped — comparing competitors only.</div>
      )}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 12, marginBottom: 8 }}>
        {wc && <Metric label="Word count" value={wc.delta != null ? gapArrow(-wc.delta) : '—'} hint={`you ${fmt(wc.client)} · median ${fmt(wc.competitor_median)}`} />}
        <Metric label="Competitors compared" value={fmt(diff.competitors_compared)} />
      </div>
      {(diff.subtopic_gap?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>Subtopics competitors cover, you don’t</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {diff.subtopic_gap!.slice(0, 10).map((s, i) => (
              <span key={i} style={chip('#fff7ed', '#c2410c')} title={`${s.count} competitor${s.count === 1 ? '' : 's'}`}>{s.heading}</span>
            ))}
          </div>
        </div>
      )}
      {(diff.element_gap?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>Missing elements</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {diff.element_gap!.map((el, i) => <span key={i} style={chip('#fef2f2', '#b91c1c')}>{el.label}</span>)}
          </div>
        </div>
      )}
      {(diff.schema_gap?.length ?? 0) > 0 && (
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', marginBottom: 4 }}>Missing schema</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {diff.schema_gap!.slice(0, 8).map((s, i) => <span key={i} style={chip('#eff6ff', '#1d4ed8')}>{s.schema}</span>)}
          </div>
        </div>
      )}
    </Section>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: '#6b7280' }}>{label}</div>
      <div style={{ fontWeight: 700 }}>{value}</div>
      {hint && <div style={{ fontSize: 10, color: '#9ca3af' }}>{hint}</div>}
    </div>
  )
}

// The softened, client-facing summary of the on-page diff (owner decision #2:
// the raw internal diff is internal-only; clients see opportunity counts, not a
// competitor-by-competitor teardown).
function ClientSummary({ gap, diff }: { gap: Gap; diff?: OnpageDiff }) {
  const opps: string[] = []
  const behind = (d: number | null | undefined) => d != null && d > 0
  if (behind(gap.authority?.domain_rd_gap) || behind(gap.authority?.page_rd_gap)) opps.push('Build authority — earn more referring domains to this page.')
  if (behind(gap.site_traffic?.delta) || behind(gap.page_traffic?.delta)) opps.push('Grow this page’s search traffic toward the leaders in this space.')
  const sub = diff?.subtopic_gap?.length ?? 0
  if (sub > 0) opps.push(`Cover ${sub} more subtopic${sub === 1 ? '' : 's'} the top results address.`)
  const el = diff?.element_gap?.length ?? 0
  if (el > 0) opps.push(`Add ${el} content element${el === 1 ? '' : 's'} (e.g. FAQ, table, CTA) the leaders use.`)
  if ((diff?.word_count?.delta ?? 0) < 0) opps.push('Deepen the page — it’s shorter than the ranking average.')
  if ((gap.entities?.client_deficiencies?.length ?? 0) > 0) opps.push('Strengthen topical coverage of the key entities for this search.')
  if (opps.length === 0) opps.push('This page is close — small refinements should help it compete.')
  return (
    <Section title="Opportunities to close the gap">
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#374151' }}>
        {opps.map((o, i) => <li key={i} style={{ marginBottom: 4 }}>{o}</li>)}
      </ul>
    </Section>
  )
}
