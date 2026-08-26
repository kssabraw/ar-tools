import { useState } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, Loader2, Mail, Phone, Search, Sparkles, User } from 'lucide-react'
import { api } from '../../lib/api'
import { useResumableBatch } from '../../lib/useResumableBatch'

// Lead enrichment — contact names / phones / emails via Outscraper. Placing an order BILLS on the
// outreach job's next tick (order-driven, admin-only, budget-guarded), so this UI mirrors the scan
// trigger: a free cost estimate before confirming, then a resumable progress read. `useResumableBatch`
// makes the progress survive navigation — the same "leave & finish in the background" affordance the
// bulk content tools use. Contacts appear once a tick has drained the order (latency ≈ one cron
// interval), exactly like a scan's coverage.

interface Contact {
  id: string
  full_name: string | null
  title: string | null
  name_for_emails: string | null
  email: string | null
  email_status: string | null
  email_is_generic: boolean
  phone: string | null
  phone_type: string | null
  source?: string | null
}
// The FREE site name-scrape's per-prospect status (owner/manager fallback). Distinct from
// `enrichment` (the paid Outscraper pull) — a prospect can carry both.
export interface NameScrapeStatus {
  status: 'found' | 'no_names' | 'unreachable' | 'failed'
  name_count: number
  fetch_status: string | null
  error: string | null
  scraped_at: string
}
interface ContactsResp {
  prospect_id: string
  enrichment: { status: string; contact_count: number; error: string | null; enriched_at: string } | null
  name_scrape?: NameScrapeStatus | null
  website?: string | null
  contacts: Contact[]
}
interface EnrichOrder {
  id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  error?: string | null
  progress?: { requested: number; done: number; enriched: number; skipped: number; failed: number; contacts: number }
}
export interface EnrichEstimate {
  selected: number
  already_enriched: number
  unknown: number
  billable: number
  est_cost_cents: number
  est_cost_usd: number
  spent_today_cents: number
  daily_budget_usd: number
  allowed: boolean
  denial: string | null
}

// ── The shared controller: one resumable batch of enrichment orders per coverage table ──────────
export function useEnrichment(scopeKey: string) {
  const qc = useQueryClient()
  const batch = useResumableBatch<{ n: number }>({
    storageKey: `outreach-enrich-${scopeKey}`,
    poll: (ids) =>
      Promise.all(
        ids.map(async (id) => {
          const r = await api.get<{ enrichment_request: EnrichOrder }>(`/outreach/enrichment/${id}`)
          const o = r.enrichment_request
          // useResumableBatch's terminal vocabulary is the async_jobs one
          // (complete|failed|cancelled), but an enrichment order reports SUCCESS as `done`.
          // Normalize it here or the batch never sees a terminal state — leaving the UI stuck
          // "Enriching…" forever (localStorage-persisted, so a reload doesn't clear it) and
          // blocking the next order. Only `done` needs mapping; failed/cancelled already match.
          const status = o.status === 'done' ? 'complete' : o.status
          return { id, status, error: o.error ?? null, result: (o.progress ?? {}) as Record<string, unknown> }
        }),
      ),
    onDone: () => {
      // The drained orders wrote contacts + statuses — refresh the per-row contact cells (both the
      // batched table read and the single-prospect drawer read) and the coverage list (an enriched
      // prospect's phone may now be known).
      qc.invalidateQueries({ queryKey: ['outreach-contacts'] })
      qc.invalidateQueries({ queryKey: ['outreach-contacts-batch'] })
      qc.invalidateQueries({ queryKey: ['outreach-placeholder-scores'] })
    },
  })

  const create = useMutation({
    mutationFn: (prospectIds: string[]) =>
      prospectIds.length === 1
        ? api.post<{ enrichment_request: EnrichOrder }>(`/outreach/prospects/${prospectIds[0]}/enrich`, {})
        : api.post<{ enrichment_request: EnrichOrder }>(`/outreach/enrichment`, { prospect_ids: prospectIds }),
    onSuccess: (data) => {
      // Append the new order to the in-flight batch so several enrichments (per-row + bulk) track
      // together; useResumableBatch persists the id list, so this survives a reload.
      const existing = batch.batch?.jobIds ?? []
      const ids = [...new Set([...existing, data.enrichment_request.id])]
      batch.start(ids, { n: ids.length })
    },
  })

  return { batch, create }
}

