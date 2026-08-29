import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api'
import type {
  PaceDispositionResult,
  PaceIntervention,
  PaceInterventionsResponse,
} from '../../lib/types'

// The PACE Proactive Interventions approvals panel (docs/modules/
// pace-proactive-interventions-plan-v1_0.md). PACE surfaces systemic delivery
// problems it spotted (severe overload, duplicate-name collisions, untriaged /
// overdue / slip clusters) with a concrete fix plan; the PM dispositions each
// four ways — Approve (PACE executes the bulk fix), Deny, Defer (to a date), or
// Approve-with-conditions (a free-text constraint PACE re-plans against). It
// renders nothing when there's nothing to decide, so the page stays clean.

type Disposition = 'approve' | 'deny' | 'defer' | 'conditions'

const SEV: Record<string, { dot: string; label: string; bg: string; fg: string }> = {
  critical: { dot: '#dc2626', label: 'Critical', bg: '#fef2f2', fg: '#b91c1c' },
  warning: { dot: '#f59e0b', label: 'Attention', bg: '#fffbeb', fg: '#b45309' },
  info: { dot: '#0d9488', label: 'Info', bg: '#f0fdfa', fg: '#0f766e' },
}

function tomorrowISO(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return d.toISOString().slice(0, 10)
}

export function InterventionsPanel() {
  const [items, setItems] = useState<PaceIntervention[]>([])
  const [enabled, setEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await api.get<PaceInterventionsResponse>('/pace/interventions?status=open')
      setItems(res.interventions || [])
      setEnabled(res.enabled)
    } catch (e) {
      // 503 pace_not_enabled just means the panel has nothing to show — stay quiet.
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('pace_not_enabled')) setItems([])
      else setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) return null
  if (error) {
    return (
      <div style={panelWrap}>
        <div style={{ ...card, color: '#b91c1c', fontSize: 13 }}>Couldn't load interventions: {error}</div>
      </div>
    )
  }
  if (items.length === 0) {
    if (!enabled) return null
    return null // nothing to decide — keep the page clean
  }

  return (
    <div style={panelWrap}>
      <div style={headerRow}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
          Needs your decision · {items.length}
        </div>
        <button style={ghostBtn} onClick={() => void load()}>Refresh</button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {items.map((it) => (
          <InterventionCard key={it.id} item={it} onChanged={load} />
        ))}
      </div>
    </div>
  )
}

