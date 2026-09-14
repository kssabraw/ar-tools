import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, LayoutGrid, RefreshCw, AlertTriangle, Download, Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { useResumableJob } from '../lib/useResumableJob'
import type { Client } from '../lib/types'

// Coverage Audit — Phase 1 (Tier 1: city × main-service). Scans the client's site
// as it stands, derives the service + location axes, diffs the ideal coverage
// universe against what exists, demand-ranks the gaps, and seeds a Service×Location
// Matrix (axes only) from them. Its own page, deep-linking into Local SEO / the
// Matrix for execution. See docs/modules/coverage-audit-module-plan-v1_0.md.

interface Gap {
  service?: string
  location?: string
  keyword: string
  volume: number | null
  cpc_usd: number | null
  competition: string | null
  est_value: number | null
  opportunity_score: number | null
}
interface AuditCounts {
  services_present: number
  services_absent: number
  locations_present: number
  locations_absent: number
  cells_present: number
  cells_absent: number
  cells_total: number
  cells_shown?: number
  cells_below_floor?: number
  cell_floor?: number
}
interface AuditGaps {
  missing_services: Gap[]
  missing_locations: Gap[]
  missing_cells: Gap[]
  counts: AuditCounts
}
interface ServiceAxisEntry {
  label: string
  sources?: string[]
}
interface LocationAxisEntry {
  name: string
  source?: string
}
interface AuditRun {
  id: string
  client_id: string
  status: string
  tier: number
  service_axis: ServiceAxisEntry[] | null
  location_axis: LocationAxisEntry[] | null
  gaps: AuditGaps | null
  provenance:
    | { degraded_notes?: string[]; service_axis?: { confirmed?: boolean }; location_rows_shown?: boolean }
    | null
  error: string | null
  created_at: string
}
interface StatusResponse {
  enabled: boolean
  tier: number
  supported_tiers: number[]
  budget_remaining: number
  audits: { id: string; status: string; tier: number; created_at: string; error: string | null }[]
  latest: AuditRun | null
}

type Tier = 1 | 2 | 3 | 4

const tierLabel: Record<Tier, string> = {
  1: 'main services',
  2: 'subservices',
  3: 'CDPs',
  4: 'CDPs · subservices',
}
const tierTitle: Record<Tier, string> = {
  1: 'City × main service',
  2: 'City × subservice',
  3: 'CDP × main service',
  4: 'CDP × subservice',
}

