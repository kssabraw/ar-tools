import { useState } from 'react'
import type { CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CreditCard, Loader2 } from 'lucide-react'
import { api } from '../../lib/api'
import { useResumableBatch } from '../../lib/useResumableBatch'

// Enigma card revenue — per-prospect card_revenue_amount over Enigma's 1m/3m/12m windows. Placing an
// order BILLS on the outreach job's next tick (one Enigma `search` per prospect — order-driven,
// admin-only, budget-guarded), so this UI mirrors the enrichment trigger exactly: a free cost estimate
// before confirming, then a resumable progress read (`useResumableBatch` survives navigation). Card
// figures appear once a tick has drained the order (latency ≈ one cron interval), like a scan's
// coverage. This is the PROVEN half of the Enigma rung (the owner/contacts half is deferred).

// The prospect_enigma read shape (the structured card fields + match audit; the raw entity is never
// sent). One per prospect; null when it has not been looked up.
export interface ProspectEnigma {
  prospect_id: string
  status: 'matched' | 'no_card' | 'no_match' | 'failed'
  matched: boolean
  matched_name: string | null
  card_revenue_1m: number | null
  card_revenue_3m: number | null
  card_revenue_12m: number | null
  card_as_of: string | null
  entity_type: string | null
  error: string | null
  fetched_at: string
}

export interface EnigmaEstimate {
  selected: number
  already_fetched: number
  unknown: number
  no_name: number
  billable: number
  est_cost_cents: number
  est_cost_usd: number
  spent_today_cents: number
  daily_budget_usd: number
  allowed: boolean
  denial: string | null
}

interface EnigmaOrder {
  id: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  error?: string | null
  progress?: { requested: number; done: number; matched: number; card: number; no_match: number; skipped: number; failed: number }
}

// ── The shared controller: one resumable batch of Enigma orders per coverage table ──────────────
export function useEnigma(scopeKey: string) {
  const qc = useQueryClient()
  const batch = useResumableBatch<{ n: number }>({
    storageKey: `outreach-enigma-${scopeKey}`,
    poll: (ids) =>
      Promise.all(
        ids.map(async (id) => {
          const r = await api.get<{ enigma_request: EnigmaOrder }>(`/outreach/enigma/${id}`)
          const o = r.enigma_request
          // useResumableBatch's terminal vocabulary is the async_jobs one (complete|failed|cancelled),
          // but an enigma order reports SUCCESS as `done` — normalize it or the batch never sees a
          // terminal state and the UI stays stuck "Looking up…" (same fix as useEnrichment).
          const status = o.status === 'done' ? 'complete' : o.status
          return { id, status, error: o.error ?? null, result: (o.progress ?? {}) as Record<string, unknown> }
        }),
      ),
    onDone: () => {
      // The drained orders wrote prospect_enigma rows — refresh the per-row card cells (batched +
      // single) and the coverage list.
      qc.invalidateQueries({ queryKey: ['outreach-enigma'] })
      qc.invalidateQueries({ queryKey: ['outreach-enigma-batch'] })
    },
  })

  const create = useMutation({
    mutationFn: (prospectIds: string[]) =>
      prospectIds.length === 1
        ? api.post<{ enigma_request: EnigmaOrder }>(`/outreach/prospects/${prospectIds[0]}/enigma`, {})
        : api.post<{ enigma_request: EnigmaOrder }>(`/outreach/enigma`, { prospect_ids: prospectIds }),
    onSuccess: (data) => {
      // Append the new order to the in-flight batch so several lookups (per-row + bulk) track together;
      // useResumableBatch persists the id list, so this survives a reload.
      const existing = batch.batch?.jobIds ?? []
      const ids = [...new Set([...existing, data.enigma_request.id])]
      batch.start(ids, { n: ids.length })
    },
  })

  return { batch, create }
}

export type EnigmaController = ReturnType<typeof useEnigma>