function InterventionCard({ item, onChanged }: { item: PaceIntervention; onChanged: () => Promise<void> | void }) {
  const [busy, setBusy] = useState(false)
  // Expanded by default — the itemized rundown of exactly what PACE will do is
  // shown up front, so the PM sees the plan before Approve, not after a click.
  const [showActions, setShowActions] = useState(true)
  const [mode, setMode] = useState<Disposition | null>(null)
  const [deferDate, setDeferDate] = useState(tomorrowISO())
  const [conditions, setConditions] = useState('')
  const [note, setNote] = useState('')
  const [result, setResult] = useState<string | null>(null)

  const sev = SEV[item.severity] || SEV.warning
  const actions = item.plan?.actions || []
  const overflow = item.plan?.overflow || 0

  const dispose = async (disposition: Disposition) => {
    setBusy(true)
    setResult(null)
    try {
      const body: Record<string, unknown> = { disposition }
      if (disposition === 'defer') body.until = deferDate
      if (disposition === 'conditions') body.conditions = conditions
      if (disposition === 'deny') body.note = note || undefined
      const res = await api.post<PaceDispositionResult>(
        `/pace/interventions/${item.id}/disposition`,
        body,
      )
      setResult(res.message)
      // A terminal disposition removes it from the open list; refresh after a beat
      // so the PM sees the outcome message first.
      setTimeout(() => void onChanged(), 1200)
    } catch (e) {
      setResult(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div style={{ ...card, borderLeft: `3px solid ${sev.dot}` }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ ...sevChip, background: sev.bg, color: sev.fg }}>{sev.label}</span>
        <span style={{ fontWeight: 650, fontSize: 14, color: '#0f172a' }}>{item.title}</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#94a3b8' }}>{item.kind.replace(/_/g, ' ')}</span>
      </div>
      <div style={{ fontSize: 13, color: '#475569', marginTop: 6, lineHeight: 1.5 }}>{item.problem}</div>

      {actions.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button style={linkBtn} onClick={() => setShowActions((v) => !v)}>
            {showActions ? 'Hide' : 'Show'} {actions.length} proposed fix{actions.length !== 1 ? 'es' : ''}
            {overflow ? ` (+${overflow} more held)` : ''}
          </button>
          {showActions && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, color: '#475569', fontSize: 12.5, lineHeight: 1.6 }}>
              {actions.map((a, i) => (
                <li key={i}>
                  {a.reason || a.action}
                  {a.client_name ? <span style={{ color: '#94a3b8' }}> — {a.client_name}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {result ? (
        <div style={{ marginTop: 10, fontSize: 12.5, color: '#0f766e', background: '#f0fdfa', border: '1px solid #ccfbf1', borderRadius: 8, padding: '8px 10px' }}>
          {result}
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
            <button style={primaryBtn(busy)} disabled={busy} onClick={() => void dispose('approve')}>
              {actions.length ? 'Approve & run' : 'Acknowledge'}
            </button>
            <button style={secondaryBtn} disabled={busy} onClick={() => setMode(mode === 'conditions' ? null : 'conditions')}>
              Approve with conditions…
            </button>
            <button style={secondaryBtn} disabled={busy} onClick={() => setMode(mode === 'defer' ? null : 'defer')}>
              Defer…
            </button>
            <button style={dangerBtn} disabled={busy} onClick={() => setMode(mode === 'deny' ? null : 'deny')}>
              Deny…
            </button>
          </div>

          {mode === 'conditions' && (
            <div style={subForm}>
              <textarea
                style={textArea}
                placeholder="e.g. only reassign to Ivy · cap at 3 moves · skip Acme"
                value={conditions}
                onChange={(e) => setConditions(e.target.value)}
                rows={2}
              />
              <button style={primaryBtn(busy || !conditions.trim())} disabled={busy || !conditions.trim()} onClick={() => void dispose('conditions')}>
                Apply & run
              </button>
            </div>
          )}
          {mode === 'defer' && (
            <div style={subForm}>
              <input type="date" style={dateInput} min={tomorrowISO()} value={deferDate} onChange={(e) => setDeferDate(e.target.value)} />
              <button style={primaryBtn(busy)} disabled={busy} onClick={() => void dispose('defer')}>Defer to this date</button>
            </div>
          )}
          {mode === 'deny' && (
            <div style={subForm}>
              <input style={dateInput} placeholder="Optional reason" value={note} onChange={(e) => setNote(e.target.value)} />
              <button style={dangerBtn} disabled={busy} onClick={() => void dispose('deny')}>Deny</button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// --- styles (teal PACE palette, matching PaceChat) ---
const panelWrap: React.CSSProperties = { marginBottom: 16 }
const headerRow: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '14px 16px' }
const sevChip: React.CSSProperties = { fontSize: 10.5, fontWeight: 700, letterSpacing: '0.03em', textTransform: 'uppercase', borderRadius: 6, padding: '2px 7px' }
const linkBtn: React.CSSProperties = { border: 'none', background: 'transparent', color: '#0d9488', fontSize: 12.5, fontWeight: 600, cursor: 'pointer', padding: 0 }
const ghostBtn: React.CSSProperties = { border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', borderRadius: 8, fontSize: 12, padding: '4px 10px', cursor: 'pointer' }
const primaryBtn = (disabled: boolean): React.CSSProperties => ({ background: disabled ? '#99f6e4' : '#0d9488', color: '#fff', border: 'none', borderRadius: 8, fontSize: 12.5, fontWeight: 600, padding: '7px 12px', cursor: disabled ? 'default' : 'pointer' })
const secondaryBtn: React.CSSProperties = { background: '#f8fafc', color: '#334155', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12.5, fontWeight: 600, padding: '7px 12px', cursor: 'pointer' }
const dangerBtn: React.CSSProperties = { background: '#fff', color: '#b91c1c', border: '1px solid #fecaca', borderRadius: 8, fontSize: 12.5, fontWeight: 600, padding: '7px 12px', cursor: 'pointer' }
const subForm: React.CSSProperties = { display: 'flex', gap: 8, marginTop: 10, alignItems: 'flex-start', flexWrap: 'wrap' }
const textArea: React.CSSProperties = { flex: 1, minWidth: 220, fontSize: 13, color: '#0f172a', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', outline: 'none', resize: 'vertical', fontFamily: 'inherit' }
const dateInput: React.CSSProperties = { fontSize: 13, color: '#0f172a', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 10px', outline: 'none' }