const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? '—' : n.toLocaleString(undefined, { maximumFractionDigits: digits })
const money = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`

function csvDownload(name: string, header: string[], rows: (string | number | null)[][]) {
  const csv = [header, ...rows]
    .map((r) => r.map((c) => `"${String(c ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export function CoverageAudit() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [tier, setTier] = useState<Tier>(1)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data: status } = useQuery<StatusResponse>({
    queryKey: ['coverage-audit', id, tier],
    queryFn: () => api.get<StatusResponse>(`/clients/${id}/coverage-audit?tier=${tier}`),
    enabled: Boolean(id),
  })

  const [runError, setRunError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [axisDraft, setAxisDraft] = useState('')
  const [seedError, setSeedError] = useState<string | null>(null)

  // The audit runs as a background async_jobs job (one per tier). The in-flight
  // job id is persisted per tier so navigating away — or switching tiers — and back
  // reconnects to the right job.
  const auditJob = useResumableJob<{ audit_id?: string }, undefined>({
    storageKey: `coverage-audit:${id}:${tier}`,
    poll: async (jobId) => {
      const st = await api.get<{ status: string; error?: string; result?: { audit_id?: string } }>(
        `/clients/${id}/coverage-audit/jobs/${jobId}`,
      )
      return { status: st.status, result: st.result ?? null, error: st.error }
    },
    onComplete: () => {
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['coverage-audit', id] })
    },
    onError: (err) => setRunError(err === 'job_failed' ? '' : err),
    intervalMs: 3000,
  })
  const running = auditJob.running

  const runAudit = () => {
    setRunError(null)
    void auditJob.start(async () => {
      const r = await api.post<{ job_id: string }>(`/clients/${id}/coverage-audit`, { tier })
      return r.job_id
    }, undefined)
  }

  const rerunWithAxis = () => {
    if (!latest) return
    const services = axisDraft
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    if (!services.length) {
      setRunError('Add at least one service before re-running.')
      return
    }
    setRunError(null)
    void auditJob.start(async () => {
      const r = await api.put<{ job_id: string }>(
        `/clients/${id}/coverage-audit/${latest.id}/service-axis`,
        { services },
      )
      return r.job_id
    }, undefined)
  }

  const seedMatrix = useMutation({
    mutationFn: () =>
      api.post<{ matrix: { id: string } }>(`/clients/${id}/coverage-audit/${latest!.id}/seed-matrix`, {}),
    onMutate: () => setSeedError(null),
    onSuccess: (r) => {
      const mid = r?.matrix?.id
      navigate(`/clients/${id}/local-seo?tab=matrix${mid ? `&matrix=${mid}` : ''}`)
    },
    onError: (e) => setSeedError(e instanceof Error ? e.message : 'seed_failed'),
  })

  const latest = status?.latest ?? null
  const budget = status?.budget_remaining ?? 0
  const disabled = status?.enabled === false
  const gaps = latest?.status === 'complete' ? latest.gaps : null
  const counts = gaps?.counts
  const notes = latest?.provenance?.degraded_notes ?? []
  const confirmed = latest?.provenance?.service_axis?.confirmed ?? false
  const serviceAxis = latest?.service_axis ?? []
  const locationAxis = latest?.location_axis ?? []
  // Render off the RUN's own tier (a completed run may predate a tier switch).
  const reportTier = latest?.tier ?? tier
  // Subservice tiers: T2 (city × subservice) + T4 (CDP × subservice).
  const isSubservice = reportTier === 2 || reportTier === 4
  // CDP location tiers: T3 (CDP × main service) + T4 (CDP × subservice) — the
  // location axis is CDPs (Census Designated Places), not cities.
  const isCdp = reportTier === 3 || reportTier === 4
  const locationNoun = isCdp ? 'CDP' : 'City'
  const locationNounPlural = isCdp ? 'CDPs' : 'Cities'
  // Subservice tiers (2/4) drop the location-hub rows; main-service tiers (1/3) keep
  // them. The server records the decision on the run; default off the subservice
  // tiers when an older run lacks the flag.
  const showLocations =
    latest?.provenance?.location_rows_shown ?? (reportTier !== 2 && reportTier !== 4)
  const serviceAxisLabel = isSubservice ? 'Subservice axis' : 'Service axis'

  const startEditing = () => {
    setAxisDraft(serviceAxis.map((s) => s.label).join('\n'))
    setEditing(true)
  }

  const localSeoNew = useMemo(() => `/clients/${id}/local-seo?tab=new`, [id])

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 4px' }}>
        <LayoutGrid size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Coverage Audit</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 13, margin: '0 0 16px' }}>
        Scans the whole site as it stands and finds the location & service pages that don't exist yet,
        ranked by real search demand. <strong>Tier 1</strong> covers city × main service;{' '}
        <strong>Tier 2</strong> drills into city × subservice (each main service expanded into its
        variations); <strong>Tier 3</strong> widens to CDP × main service (the authoritative Census
        Designated Places across the service area); <strong>Tier 4</strong> crosses both — CDP ×
        subservice, the widest net.
      </p>

      {disabled && (
        <div style={errBox}>Coverage Audit is disabled for this environment.</div>
      )}

      {/* Tier selector — switches the run + report between city×main-service (T1),
          city×subservice (T2), CDP×main-service (T3), and CDP×subservice (T4). Each
          tier keeps its own latest run + in-flight job. */}
      <div style={{ display: 'inline-flex', gap: 2, marginBottom: 16, background: '#f1f5f9', borderRadius: 8, padding: 3 }}>
        {([1, 2, 3, 4] as Tier[]).map((t) => (
          <button
            key={t}
            style={t === tier ? tierBtnActive : tierBtn}
            onClick={() => {
              if (t === tier) return
              setEditing(false)
              setRunError(null)
              setSeedError(null)
              setTier(t)
            }}
            disabled={running}
            title={tierTitle[t]}
          >
            Tier {t} · {tierLabel[t]}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <button style={running || disabled ? { ...primaryBtn, opacity: 0.6, cursor: 'default' } : primaryBtn}
          onClick={runAudit} disabled={running || disabled}>
          <RefreshCw size={15} className={running ? 'spin' : undefined} />
          {running ? `Running… ${auditJob.elapsed}s` : latest ? `Re-run Tier ${tier}` : `Run Tier ${tier} audit`}
        </button>
        <span style={{ color: '#94a3b8', fontSize: 12 }}>
          {budget > 100000 ? 'Demand budget: unlimited' : `Demand budget left today: ${num(budget)}`}
        </span>
        {latest && (
          <span style={{ color: '#94a3b8', fontSize: 12 }}>
            Last run: {new Date(latest.created_at).toLocaleString()} · {latest.status}
          </span>
        )}
      </div>

      {runError !== null && (
        <div style={errBox}>
          {runError || 'The audit failed to run. Try again, or check the client has a website + business location set.'}
        </div>
      )}

      {!latest && !running && (
        <div style={emptyBox}>
          No audit yet. Click <strong>Run audit</strong> to scan {client?.name ?? 'this client'}'s site and
          find its coverage gaps.
        </div>
      )}

      {latest?.status === 'failed' && (
        <div style={errBox}>The last audit failed{latest.error ? `: ${latest.error}` : '.'} — try running it again.</div>
      )}

      {/* Degraded-source notes — visible, never silent (plan §5). */}
      {notes.length > 0 && (
        <div style={warnBox}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: 6 }}>
            <AlertTriangle size={15} /> Heads up
          </div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {notes.map((n, i) => (
              <li key={i} style={{ marginBottom: 2 }}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      {gaps && (
        <>
          {/* Coverage summary */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            <Stat label={isSubservice ? 'Subservices' : 'Services'} present={counts?.services_present} absent={counts?.services_absent} />
            {showLocations && (
              <Stat label={locationNounPlural} present={counts?.locations_present} absent={counts?.locations_absent} />
            )}
            <Stat
              label={`${isSubservice ? 'Subservice' : 'Service'} × ${locationNoun} cells`}
              present={counts?.cells_present}
              absent={counts?.cells_absent}
            />
          </div>

          {/* Service axis — auto-derived, confirm to refine (plan §8 item / §7). */}
          <section style={panel}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <h2 style={panelTitle}>{serviceAxisLabel}</h2>
              {!editing && (
                <button style={ghostBtn} onClick={startEditing} disabled={running}>
                  <Pencil size={13} /> Edit & re-run
                </button>
              )}
            </div>
            {!confirmed && !editing && (
              <div style={{ ...noteLine, marginBottom: 10 }}>
                {isSubservice
                  ? 'These subservices were expanded from the main services by the planner. Edit and re-run to refine the audit.'
                  : 'These services were auto-derived from the site + GBP categories. Edit and re-run to refine the audit.'}
              </div>
            )}
            {editing ? (
              <div>
                <div style={{ ...noteLine, marginBottom: 8 }}>
                  One {isSubservice ? 'subservice' : 'service'} per line. Re-running audits the edited axis.
                </div>
                <textarea value={axisDraft} onChange={(e) => setAxisDraft(e.target.value)}
                  rows={Math.max(4, serviceAxis.length + 1)} style={textareaStyle} />
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button style={running ? { ...primaryBtn, opacity: 0.6 } : primaryBtn} onClick={rerunWithAxis} disabled={running}>
                    <RefreshCw size={14} /> Re-run with these services
                  </button>
                  <button style={ghostBtn} onClick={() => setEditing(false)} disabled={running}>Cancel</button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {serviceAxis.map((s) => (
                  <span key={s.label} style={axisChip} title={(s.sources ?? []).join(', ')}>{s.label}</span>
                ))}
                {serviceAxis.length === 0 && (
                  <span style={{ color: '#94a3b8', fontSize: 13 }}>
                    No {isSubservice ? 'subservices' : 'services'} derived.
                  </span>
                )}
              </div>
            )}
          </section>

          {/* Location axis */}
          <section style={panel}>
            <h2 style={panelTitle}>Location axis ({locationAxis.length})</h2>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {locationAxis.map((l) => (
                <span key={l.name} style={axisChip} title={l.source}>{l.name}</span>
              ))}
              {locationAxis.length === 0 && (
                <span style={{ color: '#94a3b8', fontSize: 13 }}>
                  {isCdp
                    ? "No CDPs — set the client's business location + geocoding (GOOGLE_MAPS_API_KEY)."
                    : "No cities — set the client's business location + geocoding."}
                </span>
              )}
            </div>
          </section>

          {/* Seed matrix — AXES ONLY (the Matrix marks its own cell coverage). */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '4px 0 20px' }}>
            <button
              style={seedMatrix.isPending || !serviceAxis.length || !locationAxis.length
                ? { ...primaryBtn, opacity: 0.6, cursor: 'default' } : primaryBtn}
              onClick={() => seedMatrix.mutate()}
              disabled={seedMatrix.isPending || !serviceAxis.length || !locationAxis.length}>
              <LayoutGrid size={15} /> {seedMatrix.isPending ? 'Seeding…' : 'Seed Service × Location Matrix'}
            </button>
            <span style={{ color: '#94a3b8', fontSize: 12 }}>
              Creates a matrix from the full axes; it marks each cell's coverage itself.
            </span>
          </div>
          {seedError && <div style={errBox}>{seedError}</div>}

          {/* Gap tables */}
          <GapTable
            title={isSubservice ? 'Missing subservices' : 'Missing services'}
            subtitle={
              isSubservice
                ? "City-less subservice pages the site doesn't have yet."
                : "City-less service pages the site doesn't have yet."
            }
            rows={gaps.missing_services}
            kind="service"
            newHref={localSeoNew}
          />
          {/* Tier 2 drops the location-hub rows — a city-hub gap is a Tier-1 concern
              (measured against the main-service axis), not a subservice one. Tiers 1
              and 3 keep them (a CDP hub IS a main-service concept). */}
          {showLocations && (
            <GapTable
              title={`Missing ${locationNounPlural.toLowerCase()}`}
              subtitle={`${locationNounPlural} with no dedicated page (ranked by the primary service's demand there).`}
              rows={gaps.missing_locations}
              kind="location"
              locationLabel={locationNoun}
              newHref={localSeoNew}
            />
          )}
          <GapTable
            title={`Missing ${isSubservice ? 'subservice' : 'service'} × ${locationNoun.toLowerCase()} pages`}
            subtitle={
              counts?.cell_floor
                ? `Demand-ranked; ${num(counts.cells_below_floor)} sub-floor combos (< ${num(counts.cell_floor)} searches/mo) hidden.`
                : `${isSubservice ? 'Subservice' : 'Service'} × ${locationNoun.toLowerCase()} combinations the site is missing.`
            }
            rows={gaps.missing_cells}
            kind="cell"
            locationLabel={locationNoun}
            newHref={localSeoNew}
          />
        </>
      )}

      <style>{`.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}

function Stat({ label, present, absent }: { label: string; present?: number; absent?: number }) {
  const total = (present ?? 0) + (absent ?? 0)
  return (
    <div style={statBox}>
      <div style={{ fontSize: 12, color: '#64748b' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>
        {num(present)}<span style={{ fontSize: 13, color: '#94a3b8', fontWeight: 500 }}> / {num(total)} covered</span>
      </div>
      <div style={{ fontSize: 12, color: absent ? '#b45309' : '#16a34a' }}>{num(absent)} missing</div>
    </div>
  )
}

function GapTable({
  title, subtitle, rows, kind, newHref, locationLabel = 'City',
}: {
  title: string
  subtitle: string
  rows: Gap[]
  kind: 'service' | 'location' | 'cell'
  newHref: string
  locationLabel?: string
}) {
  const exportCsv = () => {
    const header = kind === 'cell'
      ? ['service', 'location', 'keyword', 'volume', 'cpc_usd', 'competition', 'est_value', 'opportunity_score']
      : [kind, 'keyword', 'volume', 'cpc_usd', 'competition', 'est_value', 'opportunity_score']
    const body = rows.map((g) =>
      kind === 'cell'
        ? [g.service ?? '', g.location ?? '', g.keyword, g.volume, g.cpc_usd, g.competition, g.est_value, g.opportunity_score]
        : [(kind === 'service' ? g.service : g.location) ?? '', g.keyword, g.volume, g.cpc_usd, g.competition, g.est_value, g.opportunity_score],
    )
    csvDownload(`coverage-${kind}-gaps.csv`, header, body)
  }
  return (
    <section style={panel}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <h2 style={panelTitle}>{title} <span style={{ color: '#94a3b8', fontWeight: 500 }}>({rows.length})</span></h2>
        {rows.length > 0 && (
          <button style={ghostBtn} onClick={exportCsv}><Download size={13} /> CSV</button>
        )}
      </div>
      <div style={{ ...noteLine, marginBottom: 10 }}>{subtitle}</div>
      {rows.length === 0 ? (
        <div style={{ color: '#16a34a', fontSize: 13 }}>No gaps — full coverage here. ✓</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                {kind === 'cell' && <th style={th}>Service</th>}
                {kind === 'cell' && <th style={th}>{locationLabel}</th>}
                <th style={th}>Keyword</th>
                <th style={{ ...th, textAlign: 'right' }}>Volume</th>
                <th style={{ ...th, textAlign: 'right' }}>CPC</th>
                <th style={{ ...th, textAlign: 'right' }}>Est. value/mo</th>
                <th style={{ ...th, textAlign: 'right' }}>Opportunity</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((g, i) => (
                <tr key={`${g.keyword}-${i}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                  {kind === 'cell' && <td style={td}>{g.service}</td>}
                  {kind === 'cell' && <td style={td}>{g.location}</td>}
                  <td style={{ ...td, fontWeight: 500 }}>{g.keyword}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{num(g.volume)}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{g.cpc_usd == null ? '—' : `$${num(g.cpc_usd, 2)}`}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{money(g.est_value)}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{num(g.opportunity_score, 1)}</td>
                  <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <Link to={newHref} style={createLink}>Create page <ArrowRight size={12} /></Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const backLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#64748b', fontSize: 13, textDecoration: 'none', marginBottom: 16 }
const primaryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 16px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: '#fff', color: '#475569', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: 'pointer' }
const tierBtn: React.CSSProperties = { padding: '6px 14px', background: 'transparent', color: '#475569', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const tierBtnActive: React.CSSProperties = { ...tierBtn, background: '#fff', color: '#4338ca', boxShadow: '0 1px 2px rgba(15,23,42,0.12)' }
const th: React.CSSProperties = { textAlign: 'left', padding: '9px 12px', background: '#f8fafc', color: '#475569', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap' }
const td: React.CSSProperties = { padding: '8px 12px', color: '#334155' }
const emptyBox: React.CSSProperties = { padding: 40, textAlign: 'center', color: '#94a3b8', border: '1px dashed #e2e8f0', borderRadius: 8 }
const errBox: React.CSSProperties = { padding: '10px 14px', background: '#fef2f2', color: '#b91c1c', borderRadius: 8, fontSize: 13, marginBottom: 16 }
const warnBox: React.CSSProperties = { padding: '10px 14px', background: '#fffbeb', color: '#92400e', border: '1px solid #fde68a', borderRadius: 8, fontSize: 13, marginBottom: 16 }
const panel: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, marginBottom: 16, background: '#fff' }
const panelTitle: React.CSSProperties = { fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }
const noteLine: React.CSSProperties = { fontSize: 12, color: '#94a3b8' }
const statBox: React.CSSProperties = { flex: '1 1 200px', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 16px', background: '#fff' }
const axisChip: React.CSSProperties = { padding: '4px 10px', background: '#eef2ff', color: '#4338ca', borderRadius: 999, fontSize: 12, fontWeight: 500 }
const createLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 3, color: '#6366f1', fontSize: 12, fontWeight: 600, textDecoration: 'none' }
const textareaStyle: React.CSSProperties = { width: '100%', padding: '9px 12px', border: '1px solid #cbd5e1', borderRadius: 8, fontSize: 13, color: '#0f172a', outline: 'none', fontFamily: 'inherit', resize: 'vertical' }