type Controller = ReturnType<typeof useEnrichment>

// ── The site name-scrape controller (FREE owner/manager fallback) ────────────────────────────────
// Mirrors useEnrichment but for the free `name_scrape_request` order: no cost estimate, staff (not
// admin) gated. Placed when Outscraper enrichment couldn't find a name; the outreach tick scrapes
// the prospect's own site and writes any owner/manager it finds as a `site_scrape` contact.
interface NameScrapeOrder {
  id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  error?: string | null
  progress?: { requested: number; done: number; scraped: number; found: number; names: number; skipped: number; failed: number }
}
export function useNameScrape(scopeKey: string) {
  const qc = useQueryClient()
  const batch = useResumableBatch<{ n: number }>({
    storageKey: `outreach-namescrape-${scopeKey}`,
    poll: (ids) =>
      Promise.all(
        ids.map(async (id) => {
          const r = await api.get<{ name_scrape_request: NameScrapeOrder }>(`/outreach/name-scrape/${id}`)
          const o = r.name_scrape_request
          // Normalize the order's `done` to useResumableBatch's terminal `complete` (same reason as
          // useEnrichment) so the UI leaves the "Scanning…" state.
          const status = o.status === 'done' ? 'complete' : o.status
          return { id, status, error: o.error ?? null, result: (o.progress ?? {}) as Record<string, unknown> }
        }),
      ),
    onDone: () => {
      qc.invalidateQueries({ queryKey: ['outreach-contacts'] })
      qc.invalidateQueries({ queryKey: ['outreach-contacts-batch'] })
    },
  })

  const create = useMutation({
    mutationFn: (prospectIds: string[]) =>
      prospectIds.length === 1
        ? api.post<{ name_scrape_request: NameScrapeOrder }>(`/outreach/prospects/${prospectIds[0]}/scrape-names`, {})
        : api.post<{ name_scrape_request: NameScrapeOrder }>(`/outreach/name-scrape`, { prospect_ids: prospectIds }),
    onSuccess: (data) => {
      const existing = batch.batch?.jobIds ?? []
      const ids = [...new Set([...existing, data.name_scrape_request.id])]
      batch.start(ids, { n: ids.length })
    },
  })

  return { batch, create }
}

type NameController = ReturnType<typeof useNameScrape>

// ── The bulk name-scrape bar (select-all → Scan sites). FREE, so no estimate step ───────────────
export function NameScrapeBar({
  selectedIds,
  controller,
  onCleared,
}: {
  selectedIds: string[]
  controller: NameController
  onCleared: () => void
}) {
  const running = controller.batch.running
  const progress = controller.batch.rows.reduce(
    (acc, r) => {
      const p = (r.result ?? {}) as Record<string, number>
      acc.found += p.found ?? 0
      acc.names += p.names ?? 0
      acc.failed += p.failed ?? 0
      return acc
    },
    { found: 0, names: 0, failed: 0 },
  )

  if (running) {
    return (
      <div style={{ ...barStyle, borderColor: '#bfdbfe', background: '#eff6ff' }}>
        <Loader2 size={14} className="animate-spin" />
        <span style={{ fontSize: 13 }}>
          Scanning sites for names… {controller.batch.finished}/{controller.batch.total} · {progress.found} found,
          {' '}{progress.names} names{progress.failed ? ` · ${progress.failed} failed` : ''}
        </span>
        <button onClick={() => controller.batch.detach()} style={ghostBtn}>
          Leave & finish in the background
        </button>
      </div>
    )
  }

  if (selectedIds.length === 0) return null
  return (
    <div style={{ ...barStyle, borderColor: '#bfdbfe', background: '#eff6ff' }}>
      <Search size={14} color="#2563eb" />
      <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.length} selected</span>
      <button
        onClick={() => {
          controller.create.mutate(selectedIds)
          onCleared()
        }}
        disabled={controller.create.isPending}
        title="Scan each selected business's own website for an owner/manager name — free, finishes on the next run"
        style={{ ...primaryBtn, background: '#2563eb' }}
      >
        Scan sites for names (free)
      </button>
      {controller.create.isError && (
        <span style={{ fontSize: 12, color: '#b91c1c' }}>
          {(controller.create.error as { message?: string })?.message ?? 'Could not place the order'}
        </span>
      )}
    </div>
  )
}

