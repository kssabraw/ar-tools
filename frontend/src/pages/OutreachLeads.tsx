import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Crosshair, Loader2, Plus, X, AlertTriangle, Ban, Search, Phone, Clock,
} from 'lucide-react'
import { api } from '../lib/api'
import { Justification } from '../components/outreach/Justification'
import { ProspectReportButtons } from '../components/outreach/ProspectReport'
import { LeadContacts } from '../components/outreach/Enrichment'
import { useAuth } from '../context/AuthContext'

// ── Types (mirror the CRM half of routers/outreach.py) ───────────────────────
interface LeadStage { key: string; label: string; sort_order: number; is_terminal: boolean }
// Per-lead touch-cadence rollup (T2.1), from v_lead_cadence — attached to every lead + queue row.
interface Cadence {
  attempt_count: number
  last_touched_at: string | null
  last_disposition: string | null
}
interface Lead {
  id: string
  source: string
  stage: string
  prospect_id: string | null
  company_name: string | null
  contact_name: string | null
  email: string | null
  phone: string | null
  website: string | null
  category: string | null
  notes_intake: string | null
  suppressed_at: string | null
  suppression_reason: string | null
  lost_reason: string | null
  next_action: string | null
  next_action_due: string | null
  next_action_at: string | null
  next_action_tz: string | null
  stage_changed_at: string | null
  created_at: string
  cadence: Cadence | null
}
// The structured disposition picker (T1.2) + its next-action hints (T1.3), served by
// GET /outreach/dispositions so the vocabulary + behaviour live in one place (the backend).
interface Disposition {
  value: string
  label: string
  reveal_callback?: boolean
  default_next_action?: string
  offset_days?: number
  suggest_lost_reason?: string
  suggest_suppress?: boolean
  suppress_scope?: string
}
interface DispositionCatalog { phone: Disposition[]; email: Disposition[] }
// A row of the score-ordered call queue (T1.1) — GET /outreach/call-queue.
interface BusinessHours { tz: string | null; local_time: string | null; in_business_hours: boolean | null }
interface QueueRow {
  lead_id: string
  prospect_id: string | null
  name: string
  phone: string | null
  phone_type: string | null
  submarket: string | null
  source: string
  stage: string
  next_action: string | null
  next_action_due: string | null
  next_action_at: string | null
  next_action_tz: string | null
  score: number | string | null
  decile: number | null
  primary_pitch: string | null
  vendor_failing: boolean
  last_disposition: string | null
  business_hours: BusinessHours | null
  attempt_count: number
  last_touched_at: string | null
}
// The caller scoreboard (T2.2) — GET /outreach/scoreboard.
interface ScoreboardCaller {
  actor_id: string
  name: string
  dials: number
  conversations: number
  dm_reached: number
  callbacks: number
  voicemails: number
  not_interested: number
  dnc: number
  touches: number
  connect_rate: number | null
  last_touch_at: string | null
}
interface Scoreboard { window_days: number; since: string; callers: ScoreboardCaller[]; me: ScoreboardCaller | null }
// A prospect-search result for the T2.5 "link to a scanned prospect" control (GET /outreach/prospects).
interface ProspectLite {
  id: string
  name: string
  submarket_name: string | null
  address: string | null
  review_count: number | null
  rating: number | null
}
interface Activity {
  id: number
  occurred_at: string
  kind: string
  body: string
  from_stage: string | null
  to_stage: string | null
}
interface LeadDetail extends Lead {
  activity: Activity[]
  activity_total: number
  prospect: {
    name: string; address: string | null; rating: number | null; review_count: number | null
    submarket_name: string | null; place_id: string | null; phone: string | null
    lat: number | null; lng: number | null
  } | null
  ranked: { score: number | string | null; decile: number | null; primary_pitch: string | null } | null
}
// The Phase 3 modelling substrate (outbound-only). Written by emit / rolled up by touches.
interface Outcome {
  prospect_id: string
  selection_reason: string
  sequence_version: string
  touches_per_sequence_at_send: number
  touch_count: number
  first_contacted_at: string | null
  replied_at: string | null
  closed_at: string | null
}

const LOST_REASONS = [
  'no_response', 'not_interested', 'no_budget', 'has_agency', 'timing',
  'went_elsewhere', 'disqualified', 'unreachable', 'opted_out',
]
const CREATE_SOURCES = ['manual', 'inbound_call', 'inbound_form', 'referral', 'partner']
// Every source a lead can carry, for the board's source filter (T2.4). outbound_scan is the scanner
// path (not creatable by hand), so it's here but not in CREATE_SOURCES.
const FILTER_SOURCES = ['outbound_scan', ...CREATE_SOURCES]
// Board sort control (T2.4) — labels for the backend's sort whitelist (services/outreach._LEAD_SORTS).
const LEAD_SORTS: { value: string; label: string }[] = [
  { value: 'recent', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'due', label: 'Due soonest' },
  { value: 'name', label: 'Company A–Z' },
]
// The planned contact-sequence length (config `outreach_touches_per_sequence`), shown as "N of 5".
// Mirrored here like LOST_REASONS / US_TIMEZONES; the backend owns the real value.
const TOUCHES_PER_SEQUENCE = 5

// Cadence line (T2.1): "attempt 3 of 5 · last: voicemail". Renders nothing when there are no
// attempts yet, so a fresh lead's card stays clean rather than showing "attempt 0".
function CadenceLine({ cadence }: { cadence: Cadence | null | undefined }) {
  if (!cadence || !cadence.attempt_count) return null
  const capped = Math.min(cadence.attempt_count, TOUCHES_PER_SEQUENCE)
  const over = cadence.attempt_count > TOUCHES_PER_SEQUENCE
  return (
    <span style={{ fontSize: 11, color: '#94a3b8' }}>
      attempt {over ? cadence.attempt_count : capped} of {TOUCHES_PER_SEQUENCE}
      {cadence.last_disposition ? ` · last: ${cadence.last_disposition.replace(/_/g, ' ')}` : ''}
    </span>
  )
}

function overdue(lead: Lead, terminal: Set<string>): boolean {
  return !!lead.next_action_due
    && !terminal.has(lead.stage)
    && new Date(lead.next_action_due) < new Date(new Date().toDateString())
}

