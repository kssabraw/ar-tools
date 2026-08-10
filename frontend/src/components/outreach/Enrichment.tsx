import { useState } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Globe, Loader2, Mail, Phone, Sparkles, User } from 'lucide-react'
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
}
interface ContactsResp {
  prospect_id: string
  enrichment: { status: string; contact_count: number; error: string | null; enriched_at: string } | null
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
          return { id, status: o.status, error: o.error ?? null, result: (o.progress ?? {}) as Record<string, unknown> }
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
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>
        Contacts
      </div>
      <ContactCell prospectId={prospectId} isAdmin={isAdmin} controller={controller}
        batchRunning={controller.batch.running} />
    </div>
  )
}

export interface ProspectContacts {
  enrichment: ContactsResp['enrichment']
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
  provided,
}: {
  prospectId: string
  isAdmin: boolean
  controller: Controller
  batchRunning: boolean
  provided?: ProspectContacts | null
}) {
  const self = useQuery<ContactsResp>({
    queryKey: ['outreach-contacts', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/contacts`),
    // Only self-query when the parent did NOT provide a batched read.
    enabled: provided === undefined,
    // While a batch is draining, keep checking so freshly-written contacts appear without a manual
    // refresh (the order finishes on a tick, not synchronously).
    refetchInterval: provided === undefined && batchRunning ? 6000 : false,
  })

  const enrichment = provided !== undefined ? provided?.enrichment : self.data?.enrichment
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

  if (!website) return body
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <a href={website} target="_blank" rel="noreferrer"
        style={{ display: 'inline-flex', gap: 3, alignItems: 'center', fontSize: 12, color: '#0369a1' }}
        title={website}>
        <Globe size={11} /> {website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}
      </a>
      {body}
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