// ── The bulk bar (select-all → estimate → Enrich) ───────────────────────────────────────────────
export function EnrichmentBar({
  selectedIds,
  controller,
  onCleared,
}: {
  selectedIds: string[]
  controller: Controller
  onCleared: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const estimate = useQuery<EnrichEstimate>({
    queryKey: ['outreach-enrich-estimate', [...selectedIds].sort()],
    queryFn: () => api.post<EnrichEstimate>('/outreach/enrichment/estimate', { prospect_ids: selectedIds }),
    enabled: confirming && selectedIds.length > 0,
  })

  const rows = controller.batch.rows
  const running = controller.batch.running
  const progress = rows.reduce(
    (acc, r) => {
      const p = (r.result ?? {}) as Record<string, number>
      acc.enriched += p.enriched ?? 0
      acc.contacts += p.contacts ?? 0
      acc.skipped += p.skipped ?? 0
      acc.failed += p.failed ?? 0
      return acc
    },
    { enriched: 0, contacts: 0, skipped: 0, failed: 0 },
  )

  if (running) {
    return (
      <div style={barStyle}>
        <Loader2 size={14} className="animate-spin" />
        <span style={{ fontSize: 13 }}>
          Enriching… {controller.batch.finished}/{controller.batch.total} orders · {progress.enriched} enriched,
          {' '}{progress.contacts} contacts{progress.skipped ? ` · ${progress.skipped} already done` : ''}
          {progress.failed ? ` · ${progress.failed} failed` : ''}
        </span>
        <button onClick={() => controller.batch.detach()} style={ghostBtn}>
          Leave & finish in the background
        </button>
      </div>
    )
  }

  if (selectedIds.length === 0) return null

  if (!confirming) {
    return (
      <div style={barStyle}>
        <Sparkles size={14} color="#7c3aed" />
        <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.length} selected</span>
        <button onClick={() => setConfirming(true)} style={primaryBtn}>
          Enrich contacts…
        </button>
        <button onClick={onCleared} style={ghostBtn}>Clear</button>
      </div>
    )
  }

  const est = estimate.data
  return (
    <div style={{ ...barStyle, flexWrap: 'wrap' }}>
      <Sparkles size={14} color="#7c3aed" />
      {estimate.isError ? (
        <>
          <span style={{ fontSize: 12, color: '#b91c1c' }}>
            {(estimate.error as { message?: string })?.message ?? 'Could not estimate — try again'}
          </span>
          <button onClick={() => estimate.refetch()} style={ghostBtn}>Retry</button>
          <button onClick={() => setConfirming(false)} style={ghostBtn}>Cancel</button>
        </>
      ) : estimate.isLoading || !est ? (
        <span style={{ fontSize: 13 }}>Estimating…</span>
      ) : (
        <>
          <span style={{ fontSize: 13 }}>
            {est.billable} to enrich (~${est.est_cost_usd.toFixed(2)})
            {est.already_enriched ? ` · ${est.already_enriched} already enriched` : ''}
            {' · '}${(est.spent_today_cents / 100).toFixed(2)}/${est.daily_budget_usd.toFixed(2)} spent today
          </span>
          {!est.allowed ? (
            <span style={{ fontSize: 12, color: '#b91c1c' }}>{est.denial}</span>
          ) : est.billable === 0 ? (
            <span style={{ fontSize: 12, color: '#b45309' }}>Nothing to enrich in this selection.</span>
          ) : (
            <button
              onClick={() => {
                controller.create.mutate(selectedIds)
                setConfirming(false)
                onCleared()
              }}
              disabled={controller.create.isPending}
              style={primaryBtn}
            >
              Enrich {est.billable} (~${est.est_cost_usd.toFixed(2)})
            </button>
          )}
          <button onClick={() => setConfirming(false)} style={ghostBtn}>Cancel</button>
        </>
      )}
      {controller.create.isError && (
        <span style={{ fontSize: 12, color: '#b91c1c' }}>
          {(controller.create.error as { message?: string })?.message ?? 'Could not place the order'}
        </span>
      )}
    </div>
  )
}