// ── Calling helpers (T1.3 / T1.4) ─────────────────────────────────────────────
// The zones a US cold-caller actually dials into, plus the stored/derived one. This is a picker
// convenience only — the backend validates any IANA zone, so an unlisted one still works.
const US_TIMEZONES: { value: string; label: string }[] = [
  { value: 'America/New_York', label: 'Eastern' },
  { value: 'America/Chicago', label: 'Central' },
  { value: 'America/Denver', label: 'Mountain' },
  { value: 'America/Phoenix', label: 'Arizona (no DST)' },
  { value: 'America/Los_Angeles', label: 'Pacific' },
  { value: 'America/Anchorage', label: 'Alaska' },
  { value: 'Pacific/Honolulu', label: 'Hawaii' },
]

// A default zone for the picker only — a rough longitude band, drift-tolerant because the caller
// confirms it. The backend owns the authoritative derivation; this just seeds the dropdown.
function guessTz(lng: number | null | undefined): string {
  // Out of the US longitude range (or unknown) → the config default; the bands only mean anything
  // for a US coordinate, and a positive/European lng would otherwise seed the picker with Eastern.
  if (lng == null || lng > -60) return 'America/Los_Angeles'
  if (lng >= -87.5) return 'America/New_York'
  if (lng >= -102) return 'America/Chicago'
  if (lng >= -115) return 'America/Denver'
  if (lng >= -140) return 'America/Los_Angeles'
  if (lng >= -150) return 'America/Anchorage'
  return 'Pacific/Honolulu'
}

// The prospect's local clock right now + whether it's inside 8–18 on a weekday. Display-only, so
// it's computed client-side via Intl (no backend round trip); PR2's queue computes it server-side.
function localClock(tz: string | null | undefined): { time: string; inHours: boolean } | null {
  if (!tz) return null
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
    }).formatToParts(new Date())
    const get = (t: string) => parts.find(p => p.type === t)?.value ?? ''
    const hour24 = Number(new Intl.DateTimeFormat('en-US', { timeZone: tz, hour: 'numeric', hour12: false })
      .formatToParts(new Date()).find(p => p.type === 'hour')?.value ?? '0')
    const weekday = get('weekday')
    const isWeekend = weekday === 'Sat' || weekday === 'Sun'
    return {
      time: `${weekday} ${get('hour')}:${get('minute')} ${get('dayPeriod')}`.trim(),
      inHours: !isWeekend && hour24 >= 8 && hour24 < 18,
    }
  } catch {
    return null
  }
}

function todayPlusDays(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

function fmtScore(s: number | string | null): string | null {
  if (s == null) return null
  const n = typeof s === 'string' ? Number(s) : s
  return Number.isFinite(n) ? Math.round(n).toLocaleString() : null
}

// Score + decile pill (T1.5). A top-decile lead reads green; the number is the value model's.
function ScorePill({ score, decile }: { score: number | string | null; decile: number | null }) {
  const s = fmtScore(score)
  if (s == null) return null
  const strong = (decile ?? 0) >= 8
  return (
    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 700,
      background: strong ? '#dcfce7' : '#f1f5f9', color: strong ? '#166534' : '#475569' }}>
      {s}{decile != null ? ` · D${decile}` : ''}
    </span>
  )
}

// ── Work-the-queue list (T1.1 / T1.5) ─────────────────────────────────────────

function QueueView({ queue, loading, onOpen }: {
  queue: QueueRow[]; loading: boolean; onOpen: (id: string) => void
}) {
  if (loading) return <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>Loading queue…</p>
  if (queue.length === 0) {
    return (
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>
        Nothing to call. Promote scored prospects from a scan's coverage results — every workable,
        non-suppressed lead lands here, best-first.
      </p>
    )
  }
  return (
    <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
      <div style={{ fontSize: 11, color: '#94a3b8' }}>
        {queue.length} to work · best-first (due date, then value score)
      </div>
      {queue.map(row => <QueueCard key={row.lead_id} row={row} onOpen={onOpen} />)}
    </div>
  )
}

