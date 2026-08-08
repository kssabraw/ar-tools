import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Crosshair, Loader2, Plus, X, AlertTriangle, Ban, Search, Phone,
} from 'lucide-react'
import { api } from '../lib/api'
import { Justification } from '../components/outreach/Justification'
import { ProspectReportButtons } from '../components/outreach/ProspectReport'

// ── Types (mirror the CRM half of routers/outreach.py) ───────────────────────
interface LeadStage { key: string; label: string; sort_order: number; is_terminal: boolean }
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
  stage_changed_at: string | null
  created_at: string
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
  prospect: { name: string; address: string | null; rating: number | null; review_count: number | null; submarket_name: string | null } | null
}

const LOST_REASONS = [
  'no_response', 'not_interested', 'no_budget', 'has_agency', 'timing',
  'went_elsewhere', 'disqualified', 'unreachable', 'opted_out',
]
const CREATE_SOURCES = ['manual', 'inbound_call', 'inbound_form', 'referral', 'partner']

function overdue(lead: Lead, terminal: Set<string>): boolean {
  return !!lead.next_action_due
    && !terminal.has(lead.stage)
    && new Date(lead.next_action_due) < new Date(new Date().toDateString())
}

// ── The page ─────────────────────────────────────────────────────────────────

export function OutreachLeads() {
  const queryClient = useQueryClient()
  const [openLead, setOpenLead] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [search, setSearch] = useState('')

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

  const { data: leadsData, isLoading } = useQuery<{ leads: Lead[]; total: number }>({
    queryKey: ['outreach-leads', search],
    queryFn: () =>
      api.get(`/outreach/leads?limit=200${search ? `&search=${encodeURIComponent(search)}` : ''}`),
  })
  const leads = leadsData?.leads ?? []
  const byStage = useMemo(() => {
    const map: Record<string, Lead[]> = {}
    for (const lead of leads) (map[lead.stage] ??= []).push(lead)
    return map
  }, [leads])

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

      {isLoading ? (
        <p style={{ fontSize: 13, color: '#64748b', marginTop: 16 }}>Loading…</p>
      ) : leads.length === 0 && !search ? (
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
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {adding && <AddLeadModal onClose={() => setAdding(false)} />}
      {openLead && (
        <LeadDrawer id={openLead} stages={stages} onClose={() => {
          setOpenLead(null)
          queryClient.invalidateQueries({ queryKey: ['outreach-leads'] })
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

function LeadDrawer({ id, stages, onClose }: { id: string; stages: LeadStage[]; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')
  const [lostReason, setLostReason] = useState('')
  const [pendingStage, setPendingStage] = useState<string | null>(null)
  const [showHook, setShowHook] = useState(false)

  const { data: lead } = useQuery<LeadDetail>({
    queryKey: ['outreach-lead', id],
    queryFn: () => api.get(`/outreach/leads/${id}`),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['outreach-lead', id] })
    queryClient.invalidateQueries({ queryKey: ['outreach-leads'] })
  }

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patch(`/outreach/leads/${id}`, body),
    onSuccess: () => { setPendingStage(null); setLostReason(''); refresh() },
  })
  const addNote = useMutation({
    mutationFn: () => api.post(`/outreach/leads/${id}/activities`, { kind: 'note', body: note }),
    onSuccess: () => { setNote(''); refresh() },
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

          <div style={{ marginTop: 12, fontSize: 12, color: '#475569', display: 'grid',
            gridTemplateColumns: 'auto 1fr', gap: '4px 10px' }}>
            <span style={{ color: '#94a3b8' }}>Source</span><span>{lead.source.replace('_', ' ')}</span>
            {lead.phone && <><span style={{ color: '#94a3b8' }}>Phone</span><span>{lead.phone}</span></>}
            {lead.email && <><span style={{ color: '#94a3b8' }}>Email</span><span>{lead.email}</span></>}
            {lead.website && <><span style={{ color: '#94a3b8' }}>Website</span>
              <a href={lead.website} target="_blank" rel="noreferrer">{lead.website}</a></>}
            {lead.prospect && <>
              <span style={{ color: '#94a3b8' }}>From scan</span>
              <span>{lead.prospect.submarket_name ?? ''} · {lead.prospect.review_count ?? 0} reviews
                {lead.prospect.rating ? ` · ${lead.prospect.rating}★` : ''}</span>
            </>}
          </div>

          {lead.prospect_id && (
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
            </div>
          )}

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
            <NextAction lead={lead} onSave={(next_action, next_action_due) =>
              patch.mutate({ next_action, next_action_due })} />
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

function NextAction({ lead, onSave }: {
  lead: LeadDetail
  onSave: (action: string | null, due: string | null) => void
}) {
  const [action, setAction] = useState(lead.next_action ?? '')
  const [due, setDue] = useState(lead.next_action_due?.slice(0, 10) ?? '')
  const dirty = action !== (lead.next_action ?? '') || due !== (lead.next_action_due?.slice(0, 10) ?? '')
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
      <input value={action} onChange={e => setAction(e.target.value)} placeholder="e.g. Call back about audit"
        style={{ flex: 1, minWidth: 140, padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
      <input type="date" value={due} onChange={e => setDue(e.target.value)}
        style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }} />
      {dirty && (
        <button onClick={() => onSave(action.trim() || null, due || null)}
          style={{ padding: '6px 12px', borderRadius: 8, border: 'none', fontSize: 13, fontWeight: 600,
            background: '#0f172a', color: '#fff', cursor: 'pointer' }}>Save</button>
      )}
    </div>
  )
}
