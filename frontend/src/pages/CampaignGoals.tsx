import { useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Clock, HelpCircle, Pencil, Plus, Target, Trash2, TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api'
import type { CampaignGoal, Client } from '../lib/types'

// Campaign goals — what success MEANS for this client. Status is computed
// server-side on every read (never stored), so this page is always honest:
// achieved / on-track / behind / overdue against the live metric.

const GOAL_TYPE_META: Record<string, { label: string; hint: string; unit: string }> = {
  keyword_position: { label: 'Keyword to position', hint: 'One keyword to position ≤ target (e.g. “roof repair” to top 3)', unit: 'position' },
  keywords_in_top: { label: 'Keywords in top N', hint: 'How many tracked keywords should sit at position ≤ N', unit: 'keywords' },
  organic_clicks: { label: 'Organic clicks / 30 days', hint: 'GSC clicks over a rolling 30-day window', unit: 'clicks' },
  organic_impressions: { label: 'Organic impressions / 30 days', hint: 'GSC impressions over a rolling 30-day window', unit: 'impressions' },
  ai_visibility: { label: 'AI visibility %', hint: 'Share of keyword×engine cells where AI assistants mention the brand', unit: '%' },
  maps_pack_presence: { label: 'Local-pack presence %', hint: 'Share of geo-grid pins in the top-3 map pack', unit: '%' },
  custom: { label: 'Custom (manual)', hint: 'A free-text goal SerMaStr sees but can’t auto-measure', unit: '' },
}

const STATUS_META: Record<string, { label: string; color: string; bg: string; icon: ReactNode }> = {
  achieved: { label: 'Achieved', color: '#15803d', bg: '#f0fdf4', icon: <CheckCircle2 size={13} /> },
  on_track: { label: 'On track', color: '#0369a1', bg: '#f0f9ff', icon: <TrendingUp size={13} /> },
  behind: { label: 'Behind', color: '#b45309', bg: '#fffbeb', icon: <AlertTriangle size={13} /> },
  overdue: { label: 'Overdue', color: '#b91c1c', bg: '#fef2f2', icon: <Clock size={13} /> },
  no_data: { label: 'No data', color: '#64748b', bg: '#f8fafc', icon: <HelpCircle size={13} /> },
  manual: { label: 'Manual', color: '#7c3aed', bg: '#f5f3ff', icon: <Target size={13} /> },
}

export function CampaignGoals() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data: goals, isLoading } = useQuery<CampaignGoal[]>({
    queryKey: ['campaign-goals', id],
    queryFn: () => api.get<CampaignGoal[]>(`/clients/${id}/goals`),
    enabled: Boolean(id),
  })

  const [showForm, setShowForm] = useState(false)
  const [goalType, setGoalType] = useState('keyword_position')
  const [label, setLabel] = useState('')
  const [keyword, setKeyword] = useState('')
  const [targetValue, setTargetValue] = useState('')
  const [targetPosition, setTargetPosition] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [notes, setNotes] = useState('')

  const resetForm = () => {
    setLabel(''); setKeyword(''); setTargetValue(''); setTargetPosition(''); setDueDate(''); setNotes('')
  }

  const autoLabel = (): string => {
    const meta = GOAL_TYPE_META[goalType]
    if (goalType === 'keyword_position' && keyword && targetValue) return `“${keyword}” to position ${targetValue}`
    if (goalType === 'keywords_in_top' && targetValue && targetPosition) return `${targetValue} keywords in top ${targetPosition}`
    if (targetValue) return `${meta.label}: ${targetValue}`
    return meta.label
  }

  const createGoal = useMutation({
    mutationFn: () =>
      api.post<CampaignGoal>(`/clients/${id}/goals`, {
        goal_type: goalType,
        label: (label.trim() || autoLabel()).slice(0, 200),
        keyword: goalType === 'keyword_position' ? keyword.trim() || null : null,
        target_value: goalType === 'custom' ? null : Number(targetValue),
        target_position: goalType === 'keywords_in_top' ? Number(targetPosition) : null,
        due_date: dueDate || null,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaign-goals', id] })
      resetForm()
      setShowForm(false)
    },
  })

  const deleteGoal = useMutation({
    mutationFn: (goalId: string) => api.delete(`/clients/${id}/goals/${goalId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['campaign-goals', id] }),
  })

  // ── Inline editing (target / due date / label / notes — baseline is kept) ──
  const [editingId, setEditingId] = useState<string | null>(null)
  const [eLabel, setELabel] = useState('')
  const [eTarget, setETarget] = useState('')
  const [ePosition, setEPosition] = useState('')
  const [eDue, setEDue] = useState('')
  const [eNotes, setENotes] = useState('')

  const startEdit = (g: CampaignGoal) => {
    setEditingId(g.id)
    setELabel(g.label)
    setETarget(g.target_value != null ? String(g.target_value) : '')
    setEPosition(g.target_position != null ? String(g.target_position) : '')
    setEDue(g.due_date ?? '')
    setENotes(g.notes ?? '')
  }

  const updateGoal = useMutation({
    mutationFn: (g: CampaignGoal) => {
      const body: Record<string, unknown> = {
        label: eLabel.trim() || g.label,
        due_date: eDue || null,
        notes: eNotes.trim() || null,
      }
      if (g.goal_type !== 'custom') body.target_value = Number(eTarget)
      if (g.goal_type === 'keywords_in_top') body.target_position = Number(ePosition)
      return api.put<CampaignGoal>(`/clients/${id}/goals/${g.id}`, body)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaign-goals', id] })
      setEditingId(null)
    },
  })

  const canSubmit =
    goalType === 'custom'
      ? Boolean(label.trim() || notes.trim())
      : Boolean(targetValue) &&
        (goalType !== 'keyword_position' || Boolean(keyword.trim())) &&
        (goalType !== 'keywords_in_top' || Boolean(targetPosition))

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 0 4px' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Campaign Goals</h1>
        <button style={primaryBtn} onClick={() => setShowForm((s) => !s)}>
          <Plus size={14} /> Add goal
        </button>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        What success means for this campaign. SerMaStr judges every review, Slack answer and
        weekly digest against these — status is recomputed from live data on every view.
      </p>

      {id && <LeadoffActualsCard clientId={id} />}

      {showForm && (
        <section style={card}>
          <h2 style={cardTitle}>New goal</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <label style={fieldLabel}>Goal type</label>
              <select style={input} value={goalType} onChange={(e) => setGoalType(e.target.value)}>
                {Object.entries(GOAL_TYPE_META).map(([k, m]) => (
                  <option key={k} value={k}>{m.label}</option>
                ))}
              </select>
              <p style={{ fontSize: 11.5, color: '#94a3b8', margin: '4px 0 0' }}>{GOAL_TYPE_META[goalType].hint}</p>
            </div>
            <div>
              <label style={fieldLabel}>Label (optional)</label>
              <input style={input} placeholder={autoLabel()} value={label} onChange={(e) => setLabel(e.target.value)} />
            </div>
            {goalType === 'keyword_position' && (
              <div>
                <label style={fieldLabel}>Keyword (as tracked in the rank tracker)</label>
                <input style={input} placeholder="e.g. roof repair vancouver wa" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
              </div>
            )}
            {goalType !== 'custom' && (
              <div>
                <label style={fieldLabel}>
                  Target {GOAL_TYPE_META[goalType].unit && `(${GOAL_TYPE_META[goalType].unit})`}
                </label>
                <input style={input} type="number" placeholder={goalType === 'keyword_position' ? '3' : '800'} value={targetValue} onChange={(e) => setTargetValue(e.target.value)} />
              </div>
            )}
            {goalType === 'keywords_in_top' && (
              <div>
                <label style={fieldLabel}>Top N (the position bar)</label>
                <input style={input} type="number" placeholder="3" value={targetPosition} onChange={(e) => setTargetPosition(e.target.value)} />
              </div>
            )}
            <div>
              <label style={fieldLabel}>Due date (optional — enables on-pace tracking)</label>
              <input style={input} type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={fieldLabel}>Notes (optional)</label>
              <input style={input} placeholder="Context for the team & SerMaStr" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button style={primaryBtn} disabled={!canSubmit || createGoal.isPending} onClick={() => createGoal.mutate()}>
              {createGoal.isPending ? 'Saving…' : 'Create goal'}
            </button>
            <button style={ghostBtn} onClick={() => setShowForm(false)}>Cancel</button>
          </div>
          {createGoal.isError && (
            <p style={{ color: '#dc2626', fontSize: 12, margin: '8px 0 0' }}>
              Couldn’t save: {(createGoal.error as Error).message}
            </p>
          )}
        </section>
      )}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : !goals?.length ? (
        <div style={emptyBox}>
          No goals yet. Add the campaign’s targets — “roof repair to top 3 by October”, “800
          organic clicks a month” — and SerMaStr will report on-track / behind against them.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {goals.map((g) => {
            const meta = STATUS_META[g.status ?? 'no_data'] ?? STATUS_META.no_data
            const pct = g.progress_pct
            if (editingId === g.id) {
              const canSave =
                (g.goal_type === 'custom' || (eTarget !== '' && !Number.isNaN(Number(eTarget)))) &&
                (g.goal_type !== 'keywords_in_top' || (ePosition !== '' && !Number.isNaN(Number(ePosition))))
              return (
                <section key={g.id} style={{ ...card, borderColor: '#c7d2fe' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <div style={{ gridColumn: '1 / -1' }}>
                      <label style={fieldLabel}>Label</label>
                      <input style={input} value={eLabel} onChange={(e) => setELabel(e.target.value)} />
                    </div>
                    {g.goal_type !== 'custom' && (
                      <div>
                        <label style={fieldLabel}>Target {GOAL_TYPE_META[g.goal_type]?.unit && `(${GOAL_TYPE_META[g.goal_type].unit})`}</label>
                        <input style={input} type="number" value={eTarget} onChange={(e) => setETarget(e.target.value)} />
                      </div>
                    )}
                    {g.goal_type === 'keywords_in_top' && (
                      <div>
                        <label style={fieldLabel}>Top N (the position bar)</label>
                        <input style={input} type="number" value={ePosition} onChange={(e) => setEPosition(e.target.value)} />
                      </div>
                    )}
                    <div>
                      <label style={fieldLabel}>Due date (blank = no deadline)</label>
                      <input style={input} type="date" value={eDue} onChange={(e) => setEDue(e.target.value)} />
                    </div>
                    <div style={{ gridColumn: '1 / -1' }}>
                      <label style={fieldLabel}>Notes</label>
                      <input style={input} value={eNotes} onChange={(e) => setENotes(e.target.value)} />
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                    <button style={primaryBtn} disabled={!canSave || updateGoal.isPending} onClick={() => updateGoal.mutate(g)}>
                      {updateGoal.isPending ? 'Saving…' : 'Save changes'}
                    </button>
                    <button style={ghostBtn} onClick={() => setEditingId(null)}>Cancel</button>
                    <span style={{ fontSize: 11.5, color: '#94a3b8' }}>
                      The original baseline ({g.baseline_value != null ? fmt(g.baseline_value) : '—'}) is kept — progress keeps measuring from where the campaign started.
                    </span>
                  </div>
                  {updateGoal.isError && (
                    <p style={{ color: '#dc2626', fontSize: 12, margin: '8px 0 0' }}>
                      Couldn’t save: {(updateGoal.error as Error).message}
                    </p>
                  )}
                </section>
              )
            }
            return (
              <section key={g.id} style={card}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{g.label}</span>
                      <span style={{ ...chip, color: meta.color, background: meta.bg }}>{meta.icon} {meta.label}</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 4 }}>
                      {g.current_value != null && <>Now <strong>{fmt(g.current_value)}</strong></>}
                      {g.target_value != null && <> · target <strong>{fmt(g.target_value)}</strong></>}
                      {g.baseline_value != null && <> · started at {fmt(g.baseline_value)}</>}
                      {g.due_date && <> · due {g.due_date}</>}
                    </div>
                    {g.notes && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{g.notes}</div>}
                  </div>
                  <div style={{ display: 'flex', gap: 2 }}>
                    <button style={iconBtn} title="Edit goal" onClick={() => startEdit(g)}>
                      <Pencil size={15} />
                    </button>
                    <button
                      style={iconBtn}
                      title="Delete goal"
                      onClick={() => { if (window.confirm(`Delete goal “${g.label}”?`)) deleteGoal.mutate(g.id) }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
                {pct != null && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ height: 6, borderRadius: 999, background: '#f1f5f9', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.min(100, pct)}%`, borderRadius: 999, background: meta.color, transition: 'width .3s' }} />
                    </div>
                    <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 4 }}>
                      {pct}% of the way{g.elapsed_pct != null && <> · {g.elapsed_pct}% of the time used</>}
                    </div>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

