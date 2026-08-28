import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, ChevronDown } from 'lucide-react'
import { api } from '../lib/api'
import type {
  Intervention,
  InterventionList,
  InterventionTally,
  InterventionVerdict,
} from '../lib/types'

// Intervention-outcome loop — the "Intervention Outcomes" card on the client
// workspace, under the Strategist Review. Report-only evidence of whether past
// goal-linked link-building / reoptimization work actually moved the metric it
// targeted, judged worked/partial/no_effect at its 6-week mark
// (services/interventions.py). Renders nothing while the feature flag is off and
// nothing has ever been tracked, so quiet clients stay clean.
export function InterventionOutcomes({ clientId }: { clientId: string }) {
  const [expanded, setExpanded] = useState(false)

  const { data } = useQuery<InterventionList>({
    queryKey: ['interventions', clientId],
    queryFn: () => api.get<InterventionList>(`/clients/${clientId}/interventions`),
    enabled: Boolean(clientId),
    retry: false,
  })

  if (!data) return null
  const rows = data.interventions ?? []
  // Feature dark (flag off) and nothing ever tracked → invisible.
  if (!data.enabled && rows.length === 0) return null

  const byTactic = data.effectiveness?.by_tactic ?? {}
  const tactics = Object.keys(byTactic).sort()
  const overall = data.effectiveness?.overall

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Activity size={18} style={{ color: '#0891b2', flexShrink: 0 }} />
        <span style={{ fontWeight: 700, fontSize: 15, color: '#0f172a' }}>Intervention Outcomes</span>
        <span style={smallMuted}>Did link-building / reoptimization move the metric it targeted?</span>
      </div>

      {rows.length === 0 ? (
        <div style={smallMuted}>
          No interventions tracked yet — approve a goal-linked link-building or reoptimization
          proposal (or complete its task) to start measuring.
        </div>
      ) : (
        <>
          {tactics.length === 0 ? (
            <div style={smallMuted}>Interventions registered — none measured yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {tactics.map((t) => (
                <TacticRollup key={t} tactic={t} tally={byTactic[t]} />
              ))}
            </div>
          )}

          {overall && overall.total > 1 && (
            <div style={smallMuted}>
              Overall: {overall.worked} worked · {overall.partial} partial · {overall.no_effect} no
              effect · {overall.pending} pending ({overall.total} total).
            </div>
          )}

          <button style={collapseToggle} onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            <ChevronDown
              size={14}
              style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform .15s', flexShrink: 0 }}
            />
            <span>{expanded ? 'Hide details' : `Show all ${rows.length} intervention${rows.length !== 1 ? 's' : ''}`}</span>
          </button>

          {expanded && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {rows.map((iv) => (
                <InterventionRow key={iv.id} iv={iv} />
              ))}
            </div>
          )}

          <div style={noteLine}>
            Report-only — this measures what has a track record; it doesn’t yet steer proposals.
          </div>
        </>
      )}
    </div>
  )
}

function TacticRollup({ tactic, tally }: { tactic: string; tally: InterventionTally }) {
  const segments: Array<[keyof InterventionTally, string]> = [
    ['worked', '#16a34a'],
    ['partial', '#d97706'],
    ['no_effect', '#94a3b8'],
    ['pending', '#e2e8f0'],
  ]
  const total = tally.total || 1
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{tacticLabel(tactic)}</span>
        <span style={smallMuted}>
          {tally.worked}/{tally.total} worked
          {tally.pending ? ` · ${tally.pending} pending` : ''}
        </span>
      </div>
      <div style={{ display: 'flex', height: 8, borderRadius: 999, overflow: 'hidden', background: '#f1f5f9' }}>
        {segments.map(([key, color]) =>
          tally[key] > 0 ? (
            <div
              key={key}
              style={{ width: `${(tally[key] / total) * 100}%`, background: color }}
              title={`${tally[key]} ${verdictLabel(key)}`}
            />
          ) : null,
        )}
      </div>
    </div>
  )
}

function InterventionRow({ iv }: { iv: Intervention }) {
  const anchor = iv.target?.keyword || iv.target?.page_url || '—'
  const baseline = iv.baseline?.value
  const metric = iv.baseline?.metric
  return (
    <div style={ivRow}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={metaPill}>{tacticLabel(iv.tactic_type)}</span>
          <span style={{ fontSize: 13, color: '#0f172a', fontWeight: 600, overflowWrap: 'anywhere' }}>{anchor}</span>
        </div>
        <div style={{ ...smallMuted, marginTop: 2 }}>
          {baseline != null ? `baseline ${formatMetric(metric, baseline)}` : 'baseline unmeasured'}
          {iv.applied_at ? ` · started ${new Date(iv.applied_at).toLocaleDateString()}` : ''}
        </div>
      </div>
      <VerdictBadge iv={iv} />
    </div>
  )
}

function VerdictBadge({ iv }: { iv: Intervention }) {
  if (iv.verdict) {
    const [color, bg] = verdictColors(iv.verdict)
    return <span style={{ ...badge, color, background: bg }}>{verdictLabel(iv.verdict)}</span>
  }
  // Still open: show the next check, or how long since the last one.
  const next = iv.next_check_at ? daysUntil(iv.next_check_at) : null
  const label =
    next == null ? 'pending' : next <= 0 ? 'check due' : `pending · ~${next}d`
  return <span style={{ ...badge, color: '#64748b', background: '#f1f5f9' }}>{label}</span>
}

// ── labels / formatting ────────────────────────────────────────────────────
function tacticLabel(tactic: string): string {
  switch (tactic) {
    case 'link_building': return 'Link building'
    case 'reoptimization': return 'Reoptimization'
    default: return tactic.replace(/_/g, ' ')
  }
}

function verdictLabel(v: keyof InterventionTally | InterventionVerdict): string {
  switch (v) {
    case 'worked': return 'worked'
    case 'partial': return 'partial'
    case 'no_effect': return 'no effect'
    case 'pending': return 'pending'
    default: return String(v)
  }
}

function verdictColors(v: InterventionVerdict): [string, string] {
  switch (v) {
    case 'worked': return ['#16a34a', '#f0fdf4']
    case 'partial': return ['#b45309', '#fffbeb']
    case 'no_effect': return ['#64748b', '#f8fafc']
  }
}

function formatMetric(metric: string | null | undefined, value: number): string {
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 10) / 10
  if (metric === 'keyword_position') return `rank ${rounded}`
  return String(rounded)
}

function daysUntil(iso: string): number {
  const ms = new Date(iso).getTime() - Date.now()
  return Math.ceil(ms / (1000 * 60 * 60 * 24))
}

const card: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 16px',
  border: '1px solid #cffafe', borderRadius: 10, background: '#fff', marginBottom: 20,
}
const smallMuted: React.CSSProperties = { fontSize: 12, color: '#94a3b8' }
const noteLine: React.CSSProperties = { fontSize: 11, color: '#94a3b8', fontStyle: 'italic' }
const ivRow: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', gap: 10,
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', background: '#fff',
}
const metaPill: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: '#0e7490', background: '#ecfeff',
  borderRadius: 999, padding: '2px 8px', flexShrink: 0,
}
const badge: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, borderRadius: 999, padding: '2px 8px', flexShrink: 0,
  textTransform: 'uppercase', letterSpacing: '0.03em',
}
const collapseToggle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
  fontSize: 12.5, fontWeight: 600, color: '#475569', background: 'transparent',
  border: 'none', padding: 0, cursor: 'pointer', textAlign: 'left',
}
