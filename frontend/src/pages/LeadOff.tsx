import { Fragment, useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Radar, Download, Search, X, Flame, Snowflake, AlertTriangle, Loader2, UserPlus, Binoculars, FlaskConical, Compass, Hammer, ArrowUp, ArrowDown, ChevronsUpDown } from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'

// ── Types (mirror services/leadoff.py) ───────────────────────────────────────
interface MarketRow {
  grade: string
  luck: string
  conf: string
  build: number
  roi: number
  exp_val: number
  value_mo: number | null
  rankab: number
  city_name: string
  state_code: string
  category: string
  xdem: number
  rev_win: number
  rating: number | null
  namekw: number
  exact_open: number
  v3: number
  city_id: number
  category_id: string
  population: number
  // Prospect pipeline (context only — never a grade input). Present once
  // the leadoff_permits job has populated city_permits.
  permit_units_1yr?: number | null
  permits_pc?: number | null
  permit_sf_share?: number | null
  permit_trend?: number | null
  permit_flag?: string | null
  permit_vintage?: number | null
  permit_relevance?: 'high' | 'low'
  // score enrichment (context signals promoted to grade inputs, owner ruling
  // 2026-07-12). base_* is the pre-enrichment grade, kept for inspection.
  enriched?: boolean
  base_grade?: string | null
  base_exp_val?: number | null
  base_rankab?: number | null
  base_v3?: number | null
  opportunity_v3?: number | null
  score_factors?: { winnability: number; demand: number
    signals: Record<string, number | string> } | null
  // peer-cohort field-strength: this market's rev_win vs comparable-size,
  // comparable-income cities in the same category (context for the signal).
  peer_cohort_median?: number | null
  peer_cohort_n?: number | null
}
interface BoardResponse {
  markets: MarketRow[]
  as_of: string | null
  assumptions: { capture: number; lead_tier: string; approximate: boolean }
}
interface Competitor {
  rank_position: number
  business_name: string
  rating: number | null
  review_count: number | null
  domain: string | null
  // brand footprint (cached context, filled by tryout/scout pulls)
  site_pages?: number | null
  mentions?: number | null
  unlinked_mentions?: number | null
  nap_citations?: number | null
  generic_name?: boolean | null
}
interface Enrichment {
  rd_min: number | null
  rd_med: number | null
  field_vel30: number | null
  field_prior30: number | null
  vel_matched: number | null
  momentum: string | null
  newest_review: string | null
  growth_yoy: number | null
  growth_yoy_ss: number | null
  peak_months: string | null
}
interface MarketBrief extends MarketRow {
  competitors: Competitor[]
  enrichment: Enrichment | null
}
interface Neighborhood {
  neighborhood: string
  state: string
  metro: string
  service: string
  demand_vol: number | null
  cpc: number | null
  exact_cat_holders: number | null
  avg_top5_reviews: number | null
  opportunity_score_v3: number | null
  lead_value_mid: number | null
  est_leads_mo: number | null
  est_value_mo: number | null
}
interface TryoutRow {
  grade: string
  field_pages_med?: number | null
  field_mentions_med?: number | null
  natl_pct: number
  exp_val: number
  value_mo: number | null
  roi: number
  rankab: number
  category: string
  vol: number | null
  supply: number
  rev_win: number
  rating: number
  namekw: number
  exact_open: number
}
interface Tryout {
  id: string
  city_name: string
  state_code: string
  status: 'pending' | 'running' | 'complete' | 'failed'
  results: TryoutRow[] | null
  error: string | null
  est_cost: number | null
  created_at: string
}
interface ScoutEstimate {
  est_cost: number
  rd_misses: number
  velocity_misses: number
  trend_miss: boolean
  site_misses?: number
  mention_misses?: number
  fully_cached: boolean
  running_job_id?: string | null
}

type Sort = 'v3' | 'build' | 'roi' | 'expected' | 'value' | 'leads' | 'demand'
type Tier = 'low' | 'mid' | 'high'