function fmt(v: number): string {
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b',
  textDecoration: 'none', marginBottom: 14,
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff', marginBottom: 4 }
const cardTitle: React.CSSProperties = { fontSize: 14, fontWeight: 600, color: '#0f172a', margin: '0 0 10px' }
const fieldLabel: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '7px 10px', fontSize: 13,
  border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#0f172a',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#fff', background: '#4f46e5', border: 'none', borderRadius: 8, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#475569', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 6,
  color: '#94a3b8', background: 'transparent', border: 'none', cursor: 'pointer',
}
const chip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 700,
  padding: '2px 8px', borderRadius: 999,
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}

// LeadOff calibration Phase 0 (leadoff-calibration-plan-v1_0.md §3.3, owner
// ruling: manual lead entry lives here). Renders only for clients created
// through the market handoff; entered counts become append-only outcome
// checks — the model's actuals, never conflated with automatic sources.
interface LeadoffPrediction {
  id: string
  category: string
  city_name: string
  state_code: string
  as_of: string | null
  predicted: { exp_leads_mo?: number | null; exp_val?: number | null }
}

function LeadoffActualsCard({ clientId }: { clientId: string }) {
  const [leads, setLeads] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { data: prediction } = useQuery<LeadoffPrediction>({
    queryKey: ['leadoff-prediction', clientId],
    queryFn: () => api.get<LeadoffPrediction>(`/clients/${clientId}/leadoff-prediction`),
    retry: false, // 404 = not a handoff client; card simply doesn't render
  })
  if (!prediction) return null

  const submit = async () => {
    const n = Number(leads)
    if (!leads.trim() || Number.isNaN(n) || n < 0 || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.post(`/leadoff/predictions/${prediction.id}/leads`, { actual_leads_mo: n })
      setSaved(`Recorded ${n} leads/mo — thanks, the model learns from this.`)
      setLeads('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'save_failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section style={{ ...card, marginBottom: 16, background: '#f8fafc' }}>
      <h2 style={cardTitle}>
        LeadOff actuals — {prediction.category}, {prediction.city_name}, {prediction.state_code}
      </h2>
      <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 10px' }}>
        LeadOff predicted <b>{prediction.predicted?.exp_leads_mo ?? '—'} leads/mo</b>
        {prediction.predicted?.exp_val != null && <> (~${Math.round(prediction.predicted.exp_val).toLocaleString()}/mo expected)</>}
        {prediction.as_of && <> from the {prediction.as_of} scan</>}. Enter last month's actual
        lead count — it's the one outcome the app can't observe on its own.
      </p>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input style={{ ...input, width: 140 }} type="number" min={0} placeholder="leads last month"
          value={leads} onChange={(e) => { setLeads(e.target.value); setSaved(null) }} />
        <button style={primaryBtn} disabled={busy || !leads.trim()} onClick={submit}>
          Record
        </button>
        {saved && <span style={{ fontSize: 12, color: '#177245' }}>{saved}</span>}
        {error && <span style={{ fontSize: 12, color: '#b91c1c' }}>{error}</span>}
      </div>
    </section>
  )
}