// ── The bulk Enigma bar (select-all → estimate → confirm). PAID, so it mirrors EnrichmentBar ─────
export function EnigmaBar({
  selectedIds,
  controller,
  onCleared,
}: {
  selectedIds: string[]
  controller: EnigmaController
  onCleared: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const estimate = useQuery<EnigmaEstimate>({
    queryKey: ['outreach-enigma-estimate', [...selectedIds].sort()],
    queryFn: () => api.post<EnigmaEstimate>('/outreach/enigma/estimate', { prospect_ids: selectedIds }),
    enabled: confirming && selectedIds.length > 0,
  })

  const rows = controller.batch.rows
  const running = controller.batch.running
  const progress = rows.reduce(
    (acc, r) => {
      const p = (r.result ?? {}) as Record<string, number>
      acc.matched += p.matched ?? 0
      acc.card += p.card ?? 0
      acc.failed += p.failed ?? 0
      return acc
    },
    { matched: 0, card: 0, failed: 0 },
  )

  if (running) {
    return (
      <div style={barStyle}>
        <Loader2 size={14} className="animate-spin" />
        <span style={{ fontSize: 13 }}>
          Looking up card revenue… {controller.batch.finished}/{controller.batch.total} orders ·
          {' '}{progress.matched} matched, {progress.card} with card data
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
        <CreditCard size={14} color="#0d9488" />
        <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.length} selected</span>
        <button onClick={() => setConfirming(true)} style={primaryBtn}>
          Get card revenue…
        </button>
        <button onClick={onCleared} style={ghostBtn}>Clear</button>
      </div>
    )
  }

  const est = estimate.data
  return (
    <div style={{ ...barStyle, flexWrap: 'wrap' }}>
      <CreditCard size={14} color="#0d9488" />
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
            {est.billable} to look up (~${est.est_cost_usd.toFixed(2)})
            {est.already_fetched ? ` · ${est.already_fetched} already done` : ''}
            {est.no_name ? ` · ${est.no_name} without a name (skipped)` : ''}
            {' · '}${(est.spent_today_cents / 100).toFixed(2)}/${est.daily_budget_usd.toFixed(2)} spent today
          </span>
          {!est.allowed ? (
            <span style={{ fontSize: 12, color: '#b91c1c' }}>{est.denial}</span>
          ) : est.billable === 0 ? (
            <span style={{ fontSize: 12, color: '#b45309' }}>Nothing to look up in this selection.</span>
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
              Look up {est.billable} (~${est.est_cost_usd.toFixed(2)})
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

// Compact USD for a card figure: $8.4k, $1.2M, $940. Card revenue can be large, so abbreviate.
function fmtUsd(n: number | null): string {
  if (n == null) return '—'
  const v = Math.round(n)
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(v >= 10_000 ? 0 : 1)}k`
  return `$${v}`
}

// ── A single prospect's card-revenue cell (a coverage-table column + the lead drawer) ────────────
// Reads the batch entry (`provided`) when the table passes one, else fetches itself. Shows the three
// windows when present; otherwise the match state, and — for an admin who hasn't looked it up — a
// per-row "Get card data" button (paid; budget-guarded server-side, so no estimate step here).
export function CardRevenueCell({
  prospectId,
  isAdmin,
  controller,
  batchRunning,
  provided,
}: {
  prospectId: string
  isAdmin: boolean
  controller: EnigmaController
  batchRunning: boolean
  // undefined → this cell fetches itself (the drawer); a value (row or null) → the table's batch read.
  provided?: ProspectEnigma | null
}) {
  const self = useQuery<{ prospect_id: string; enigma: ProspectEnigma | null }>({
    queryKey: ['outreach-enigma', prospectId],
    queryFn: () => api.get(`/outreach/prospects/${prospectId}/enigma`),
    enabled: provided === undefined,
    refetchInterval: provided === undefined && batchRunning ? 6000 : false,
  })
  const enigma = provided !== undefined ? provided : self.data?.enigma ?? null
  const placing = controller.create.isPending && controller.create.variables?.[0] === prospectId

  if (enigma && (enigma.status === 'matched' || enigma.status === 'no_card')) {
    if (enigma.status === 'no_card') {
      return (
        <span style={{ fontSize: 12, color: '#94a3b8' }} title={enigma.matched_name ?? undefined}>
          matched, no card data
        </span>
      )
    }
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1, whiteSpace: 'nowrap' }}
        title={`${enigma.matched_name ?? 'matched'}${enigma.card_as_of ? ` · as of ${enigma.card_as_of}` : ''}`}>
        <span style={{ fontSize: 12 }}>
          <b>{fmtUsd(enigma.card_revenue_12m)}</b> <span style={{ color: '#94a3b8' }}>12m</span>
        </span>
        <span style={{ fontSize: 11, color: '#64748b' }}>
          {fmtUsd(enigma.card_revenue_3m)} 3m · {fmtUsd(enigma.card_revenue_1m)} 1m
        </span>
      </div>
    )
  }

  if (enigma && enigma.status === 'no_match') {
    return <span style={{ fontSize: 12, color: '#94a3b8' }}>no Enigma match</span>
  }

  if (enigma && enigma.status === 'failed') {
    return (
      <span style={{ fontSize: 12, color: '#b45309' }}>
        lookup failed
        {isAdmin && (
          <button onClick={() => controller.create.mutate([prospectId])} disabled={placing}
            style={{ ...linkBtn, marginLeft: 6 }}>retry</button>
        )}
      </span>
    )
  }

  // Not looked up yet.
  if (batchRunning || placing) {
    return <span style={{ fontSize: 12, color: '#0d9488' }}>Looking up…</span>
  }
  if (isAdmin) {
    return (
      <button onClick={() => controller.create.mutate([prospectId])} disabled={placing}
        title="Look up this prospect's card revenue via Enigma (paid; budget-guarded)"
        style={cellBtn}>
        <CreditCard size={11} /> Get card data
      </button>
    )
  }
  return <span style={{ fontSize: 12, color: '#cbd5e1' }}>—</span>
}

// ── local styles (the enrichment bar's are module-private; these match visually) ─────────────────
const barStyle: CSSProperties = {
  display: 'flex', gap: 10, alignItems: 'center', margin: '8px 0 0', padding: '6px 10px',
  background: '#f0fdfa', border: '1px solid #99f6e4', borderRadius: 8,
}
const primaryBtn: CSSProperties = {
  fontSize: 13, border: 'none', background: '#0d9488', color: '#fff', borderRadius: 6,
  padding: '3px 12px', cursor: 'pointer',
}
const ghostBtn: CSSProperties = {
  fontSize: 12, border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6,
  padding: '3px 10px', cursor: 'pointer',
}
const cellBtn: CSSProperties = {
  fontSize: 12, border: '1px solid #99f6e4', background: '#f0fdfa', color: '#0f766e',
  borderRadius: 6, padding: '2px 8px', cursor: 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center',
}
const linkBtn: CSSProperties = {
  fontSize: 12, border: 'none', background: 'none', color: '#0d9488', cursor: 'pointer',
  textDecoration: 'underline', padding: 0,
}
