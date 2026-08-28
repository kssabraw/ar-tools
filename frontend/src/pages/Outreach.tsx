import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Crosshair, Loader2, AlertTriangle, XCircle, CheckCircle2, Clock, Ban, RefreshCw, Phone, Download,
} from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import { useAuth } from '../context/AuthContext'
import { Tabs } from './OutreachLeads'
import { Justification } from '../components/outreach/Justification'
import { ProspectReportButtons } from '../components/outreach/ProspectReport'
import { ContactCell, EnrichmentBar, NameScrapeBar, NameSearchBar, useEnrichment, useNameScrape, useNameSearch } from '../components/outreach/Enrichment'
import type { ProspectContacts } from '../components/outreach/Enrichment'
import { CardRevenueCell, EnigmaBar, useEnigma } from '../components/outreach/EnigmaCards'
import type { ProspectEnigma } from '../components/outreach/EnigmaCards'

// ── Types (mirror routers/outreach.py's scan-order section) ──────────────────
interface Market { id: string; name: string }
interface Submarket { id: string; name: string }
interface Keyword { id: string; term: string; is_primary: boolean }
interface ScanRequest {
  id: string
  submarket_id: string
  keyword_id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  snapshot_id: string | null
  error: string | null
  note: string | null
  created_at: string
  finished_at: string | null
  submarket?: { name: string } | null
  keyword?: { term: string } | null
}
interface TaskProgress {
  counts: Record<string, number>
  total: number
  collected: number
  outstanding: number
  failed: number
}
interface ScanRequestDetail {
  scan_request: ScanRequest
  snapshot: {
    id: string; expected_points: number; actual_points: number
    complete: boolean; scanned_at: string; geometry_version: string
  } | null
  task_progress: TaskProgress | null
  rolled_up: boolean
}
// The fitted Phase-4 model overlay, present on each row only when a score run exists for the
// submarket (I-108). Organic-inclusive: the reply/value scores fold in organic + maps + review + tech.
interface ModelScore {
  channel: string | null
  reply_score: number | null
  reply_prob: number | null
  reply_decile: number | null
  value_score: number | null
  value_decile: number | null
  primary_pitch: string | null
}
interface PlaceholderScore {
  prospect_id: string
  name: string
  phone: string | null
  excluded: boolean | null
  keywords_measured: number
  keywords_present: number
  coverage_pct: number
  coverage_deficit: number
  best_rank: number | null
  centroid_dist_at_loss: number | null
  measured_at: string
  // Present only when the submarket has been scored; absent on the maps-only placeholder fallback.
  model?: ModelScore | null
}

// Any-city onboarding (mirror routers/outreach.py's geo + onboard section)
interface ResolvedCity { name: string; city?: string | null; region?: string | null; lat: number; lng: number; place_id?: string | null }
interface Subarea { name: string; lat: number; lng: number; place_id?: string | null }
interface SubareasResponse { city: ResolvedCity; subareas: Subarea[]; note: string | null }
interface OnboardRequest {
  id: string
  submarket_id: string
  category: string
  region: string | null
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: string | null
  prospects_ingested: number | null
  prospects_survived: number | null
  snapshot_id: string | null
  error: string | null
  created_at: string
  finished_at: string | null
  submarket?: { name: string } | null
  keyword?: { term: string } | null
}

interface OnboardRequestDetail {
  onboard_request: OnboardRequest
  snapshot: {
    id: string; expected_points: number; actual_points: number
    complete: boolean; scanned_at: string; geometry_version: string
  } | null
  task_progress: TaskProgress | null
  rolled_up: boolean
}
// The discovered/collected business data (v_prospect_status), available as soon as discovery runs.
interface Prospect {
  id: string
  name: string
  category: string | null
  phone: string | null
  website: string | null
  rating: number | null
  review_count: number | null
  address: string | null
  excluded: boolean | null
  evaluated: boolean | null
}

const ACTIVE = new Set(['pending', 'running'])

const STATUS_STYLE: Record<ScanRequest['status'], { color: string; bg: string; Icon: typeof Clock }> = {
  pending: { color: '#92400e', bg: '#fef3c7', Icon: Clock },
  running: { color: '#1d4ed8', bg: '#dbeafe', Icon: Loader2 },
  done: { color: '#166534', bg: '#dcfce7', Icon: CheckCircle2 },
  failed: { color: '#b91c1c', bg: '#fee2e2', Icon: XCircle },
  cancelled: { color: '#475569', bg: '#f1f5f9', Icon: Ban },
}

function StatusChip({ status }: { status: ScanRequest['status'] }) {
  const { color, bg, Icon } = STATUS_STYLE[status]
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
      borderRadius: 999, fontSize: 11, fontWeight: 600, color, background: bg,
    }}>
      <Icon size={12} className={status === 'running' ? 'animate-spin' : undefined} />
      {status}
    </span>
  )
}

// A small "Download CSV" button. Builds the file client-side from data the card
// already fetched (the suite's toCsv/downloadCsv convention) — no backend call.
function DownloadCsvButton({ onClick, title }: { onClick: () => void; title?: string }) {
  return (
    <button onClick={onClick} title={title ?? 'Download this run as a CSV'}
      style={{ fontSize: 12, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6,
        padding: '2px 8px', cursor: 'pointer', color: '#334155',
        display: 'inline-flex', gap: 4, alignItems: 'center' }}>
      <Download size={12} /> CSV
    </button>
  )
}

// ── The page ─────────────────────────────────────────────────────────────────