const GRADE_COLORS: Record<string, string> = {
  'A+': '#0d5c38', A: '#177245', 'B+': '#0e7d6f', B: '#3d998c',
  C: '#c99a2e', D: '#94a3b8', F: '#b3362b',
}
const usd = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `$${Math.round(n).toLocaleString()}`
// compact count for footprint columns (site pages / brand mentions)
const compact = (n: number | null | undefined) =>
  n === null || n === undefined ? '—'
    : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M`
      : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n)

type View = 'board' | 'neighborhoods' | 'tryouts'

// Board columns + click-to-sort model. `key: null` = a non-sortable column
// (the luck/permit icon strip). `num` picks the default first-click direction
// (descending for numbers, ascending for text) and the compare fn.
type ColKey = 'grade' | 'market' | 'category' | 'opportunity' | 'exp_val'
  | 'roi' | 'demand' | 'rev_win' | 'rating' | 'exact_open'
const BOARD_COLUMNS: { label: string; key: ColKey | null; num: boolean }[] = [
  { label: 'Grade', key: 'grade', num: true },
  { label: '', key: null, num: false },
  { label: 'Market', key: 'market', num: false },
  { label: 'Category', key: 'category', num: false },
  { label: 'Opportunity', key: 'opportunity', num: true },
  { label: 'Exp $/mo', key: 'exp_val', num: true },
  { label: 'ROI $/rev', key: 'roi', num: true },
  { label: 'Demand', key: 'demand', num: true },
  { label: 'Rev to win', key: 'rev_win', num: true },
  { label: 'Field ★', key: 'rating', num: true },
  { label: 'Cat open', key: 'exact_open', num: true },
]

function colValue(r: MarketRow, key: ColKey): number | string {
  switch (key) {
    case 'grade': return r.build ?? -1            // numeric grade score
    case 'market': return `${r.city_name}, ${r.state_code}`
    case 'category': return r.category ?? ''
    case 'opportunity': return r.opportunity_v3 ?? r.v3 ?? -1
    case 'exp_val': return r.exp_val ?? -1
    case 'roi': return r.roi ?? -1
    case 'demand': return r.xdem ?? -1
    case 'rev_win': return r.rev_win ?? -1
    case 'rating': return r.rating ?? -1
    case 'exact_open': return r.exact_open ?? -1
  }
}

// Client-side sort of the loaded rows (a table nicety over the server's
// top-N ordering — re-orders what's shown, e.g. "of these, fewest reviews
// to win"). Nulls sort last via the -1 fallbacks in colValue.
function sortMarkets(rows: MarketRow[], cs: { key: ColKey; dir: 'asc' | 'desc' }): MarketRow[] {
  const mult = cs.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = colValue(a, cs.key), vb = colValue(b, cs.key)
    if (typeof va === 'string' || typeof vb === 'string')
      return mult * String(va).localeCompare(String(vb))
    return mult * (va - vb)
  })
}

export function LeadOff() {
  const [view, setView] = useState<View>('board')
  const [filters, setFilters] = useState({ city: '', state: '', category: '', minDemand: '' })
  const [applied, setApplied] = useState(filters)
  const [sort, setSort] = useState<Sort>('v3')
  const [capture, setCapture] = useState(0.10)
  const [tier, setTier] = useState<Tier>('mid')
  const [selected, setSelected] = useState<{ city_id: number; category_id: string } | null>(null)

  const params = new URLSearchParams()
  if (applied.city) params.set('city', applied.city)
  if (applied.state) params.set('state', applied.state)
  if (applied.category) params.set('category', applied.category)
  if (applied.minDemand) params.set('min_demand', applied.minDemand)
  params.set('sort', sort)
  params.set('capture', String(capture))
  params.set('lead_tier', tier)
  params.set('limit', '50')

  const { data: board, isLoading, error } = useQuery<BoardResponse>({
    queryKey: ['leadoff-board', applied, sort, capture, tier],
    queryFn: () => api.get<BoardResponse>(`/leadoff/board?${params.toString()}`),
  })

  const { data: brief, isLoading: briefLoading } = useQuery<MarketBrief>({
    queryKey: ['leadoff-brief', selected],
    queryFn: () =>
      api.get<MarketBrief>(
        `/leadoff/market-brief?city_id=${selected!.city_id}&category_id=${encodeURIComponent(selected!.category_id)}`,
      ),
    enabled: Boolean(selected),
  })

  // Click-to-sort on the column headers (client-side, over the loaded rows).
  const [colSort, setColSort] = useState<{ key: ColKey; dir: 'asc' | 'desc' } | null>(null)
  // Reset when the loaded population changes (server sort / filters / assumptions
  // re-fetch), so the server ordering takes over until a header is clicked again.
  useEffect(() => { setColSort(null) }, [applied, sort, capture, tier])
  const onHeaderSort = (key: ColKey | null, num: boolean) => {
    if (!key) return
    setColSort(prev => prev?.key === key
      ? { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
      : { key, dir: num ? 'desc' : 'asc' })
  }
  const displayRows = useMemo(() => {
    const rows = board?.markets ?? []
    return colSort ? sortMarkets(rows, colSort) : rows
  }, [board, colSort])

  const exportCsv = () => {
    const rows = displayRows
    if (!rows.length) return
    const headers = ['grade', 'city_name', 'state_code', 'category', 'opportunity',
      'exp_val', 'roi', 'demand', 'rev_win', 'rating', 'exact_open']
    downloadCsv('leadoff_shortlist.csv', toCsv(headers,
      rows.map(r => [r.grade, r.city_name, r.state_code, r.category,
        r.opportunity_v3 ?? r.v3, r.exp_val,
        r.roi, r.xdem, r.rev_win, r.rating, r.exact_open])))
  }

  return (
    <div style={{ padding: 32, display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <Radar size={22} color="#0e7d6f" />
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>LeadOff</h1>
          {board?.as_of && <span style={pill}>data {board.as_of}</span>}
          {board?.assumptions.approximate && (
            <span style={{ ...pill, background: '#fef3c7', color: '#92400e' }}
              title="Grades under non-default assumptions are approximate (percentile reference is fixed at 10% / mid)">
              approx grades
            </span>
          )}
          {(board?.markets ?? []).some(m => m.enriched) && (
            <span style={{ ...pill, background: '#e3f2ef', color: '#0e7d6f' }}
              title="Grades include the context-enrichment layer: winnability adjusted by proximity + incumbent size + peer-cohort field-strength (field vs comparable-size, comparable-income cities), demand by permits + seasonal trend (conservative, calibration-tunable). The full grade runs on each market's brief.">
              enriched grades
            </span>
          )}
        </div>
        <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 12px' }}>
          Market intelligence — every scanned US market graded for lead-gen buildability.
          Default sort is <b>Opportunity</b> — the hidden-gem score (markets less competitive than their demand predicts). Estimates are planning numbers, not promises.
        </p>

        {/* View tabs */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
          <TabButton active={view === 'board'} onClick={() => setView('board')}>
            <Radar size={13} /> Board
          </TabButton>
          <TabButton active={view === 'neighborhoods'} onClick={() => setView('neighborhoods')}>
            <Compass size={13} /> Neighborhoods
          </TabButton>
          <TabButton active={view === 'tryouts'} onClick={() => setView('tryouts')}>
            <FlaskConical size={13} /> Tryouts
          </TabButton>
        </div>

        {view === 'neighborhoods' && <NeighborhoodsView />}
        {view === 'tryouts' && <TryoutsView />}

        {view === 'board' && <>
        {/* Filter / assumption bar */}
        <div style={barStyle}>
          <Field label="City">
            <input style={inputStyle} value={filters.city} placeholder="any"
              onChange={e => setFilters({ ...filters, city: e.target.value })} />
          </Field>
          <Field label="State">
            <input style={{ ...inputStyle, width: 52 }} value={filters.state} placeholder="any" maxLength={2}
              onChange={e => setFilters({ ...filters, state: e.target.value.toUpperCase() })} />
          </Field>
          <Field label="Category">
            <input style={inputStyle} value={filters.category} placeholder="any"
              onChange={e => setFilters({ ...filters, category: e.target.value })} />
          </Field>
          <Field label="Min demand">
            <input style={{ ...inputStyle, width: 80 }} type="number" value={filters.minDemand}
              onChange={e => setFilters({ ...filters, minDemand: e.target.value })} />
          </Field>
          <Field label="Sort">
            <select style={inputStyle} value={sort} onChange={e => setSort(e.target.value as Sort)}>
              <option value="v3">Opportunity — hidden gems (default)</option>
              <option value="build">Grade — raw value (big metros)</option>
              <option value="roi">ROI — win cheapest</option>
              <option value="expected">Expected $/mo</option>
              <option value="leads">Expected leads</option>
              <option value="value">$/mo if ranked</option>
              <option value="demand">Demand</option>
            </select>
          </Field>
          <Field label={`Capture ${(capture * 100).toFixed(0)}%`}>
            <input type="range" min={0.05} max={0.25} step={0.05} value={capture}
              onChange={e => setCapture(Number(e.target.value))} style={{ width: 90 }} />
          </Field>
          <Field label="Lead value">
            <select style={inputStyle} value={tier} onChange={e => setTier(e.target.value as Tier)}>
              <option value="low">Conservative</option>
              <option value="mid">Mid</option>
              <option value="high">Optimistic</option>
            </select>
          </Field>
          <button style={primaryBtn} onClick={() => setApplied(filters)}>
            <Search size={14} /> Apply
          </button>
          <button style={secondaryBtn} onClick={exportCsv} title="Export shortlist CSV">
            <Download size={14} />
          </button>
        </div>

        {error instanceof Error && (
          <div style={errorBox}>{error.message === 'not_found' ? 'No data.' : error.message}</div>
        )}

        {/* Board */}
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 900, fontSize: 13 }}>
              <thead>
                <tr>
                  {BOARD_COLUMNS.map((c, i) => {
                    const active = c.key !== null && colSort?.key === c.key
                    return (
                      <th key={c.label || `icons-${i}`}
                        onClick={() => onHeaderSort(c.key, c.num)}
                        title={c.key ? `Sort by ${c.label}` : undefined}
                        style={{ ...thStyle, whiteSpace: 'nowrap', userSelect: 'none',
                          cursor: c.key ? 'pointer' : 'default' }}>
                        {c.label}
                        {c.key && (
                          <span style={{ verticalAlign: 'middle', marginLeft: 3,
                            display: 'inline-flex', opacity: active ? 1 : 0.3 }}>
                            {active
                              ? (colSort!.dir === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)
                              : <ChevronsUpDown size={11} />}
                          </span>
                        )}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {displayRows.map(r => {
                  const isSel = selected?.city_id === r.city_id && selected?.category_id === r.category_id
                  return (
                    <tr key={`${r.city_id}:${r.category_id}`}
                      onClick={() => setSelected({ city_id: r.city_id, category_id: r.category_id })}
                      style={{ cursor: 'pointer', background: isSel ? '#e3f2ef' : undefined }}>
                      <td style={tdStyle}><GradeChip grade={r.grade} /></td>
                      <td style={{ ...tdStyle, paddingLeft: 0 }}>
                        {r.luck === 'HOT?' && <Flame size={14} color="#ea580c" aria-label="Demand ≥2× city norm — verify" />}
                        {r.luck === 'COLD?' && <Snowflake size={14} color="#38bdf8" aria-label="Demand ≤0.5× norm" />}
                        {r.conf === 'low' && <AlertTriangle size={12} color="#94a3b8" aria-label="Low-confidence demand" />}
                        {r.permit_flag === 'HOT-pipeline' && (
                          <Hammer size={13} color="#b45309"
                            aria-label={`Housing pipeline hot: ${r.permits_pc}/1k residents, trend ${r.permit_trend}× — leading indicator, strongest for construction-adjacent categories`} />
                        )}
                      </td>
                      <td style={{ ...tdStyle, fontWeight: 600, whiteSpace: 'nowrap' }}>{r.city_name}, {r.state_code}</td>
                      <td style={tdStyle}>{r.category}</td>
                      <td style={{ ...tdStyle, fontWeight: 700, color: '#0f766e' }}
                        title={r.opportunity_v3 != null && r.base_v3 != null && r.score_factors
                          ? `Hidden-gem score. Raw v3 ${r.base_v3.toFixed(1)} × winnability ${r.score_factors.winnability.toFixed(2)} × demand ${r.score_factors.demand.toFixed(2)}`
                          : 'Hidden-gem score (v3): demand vs competition undervaluation'}>
                        {(r.opportunity_v3 ?? r.v3)?.toFixed(1) ?? '—'}
                      </td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>{usd(r.exp_val)}</td>
                      <td style={tdStyle}>{r.roi?.toFixed(1)}</td>
                      <td style={tdStyle}>{r.xdem?.toLocaleString()}</td>
                      <td style={tdStyle}>{r.rev_win}</td>
                      <td style={tdStyle}>{r.rating ?? '—'}</td>
                      <td style={tdStyle}>{r.exact_open}</td>
                    </tr>
                  )
                })}
                {isLoading && (
                  <tr><td colSpan={BOARD_COLUMNS.length} style={{ ...tdStyle, textAlign: 'center', padding: 32 }}>
                    <Loader2 size={18} className="spin" style={{ verticalAlign: -4 }} /> Loading board…
                  </td></tr>
                )}
                {!isLoading && !displayRows.length && (
                  <tr><td colSpan={BOARD_COLUMNS.length} style={{ ...tdStyle, textAlign: 'center', padding: 32, color: '#64748b' }}>
                    No markets match.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        </>}
      </div>

      {/* Drill-in brief */}
      {view === 'board' && selected && (
        <div style={panelStyle}>
          <button style={closeBtn} onClick={() => setSelected(null)} aria-label="Close"><X size={16} /></button>
          {briefLoading && <div style={{ textAlign: 'center', padding: 40 }}><Loader2 size={20} className="spin" /></div>}
          {brief && !briefLoading && (
            <>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <GradeChip grade={brief.grade} />
                {brief.enriched && brief.base_grade && brief.base_grade !== brief.grade && (
                  <span style={{ fontSize: 12, color: '#64748b' }}
                    title="Base grade before the context-signal enrichment layer">
                    (base <b style={{ color: GRADE_COLORS[brief.base_grade] ?? '#475569' }}>{brief.base_grade}</b>)
                  </span>
                )}
                {brief.luck === 'HOT?' && <span style={{ fontSize: 12, color: '#ea580c', fontWeight: 700 }}>🔥 HOT?</span>}
              </div>
              <h2 style={{ fontSize: 16, fontWeight: 700, margin: '6px 0 0', color: '#0f172a' }}>{brief.category}</h2>
              <div style={{ fontSize: 13, color: '#64748b' }}>{brief.city_name}, {brief.state_code}</div>

              <SectionTitle>Economics</SectionTitle>
              {brief.enriched && brief.score_factors && (
                <div style={{ fontSize: 11, color: '#0e7d6f', background: '#e3f2ef',
                  borderRadius: 6, padding: '6px 8px', margin: '2px 0 6px', lineHeight: 1.5 }}
                  title="Today's context signals promoted to grade inputs (conservative, config-weighted, calibration-tunable). Winnability ×proximity/site/brand/peer-cohort field-strength; demand ×permits/seasonal.">
                  Grade includes context enrichment — winnability ×{brief.score_factors.winnability.toFixed(2)},
                  demand ×{brief.score_factors.demand.toFixed(2)}
                  {brief.base_exp_val != null && <> · base {usd(brief.base_exp_val)} → {usd(brief.exp_val)}</>}
                  {brief.opportunity_v3 != null && brief.base_v3 != null && (
                    <> · opportunity {brief.base_v3.toFixed(1)} → {brief.opportunity_v3.toFixed(1)}</>
                  )}
                </div>
              )}
              <KV k="Opportunity (hidden-gem score)" v={(brief.opportunity_v3 ?? brief.v3)?.toFixed(1)} strong />
              <KV k="Expected $/mo" v={usd(brief.exp_val)} strong />
              <KV k="$/mo if ranked" v={usd(brief.value_mo)} />
              <KV k="Win likelihood" v={brief.rankab?.toFixed(2)} />
              <KV k="ROI ($/mo per review)" v={brief.roi?.toFixed(1)} />
              <KV k="Demand (regressed)" v={`${brief.xdem?.toLocaleString()}/mo`} />
              {brief.permits_pc != null && (
                <KV k={`Prospect pipeline${brief.permit_flag && brief.permit_flag !== '-' ? ` · ${brief.permit_flag}` : ''}`}
                  v={`${brief.permit_units_1yr?.toLocaleString()} units/yr (${brief.permits_pc}/1k)`}
                  hint={`${brief.permit_vintage} housing permits — leading indicator of home-services demand, 6–18mo horizon. `
                    + `Trend ${brief.permit_trend ?? '—'}× vs 3-yr base · ${Math.round((brief.permit_sf_share ?? 0) * 100)}% single-family. `
                    + (brief.permit_relevance === 'low'
                      ? 'LOW relevance for this category (not construction-adjacent) — context only.'
                      : 'Construction-adjacent category — pipeline is a meaningful tailwind. Context only, never in the grade.')} />
              )}

              <SectionTitle>Field forensics</SectionTitle>
              <KV k="Reviews to beat #3" v={String(brief.rev_win)} strong />
              {brief.peer_cohort_median != null && (
                <KV k="Field vs comparable cities"
                  v={`${brief.rev_win} vs ${brief.peer_cohort_median} median`
                    + (brief.rev_win < brief.peer_cohort_median ? ' — softer'
                      : brief.rev_win > brief.peer_cohort_median ? ' — tougher' : ' — typical')}
                  hint={`This market's reviews-to-win vs the median of ${brief.peer_cohort_n ?? '—'} `
                    + `cities of similar size and household income in the same category. `
                    + `A field softer than its peers is genuinely beatable (not just small); `
                    + `a tougher-than-peers field is harder than it looks. Feeds the winnability grade.`} />
              )}
              <KV k="Field rating" v={brief.rating != null ? `${brief.rating}★` : '—'} />
              <KV k="Keyword-named top-5" v={`${brief.namekw}/5`} />
              <KV k="Exact-category holders" v={String(brief.exact_open)} />
              <div style={{ marginTop: 8 }}>
                {brief.competitors.map(c => (
                  <div key={c.rank_position} style={{ fontSize: 12, color: '#64748b', padding: '2px 0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 8 }}>
                        {c.rank_position}. {c.business_name}
                      </span>
                      <span style={{ whiteSpace: 'nowrap' }}>
                        {(c.review_count ?? 0).toLocaleString()} rev{c.rating ? ` · ${c.rating}★` : ''}
                      </span>
                    </div>
                    {(c.site_pages != null || c.mentions != null || c.nap_citations != null) && (
                      <div style={{ fontSize: 11, color: '#94a3b8', paddingLeft: 14 }}
                        title={'Site size = Google indexed-page estimate (site: query). Mentions = total web mentions incl. unlinked (Content Analysis index'
                          + (c.generic_name ? '; generic name — count filtered to city/phone co-occurrence' : '')
                          + '). Unlinked = mentioning domains that do not link. NAP = phone-number citations. Context only.'}>
                        {compact(c.site_pages)} pages
                        {c.mentions != null && <> · {compact(c.mentions)} mentions{c.generic_name ? '*' : ''}</>}
                        {c.unlinked_mentions != null && <> ({compact(c.unlinked_mentions)} unlinked)</>}
                        {(c.nap_citations ?? 0) > 0 && <> · {compact(c.nap_citations)} NAP</>}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <SectionTitle>Scouting report</SectionTitle>
              {brief.enrichment ? (
                <>
                  <KV k="Links to win (true RD)"
                    v={brief.enrichment.rd_min != null ? `~${brief.enrichment.rd_min * 10}` : '—'} strong
                    hint="tool read ×10 per orchestrator rule" />
                  <KV k="Field reviews 30d (vs prior)"
                    v={brief.enrichment.field_vel30 != null
                      ? `${brief.enrichment.field_vel30} vs ${brief.enrichment.field_prior30 ?? 0}` : '—'}
                    hint={brief.enrichment.vel_matched != null
                      ? `summed over ${brief.enrichment.vel_matched} of ${brief.competitors.length} top-5 competitors found in the review cache`
                      : undefined} />
                  <KV k="Momentum"
                    v={brief.enrichment.momentum
                      ?? (brief.enrichment.vel_matched ? 'thin data' : '—')}
                    hint={brief.enrichment.momentum == null && brief.enrichment.vel_matched
                      ? `only ${brief.enrichment.vel_matched} of ${brief.competitors.length} competitors matched the review cache — below the 2-competitor floor for a momentum verdict`
                      : undefined} />
                  <KV k="Newest field review" v={brief.enrichment.newest_review ?? '—'} />
                  <KV k="Demand growth (YoY)"
                    v={brief.enrichment.growth_yoy_ss != null
                      ? `${brief.enrichment.growth_yoy_ss}×`
                      : brief.enrichment.growth_yoy != null ? `${brief.enrichment.growth_yoy}× ⚠` : '—'}
                    hint={brief.enrichment.growth_yoy_ss != null
                      ? `same-month YoY (seasonality-cancelled)${brief.enrichment.peak_months ? ` · peaks: months ${brief.enrichment.peak_months}` : ''}`
                      : brief.enrichment.peak_months
                        ? `12-mo window — seasonal categories confound this; read with peaks: months ${brief.enrichment.peak_months}`
                        : '12-mo window — seasonal categories confound this'} />
                </>
              ) : (
                <div style={{ fontSize: 12, color: '#94a3b8' }}>
                  Not scouted yet — RD, review velocity, and demand trend land here
                  after a scout pull.
                </div>
              )}
              <ProximityCard key={`px:${brief.city_id}:${brief.category_id}`}
                cityId={brief.city_id} categoryId={brief.category_id} />

              <ScoutCard key={`${brief.city_id}:${brief.category_id}`}
                cityId={brief.city_id} categoryId={brief.category_id} />

              <CreateClientCard key={`${brief.city_id}:${brief.category_id}`} brief={brief} />

              <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 14, lineHeight: 1.5 }}>
                Before committing: eyeball the live Maps SERP. HOT? needs a trend pull; category
                picks need label verification (LeadOff SOP §6).
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
function TabButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button onClick={onClick} style={{
      display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13,
      fontWeight: 600, padding: '7px 13px', borderRadius: 8, cursor: 'pointer',
      border: '1px solid ' + (active ? '#0e7d6f' : '#cbd5e1'),
      background: active ? '#e3f2ef' : '#fff', color: active ? '#0e7d6f' : '#475569',
    }}>{children}</button>
  )
}

// The nameable-neighborhood board (955 combos, precomputed). Scored on
// demand/economics — neighborhood supply ≈ the parent metro's at 13z, so
// competition columns are context, not signal (scanner lesson #5).
function NeighborhoodsView() {
  const [filters, setFilters] = useState({ metro: '', state: '', service: '' })
  const [applied, setApplied] = useState(filters)
  const [sort, setSort] = useState('demand')
  const params = new URLSearchParams()
  if (applied.metro) params.set('metro', applied.metro)
  if (applied.state) params.set('state', applied.state)
  if (applied.service) params.set('service', applied.service)
  params.set('sort', sort)
  params.set('limit', '100')
  const { data, isLoading } = useQuery<{ neighborhoods: Neighborhood[] }>({
    queryKey: ['leadoff-neighborhoods', applied, sort],
    queryFn: () => api.get(`/leadoff/neighborhoods?${params.toString()}`),
  })
  const rows = data?.neighborhoods ?? []
  return (
    <>
      <div style={barStyle}>
        <Field label="Metro">
          <input style={inputStyle} value={filters.metro} placeholder="any"
            onChange={e => setFilters({ ...filters, metro: e.target.value })} />
        </Field>
        <Field label="State">
          <input style={{ ...inputStyle, width: 52 }} value={filters.state} placeholder="any" maxLength={2}
            onChange={e => setFilters({ ...filters, state: e.target.value.toUpperCase() })} />
        </Field>
        <Field label="Service">
          <input style={inputStyle} value={filters.service} placeholder="any"
            onChange={e => setFilters({ ...filters, service: e.target.value })} />
        </Field>
        <Field label="Sort">
          <select style={inputStyle} value={sort} onChange={e => setSort(e.target.value)}>
            <option value="demand">Demand</option>
            <option value="value">$/mo if ranked</option>
            <option value="leads">Est leads/mo</option>
            <option value="v3">v3 (within-category)</option>
          </select>
        </Field>
        <button style={primaryBtn} onClick={() => setApplied(filters)}>
          <Search size={14} /> Apply
        </button>
      </div>
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 860, fontSize: 13 }}>
            <thead>
              <tr>
                {['Neighborhood', 'Metro', 'Service', 'Demand', 'Est leads/mo', '$/mo if ranked',
                  'v3', 'CPC', 'Exact holders', 'Top-5 ★ reviews'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((n, i) => (
                <tr key={i}>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{n.neighborhood}</td>
                  <td style={tdStyle}>{n.metro}, {n.state}</td>
                  <td style={tdStyle}>{n.service}</td>
                  <td style={tdStyle}>{n.demand_vol?.toLocaleString() ?? '—'}</td>
                  <td style={tdStyle}>{n.est_leads_mo ?? '—'}</td>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{usd(n.est_value_mo)}</td>
                  <td style={tdStyle}>{n.opportunity_score_v3?.toFixed(1) ?? '—'}</td>
                  <td style={tdStyle}>{n.cpc != null ? `$${n.cpc.toFixed(2)}` : '—'}</td>
                  <td style={tdStyle}>{n.exact_cat_holders ?? '—'}</td>
                  <td style={tdStyle}>{n.avg_top5_reviews != null ? Math.round(n.avg_top5_reviews) : '—'}</td>
                </tr>
              ))}
              {isLoading && (
                <tr><td colSpan={10} style={{ ...tdStyle, textAlign: 'center', padding: 32 }}>
                  <Loader2 size={18} className="spin" style={{ verticalAlign: -4 }} /> Loading…
                </td></tr>
              )}
              {!isLoading && !rows.length && (
                <tr><td colSpan={10} style={{ ...tdStyle, textAlign: 'center', padding: 32, color: '#64748b' }}>
                  No neighborhoods match.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 10, lineHeight: 1.5 }}>
        Neighborhood supply ≈ the parent metro's — pick on demand and economics, not the
        competition columns. GBP-nameability is already filtered in (all rows are nameable).
      </div>
    </>
  )
}

// Tryouts: score ANY off-list city (~$0.20, ~3 min) — the check_city port.
function TryoutsView() {
  const qc = useQueryClient()
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const { data } = useQuery<{ tryouts: Tryout[] }>({
    queryKey: ['leadoff-tryouts'],
    queryFn: () => api.get('/leadoff/tryouts?limit=20'),
    refetchInterval: q =>
      (q.state.data?.tryouts ?? []).some(t => t.status === 'pending' || t.status === 'running')
        ? 5000 : false,
  })
  const tryouts = data?.tryouts ?? []
  const open = tryouts.find(t => t.id === openId)

  const submit = async () => {
    if (!city.trim() || state.trim().length !== 2 || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<{ tryout_id: string }>('/leadoff/tryout', {
        city: city.trim(), state: state.trim().toUpperCase(),
      })
      setOpenId(res.tryout_id)
      setCity('')
      qc.invalidateQueries({ queryKey: ['leadoff-tryouts'] })
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'tryout_failed'
      setError(msg === 'city_not_found'
        ? 'City not found (covers US places ≥10k population — check spelling/state).'
        : msg === 'budget_exceeded' ? 'Daily LeadOff budget reached — try tomorrow or raise the budget.'
        : msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div style={barStyle}>
        <Field label="City">
          <input style={inputStyle} value={city} placeholder="Moses Lake"
            onChange={e => setCity(e.target.value)} />
        </Field>
        <Field label="State">
          <input style={{ ...inputStyle, width: 52 }} value={state} placeholder="WA" maxLength={2}
            onChange={e => setState(e.target.value.toUpperCase())} />
        </Field>
        <button style={primaryBtn} disabled={busy || !city.trim() || state.length !== 2} onClick={submit}>
          {busy ? <Loader2 size={14} className="spin" /> : <FlaskConical size={14} />} Run tryout
        </button>
        <span style={{ fontSize: 11, color: '#92400e', background: '#fef3c7', borderRadius: 99, padding: '3px 10px', fontWeight: 600 }}>
          paid pull · ~$0.20 · ~3 min
        </span>
      </div>
      {error && <div style={errorBox}>{error}</div>}

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <div style={{ width: 300, flexShrink: 0, border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
          {tryouts.map(t => (
            <button key={t.id} onClick={() => setOpenId(t.id)} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
              padding: '9px 12px', fontSize: 13, cursor: 'pointer', textAlign: 'left',
              border: 'none', borderBottom: '1px solid #e2e8f0',
              background: openId === t.id ? '#e3f2ef' : '#fff',
            }}>
              <span style={{ fontWeight: 600, color: '#0f172a' }}>{t.city_name}, {t.state_code}</span>
              <span style={{ fontSize: 11, color: t.status === 'failed' ? '#b91c1c' : '#64748b' }}>
                {(t.status === 'pending' || t.status === 'running')
                  ? <Loader2 size={12} className="spin" style={{ verticalAlign: -2 }} />
                  : t.status === 'failed' ? 'failed' : new Date(t.created_at).toLocaleDateString()}
              </span>
            </button>
          ))}
          {!tryouts.length && (
            <div style={{ padding: 20, fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>
              No tryouts yet. Score any US city ≥10k population — the board only covers ≥30k.
            </div>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          {open?.status === 'failed' && (
            <div style={errorBox}>
              {open.error === 'dataforseo_daily_limit'
                ? 'DataForSEO daily money limit hit — nothing was recorded; retry after midnight UTC.'
                : `Tryout failed: ${open.error}`}
            </div>
          )}
          {(open?.status === 'pending' || open?.status === 'running') && (
            <div style={{ padding: 40, textAlign: 'center', color: '#64748b', fontSize: 13 }}>
              <Loader2 size={18} className="spin" style={{ verticalAlign: -4 }} /> Scoring {open.city_name},
              {' '}{open.state_code} — demand pull, then the Maps field at 13z (~3 min)…
            </div>
          )}
          {open?.status === 'complete' && (
            <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 780, fontSize: 13 }}>
                  <thead>
                    <tr>{['Grade', 'Category', 'Exp $/mo', 'ROI $/rev', 'Demand', 'Supply',
                          'Rev to win', 'Field ★', 'Cat open', 'Field pages', 'Field mentions'].map(h => (
                      <th key={h} style={thStyle}>{h}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {(open.results ?? []).map((r, i) => (
                      <tr key={i}>
                        <td style={tdStyle}><GradeChip grade={r.grade} /></td>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>{r.category}</td>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>{usd(r.exp_val)}</td>
                        <td style={tdStyle}>{r.roi?.toFixed(1)}</td>
                        <td style={tdStyle}>{r.vol?.toLocaleString() ?? '—'}</td>
                        <td style={tdStyle}>{r.supply}</td>
                        <td style={tdStyle}>{r.rev_win}</td>
                        <td style={tdStyle}>{r.rating || '—'}</td>
                        <td style={tdStyle}>{r.exact_open}</td>
                        <td style={tdStyle} title="median indexed pages across the category's top-5 (site: estimate)">{compact(r.field_pages_med)}</td>
                        <td style={tdStyle} title="median web-mention count across the top-5 (generic names inflate — context only)">{compact(r.field_mentions_med)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {!open && (
            <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
              Run a tryout or pick one from the list. Grades are vs the same national
              reference as the board (raw demand, not regressed — outlier cities read hot).
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// Scout (Pass 2, ~$0.10–1 cache-cheapened): fills the shared RD / velocity /
// trend caches for one market; the brief re-reads them on completion.
// The Distance-pillar octant read (proximity plan §2/§3): where the ranked
// field is physically anchored and where it is not. Context only — never a
// grade input. Loaded lazily so the brief itself stays fast.
interface ProximityRead {
  available: boolean
  reason?: string
  hint?: string
  thin_data?: boolean
  pins_used?: number
  pins_out_of_radius?: number
  radius_miles?: number
  octants?: { octant: string; count: number; reviews: number; defense: number; bar_pct: number
    anchors: { name: string | null; reviews: number; miles: number }[] }[]
  underserved?: string[]
  placement?: { octant: string; lat: number; lng: number; radius_mi: number
    maps_url: string; locality?: string | null }[]
  opportunity?: number
  note?: string
}

function ProximityCard({ cityId, categoryId }: { cityId: number; categoryId: string }) {
  const { data: px, isLoading } = useQuery<ProximityRead>({
    queryKey: ['leadoff-proximity', cityId, categoryId],
    queryFn: () => api.get(`/leadoff/proximity?city_id=${cityId}&category_id=${encodeURIComponent(categoryId)}`),
  })
  return (
    <>
      <SectionTitle>Proximity (where the field sits)</SectionTitle>
      {isLoading && <div style={{ fontSize: 12, color: '#94a3b8' }}>Reading competitor pins…</div>}
      {px && !px.available && (
        <div style={{ fontSize: 12, color: '#94a3b8' }}>
          {px.reason === 'no_geocoded_competitors'
            ? (px.hint ?? 'No geocoded competitors for this market.')
            : 'Proximity read unavailable for this market.'}
        </div>
      )}
      {px?.available && (
        <>
          {px.thin_data && (
            <div style={{ fontSize: 12, color: '#b45309', marginBottom: 6 }}>
              Thin data — only {px.pins_used} pinned competitor{px.pins_used === 1 ? '' : 's'};
              below the floor for an underserved-zone verdict.
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '28px 1fr 44px', gap: '3px 8px', alignItems: 'center' }}>
            {(px.octants ?? []).map(o => (
              <Fragment key={o.octant}>
                <span style={{ fontSize: 11, fontWeight: 600, color: px.underserved?.includes(o.octant) ? '#b45309' : '#475569' }}>
                  {o.octant}
                </span>
                <div style={{ background: '#f1f5f9', borderRadius: 3, height: 10, overflow: 'hidden' }}
                  title={o.anchors.map(a => `${a.name} (${a.reviews} rev @ ${a.miles}mi)`).join(', ') || 'no ranked competitor anchored here'}>
                  <div style={{ width: `${o.bar_pct}%`, height: '100%', background: '#0e7d6f', opacity: 0.85 }} />
                </div>
                <span style={{ fontSize: 11, color: '#94a3b8', textAlign: 'right' }}>{o.count || '—'}</span>
              </Fragment>
            ))}
          </div>
          {!px.thin_data && (px.underserved?.length ?? 0) > 0 && (
            <div style={{ marginTop: 8 }}>
              <KV k="Underserved octants" v={px.underserved!.join(', ')} strong
                hint="defense below ¼ of the median defended octant — no ranked competitor is anchored there (someone may still serve it)" />
              {(px.placement ?? []).map(p => (
                <div key={p.octant} style={{ fontSize: 12, padding: '2px 0' }}>
                  <a href={p.maps_url} target="_blank" rel="noreferrer" style={{ color: '#0e7d6f', fontWeight: 600 }}>
                    Suggested GBP zone: {p.octant}{p.locality ? ` — near ${p.locality}` : ''} ({p.radius_mi} mi out) ↗
                  </a>
                </div>
              ))}
              <KV k="Proximity opportunity" v={px.opportunity?.toFixed(2)}
                hint="0–1 share of the demand-space weakly defended. Context only — never in the grade." />
            </div>
          )}
          {!px.thin_data && (px.underserved?.length ?? 0) === 0 && (
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>
              Field is spread across all octants — no clearly undefended bearing.
            </div>
          )}
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6, lineHeight: 1.4 }}>
            {px.pins_used} pins within {px.radius_miles} mi (street-centroid resolution).
            Empty octant = no <em>ranked</em> competitor anchored there — pre-client forecast;
            the geo-grid verifies it post-client.
          </div>
        </>
      )}
    </>
  )
}

function ScoutCard({ cityId, categoryId }: { cityId: number; categoryId: string }) {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: est } = useQuery<ScoutEstimate>({
    queryKey: ['leadoff-scout-est', cityId, categoryId],
    queryFn: () => api.get(`/leadoff/scout/estimate?city_id=${cityId}&category_id=${encodeURIComponent(categoryId)}`),
  })
  useQuery<{ status: string; error: string | null }>({
    queryKey: ['leadoff-scout-job', jobId],
    queryFn: async () => {
      const job = await api.get<{ status: string; error: string | null }>(`/leadoff/jobs/${jobId}`)
      if (job.status === 'complete' || job.status === 'failed') {
        setJobId(null)
        if (job.status === 'failed') setError(job.error ?? 'scout_failed')
        qc.invalidateQueries({ queryKey: ['leadoff-brief'] })
        qc.invalidateQueries({ queryKey: ['leadoff-scout-est', cityId, categoryId] })
      }
      return job
    },
    enabled: Boolean(jobId),
    refetchInterval: jobId ? 5000 : false,
  })

  // Adopt an in-flight scout for this market (e.g. one started before the brief
  // was reopened) so the running indicator survives navigating away and back.
  useEffect(() => {
    if (est?.running_job_id && !jobId) setJobId(est.running_job_id)
  }, [est?.running_job_id])

  const start = async () => {
    if (busy || !est) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<{ job_id: string | null }>('/leadoff/scout', {
        city_id: cityId, category_id: categoryId,
      })
      if (res.job_id) setJobId(res.job_id)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'scout_failed'
      setError(msg === 'budget_exceeded'
        ? 'Daily LeadOff budget reached — try tomorrow or raise the budget.' : msg)
    } finally {
      setBusy(false)
    }
  }

  if (est?.fully_cached) {
    return <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>Scouting data is fresh (≤90 days).</div>
  }
  return (
    <div style={{ marginTop: 8 }}>
      {jobId ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
          background: '#f0fdfa', border: '1px solid #99f6e4', borderRadius: 8 }}>
          <Loader2 size={18} className="spin" style={{ color: '#0e7d6f', flexShrink: 0 }} />
          <div style={{ fontSize: 12, color: '#0f766e', lineHeight: 1.4 }}>
            <div style={{ fontWeight: 600 }}>Scouting this market…</div>
            <div style={{ color: '#5b8c85' }}>
              Pulling RD, review velocity &amp; demand trend · estimated time ~7 minutes.
              Safe to leave — results save automatically and appear here when done.
            </div>
          </div>
        </div>
      ) : (
        <button style={{ ...secondaryBtn, width: '100%', justifyContent: 'center' }} disabled={busy || !est} onClick={start}>
          {busy ? <Loader2 size={14} className="spin" /> : <Binoculars size={14} />}
          Scout this market{est ? ` (~$${est.est_cost.toFixed(2)})` : ''}
        </button>
      )}
      {est && !jobId && (
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
          Paid pull: {est.rd_misses} domain RD, {est.velocity_misses} review-velocity,
          {' '}{est.trend_miss ? 'demand trend' : 'trend cached'}
          {(est.site_misses ?? 0) > 0 && `, ${est.site_misses} site-size`}
          {(est.mention_misses ?? 0) > 0 && `, ${est.mention_misses} brand-mentions`}
          {' '}— cached pieces are free.
        </div>
      )}
      {error && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 4 }}>{error}</div>}
    </div>
  )
}

// ── Bits ─────────────────────────────────────────────────────────────────────
// The handoff (PRD §5 item 2): create a client card pre-loaded with this
// market — location, top-5 competitors into Competitive Intel, effort targets
// as a campaign goal. Website is optional: LeadOff is research-first, the
// site can be added on the client form later.
function CreateClientCard({ brief }: { brief: MarketBrief }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.post<{ client_id: string }>('/leadoff/create-client', {
        city_id: brief.city_id,
        category_id: brief.category_id,
        name: name.trim(),
        website_url: website.trim(),
      })
      navigate(`/clients/${res.client_id}`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'create_failed'
      setError(msg === 'client_name_taken' ? 'A client with that name already exists.' : msg)
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        style={{ ...primaryBtn, width: '100%', justifyContent: 'center', marginTop: 14 }}
        onClick={() => setOpen(true)}
      >
        <UserPlus size={14} /> Create client from this market
      </button>
    )
  }
  const fullInput: React.CSSProperties = { ...inputStyle, width: '100%', boxSizing: 'border-box' }
  return (
    <div style={{
      marginTop: 14, border: '1px solid #e2e8f0', borderRadius: 8, padding: 10,
      display: 'flex', flexDirection: 'column', gap: 8, background: '#f8fafc',
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#0f172a' }}>
        New client — {brief.category}, {brief.city_name}, {brief.state_code}
      </div>
      <input style={fullInput} placeholder="Client name (required)" value={name}
        onChange={e => setName(e.target.value)} autoFocus />
      <input style={fullInput} placeholder="Website (optional — add later)" value={website}
        onChange={e => setWebsite(e.target.value)} />
      <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.4 }}>
        Seeds the top-5 into Competitive Intel and records the effort targets
        (reviews to beat #3, link budget) as a campaign goal.
      </div>
      {error && <div style={{ fontSize: 12, color: '#b91c1c' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button style={primaryBtn} disabled={busy || !name.trim()} onClick={submit}>
          {busy ? <Loader2 size={14} className="spin" /> : <UserPlus size={14} />} Create
        </button>
        <button style={secondaryBtn} onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  )
}

function GradeChip({ grade }: { grade: string }) {
  return (
    <span style={{
      display: 'inline-block', minWidth: 24, textAlign: 'center', borderRadius: 5,
      padding: '2px 6px', fontSize: 11, fontWeight: 700, color: '#fff',
      background: GRADE_COLORS[grade] ?? '#94a3b8',
    }}>{grade}</span>
  )
}
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: '#64748b' }}>
      {label}{children}
    </label>
  )
}
function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, letterSpacing: 0.6, textTransform: 'uppercase',
      color: '#94a3b8', margin: '16px 0 6px',
    }}>{children}</div>
  )
}
function KV({ k, v, strong, hint }: { k: string; v?: string; strong?: boolean; hint?: string }) {
  return (
    <div title={hint} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '2px 0' }}>
      <span style={{ color: '#64748b' }}>{k}</span>
      <span style={{ fontWeight: strong ? 700 : 500, color: '#0f172a' }}>{v ?? '—'}</span>
    </div>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────
const pill: React.CSSProperties = {
  fontSize: 11, background: '#f1f5f9', color: '#64748b', borderRadius: 99,
  padding: '2px 9px', fontWeight: 600,
}
const barStyle: React.CSSProperties = {
  display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 12,
  border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px',
  marginBottom: 14, background: '#fff',
}
const inputStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1', borderRadius: 6, padding: '6px 9px', fontSize: 13, width: 110,
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', gap: 6, alignItems: 'center', background: '#0e7d6f',
  color: '#fff', border: 'none', borderRadius: 7, padding: '8px 14px',
  fontWeight: 600, fontSize: 13, cursor: 'pointer',
}
const secondaryBtn: React.CSSProperties = {
  display: 'inline-flex', gap: 6, alignItems: 'center', background: '#fff',
  color: '#0f172a', border: '1px solid #cbd5e1', borderRadius: 7,
  padding: '8px 12px', fontWeight: 600, fontSize: 13, cursor: 'pointer',
}
const errorBox: React.CSSProperties = {
  border: '1px solid #fca5a5', background: '#fef2f2', color: '#b91c1c',
  borderRadius: 8, padding: '8px 12px', fontSize: 13, marginBottom: 12,
}
const thStyle: React.CSSProperties = {
  fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: '#94a3b8',
  textAlign: 'left', padding: '10px 12px', background: '#f8fafc', whiteSpace: 'nowrap',
}
const tdStyle: React.CSSProperties = {
  padding: '9px 12px', borderTop: '1px solid #e2e8f0', whiteSpace: 'nowrap', color: '#0f172a',
}
const panelStyle: React.CSSProperties = {
  width: 330, flexShrink: 0, border: '1px solid #e2e8f0', borderRadius: 10,
  padding: 18, background: '#fff', position: 'sticky', top: 18,
}
const closeBtn: React.CSSProperties = {
  float: 'right', border: 'none', background: 'none', color: '#94a3b8', cursor: 'pointer',
}