function QueueCard({ row, onOpen }: { row: QueueRow; onOpen: (id: string) => void }) {
  const bh = row.business_hours
  const isOverdue = !!row.next_action_due && new Date(row.next_action_due) < new Date(new Date().toDateString())
  return (
    // A div (not a button) so the tel: anchor can nest without invalid button-in-button; the
    // role/tabIndex/onKeyDown give it the keyboard access a button would have had.
    <div role="button" tabIndex={0} onClick={() => onOpen(row.lead_id)}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(row.lead_id) } }}
      style={{ textAlign: 'left', padding: 12, borderRadius: 10, cursor: 'pointer',
        border: '1px solid #e2e8f0', background: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{row.name}</div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <ScorePill score={row.score} decile={row.decile} />
          {row.vendor_failing && (
            <span title="Paying a vendor while losing ground — the strongest pitch"
              style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#fef3c7',
                color: '#92400e', fontWeight: 700 }}>vendor-failing</span>
          )}
        </div>
      </div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 3, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {row.phone ? (
          <a href={`tel:${row.phone}`} onClick={e => e.stopPropagation()}
            style={{ color: '#0369a1', textDecoration: 'none', fontWeight: 600,
              display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <Phone size={11} /> {row.phone}
          </a>
        ) : <span style={{ color: '#b45309' }}>no phone</span>}
        {row.phone_type && row.phone_type !== 'unknown' && <span>· {row.phone_type}</span>}
        {row.submarket && <span>· {row.submarket}</span>}
        {row.primary_pitch && <span>· {row.primary_pitch}</span>}
      </div>
      {row.next_action && (
        <div style={{ fontSize: 11, marginTop: 4, color: isOverdue ? '#b91c1c' : '#475569' }}>
          {isOverdue ? '⚠ ' : ''}{row.next_action}
          {row.next_action_due ? ` — ${row.next_action_due.slice(0, 10)}` : ''}
        </div>
      )}
      <div style={{ fontSize: 11, marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <CadenceLine cadence={{ attempt_count: row.attempt_count, last_touched_at: row.last_touched_at, last_disposition: row.last_disposition }} />
        {bh?.in_business_hours != null && (
          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center',
            color: bh.in_business_hours ? '#166534' : '#b45309' }}>
            <Clock size={11} /> {bh.in_business_hours ? 'in business hours' : 'outside hours'}
            {bh.tz ? ` (${bh.tz.split('/').pop()!.replace('_', ' ')})` : ''}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Caller scoreboard (T2.2) ───────────────────────────────────────────────────
// Owner ruling: BOTH a per-caller "your numbers" card and a team leaderboard. Solo today, so the
// leaderboard is a one-row table — but it's ready for a team the moment more callers log touches.
// Every number is a count of touches + their structured dispositions (T1.2), aggregated server-side.

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div style={{ padding: 10, borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>{value}</div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{label}</div>
    </div>
  )
}

function ScoreboardView() {
  const { profile } = useAuth()
  const [days, setDays] = useState(7)
  const { data, isLoading } = useQuery<Scoreboard>({
    queryKey: ['outreach-scoreboard', days],
    queryFn: () => api.get(`/outreach/scoreboard?days=${days}`),
  })
  const windows = [{ d: 1, label: 'Today' }, { d: 7, label: '7 days' }, { d: 30, label: '30 days' }]
  const pct = (r: number | null) => (r == null ? '—' : `${Math.round(r * 100)}%`)
  const me = data?.me ?? null
  const callers = data?.callers ?? []
  const th: CSSProperties = { padding: '4px 8px', fontWeight: 600 }
  const thr: CSSProperties = { ...th, textAlign: 'right' }
  const td: CSSProperties = { padding: '6px 8px', color: '#334155' }
  const tdr: CSSProperties = { ...td, textAlign: 'right' }

  return (
    <div style={{ marginTop: 16, maxWidth: 720 }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {windows.map(w => (
          <button key={w.d} onClick={() => setDays(w.d)}
            style={{ padding: '4px 12px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12,
              fontWeight: 600, cursor: 'pointer',
              background: days === w.d ? '#0369a1' : '#fff', color: days === w.d ? '#fff' : '#475569' }}>
            {w.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>Loading scoreboard…</p>
      ) : (
        <>
          {me && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
                Your numbers{profile?.full_name ? ` · ${profile.full_name}` : ''}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
                gap: 8, marginTop: 8 }}>
                <Stat label="Dials" value={me.dials} />
                <Stat label="Conversations" value={me.conversations} />
                <Stat label="Connect rate" value={pct(me.connect_rate)} />
                <Stat label="Callbacks" value={me.callbacks} />
                <Stat label="DMs reached" value={me.dm_reached} />
                <Stat label="Voicemails" value={me.voicemails} />
                <Stat label="Not interested" value={me.not_interested} />
                <Stat label="Do-not-call" value={me.dnc} />
              </div>
            </div>
          )}

          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
              Team leaderboard
            </div>
            {callers.length === 0 ? (
              <p style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
                No calls logged in this window yet. Dispositions logged while working the queue feed
                this scoreboard.
              </p>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 13 }}>
                <thead>
                  <tr style={{ color: '#94a3b8', fontSize: 11, textAlign: 'left' }}>
                    <th style={th}>#</th><th style={th}>Caller</th><th style={thr}>Dials</th>
                    <th style={thr}>Convos</th><th style={thr}>Connect</th><th style={thr}>Callbacks</th>
                  </tr>
                </thead>
                <tbody>
                  {callers.map((c, i) => {
                    const isMe = !!me && c.actor_id === me.actor_id
                    return (
                      <tr key={c.actor_id} style={{ borderTop: '1px solid #f1f5f9',
                        background: isMe ? '#f8fafc' : undefined }}>
                        <td style={td}>{i + 1}</td>
                        <td style={{ ...td, fontWeight: 600 }}>{c.name}{isMe ? ' (you)' : ''}</td>
                        <td style={tdr}>{c.dials}</td>
                        <td style={tdr}>{c.conversations}</td>
                        <td style={tdr}>{pct(c.connect_rate)}</td>
                        <td style={tdr}>{c.callbacks}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── The page ─────────────────────────────────────────────────────────────────

export function OutreachLeads() {
  const queryClient = useQueryClient()
  const [openLead, setOpenLead] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'board' | 'queue' | 'scoreboard'>('queue')
  // Board filters + sort (T2.4). Owner is deliberately not a filter here — solo caller, so every
  // lead is the one caller's (T2.3 owner UI is a later tier). Stage is the board's columns already.
  const [sourceFilter, setSourceFilter] = useState('')
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [sortBy, setSortBy] = useState('recent')

  const { data: stagesData } = useQuery<{ stages: LeadStage[] }>({
    queryKey: ['outreach-lead-stages'],
    queryFn: () => api.get('/outreach/lead-stages'),
  })
  const stages = useMemo(
    () => (stagesData?.stages ?? []).slice().sort((a, b) => a.sort_order - b.sort_order),
    [stagesData],
  )
  const terminal = useMemo(
    () => new Set(stages.filter(s => s.is_terminal).map(s => s.key)),
    [stages],
  )

  // The board fetch carries the T2.4 filters + sort. Built once so the query key and the URL can't
  // drift. The queue + scoreboard views have their own fetches, so this is skipped there.
  const leadsUrl = useMemo(() => {
    const p = new URLSearchParams({ limit: '200' })
    if (search) p.set('search', search)
    if (sourceFilter) p.set('source', sourceFilter)
    if (overdueOnly) p.set('overdue', 'true')
    if (sortBy && sortBy !== 'recent') p.set('sort', sortBy)
    return `/outreach/leads?${p.toString()}`
  }, [search, sourceFilter, overdueOnly, sortBy])

  const { data: leadsData, isLoading } = useQuery<{ leads: Lead[]; total: number }>({
    queryKey: ['outreach-leads', leadsUrl],
    queryFn: () => api.get(leadsUrl),
    // Only the board renders `leads`; the queue + scoreboard views have their own fetches, so don't
    // spend a request building `byStage` they never show.
    enabled: view === 'board',
  })
  // Memoized so its reference is stable per fetch — otherwise the `?? []` fallback is a fresh array
  // every render and re-runs the byStage grouping (and its dependents) needlessly.
  const leads = useMemo(() => leadsData?.leads ?? [], [leadsData])
  const byStage = useMemo(() => {
    const map: Record<string, Lead[]> = {}
    for (const lead of leads) (map[lead.stage] ??= []).push(lead)
    return map
  }, [leads])

  // The score-ordered call queue (T1.1). Fetched only in queue view; the backend already filters
  // to workable, non-suppressed leads and orders by due-date then value score.
  const { data: queueData, isLoading: queueLoading } = useQuery<{ queue: QueueRow[] }>({
    queryKey: ['outreach-call-queue'],
    queryFn: () => api.get('/outreach/call-queue?limit=200'),
    enabled: view === 'queue',
  })
  const queue = queueData?.queue ?? []

  // Auto-advance: after a disposition is logged in the drawer, land on the next queue lead (or
  // close on the last one) so the caller works top-down without returning to the list.
  const advanceQueue = (currentId: string) => {
    const ids = queue.map(r => r.lead_id)
    const i = ids.indexOf(currentId)
    queryClient.invalidateQueries({ queryKey: ['outreach-call-queue'] })
    setOpenLead(i >= 0 && i + 1 < ids.length ? ids[i + 1] : null)
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Crosshair size={20} /> Outreach
        </h1>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ position: 'relative' }}>
            <Search size={13} style={{ position: 'absolute', left: 8, top: 9, color: '#94a3b8' }} />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search leads…"
              style={{ padding: '6px 10px 6px 26px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
          </div>
          <button onClick={() => setAdding(true)}
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center', padding: '6px 12px',
              borderRadius: 8, border: 'none', background: '#0f172a', color: '#fff',
              fontWeight: 600, fontSize: 13, cursor: 'pointer' }}>
            <Plus size={14} /> Add lead
          </button>
        </div>
      </div>

      <Tabs active="leads" />

      {/* Work the queue (score-ordered, T1.1) vs the pipeline board. Queue is the default — it's
          the surface a caller works; the board is the manager's pipeline view. */}
      <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
        {(['queue', 'board', 'scoreboard'] as const).map(v => (
          <button key={v} onClick={() => setView(v)}
            style={{ padding: '5px 12px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12,
              fontWeight: 600, cursor: 'pointer',
              background: view === v ? '#0f172a' : '#fff', color: view === v ? '#fff' : '#475569' }}>
            {v === 'queue' ? 'Work the queue' : v === 'board' ? 'Board' : 'Scoreboard'}
          </button>
        ))}
      </div>

      {/* Board filters + sort (T2.4): slice the board by source / overdue and order the cards.
          Only shown on the board — the queue has its own fixed best-first order, the scoreboard
          its own window control. */}
      {view === 'board' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}>
            <option value="">All sources</option>
            {FILTER_SOURCES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)}
            style={{ padding: '5px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 12 }}>
            {LEAD_SORTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <label style={{ fontSize: 12, display: 'inline-flex', gap: 5, alignItems: 'center', color: '#475569', cursor: 'pointer' }}>
            <input type="checkbox" checked={overdueOnly} onChange={e => setOverdueOnly(e.target.checked)} /> Overdue only
          </label>
          {(sourceFilter || overdueOnly || sortBy !== 'recent') && (
            <button onClick={() => { setSourceFilter(''); setOverdueOnly(false); setSortBy('recent') }}
              style={{ padding: '5px 10px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff',
                fontSize: 12, color: '#64748b', cursor: 'pointer' }}>Clear</button>
          )}
        </div>
      )}

      {view === 'scoreboard' ? (
        <ScoreboardView />
      ) : view === 'queue' ? (
        <QueueView queue={queue} loading={queueLoading} onOpen={setOpenLead} />
      ) : isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>Loading…</p>
      ) : leads.length === 0 && !search && !sourceFilter && !overdueOnly ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>
          No leads yet. Send prospects here from a scan's coverage results, or add an inbound /
          referral lead by hand — both land on this board.
        </p>
      ) : (
        <div style={{ display: 'flex', gap: 12, marginTop: 16, overflowX: 'auto', paddingBottom: 8 }}>
          {stages.map(stage => (
            <div key={stage.key} style={{ minWidth: 220, flex: '0 0 220px' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', padding: '4px 2px' }}>
                {stage.label ?? stage.key}
                <span style={{ color: '#94a3b8', fontWeight: 500 }}> · {(byStage[stage.key] ?? []).length}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 6 }}>
                {(byStage[stage.key] ?? []).map(lead => (
                  <button key={lead.id} onClick={() => setOpenLead(lead.id)}
                    style={{ textAlign: 'left', padding: 10, borderRadius: 10, cursor: 'pointer',
                      border: '1px solid #e2e8f0', background: '#fff' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
                      {lead.company_name ?? lead.contact_name ?? '(unnamed)'}
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                      {lead.source === 'outbound_scan' ? 'from scan' : lead.source.replace('_', ' ')}
                      {lead.phone ? ` · ${lead.phone}` : ''}
                    </div>
                    {lead.suppressed_at && (
                      <div style={{ fontSize: 11, color: '#b91c1c', marginTop: 4,
                        display: 'flex', gap: 4, alignItems: 'center' }}>
                        <Ban size={11} /> suppressed — do not contact
                      </div>
                    )}
                    {lead.next_action && (
                      <div style={{ fontSize: 11, marginTop: 4,
                        color: overdue(lead, terminal) ? '#b91c1c' : '#475569' }}>
                        {overdue(lead, terminal) ? '⚠ ' : ''}{lead.next_action}
                        {lead.next_action_due ? ` — ${lead.next_action_due.slice(0, 10)}` : ''}
                      </div>
                    )}
                    {lead.next_action_tz && (
                      <div style={{ marginTop: 3 }}><BusinessHours tz={lead.next_action_tz} /></div>
                    )}
                    {lead.cadence && lead.cadence.attempt_count > 0 && (
                      <div style={{ marginTop: 3 }}><CadenceLine cadence={lead.cadence} /></div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {adding && <AddLeadModal onClose={() => setAdding(false)} />}
      {openLead && (
        // key on the lead id so switching leads — especially the queue's auto-advance — REMOUNTS
        // the drawer, resetting its form state (disposition, note) and NextAction's lead-seeded
        // editor. Without it React reuses the instance and the previous lead's next-action/notes
        // bleed into the next one (and a Save would write them onto the wrong lead).
        <LeadDrawer key={openLead} id={openLead} stages={stages}
          onAdvance={view === 'queue' ? () => advanceQueue(openLead) : undefined}
          onClose={() => {
            setOpenLead(null)
            queryClient.invalidateQueries({ queryKey: ['outreach-leads'] })
            if (view === 'queue') queryClient.invalidateQueries({ queryKey: ['outreach-call-queue'] })
          }} />
      )}
    </div>
  )
}

export function Tabs({ active }: { active: 'scans' | 'leads' }) {
  const tab = (key: string, to: string, label: string) => (
    <Link to={to} style={{
      padding: '6px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, textDecoration: 'none',
      background: active === key ? '#0f172a' : 'transparent',
      color: active === key ? '#fff' : '#475569',
    }}>{label}</Link>
  )
  return (
    <div style={{ display: 'flex', gap: 4, marginTop: 12, borderBottom: '1px solid #f1f5f9', paddingBottom: 8 }}>
      {tab('scans', '/outreach', 'Scans')}
      {tab('leads', '/outreach/leads', 'Leads')}
    </div>
  )
}

// ── Add lead ─────────────────────────────────────────────────────────────────

function AddLeadModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    source: 'manual', company_name: '', contact_name: '', email: '', phone: '',
    website: '', notes_intake: '',
  })
  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const create = useMutation({
    mutationFn: () => api.post('/outreach/leads', Object.fromEntries(
      Object.entries(form).filter(([, v]) => v !== ''),
    )),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['outreach-leads'] })
      onClose()
    },
  })

  const input = (k: keyof typeof form, placeholder: string) => (
    <input value={form[k]} onChange={e => set(k, e.target.value)} placeholder={placeholder}
      style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, width: '100%' }} />
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)', zIndex: 50,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}>
      <div onClick={e => e.stopPropagation()}
        style={{ background: '#fff', borderRadius: 14, padding: 20, width: 420, maxWidth: '92vw' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>Add lead</div>
          <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer' }}><X size={16} /></button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
          <select value={form.source} onChange={e => set('source', e.target.value)}
            style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
            {CREATE_SOURCES.map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
          {input('company_name', 'Company *')}
          {input('contact_name', 'Contact name')}
          {input('email', 'Email')}
          {input('phone', 'Phone')}
          {input('website', 'Website')}
          <textarea value={form.notes_intake} onChange={e => set('notes_intake', e.target.value)}
            placeholder="Intake notes — how they reached us, what they asked for"
            rows={3}
            style={{ padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, resize: 'vertical' }} />
        </div>
        {create.error instanceof Error && (
          <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 8, display: 'flex', gap: 6, alignItems: 'center' }}>
            <AlertTriangle size={13} /> {create.error.message}
          </p>
        )}
        <button onClick={() => create.mutate()} disabled={create.isPending || !form.company_name}
          style={{ marginTop: 12, width: '100%', padding: '8px 0', borderRadius: 8, border: 'none',
            fontWeight: 600, fontSize: 13, cursor: 'pointer',
            background: form.company_name ? '#0f172a' : '#e2e8f0',
            color: form.company_name ? '#fff' : '#94a3b8' }}>
          {create.isPending ? <Loader2 size={13} className="animate-spin" /> : 'Create lead'}
        </button>
      </div>
    </div>
  )
}

// ── Lead drawer ──────────────────────────────────────────────────────────────

function LeadDrawer({ id, stages, onClose, onAdvance }: {
  id: string; stages: LeadStage[]; onClose: () => void; onAdvance?: () => void
}) {
  const queryClient = useQueryClient()
  const { isAdmin, isStaff } = useAuth()
  const [note, setNote] = useState('')
  const [lostReason, setLostReason] = useState('')
  const [pendingStage, setPendingStage] = useState<string | null>(null)
  const [showHook, setShowHook] = useState(false)
  const [touchChannel, setTouchChannel] = useState('phone')
  const [touchDisposition, setTouchDisposition] = useState('')
  const [touchNote, setTouchNote] = useState('')
  // Next-action fields prefilled by the chosen disposition's hint (T1.3), editable before saving.
  const [naText, setNaText] = useState('')
  const [naDue, setNaDue] = useState('')            // day-only follow-up (YYYY-MM-DD)
  const [naLocal, setNaLocal] = useState('')        // precise callback wall-time (datetime-local)
  const [naTz, setNaTz] = useState('')

  const { data: lead } = useQuery<LeadDetail>({
    queryKey: ['outreach-lead', id],
    queryFn: () => api.get(`/outreach/leads/${id}`),
  })
  // App-level disposition vocabulary + hints (cached; it never changes within a session).
  const { data: dispCatalog } = useQuery<DispositionCatalog>({
    queryKey: ['outreach-dispositions'],
    queryFn: () => api.get('/outreach/dispositions'),
    staleTime: Infinity,
  })
  const dispositions = (touchChannel === 'email' ? dispCatalog?.email : dispCatalog?.phone) ?? []
  const dispHint = dispositions.find(d => d.value === touchDisposition)

  // The outcome exists only for outbound leads, and only once emitted or first contacted.
  const isOutbound = lead?.source === 'outbound_scan' && !!lead?.prospect_id
  const { data: outcomeData } = useQuery<{ outcome: Outcome | null }>({
    queryKey: ['outreach-outcome', lead?.prospect_id],
    queryFn: () => api.get(`/outreach/prospects/${lead!.prospect_id}/outcome`),
    enabled: !!isOutbound,
  })
  const outcome = outcomeData?.outcome ?? null

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['outreach-lead', id] })
    queryClient.invalidateQueries({ queryKey: ['outreach-leads'] })
    if (lead?.prospect_id) queryClient.invalidateQueries({ queryKey: ['outreach-outcome', lead.prospect_id] })
  }

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/outreach/leads/${id}`, body),
    onSuccess: () => { setPendingStage(null); setLostReason(''); refresh() },
  })
  const addNote = useMutation({
    mutationFn: () => api.post(`/outreach/leads/${id}/activities`, { kind: 'note', body: note }),
    onSuccess: () => { setNote(''); refresh() },
  })
  const defaultTz = lead?.next_action_tz || guessTz(lead?.prospect?.lng)
  // What a do-not-contact would suppress on: the phone digits (what "don't call this number" means),
  // else the prospect's stable place_id, else the email. Empty ⇒ nothing to suppress on, so the
  // one-click button is hidden rather than 422-ing with `empty_value`.
  const suppressValue =
    (lead?.phone ?? lead?.prospect?.phone ?? '').replace(/\D/g, '')
    || lead?.prospect?.place_id || lead?.email || ''

  // Picking a disposition prefills the next-action fields from its hint (T1.3) — editable before
  // saving. A callback disposition reveals the wall-time + zone; a follow-up one prefills a due date.
  const pickDisposition = (value: string) => {
    setTouchDisposition(value)
    const h = dispositions.find(d => d.value === value)
    setNaText(h?.default_next_action ?? '')
    setNaLocal('')
    if (h?.reveal_callback) { setNaDue(''); setNaTz(prev => prev || defaultTz) }
    else if (h?.offset_days != null) setNaDue(todayPlusDays(h.offset_days))
    else setNaDue('')
  }

  const resetTouchForm = () => {
    setTouchDisposition(''); setTouchNote(''); setNaText(''); setNaDue(''); setNaLocal('')
  }

  // A touch is authoritative for "a contact attempt happened" — distinct from a free-text note.
  // For an outbound lead it also creates/rolls up the outcome (the modelling substrate). T1.3: the
  // next action / callback booked here rides in the SAME request, so logging a call and scheduling
  // the follow-up is one save.
  const logTouch = useMutation({
    mutationFn: () => {
      const revealCallback = !!dispHint?.reveal_callback
      return api.post(`/outreach/leads/${id}/touches`, {
        channel: touchChannel,
        disposition: touchDisposition.trim() || undefined,
        note: touchNote.trim() || undefined,
        next_action: naText.trim() || undefined,
        next_action_local: revealCallback && naLocal ? naLocal : undefined,
        next_action_tz: revealCallback && naLocal ? naTz : undefined,
        next_action_due: !revealCallback && naDue ? naDue : undefined,
      })
    },
    onSuccess: () => {
      // Auto-advance the queue only when the caller actually dispositioned the lead (T1.1) — a
      // note-only touch keeps them on the current lead.
      const advance = !!(onAdvance && touchDisposition)
      resetTouchForm()
      refresh()
      if (advance) onAdvance!()
    },
  })

  // do_not_call / unsubscribe → a one-click do-not-contact write (crm-layer-spec §4). Suppress by
  // phone digits (what the caller means by "don't call this number") for a phone lead, else by the
  // prospect's place_id; scope from the disposition hint ('all' covers phone AND email).
  const suppress = useMutation({
    mutationFn: () => {
      return api.post('/outreach/suppressions', {
        scope: dispHint?.suppress_scope ?? 'all',
        value: suppressValue,
        reason: `${touchDisposition || 'do_not_contact'} (logged by caller)`,
      })
    },
    onSuccess: () => refresh(),
  })

  const onStagePick = (stage: string) => {
    // Losing a lead REQUIRES a reason — the database refuses without one, and the reason is
    // unrecoverable after the moment of loss, so the UI collects it at that moment.
    if (stage === 'lost') { setPendingStage('lost'); return }
    patch.mutate({ stage })
  }

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 400, maxWidth: '94vw',
      background: '#fff', borderLeft: '1px solid #e2e8f0', zIndex: 40, padding: 18,
      overflowY: 'auto', boxShadow: '-8px 0 24px rgba(15,23,42,0.08)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{lead?.company_name ?? '…'}</div>
        <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer' }}><X size={16} /></button>
      </div>

      {!lead ? <p style={{ fontSize: 13, color: '#64748b', marginTop: 12 }}>Loading…</p> : (
        <>
          {lead.suppressed_at && (
            <div style={{ marginTop: 10, padding: 8, borderRadius: 8, background: '#fee2e2',
              color: '#b91c1c', fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
              <Ban size={13} /> Suppressed ({lead.suppression_reason ?? 'do-not-contact'}) — do not contact.
            </div>
          )}

          {/* Priority signals (T1.5): the phone-track value score + decile + primary pitch. */}
          {lead.ranked && lead.ranked.score != null && (
            <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <ScorePill score={lead.ranked.score} decile={lead.ranked.decile} />
              {lead.ranked.primary_pitch && (
                <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, background: '#eff6ff',
                  color: '#0369a1', fontWeight: 600 }}>{lead.ranked.primary_pitch}</span>
              )}
            </div>
          )}

          <div style={{ marginTop: 12, fontSize: 12, color: '#475569', display: 'grid',
            gridTemplateColumns: 'auto 1fr', gap: '4px 10px' }}>
            <span style={{ color: '#94a3b8' }}>Source</span><span>{lead.source.replace('_', ' ')}</span>
            {lead.phone && <><span style={{ color: '#94a3b8' }}>Phone</span>
              <span><a href={`tel:${lead.phone}`} style={{ color: '#0369a1', textDecoration: 'none' }}>{lead.phone}</a></span></>}
            {lead.email && <><span style={{ color: '#94a3b8' }}>Email</span><span>{lead.email}</span></>}
            {lead.website && <><span style={{ color: '#94a3b8' }}>Website</span>
              <a href={lead.website} target="_blank" rel="noreferrer">{lead.website}</a></>}
            {lead.prospect && <>
              <span style={{ color: '#94a3b8' }}>From scan</span>
              <span>{lead.prospect.submarket_name ?? ''} · {lead.prospect.review_count ?? 0} reviews
                {lead.prospect.rating ? ` · ${lead.prospect.rating}★` : ''}</span>
            </>}
          </div>

          {lead.prospect_id ? (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <button onClick={() => setShowHook(h => !h)}
                  style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: '1px solid #e2e8f0',
                    background: showHook ? '#eff6ff' : '#fff', borderRadius: 8, padding: '6px 10px',
                    fontSize: 12, fontWeight: 600, color: '#0369a1', cursor: 'pointer' }}>
                  <Phone size={13} /> {showHook ? 'Hide call hook' : 'Why call?'}
                </button>
                <ProspectReportButtons prospectId={lead.prospect_id} />
              </div>
              {showHook && (
                <div style={{ marginTop: 8 }}>
                  <Justification prospectId={lead.prospect_id} />
                </div>
              )}
              <LeadContacts prospectId={lead.prospect_id} isAdmin={isAdmin} isStaff={isStaff} />
            </div>
          ) : isStaff ? (
            // T2.5: a manual/inbound lead has no scan behind it, so no hook/report/enrich. Offer to
            // link it to an already-scanned prospect (no new scan, no spend). Staff-gated like the write.
            <LinkProspect leadId={id} defaultQuery={lead.company_name} onLinked={refresh} />
          ) : null}

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>Stage</div>
            {pendingStage === 'lost' ? (
              <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                <select value={lostReason} onChange={e => setLostReason(e.target.value)}
                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                  <option value="">Why lost? (required)</option>
                  {LOST_REASONS.map(r => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
                </select>
                <button disabled={!lostReason}
                  onClick={() => patch.mutate({ stage: 'lost', lost_reason: lostReason })}
                  style={{ padding: '6px 12px', borderRadius: 8, border: 'none', fontSize: 13,
                    fontWeight: 600, cursor: lostReason ? 'pointer' : 'not-allowed',
                    background: lostReason ? '#b91c1c' : '#e2e8f0',
                    color: lostReason ? '#fff' : '#94a3b8' }}>
                  Mark lost
                </button>
                <button onClick={() => setPendingStage(null)}
                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0',
                    background: '#fff', fontSize: 13, cursor: 'pointer' }}>Back</button>
              </div>
            ) : (
              <select value={lead.stage} onChange={e => onStagePick(e.target.value)}
                style={{ marginTop: 6, padding: '6px 10px', borderRadius: 8,
                  border: '1px solid #e2e8f0', fontSize: 13, width: '100%' }}>
                {stages.map(s => <option key={s.key} value={s.key}>{s.label ?? s.key}</option>)}
              </select>
            )}
            {lead.stage === 'lost' && lead.lost_reason && (
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                Lost: {lead.lost_reason.replace('_', ' ')}
              </div>
            )}
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>Next action</div>
            <NextAction lead={lead} defaultTz={defaultTz} onSave={body => patch.mutate(body)} />
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
              Log contact
            </div>
            {/* Cadence (T2.1) for ANY lead — the outcome rollup below exists only for outbound. */}
            {lead.cadence && lead.cadence.attempt_count > 0 && (
              <div style={{ marginTop: 6 }}><CadenceLine cadence={lead.cadence} /></div>
            )}
            {isOutbound && (
              <div style={{ fontSize: 12, color: '#475569', marginTop: 6, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span><strong>{outcome?.touch_count ?? 0}</strong> contact{(outcome?.touch_count ?? 0) === 1 ? '' : 's'}</span>
                <span style={{ color: '#94a3b8' }}>
                  {outcome?.first_contacted_at
                    ? `first ${new Date(outcome.first_contacted_at).toLocaleDateString()}`
                    : 'not contacted yet'}
                </span>
                {outcome?.replied_at && <span style={{ color: '#166534' }}>replied</span>}
              </div>
            )}
            <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
              <select value={touchChannel}
                onChange={e => { setTouchChannel(e.target.value); resetTouchForm() }}
                style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                <option value="phone">Phone</option>
                <option value="email">Email</option>
              </select>
              {/* Structured disposition (T1.2): a fixed vocabulary, so the field 50 callers touch a
                  day can be counted. The prose note stays below. */}
              <select value={touchDisposition} onChange={e => pickDisposition(e.target.value)}
                style={{ flex: 1, minWidth: 140, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                <option value="">Disposition…</option>
                {dispositions.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </div>

            {/* T1.3: the disposition prefills the next action / callback; edit then save it with
                the call in one step. */}
            {dispHint && (dispHint.default_next_action != null || dispHint.reveal_callback || dispHint.offset_days != null) && (
              <div style={{ marginTop: 6, padding: 8, borderRadius: 8, background: '#f8fafc',
                border: '1px solid #eef2f7', display: 'flex', flexDirection: 'column', gap: 6 }}>
                <input value={naText} onChange={e => setNaText(e.target.value)} placeholder="Next action"
                  style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
                {dispHint.reveal_callback ? (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <input type="datetime-local" value={naLocal} onChange={e => setNaLocal(e.target.value)}
                      style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
                    <select value={naTz} onChange={e => setNaTz(e.target.value)}
                      style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
                      {US_TIMEZONES.some(z => z.value === naTz) ? null : <option value={naTz}>{naTz || 'zone'}</option>}
                      {US_TIMEZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
                    </select>
                    <BusinessHours tz={naTz} />
                  </div>
                ) : dispHint.offset_days != null ? (
                  <input type="date" value={naDue} onChange={e => setNaDue(e.target.value)}
                    style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, width: 170 }} />
                ) : null}
              </div>
            )}

            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <input value={touchNote} onChange={e => setTouchNote(e.target.value)}
                placeholder={touchChannel === 'phone' ? 'Call note (optional)' : 'Note (optional)'}
                style={{ flex: 1, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
              <button disabled={logTouch.isPending} onClick={() => logTouch.mutate()}
                style={{ padding: '6px 12px', borderRadius: 8, border: 'none', fontSize: 13,
                  fontWeight: 600, cursor: 'pointer', background: '#0369a1', color: '#fff',
                  display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <Phone size={13} /> Log {touchChannel === 'phone' ? 'call' : 'contact'}
              </button>
            </div>

            {/* One-click follow-through the disposition implies — never automatic. */}
            {(dispHint?.suggest_lost_reason || dispHint?.suggest_suppress) && (
              <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                {dispHint?.suggest_lost_reason && lead.stage !== 'lost' && (
                  <button onClick={() => patch.mutate({ stage: 'lost', lost_reason: dispHint.suggest_lost_reason })}
                    style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #fecaca',
                      background: '#fef2f2', color: '#b91c1c', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
                    Mark lost ({dispHint.suggest_lost_reason!.replace('_', ' ')})
                  </button>
                )}
                {dispHint?.suggest_suppress && !lead.suppressed_at && suppressValue && (
                  <button disabled={suppress.isPending} onClick={() => suppress.mutate()}
                    style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #fecaca',
                      background: '#fef2f2', color: '#b91c1c', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                      display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                    <Ban size={12} /> Suppress — do not contact
                  </button>
                )}
              </div>
            )}
            {logTouch.error instanceof Error && (
              <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{logTouch.error.message}</p>
            )}
            {suppress.error instanceof Error && (
              <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{suppress.error.message}</p>
            )}
          </div>

          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>Add note</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <input value={note} onChange={e => setNote(e.target.value)} placeholder="What happened?"
                style={{ flex: 1, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
              <button disabled={!note.trim() || addNote.isPending} onClick={() => addNote.mutate()}
                style={{ padding: '6px 12px', borderRadius: 8, border: 'none', fontSize: 13,
                  fontWeight: 600, cursor: 'pointer',
                  background: note.trim() ? '#0f172a' : '#e2e8f0',
                  color: note.trim() ? '#fff' : '#94a3b8' }}>Save</button>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
              Timeline{lead.activity_total > lead.activity.length ? ` (latest ${lead.activity.length} of ${lead.activity_total})` : ''}
            </div>
            {lead.activity.length === 0 ? (
              <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>Nothing yet.</p>
            ) : lead.activity.map(a => (
              <div key={a.id} style={{ marginTop: 8, fontSize: 12, borderLeft: '2px solid #e2e8f0', paddingLeft: 8 }}>
                <div style={{ color: '#94a3b8', fontSize: 11 }}>
                  {new Date(a.occurred_at).toLocaleString()} · {a.kind.replace('_', ' ')}
                  {a.from_stage && a.to_stage ? ` (${a.from_stage} → ${a.to_stage})` : ''}
                </div>
                {a.body && <div style={{ color: '#334155', marginTop: 2 }}>{a.body}</div>}
              </div>
            ))}
          </div>

          {patch.error instanceof Error && (
            <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 10 }}>{patch.error.message}</p>
          )}
        </>
      )}
    </div>
  )
}

// The prospect's local clock + whether it's inside calling hours (T1.4). Display-only.
function BusinessHours({ tz }: { tz: string | null | undefined }) {
  const c = localClock(tz)
  if (!c) return null
  return (
    <span style={{ fontSize: 11, display: 'inline-flex', gap: 4, alignItems: 'center',
      color: c.inHours ? '#166534' : '#b45309' }}>
      <Clock size={11} /> {c.time} · {c.inHours ? 'in business hours' : 'outside hours'}
    </span>
  )
}

// An ISO instant rendered as a datetime-local value ("YYYY-MM-DDTHH:MM") in a given zone, so the
// picker shows the callback as THEIR wall time regardless of the caller's own browser zone.
function toLocalInput(iso: string, tz: string): string {
  try {
    const p = new Intl.DateTimeFormat('en-US', {
      timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(new Date(iso))
    const g = (t: string) => p.find(x => x.type === t)?.value ?? ''
    const hour = g('hour') === '24' ? '00' : g('hour')  // en-US hour12:false emits '24' at midnight
    return `${g('year')}-${g('month')}-${g('day')}T${hour}:${g('minute')}`
  } catch {
    return ''
  }
}

// Next action (T1.4): a day-only follow-up, or a precise callback with the prospect's zone. A
// callback carries a business-hours hint so the caller knows if it's a sane time to dial there.
function NextAction({ lead, defaultTz, onSave }: {
  lead: LeadDetail
  defaultTz: string
  onSave: (body: Record<string, unknown>) => void
}) {
  const hasTime = !!lead.next_action_at
  const tz0 = lead.next_action_tz || defaultTz
  const [action, setAction] = useState(lead.next_action ?? '')
  const [mode, setMode] = useState<'day' | 'time'>(hasTime ? 'time' : 'day')
  const [due, setDue] = useState(lead.next_action_due?.slice(0, 10) ?? '')
  const [local, setLocal] = useState(hasTime ? toLocalInput(lead.next_action_at!, tz0) : '')
  const [tz, setTz] = useState(tz0)

  const save = () => {
    if (mode === 'time') {
      onSave({ next_action: action.trim() || null, next_action_local: local || null, next_action_tz: tz })
    } else {
      // Switching to a day-only follow-up clears any precise callback time.
      onSave({ next_action: action.trim() || null, next_action_due: due || null, next_action_local: null })
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
      <input value={action} onChange={e => setAction(e.target.value)} placeholder="e.g. Call back about audit"
        style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={mode} onChange={e => setMode(e.target.value as 'day' | 'time')}
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
          <option value="day">Due date</option>
          <option value="time">Callback time</option>
        </select>
        {mode === 'day' ? (
          <input type="date" value={due} onChange={e => setDue(e.target.value)}
            style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
        ) : (
          <>
            <input type="datetime-local" value={local} onChange={e => setLocal(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
            <select value={tz} onChange={e => setTz(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
              {US_TIMEZONES.some(z => z.value === tz) ? null : <option value={tz}>{tz}</option>}
              {US_TIMEZONES.map(z => <option key={z.value} value={z.value}>{z.label}</option>)}
            </select>
          </>
        )}
        <button onClick={save}
          style={{ padding: '6px 12px', borderRadius: 8, border: 'none', fontSize: 13, fontWeight: 600,
            background: '#0f172a', color: '#fff', cursor: 'pointer' }}>Save</button>
      </div>
      {mode === 'time' && <BusinessHours tz={tz} />}
    </div>
  )
}

// Link a manual/inbound lead to an already-scanned prospect (T2.5). Reuses the prospect search
// (GET /outreach/prospects?search=) — a pure link, no new scan and no spend; a business with no
// scan simply won't be found. On success the drawer refreshes and the hook/report/enrich appear.
function LinkProspect({ leadId, defaultQuery, onLinked }: {
  leadId: string; defaultQuery: string | null; onLinked: () => void
}) {
  const [q, setQ] = useState(defaultQuery ?? '')
  const [active, setActive] = useState(false)
  // Debounce the typed query so search fires once the caller pauses, not once per keystroke.
  const [term, setTerm] = useState((defaultQuery ?? '').trim())
  useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  const { data, isFetching } = useQuery<{ prospects: ProspectLite[] }>({
    queryKey: ['outreach-prospect-search', term],
    queryFn: () => api.get(`/outreach/prospects?search=${encodeURIComponent(term)}&limit=8`),
    enabled: active && term.length >= 2,
  })
  const link = useMutation({
    mutationFn: (prospectId: string) =>
      api.post(`/outreach/leads/${leadId}/link-prospect`, { prospect_id: prospectId }),
    onSuccess: () => { setActive(false); onLinked() },
  })
  const results = data?.prospects ?? []
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
        Link to a scanned prospect
      </div>
      <p style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
        This lead isn't tied to a scan, so it has no call hook, report or contact enrichment. If the
        business was already scanned, link it — no new scan, no spend.
      </p>
      {!active ? (
        <button onClick={() => setActive(true)}
          style={{ marginTop: 4, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0',
            background: '#fff', fontSize: 12, fontWeight: 600, color: '#0369a1', cursor: 'pointer' }}>
          Find a scanned prospect
        </button>
      ) : (
        <div style={{ marginTop: 6 }}>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search prospects by name…"
            autoFocus
            style={{ width: '100%', padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
          {term.length < 2 ? (
            <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>Type at least 2 characters.</p>
          ) : isFetching ? (
            <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>Searching…</p>
          ) : results.length === 0 ? (
            <p style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
              No scanned prospects match. Only a business a scan has covered can be linked.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
              {results.map(p => (
                <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8,
                  alignItems: 'center', padding: 8, border: '1px solid #e2e8f0', borderRadius: 8 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#0f172a', overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>
                      {[p.submarket_name, p.address, p.review_count != null ? `${p.review_count} reviews` : null]
                        .filter(Boolean).join(' · ')}
                    </div>
                  </div>
                  <button disabled={link.isPending} onClick={() => link.mutate(p.id)}
                    style={{ padding: '5px 10px', borderRadius: 8, border: 'none', fontSize: 12,
                      fontWeight: 600, background: '#0369a1', color: '#fff', cursor: 'pointer' }}>
                    Link
                  </button>
                </div>
              ))}
            </div>
          )}
          <button onClick={() => setActive(false)}
            style={{ marginTop: 6, padding: '4px 8px', borderRadius: 8, border: 'none', background: 'none',
              fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
            Cancel
          </button>
          {link.error instanceof Error && (
            <p style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{link.error.message}</p>
          )}
        </div>
      )}
    </div>
  )
}