export function Outreach() {
  const { isAdmin } = useAuth()

  const { data: status } = useQuery<{ enabled: boolean; configured: boolean }>({
    queryKey: ['outreach-status'],
    queryFn: () => api.get('/outreach/status'),
  })
  const ready = status?.enabled && status?.configured

  const { data: marketsData } = useQuery<{ markets: Market[] }>({
    queryKey: ['outreach-markets'],
    queryFn: () => api.get('/outreach/markets'),
    enabled: !!ready,
  })
  const markets = marketsData?.markets ?? []
  const [marketId, setMarketId] = useState('')
  const market = markets.find(m => m.id === marketId) ?? markets[0]

  if (status && !ready) {
    return (
      <div style={{ padding: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Crosshair size={20} /> Outreach
        </h1>
        <p style={{ color: '#64748b', marginTop: 12, fontSize: 14 }}>
          {status.enabled
            ? 'The outreach module is enabled but not configured — the Outreacher project credentials are missing on platform-api.'
            : 'The outreach module is not enabled on this deployment.'}
        </p>
      </div>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Crosshair size={20} /> Outreach — geogrid scans
        </h1>
        {markets.length > 1 && (
          <select value={market?.id ?? ''} onChange={e => setMarketId(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0' }}>
            {markets.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        )}
      </div>

      <Tabs active="scans" />

      <OnboardCityCard isAdmin={isAdmin} />
      <OnboardOrdersCard />
      {market && <BusinessesCard marketId={market.id} />}
      {market && <ResultsCard marketId={market.id} />}
      {market && <QueueScanCard marketId={market.id} isAdmin={isAdmin} />}
      <OrdersCard />
    </div>
  )
}

// ── Scan any city: City + Business type ──────────────────────────────────────

function OnboardCityCard({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const [cityQuery, setCityQuery] = useState('')
  const [businessType, setBusinessType] = useState('')
  const [subIdx, setSubIdx] = useState(-1)
  const [confirming, setConfirming] = useState(false)

  const find = useMutation({
    mutationFn: () =>
      api.get<SubareasResponse>(`/outreach/geo/subareas?q=${encodeURIComponent(cityQuery.trim())}`),
    onSuccess: () => { setSubIdx(-1); setConfirming(false) },
  })
  const result = find.data
  const city = result?.city
  const subareas = result?.subareas ?? []
  const WHOLE_CITY = -2
  const wholeCity = subIdx === WHOLE_CITY
  const subarea = subIdx >= 0 ? subareas[subIdx] : undefined
  const targetChosen = wholeCity || !!subarea

  const place = useMutation({
    mutationFn: () =>
      api.post<{ onboard_request: OnboardRequest }>('/outreach/onboard-requests', {
        city: { name: city!.name, region: city!.region, lat: city!.lat, lng: city!.lng },
        // Omit the sub-area to scan the whole city centre.
        subarea: subarea
          ? { name: subarea.name, lat: subarea.lat, lng: subarea.lng, place_id: subarea.place_id }
          : null,
        business_type: businessType.trim(),
      }),
    onSuccess: () => {
      setConfirming(false)
      queryClient.invalidateQueries({ queryKey: ['outreach-onboard-requests'] })
    },
  })

  const findError = find.error instanceof Error
    ? (find.error.message === 'city_not_found' ? `Couldn't find a city matching “${cityQuery}”.` : find.error.message)
    : null
  const placeError = place.error instanceof Error
    ? (place.error.message === 'onboard_request_already_active'
      ? 'This city sub-area × business type is already discovering or queued.'
      : place.error.message)
    : null

  const canQueue = isAdmin && targetChosen && businessType.trim().length > 0

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ fontWeight: 600, fontSize: 14 }}>Scan a city</div>
      <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 12px' }}>
        Type a city and the <strong>search a customer would use</strong> (e.g. “emergency plumber”).
        The engine <strong>discovers</strong> the businesses competing for that search (a paid data
        pull), filters them, then <strong>scans</strong> that search across the grid — so the results
        are real coverage, not an empty grid. Pick a specific sub-area or scan the whole city. This
        spends at two points and runs over several minutes; you can leave and check back below.
      </p>

      {/* Step 1 — city + the consumer search */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          value={cityQuery}
          onChange={e => { setCityQuery(e.target.value); find.reset(); place.reset() }}
          onKeyDown={e => { if (e.key === 'Enter' && cityQuery.trim()) find.mutate() }}
          placeholder="City, e.g. Van Nuys, CA"
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', minWidth: 200 }}
        />
        <input
          value={businessType}
          onChange={e => { setBusinessType(e.target.value); place.reset() }}
          placeholder="What a customer searches, e.g. emergency plumber"
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', minWidth: 240 }}
        />
        <button
          onClick={() => find.mutate()}
          disabled={!cityQuery.trim() || find.isPending}
          style={{ padding: '6px 14px', borderRadius: 8, border: '1px solid #e2e8f0',
            background: '#fff', fontWeight: 600, fontSize: 13,
            cursor: cityQuery.trim() ? 'pointer' : 'not-allowed' }}>
          {find.isPending ? <Loader2 size={13} className="animate-spin" /> : 'Find city'}
        </button>
      </div>
      {findError && (
        <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
          <AlertTriangle size={13} /> {findError}
        </p>
      )}

      {/* Step 2 — pick a target: the whole city, or a verified sub-area */}
      {result && (
        <div style={{ marginTop: 12 }}>
          {city && (
            <div style={{ fontSize: 12, color: '#334155', marginBottom: 6 }}>
              Resolved <strong>{city.name}</strong> —{' '}
              {subareas.length > 0
                ? `${subareas.length} Google-verified sub-area${subareas.length === 1 ? '' : 's'}, or scan the whole city.`
                : (result.note ? `${result.note} Scan the whole city.` : 'Scan the whole city.')}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <select value={subIdx} onChange={e => { setSubIdx(Number(e.target.value)); place.reset() }}
              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', minWidth: 220 }}>
              <option value={-1}>Choose a target…</option>
              <option value={WHOLE_CITY}>Whole city (center)</option>
              {subareas.map((s, i) => <option key={s.place_id ?? s.name} value={i}>{s.name}</option>)}
            </select>
            {!confirming ? (
              <button
                disabled={!canQueue}
                onClick={() => setConfirming(true)}
                title={isAdmin ? undefined : 'Placing an order is admin-only — it authorizes spend'}
                style={{ padding: '6px 14px', borderRadius: 8, border: 'none', fontWeight: 600, fontSize: 13,
                  background: canQueue ? '#0f172a' : '#e2e8f0', color: canQueue ? '#fff' : '#94a3b8',
                  cursor: canQueue ? 'pointer' : 'not-allowed' }}>
                Discover &amp; scan…
              </button>
            ) : (
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12, color: '#b45309', fontWeight: 600 }}>
                  Discover “{businessType.trim()}” across {subarea?.name ?? `${city?.name} (whole city)`},
                  then scan it? Spends on the data pull + ≈$0.81 scan.
                </span>
                <button onClick={() => place.mutate()} disabled={place.isPending}
                  style={{ padding: '6px 14px', borderRadius: 8, border: 'none', fontWeight: 600,
                    fontSize: 13, background: '#b45309', color: '#fff', cursor: 'pointer' }}>
                  {place.isPending ? <Loader2 size={13} className="animate-spin" /> : 'Confirm — place order'}
                </button>
                <button onClick={() => setConfirming(false)}
                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0',
                    background: '#fff', fontSize: 13, cursor: 'pointer' }}>
                  Back
                </button>
              </span>
            )}
          </div>
        </div>
      )}
      {!isAdmin && (
        <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 8 }}>
          Viewing only — placing an order is admin-only, because the click is the spend authorization.
        </p>
      )}
      {placeError && (
        <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
          <AlertTriangle size={13} /> {placeError}
        </p>
      )}
    </div>
  )
}

// ── Onboard orders (discover → filter → scan) ────────────────────────────────

function OnboardOrdersCard() {
  const queryClient = useQueryClient()
  const [openId, setOpenId] = useState<string | null>(null)

  const { data, isLoading, isFetching } = useQuery<{ onboard_requests: OnboardRequest[]; total: number }>({
    queryKey: ['outreach-onboard-requests'],
    queryFn: () => api.get('/outreach/onboard-requests?limit=25'),
    refetchInterval: q =>
      (q.state.data?.onboard_requests ?? []).some(r => ACTIVE.has(r.status)) ? 20_000 : false,
  })
  const orders = data?.onboard_requests ?? []

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`/outreach/onboard-requests/${id}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['outreach-onboard-requests'] }),
  })

  if (!isLoading && orders.length === 0) return null

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>City onboards (discover → filter → scan)</div>
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ['outreach-onboard-requests'] })}
          style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748b' }} title="Refresh">
          <RefreshCw size={14} style={isFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
        </button>
      </div>
      {isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>Loading…</p>
      ) : (
        // table-layout:fixed so this table's cells (incl. the colSpan results cell holding the
        // nested CoverageTable) have DEFINITE widths — otherwise an auto-layout cell expands to the
        // wide inner table and pushes the card border out instead of letting it scroll.
        <table style={{ width: '100%', tableLayout: 'fixed', marginTop: 8, fontSize: 13, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
              <th style={{ padding: '4px 8px', width: 200 }}>Placed</th>
              <th style={{ padding: '4px 8px' }}>Target</th>
              <th style={{ padding: '4px 8px' }}>Search</th>
              <th style={{ padding: '4px 8px', width: 150 }}>Stage</th>
              <th style={{ padding: '4px 8px', width: 110 }}>Status</th>
              <th style={{ padding: '4px 8px', width: 130 }} />
            </tr>
          </thead>
          <tbody>
            {orders.map(order => (
              <Fragment key={order.id}>
                <tr style={{ borderTop: '1px solid #f1f5f9', cursor: order.snapshot_id ? 'pointer' : 'default' }}
                  onClick={() => order.snapshot_id && setOpenId(openId === order.id ? null : order.id)}>
                  <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{new Date(order.created_at).toLocaleString()}</td>
                  <td style={{ padding: '6px 8px' }}>{order.submarket?.name ?? '—'}</td>
                  <td style={{ padding: '6px 8px' }}>{order.keyword?.term ?? order.category}</td>
                  <td style={{ padding: '6px 8px', color: '#475569' }}>
                    {order.status === 'running' ? (order.stage ?? 'starting…') : (order.stage ?? '—')}
                    {order.prospects_survived != null && <> · {order.prospects_survived} kept</>}
                  </td>
                  <td style={{ padding: '6px 8px' }}><StatusChip status={order.status} /></td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {order.status === 'pending' ? (
                      <button onClick={e => { e.stopPropagation(); cancel.mutate(order.id) }}
                        style={{ fontSize: 12, border: '1px solid #e2e8f0', background: '#fff',
                          borderRadius: 6, padding: '2px 8px', cursor: 'pointer', color: '#b91c1c' }}>
                        Withdraw
                      </button>
                    ) : order.snapshot_id ? (
                      <span style={{ fontSize: 12, color: '#2563eb', fontWeight: 600 }}>
                        {openId === order.id ? 'Hide ▲' : 'View results ▾'}
                      </span>
                    ) : null}
                  </td>
                </tr>
                {order.status === 'failed' && order.error && (
                  <tr>
                    <td colSpan={6} style={{ padding: '0 8px 6px', fontSize: 12, color: '#b91c1c' }}>
                      {order.stage ? `Failed at ${order.stage}: ` : ''}{order.error} — a failed order is never
                      retried automatically; place a new one once the cause is fixed.
                    </td>
                  </tr>
                )}
                {openId === order.id && order.snapshot_id && (
                  <tr>
                    <td colSpan={6} style={{ padding: '4px 8px 10px' }}>
                      <OnboardProgress id={order.id} />
                      <div style={{ fontWeight: 600, fontSize: 13, margin: '12px 0 0' }}>
                        Results for this scan
                      </div>
                      <CoverageTable submarketId={order.submarket_id}
                        submarketName={order.submarket?.name} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function OnboardProgress({ id }: { id: string }) {
  const { data } = useQuery<OnboardRequestDetail>({
    queryKey: ['outreach-onboard-request', id],
    queryFn: () => api.get(`/outreach/onboard-requests/${id}`),
    refetchInterval: q => {
      const d = q.state.data
      if (!d?.task_progress) return 30_000
      // Keep polling until every point is terminal AND the rollup marker exists.
      return d.task_progress.outstanding > 0 || !d.rolled_up ? 30_000 : false
    },
  })
  if (!data?.task_progress || !data.snapshot) {
    return <span style={{ fontSize: 12, color: '#64748b' }}>Waiting for the scan to post…</span>
  }
  const p = data.task_progress
  const pct = p.total ? Math.round((p.collected / p.total) * 100) : 0
  return (
    <div style={{ fontSize: 12, color: '#334155' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, height: 8, background: '#f1f5f9', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: '#0f172a' }} />
        </div>
        <span>{p.collected}/{p.total} points collected</span>
      </div>
      <div style={{ marginTop: 4, color: '#64748b' }}>
        {p.outstanding > 0 && <>Results arrive over the next hours as the provider finishes each point. </>}
        {p.failed > 0 && <span style={{ color: '#b91c1c' }}>{p.failed} point{p.failed > 1 ? 's' : ''} failed. </span>}
        Snapshot {data.snapshot.complete ? 'complete' : 'incomplete'} ·{' '}
        {data.rolled_up
          ? 'coverage rolled up — see “Coverage results” below.'
          : 'coverage not rolled up yet.'}
      </div>
    </div>
  )
}

// ── Businesses found (the collected data — available as soon as discovery runs) ──────────────

function BusinessesCard({ marketId }: { marketId: string }) {
  const [submarketId, setSubmarketId] = useState('')
  const { data: subsData } = useQuery<{ submarkets: Submarket[] }>({
    queryKey: ['outreach-submarkets', marketId],
    queryFn: () => api.get(`/outreach/markets/${marketId}/submarkets`),
  })
  const submarkets = subsData?.submarkets ?? []

  const { data, isLoading } = useQuery<{ prospects: Prospect[]; total: number }>({
    queryKey: ['outreach-prospects', submarketId],
    queryFn: () => api.get(`/outreach/prospects?submarket_id=${submarketId}&status=survived&limit=200`),
    enabled: !!submarketId,
  })
  const prospects = data?.prospects ?? []

  const exportCsv = () => {
    const headers = ['Business', 'Category', 'Phone', 'Website', 'Rating', 'Reviews', 'Address']
    const rows = prospects.map(p => [
      p.name, p.category ?? '', p.phone ?? '', p.website ?? '',
      p.rating != null ? p.rating.toFixed(1) : '', p.review_count ?? '', p.address ?? '',
    ])
    const slug = (submarkets.find(s => s.id === submarketId)?.name ?? 'submarket')
      .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    downloadCsv(`outreach-businesses-${slug}-${new Date().toISOString().slice(0, 10)}.csv`,
      toCsv(headers, rows))
  }

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>Businesses found</div>
        <select value={submarketId} onChange={e => setSubmarketId(e.target.value)}
          style={{ padding: '4px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
          <option value="">Choose a target…</option>
          {submarkets.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {prospects.length > 0 && (
          <div style={{ marginLeft: 'auto' }}>
            <DownloadCsvButton onClick={exportCsv} title="Download these businesses as a CSV" />
          </div>
        )}
      </div>
      <p style={{ fontSize: 11, color: '#94a3b8', margin: '6px 0 0' }}>
        The businesses discovery found and the filter kept — available as soon as a scan's discovery
        stage runs, before the grid finishes collecting. This is what was collected; coverage per
        business shows in “Coverage results” once the scan rolls up.
      </p>
      {!submarketId ? null : isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>Loading…</p>
      ) : prospects.length === 0 ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
          No businesses kept here yet — either nothing has been discovered for this target, or the
          filter excluded them all.
        </p>
      ) : (
        <table style={{ width: '100%', marginTop: 8, fontSize: 13, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
              <th style={{ padding: '4px 8px' }}>Business</th>
              <th style={{ padding: '4px 8px' }}>Category</th>
              <th style={{ padding: '4px 8px' }}>Phone</th>
              <th style={{ padding: '4px 8px' }}>Website</th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>Rating</th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>Reviews</th>
            </tr>
          </thead>
          <tbody>
            {prospects.map(p => (
              <tr key={p.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                <td style={{ padding: '6px 8px' }}>{p.name}</td>
                <td style={{ padding: '6px 8px', color: '#475569' }}>{p.category ?? '—'}</td>
                <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{p.phone ?? '—'}</td>
                <td style={{ padding: '6px 8px', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.website
                    ? <a href={p.website} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>{p.website.replace(/^https?:\/\//, '')}</a>
                    : '—'}
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.rating != null ? p.rating.toFixed(1) : '—'}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.review_count ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {prospects.length > 0 && (
        <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
          Showing up to 200 kept businesses. Coverage ranking (who's most invisible) is in “Coverage
          results”.
        </p>
      )}
    </div>
  )
}

// ── Queue a scan ─────────────────────────────────────────────────────────────

function QueueScanCard({ marketId, isAdmin }: { marketId: string; isAdmin: boolean }) {
  const queryClient = useQueryClient()
  const [submarketId, setSubmarketId] = useState('')
  const [keywordId, setKeywordId] = useState('')
  const [confirming, setConfirming] = useState(false)

  const { data: subsData } = useQuery<{ submarkets: Submarket[] }>({
    queryKey: ['outreach-submarkets', marketId],
    queryFn: () => api.get(`/outreach/markets/${marketId}/submarkets`),
  })
  const { data: kwData } = useQuery<{ keywords: Keyword[] }>({
    queryKey: ['outreach-keywords', marketId],
    queryFn: () => api.get(`/outreach/markets/${marketId}/keywords`),
  })
  const submarkets = subsData?.submarkets ?? []
  const keywords = kwData?.keywords ?? []
  const submarket = submarkets.find(s => s.id === submarketId)
  const keyword = keywords.find(k => k.id === keywordId) ?? keywords.find(k => k.is_primary)

  const place = useMutation({
    mutationFn: () => api.post<{ scan_request: ScanRequest }>('/outreach/scan-requests', {
      submarket_id: submarketId,
      keyword_id: keyword?.id,
    }),
    onSuccess: () => {
      setConfirming(false)
      queryClient.invalidateQueries({ queryKey: ['outreach-scan-requests'] })
    },
  })

  const errorText = place.error instanceof Error
    ? (place.error.message === 'scan_request_already_active'
      ? 'An order for this submarket × keyword is already pending or running.'
      : place.error.message)
    : null

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ fontWeight: 600, fontSize: 14 }}>Queue a scan</div>
      <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 12px' }}>
        Placing an order posts one <strong>paid</strong> DataForSEO task per grid point
        (81 on the standard 5-mile grid, ≈$0.81 at the configured rate). The engine picks orders
        up on its next tick — within its cron interval, not instantly — and collection follows
        over the next hours as the provider finishes each point.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={submarketId} onChange={e => { setSubmarketId(e.target.value); place.reset() }}
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          <option value="">Choose a submarket…</option>
          {submarkets.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={keyword?.id ?? ''} onChange={e => { setKeywordId(e.target.value); place.reset() }}
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0' }}>
          {keywords.map(k => (
            <option key={k.id} value={k.id}>{k.term}{k.is_primary ? ' (primary)' : ''}</option>
          ))}
        </select>
        {!confirming ? (
          <button
            disabled={!isAdmin || !submarket || !keyword}
            onClick={() => setConfirming(true)}
            title={isAdmin ? undefined : 'Placing a scan order is admin-only — it authorizes spend'}
            style={{
              padding: '6px 14px', borderRadius: 8, border: 'none', fontWeight: 600, fontSize: 13,
              background: isAdmin && submarket ? '#0f172a' : '#e2e8f0',
              color: isAdmin && submarket ? '#fff' : '#94a3b8',
              cursor: isAdmin && submarket ? 'pointer' : 'not-allowed',
            }}>
            Queue scan…
          </button>
        ) : (
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: '#b45309', fontWeight: 600 }}>
              Spend ≈$0.81 scanning “{keyword?.term}” across {submarket?.name}?
            </span>
            <button onClick={() => place.mutate()} disabled={place.isPending}
              style={{ padding: '6px 14px', borderRadius: 8, border: 'none', fontWeight: 600,
                fontSize: 13, background: '#b45309', color: '#fff', cursor: 'pointer' }}>
              {place.isPending ? <Loader2 size={13} className="animate-spin" /> : 'Confirm — place order'}
            </button>
            <button onClick={() => setConfirming(false)}
              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0',
                background: '#fff', fontSize: 13, cursor: 'pointer' }}>
              Back
            </button>
          </span>
        )}
      </div>
      {!isAdmin && (
        <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 8 }}>
          Viewing only — placing a scan order is admin-only, because the click is the spend
          authorization.
        </p>
      )}
      {errorText && (
        <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
          <AlertTriangle size={13} /> {errorText}
        </p>
      )}
    </div>
  )
}

// ── Orders ───────────────────────────────────────────────────────────────────

function OrdersCard() {
  const queryClient = useQueryClient()
  const [openId, setOpenId] = useState<string | null>(null)

  const { data, isLoading, isFetching } = useQuery<{ scan_requests: ScanRequest[]; total: number }>({
    queryKey: ['outreach-scan-requests'],
    queryFn: () => api.get('/outreach/scan-requests?limit=25'),
    // Poll only while something is in flight — a settled queue is a cheap one-off read.
    refetchInterval: q =>
      (q.state.data?.scan_requests ?? []).some(r => ACTIVE.has(r.status)) ? 20_000 : false,
  })
  const orders = data?.scan_requests ?? []

  const cancel = useMutation({
    mutationFn: (id: string) => api.post(`/outreach/scan-requests/${id}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['outreach-scan-requests'] }),
  })

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>Scan orders</div>
        <button onClick={() => queryClient.invalidateQueries({ queryKey: ['outreach-scan-requests'] })}
          style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#64748b' }}
          title="Refresh">
          <RefreshCw size={14} style={isFetching ? { animation: 'spin 1s linear infinite' } : undefined} />
        </button>
      </div>
      {isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>Loading…</p>
      ) : orders.length === 0 ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
          No orders yet. The first one placed here will be the pipeline's first live scan.
        </p>
      ) : (
        <table style={{ width: '100%', marginTop: 8, fontSize: 13, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
              <th style={{ padding: '4px 8px' }}>Placed</th>
              <th style={{ padding: '4px 8px' }}>Submarket</th>
              <th style={{ padding: '4px 8px' }}>Keyword</th>
              <th style={{ padding: '4px 8px' }}>Status</th>
              <th style={{ padding: '4px 8px' }} />
            </tr>
          </thead>
          <tbody>
            {orders.map(order => (
              <Fragment key={order.id}>
                <tr style={{ borderTop: '1px solid #f1f5f9', cursor: 'pointer' }}
                  onClick={() => setOpenId(openId === order.id ? null : order.id)}>
                  <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>
                    {new Date(order.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: '6px 8px' }}>{order.submarket?.name ?? order.submarket_id}</td>
                  <td style={{ padding: '6px 8px' }}>{order.keyword?.term ?? order.keyword_id}</td>
                  <td style={{ padding: '6px 8px' }}><StatusChip status={order.status} /></td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {order.status === 'pending' && (
                      <button
                        onClick={e => { e.stopPropagation(); cancel.mutate(order.id) }}
                        style={{ fontSize: 12, border: '1px solid #e2e8f0', background: '#fff',
                          borderRadius: 6, padding: '2px 8px', cursor: 'pointer', color: '#b91c1c' }}>
                        Withdraw
                      </button>
                    )}
                  </td>
                </tr>
                {order.status === 'failed' && order.error && (
                  <tr>
                    <td colSpan={5} style={{ padding: '0 8px 6px', fontSize: 12, color: '#b91c1c' }}>
                      {order.error} — a failed order is never retried automatically; place a new
                      one once the cause is fixed.
                    </td>
                  </tr>
                )}
                {openId === order.id && (order.status === 'running' || order.status === 'done') && (
                  <tr>
                    <td colSpan={5} style={{ padding: '4px 8px 10px' }}>
                      <OrderProgress id={order.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function OrderProgress({ id }: { id: string }) {
  const { data } = useQuery<ScanRequestDetail>({
    queryKey: ['outreach-scan-request', id],
    queryFn: () => api.get(`/outreach/scan-requests/${id}`),
    refetchInterval: q => {
      const d = q.state.data
      // Keep polling until every task is terminal AND the rollup marker exists.
      if (!d?.task_progress) return 30_000
      return d.task_progress.outstanding > 0 || !d.rolled_up ? 30_000 : false
    },
  })
  if (!data?.task_progress || !data.snapshot) {
    return <span style={{ fontSize: 12, color: '#64748b' }}>Waiting for the engine's next tick…</span>
  }
  const p = data.task_progress
  const pct = p.total ? Math.round((p.collected / p.total) * 100) : 0
  return (
    <div style={{ fontSize: 12, color: '#334155' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, height: 8, background: '#f1f5f9', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: `${pct}%`, height: '100%', background: '#0f172a' }} />
        </div>
        <span>{p.collected}/{p.total} points collected</span>
      </div>
      <div style={{ marginTop: 4, color: '#64748b' }}>
        {p.outstanding > 0 && <>Results arrive over the next hours as the provider finishes each point. </>}
        {p.failed > 0 && <span style={{ color: '#b91c1c' }}>{p.failed} point{p.failed > 1 ? 's' : ''} failed. </span>}
        Snapshot {data.snapshot.complete ? 'complete' : 'incomplete'} ·{' '}
        {data.rolled_up
          ? 'coverage rolled up — results below.'
          : 'coverage not rolled up yet.'}
      </div>
    </div>
  )
}

// ── Results ──────────────────────────────────────────────────────────────────

// The ranked coverage table for ONE submarket — reused by the Coverage results card (with a
// submarket picker) and by an onboard row's inline results (submarket fixed to that scan).
function CoverageTable({ submarketId, submarketName }: { submarketId: string; submarketName?: string }) {
  const { isAdmin, isStaff } = useAuth()
  const [promoted, setPromoted] = useState<Record<string, boolean>>({})
  const [emitted, setEmitted] = useState<Record<string, { delivered: boolean; configured: boolean }>>({})
  const [openHook, setOpenHook] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const enrich = useEnrichment(submarketId)
  const nameScrape = useNameScrape(submarketId)
  const nameSearch = useNameSearch(submarketId)
  const enigma = useEnigma(submarketId)
  const batchRunning = enrich.batch.running
  const nameBatchRunning = nameScrape.batch.running
  const nameSearchBatchRunning = nameSearch.batch.running
  const enigmaBatchRunning = enigma.batch.running
  const toggle = (id: string) =>
    setSelected(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next })
  const promote = useMutation({
    mutationFn: (prospectId: string) =>
      api.post<{ lead: { id: string; already_existed: boolean } }>(
        `/outreach/prospects/${prospectId}/promote`, {}),
    onSuccess: (_data, prospectId) => setPromoted(p => ({ ...p, [prospectId]: true })),
  })
  // Emit writes the outcome (the non-backfillable modelling substrate) and posts the outbound
  // queue webhook. The button is enabled for every measured prospect; the backend records the
  // outcome even when the webhook URL is unset (delivered:false), so the substrate fills regardless.
  const emit = useMutation({
    mutationFn: (prospectId: string) =>
      api.post<{ delivery: { delivered: boolean; configured: boolean } }>(
        `/outreach/prospects/${prospectId}/emit`, {}),
    onSuccess: (data, prospectId) =>
      setEmitted(e => ({ ...e, [prospectId]: {
        delivered: !!data.delivery?.delivered, configured: !!data.delivery?.configured } })),
  })
  const { data, isLoading } = useQuery<{ scores: PlaceholderScore[]; total: number; measured: boolean; scored?: boolean }>({
    queryKey: ['outreach-placeholder-scores', submarketId],
    queryFn: () => api.get(`/outreach/submarkets/${submarketId}/placeholder-scores?limit=200`),
    enabled: !!submarketId,
  })
  // Contacts for the whole table in ONE read (no per-row N+1). Keyed on the visible prospect ids;
  // refetched while an enrichment batch drains so freshly-written contacts appear without a reload.
  const visibleIds = (data?.scores ?? []).filter(s => !s.excluded).map(s => s.prospect_id)
  const { data: contactsBatch } = useQuery<{ by_prospect: Record<string, ProspectContacts> }>({
    queryKey: ['outreach-contacts-batch', submarketId, visibleIds],
    queryFn: () => api.post('/outreach/contacts/batch', { prospect_ids: visibleIds }),
    enabled: visibleIds.length > 0,
    refetchInterval: batchRunning || nameBatchRunning || nameSearchBatchRunning ? 6000 : false,
  })
  // Enigma card revenue for the whole table in ONE read (no per-row N+1). Refetched while an enigma
  // batch drains so freshly-written card figures appear without a reload — same pattern as contacts.
  const { data: enigmaBatch } = useQuery<{ by_prospect: Record<string, ProspectEnigma> }>({
    queryKey: ['outreach-enigma-batch', submarketId, visibleIds],
    queryFn: () => api.post('/outreach/enigma/batch', { prospect_ids: visibleIds }),
    enabled: visibleIds.length > 0,
    refetchInterval: enigmaBatchRunning ? 6000 : false,
  })

  if (!submarketId) return null
  if (isLoading) return <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>Loading…</p>
  if (!data?.measured) {
    return (
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
        Not measured yet — coverage appears once the scan finishes collecting and rolls up. An empty
        result here means “nothing measured”, never “nobody visible”.
      </p>
    )
  }
  const visible = data.scores.filter(s => !s.excluded)
  const allSelected = visible.length > 0 && visible.every(s => selected.has(s.prospect_id))
  const scored = !!data?.scored
  const colSpan = 8 + (isAdmin ? 1 : 0) + 1 + (scored ? 1 : 0)  // + checkbox + contacts + card + (model score)

  const exportCsv = () => {
    const by = contactsBatch?.by_prospect
    const join = (id: string, pick: (c: ProspectContacts['contacts'][number]) => string | null | undefined) =>
      (by?.[id]?.contacts ?? []).map(pick).filter(Boolean).join('; ')
    const en = enigmaBatch?.by_prospect
    const headers = [
      'Prospect', 'Phone',
      ...(scored ? ['Model score', 'Model decile'] : []),
      'Coverage %', 'Deficit %', 'Best rank', 'Drops out at (mi)',
      'Website', 'Contact names', 'Emails', 'Contact phones',
      'Card revenue 12m', 'Card revenue 3m', 'Card revenue 1m', 'Card as-of', 'Measured at',
    ]
    const rows = visible.map(s => {
      const e = en?.[s.prospect_id]
      const card = (v: number | null | undefined) => (v != null ? String(Math.round(v)) : '')
      return [
        s.name,
        s.phone ?? '',
        ...(scored ? [
          s.model?.reply_score != null ? String(Math.round(s.model.reply_score)) : '',
          s.model?.reply_decile != null ? String(s.model.reply_decile) : '',
        ] : []),
        s.coverage_pct != null ? s.coverage_pct.toFixed(1) : '',
        s.coverage_deficit != null ? s.coverage_deficit.toFixed(1) : '',
        s.best_rank ?? '',
        s.centroid_dist_at_loss != null ? s.centroid_dist_at_loss.toFixed(1) : '',
        by?.[s.prospect_id]?.website ?? '',
        join(s.prospect_id, c => c.full_name || c.name_for_emails),
        join(s.prospect_id, c => c.email),
        join(s.prospect_id, c => c.phone),
        card(e?.card_revenue_12m),
        card(e?.card_revenue_3m),
        card(e?.card_revenue_1m),
        e?.card_as_of ?? '',
        s.measured_at ?? '',
      ]
    })
    const slug = (submarketName ?? submarketId)
      .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    downloadCsv(`outreach-coverage-${slug}-${new Date().toISOString().slice(0, 10)}.csv`,
      toCsv(headers, rows))
  }

  return (
    <>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', margin: '6px 0 0' }}>
        <p style={{ fontSize: 11, color: '#94a3b8', margin: 0 }}>
          {scored ? (
            <>
              Ranked by the <b>fitted model</b> — it folds in organic rank, Maps coverage, reviews and
              site/ad tech. Every coefficient is an elicited prior, so treat rank order as a strong
              prior, not a prediction, until ~100 prospects have been called. Send the top ones to your CRM.
            </>
          ) : (
            <>
              Ranked by <b>Maps coverage deficit</b> — a business absent at every measured point shows
              100% deficit (zero coverage, not unknown). Run a model score to also weigh organic rank.
              Send the most invisible ones to your CRM.
            </>
          )}
        </p>
        {visible.length > 0 && (
          <div style={{ marginLeft: 'auto', flexShrink: 0 }}>
            <DownloadCsvButton onClick={exportCsv} title="Download this run's coverage (with contacts) as a CSV" />
          </div>
        )}
      </div>
      {isAdmin && (
        <EnrichmentBar
          selectedIds={[...selected]}
          controller={enrich}
          onCleared={() => setSelected(new Set())}
        />
      )}
      {isAdmin && (
        <NameScrapeBar
          selectedIds={[...selected]}
          controller={nameScrape}
          onCleared={() => setSelected(new Set())}
        />
      )}
      {isAdmin && (
        <NameSearchBar
          selectedIds={[...selected]}
          controller={nameSearch}
          onCleared={() => setSelected(new Set())}
        />
      )}
      {isAdmin && (
        <EnigmaBar
          selectedIds={[...selected]}
          controller={enigma}
          onCleared={() => setSelected(new Set())}
        />
      )}
      {/* Horizontal scroll: the coverage table has many columns (contacts + a wide actions
          group), so it can exceed the card width — scroll it rather than crush the columns.
          width:max-content sizes the table to its content (no crushing); we deliberately do NOT
          stretch it to the card (no minWidth:100%), or the extra width on a wide screen is dumped
          into the Contacts column as a big empty gap. */}
      <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table style={{ width: 'max-content', fontSize: 13, borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', color: '#64748b', fontSize: 11 }}>
            {isAdmin && (
              <th style={{ padding: '4px 8px', width: 24 }}>
                <input type="checkbox" checked={allSelected}
                  title="Select all for enrichment"
                  onChange={() => setSelected(allSelected ? new Set() : new Set(visible.map(s => s.prospect_id)))} />
              </th>
            )}
            <th style={{ padding: '4px 8px' }}>Prospect</th>
            {scored && <th style={{ padding: '4px 8px', textAlign: 'right' }} title="Fitted model reply score (organic + maps + reviews + tech). A strong prior, not a prediction.">Score</th>}
            <th style={{ padding: '4px 8px' }}>Phone</th>
            <th style={{ padding: '4px 8px' }}>Contacts</th>
            <th style={{ padding: '4px 8px' }}>Card revenue</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Coverage</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Deficit</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Best rank</th>
            <th style={{ padding: '4px 8px', textAlign: 'right' }}>Drops out at</th>
            <th style={{ padding: '4px 8px' }} />
          </tr>
        </thead>
        <tbody>
          {visible.map(s => (
            <Fragment key={s.prospect_id}>
              <tr style={{ borderTop: '1px solid #f1f5f9' }}>
                {isAdmin && (
                  <td style={{ padding: '6px 8px' }}>
                    <input type="checkbox" checked={selected.has(s.prospect_id)}
                      onChange={() => toggle(s.prospect_id)} />
                  </td>
                )}
                <td style={{ padding: '6px 8px' }}>{s.name}</td>
                {scored && (
                  <td style={{ padding: '6px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}
                    title={s.model?.primary_pitch ? `Primary pitch: ${s.model.primary_pitch}` : undefined}>
                    {s.model?.reply_score != null ? (
                      <>
                        <b>{Math.round(s.model.reply_score)}</b>
                        {s.model.reply_decile != null && (
                          <span style={{ fontSize: 11, color: '#94a3b8' }}> · d{s.model.reply_decile}</span>
                        )}
                      </>
                    ) : '—'}
                  </td>
                )}
                <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>{s.phone ?? '—'}</td>
                <td style={{ padding: '6px 8px' }}>
                  <ContactCell prospectId={s.prospect_id} isAdmin={isAdmin} isStaff={isStaff}
                    controller={enrich} batchRunning={batchRunning}
                    nameController={nameScrape} nameBatchRunning={nameBatchRunning}
                    nameSearchController={nameSearch} nameSearchBatchRunning={nameSearchBatchRunning}
                    provided={contactsBatch?.by_prospect?.[s.prospect_id] ?? null} />
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <CardRevenueCell prospectId={s.prospect_id} isAdmin={isAdmin}
                    controller={enigma} batchRunning={enigmaBatchRunning}
                    provided={enigmaBatch?.by_prospect?.[s.prospect_id] ?? null} />
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{s.coverage_pct?.toFixed(1)}%</td>
                <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>
                  {s.coverage_deficit?.toFixed(1)}%
                </td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{s.best_rank ?? '—'}</td>
                <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                  {s.centroid_dist_at_loss != null ? `${s.centroid_dist_at_loss.toFixed(1)} mi` : '—'}
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', justifyContent: 'flex-end' }}>
                    <ProspectReportButtons prospectId={s.prospect_id} compact />
                    <button
                      onClick={() => setOpenHook(openHook === s.prospect_id ? null : s.prospect_id)}
                      title="Why this business is worth calling"
                      style={{ fontSize: 12, border: '1px solid #e2e8f0', background: openHook === s.prospect_id ? '#eff6ff' : '#fff',
                        borderRadius: 6, padding: '2px 8px', cursor: 'pointer',
                        display: 'inline-flex', gap: 4, alignItems: 'center', color: '#0369a1' }}>
                      <Phone size={12} /> Why call?
                    </button>
                    {promoted[s.prospect_id] ? (
                      <span style={{ fontSize: 12, color: '#166534' }}>✓ on board</span>
                    ) : (
                      <button
                        onClick={() => promote.mutate(s.prospect_id)}
                        disabled={promote.isPending}
                        style={{ fontSize: 12, border: '1px solid #e2e8f0', background: '#fff',
                          borderRadius: 6, padding: '2px 10px', cursor: 'pointer' }}>
                        Send to CRM
                      </button>
                    )}
                    {emitted[s.prospect_id] ? (
                      <span style={{ fontSize: 12, color: emitted[s.prospect_id].delivered ? '#166534' : '#b45309' }}
                        title={emitted[s.prospect_id].configured
                          ? (emitted[s.prospect_id].delivered ? 'Queued and delivered to the outbound webhook' : 'Outcome recorded; webhook delivery failed — re-emit to retry')
                          : 'Outcome recorded; the outbound webhook is not configured yet'}>
                        {emitted[s.prospect_id].delivered ? '✓ emitted' : '✓ outcome saved'}
                      </span>
                    ) : (
                      <button
                        onClick={() => emit.mutate(s.prospect_id)}
                        disabled={emit.isPending}
                        title="Write the outcome (learning substrate); also posts a webhook only if one is configured. You can skip this and just Log calls."
                        style={{ fontSize: 12, border: 'none', background: '#0369a1', color: '#fff',
                          borderRadius: 6, padding: '2px 10px', cursor: 'pointer' }}>
                        Emit
                      </button>
                    )}
                  </div>
                </td>
              </tr>
              {openHook === s.prospect_id && (
                <tr>
                  <td colSpan={colSpan} style={{ padding: '2px 8px 10px' }}>
                    <Justification prospectId={s.prospect_id} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      </div>
    </>
  )
}

function ResultsCard({ marketId }: { marketId: string }) {
  const [submarketId, setSubmarketId] = useState('')
  const { data: subsData } = useQuery<{ submarkets: Submarket[] }>({
    queryKey: ['outreach-submarkets', marketId],
    queryFn: () => api.get(`/outreach/markets/${marketId}/submarkets`),
  })
  const submarkets = subsData?.submarkets ?? []

  return (
    <div style={{ marginTop: 16, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>Coverage results</div>
        <select value={submarketId} onChange={e => setSubmarketId(e.target.value)}
          style={{ padding: '4px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
          <option value="">Choose a submarket…</option>
          {submarkets.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
      <CoverageTable submarketId={submarketId}
        submarketName={submarkets.find(s => s.id === submarketId)?.name} />
    </div>
  )
}