// ── A single prospect's contacts block (the CRM lead drawer) ────────────────────────────────────
export function LeadContacts({ prospectId, isAdmin }: { prospectId: string; isAdmin: boolean }) {
  const controller = useEnrichment(`lead-${prospectId}`)
  const nameController = useNameScrape(`lead-${prospectId}`)
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>
        Contacts
      </div>
      <ContactCell prospectId={prospectId} isAdmin={isAdmin} controller={controller}
        batchRunning={controller.batch.running}
        nameController={nameController} nameBatchRunning={nameController.batch.running} />
    </div>
  )
}

export interface ProspectContacts {
  enrichment: ContactsResp['enrichment']
  name_scrape?: NameScrapeStatus | null
  website?: string | null
  contacts: Contact[]
}

// ── Per-row contacts + single "Enrich" button ───────────────────────────────────────────────────
// `provided` is the batched read (the coverage table fetches all rows' contacts in ONE call and
// passes each row's slice, or `null` when a prospect has no enrichment yet — avoiding an N+1 of one
// request per row). When `provided` is undefined (the CRM drawer's single prospect) the cell
// self-queries instead.
export function ContactCell({
  prospectId,
  isAdmin,
  controller,
  batchRunning,
  nameController,
  nameBatchRunning,
  provided,
}: {
  prospectId: string
  isAdmin: boolean
  controller: Controller
  batchRunning: boolean
  nameController?: NameController
  nameBatchRunning?: boolean
  provided?: ProspectContacts | null
}) {
  const self = useQuery<ContactsResp>({
    queryKey: ['outreach-contacts', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/contacts`),
    // Only self-query when the parent did NOT provide a batched read.
    enabled: provided === undefined,
    // While a batch is draining, keep checking so freshly-written contacts appear without a manual
    // refresh (the order finishes on a tick, not synchronously).
    refetchInterval: provided === undefined && (batchRunning || !!nameBatchRunning) ? 6000 : false,
  })

  const enrichment = provided !== undefined ? provided?.enrichment : self.data?.enrichment
  const nameScrape = (provided !== undefined ? provided?.name_scrape : self.data?.name_scrape) ?? null
  const contacts = (provided !== undefined ? provided?.contacts : self.data?.contacts) ?? []
  const website = (provided !== undefined ? provided?.website : self.data?.website) ?? null

  // The state-specific part (contacts / status / Enrich button) rendered UNDER the website line,
  // so the website shows in every state (enriched, not-yet, no-contacts, failed).
  let body: ReactElement
  if (contacts.length > 0) {
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {contacts.map((c) => (
          <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, flexWrap: 'wrap' }}>
            {(c.full_name || c.name_for_emails) && (
              <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
                <User size={11} color="#64748b" />
                {c.full_name || c.name_for_emails}
                {c.title ? <span style={{ color: '#94a3b8' }}>· {c.title}</span> : null}
                {c.source === 'site_scrape' ? (
                  <span
                    title="Found by scanning the business's own website — verify before using"
                    style={{ fontSize: 10, color: '#2563eb', background: '#eff6ff', border: '1px solid #bfdbfe',
                      borderRadius: 4, padding: '0 4px', display: 'inline-flex', gap: 2, alignItems: 'center' }}
                  >
                    <Globe size={9} /> from website
                  </span>
                ) : null}
              </span>
            )}
            {c.email && (
              <a href={`mailto:${c.email}`} style={{ display: 'inline-flex', gap: 3, alignItems: 'center', color: '#0369a1' }}
                title={`${c.email_status ?? 'unverified'}${c.email_is_generic ? ' · generic mailbox' : ''}`}>
                <Mail size={11} /> {c.email}
                {c.email_is_generic ? <span style={{ color: '#94a3b8' }}>(generic)</span> : null}
              </a>
            )}
            {c.phone && (
              <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
                <Phone size={11} color="#64748b" /> {c.phone}
                {c.phone_type ? <span style={{ color: '#94a3b8' }}>· {c.phone_type}</span> : null}
              </span>
            )}
          </div>
        ))}
      </div>
    )
  } else if (enrichment?.status === 'no_contacts') {
    body = <span style={{ fontSize: 12, color: '#94a3b8' }}>no contacts found</span>
  } else if (enrichment?.status === 'failed') {
    body = <span style={{ fontSize: 12, color: '#b45309' }}>enrichment failed</span>
  } else if (batchRunning) {
    body = <span style={{ fontSize: 12, color: '#1d4ed8' }}>queued…</span>
  } else if (isAdmin) {
    body = (
      <button
        onClick={() => controller.create.mutate([prospectId])}
        disabled={controller.create.isPending}
        title="Enrich this lead with contact names, phones and emails (bills on the next run)"
        style={{
          fontSize: 12, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6,
          padding: '2px 8px', cursor: 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center',
          color: '#7c3aed',
        }}
      >
        <Sparkles size={12} /> Enrich
      </button>
    )
  } else {
    body = <span style={{ fontSize: 12, color: '#cbd5e1' }}>—</span>
  }

  // ── The FREE owner/manager fallback: scan the business's own site for a name when Outscraper
  // couldn't. Offered whenever the prospect has a website and no NAME is known yet (a contact may
  // carry an email/phone but no person), and the site-scrape has no durable answer. Free + staff, so
  // it is NOT gated on isAdmin.
  const hasName = contacts.some(c => c.full_name || c.name_for_emails)
  const scanNamesBtn = (label: string) => (
    <button
      onClick={() => nameController!.create.mutate([prospectId])}
      disabled={nameController!.create.isPending}
      title="Scan this business's own website for an owner/manager name — free, finishes on the next run"
      style={{
        fontSize: 12, border: '1px solid #bfdbfe', background: '#fff', borderRadius: 6,
        padding: '2px 8px', cursor: 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center',
        color: '#2563eb',
      }}
    >
      <Search size={12} /> {label}
    </button>
  )
  let nameFallback: ReactElement | null = null
  if (nameController && website && !hasName) {
    if (nameBatchRunning) {
      nameFallback = <span style={{ fontSize: 11, color: '#1d4ed8' }}>scanning site…</span>
    } else if (nameScrape?.status === 'no_names') {
      nameFallback = <span style={{ fontSize: 11, color: '#94a3b8' }}>no owner named on site</span>
    } else if (nameScrape?.status === 'unreachable') {
      nameFallback = (
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: '#b45309' }}>couldn’t read the site</span>
          {scanNamesBtn('Retry')}
        </span>
      )
    } else if (nameScrape?.status === 'failed') {
      nameFallback = (
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: '#b45309' }}>site scan failed</span>
          {scanNamesBtn('Retry')}
        </span>
      )
    } else {
      nameFallback = scanNamesBtn('Scan site for names')
    }
  }

  const bodyWithFallback = nameFallback ? (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
      {body}
      {nameFallback}
    </div>
  ) : body

  if (!website) return bodyWithFallback
  return (
    // alignItems:flex-start so the website link and the Enrich button size to their content
    // instead of stretching to the (variable) column width.
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
      {/* Cap the width and let long URLs (utm query strings can be very long) wrap onto multiple
          lines — otherwise the single long line stretches the whole Contacts column. */}
      <a href={website} target="_blank" rel="noreferrer"
        style={{ display: 'inline-flex', gap: 3, alignItems: 'flex-start', fontSize: 12, color: '#0369a1',
          maxWidth: 240 }}
        title={website}>
        <Globe size={11} style={{ flexShrink: 0, marginTop: 2 }} />
        <span style={{ minWidth: 0, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
          {website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
        </span>
      </a>
      {bodyWithFallback}
    </div>
  )
}

const barStyle: CSSProperties = {
  display: 'flex', gap: 10, alignItems: 'center', padding: '8px 12px', marginTop: 8,
  border: '1px solid #e9d5ff', background: '#faf5ff', borderRadius: 8,
}
const primaryBtn: CSSProperties = {
  fontSize: 12, border: 'none', background: '#7c3aed', color: '#fff', borderRadius: 6,
  padding: '4px 12px', cursor: 'pointer', fontWeight: 600,
}
const ghostBtn: CSSProperties = {
  fontSize: 12, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6,
  padding: '4px 10px', cursor: 'pointer', color: '#475569',
}
