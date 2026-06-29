import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sparkles, RefreshCw, ArrowRight, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// ── Types (mirror models/engagement.py) ─────────────────────────────────────
interface Engagement {
  id: string
  status: string
  autonomy_level: string
  current_plan_id: string | null
}
interface StrategyAction {
  id: string
  module: string
  category: string
  kind: string | null
  title: string
  rationale: string | null
  target: Record<string, unknown> | null
  priority: number
  execution_mode: string
  assignee_role: string | null
  status: string
  deep_link: string | null
}
interface StrategyPlan {
  id: string
  status: string
  summary: { headline?: string; counts?: Record<string, number>; severity?: string } | null
  created_at: string | null
  actions: StrategyAction[]
}

const MODULES: { key: string; label: string }[] = [
  { key: 'organic', label: 'Organic' },
  { key: 'maps', label: 'Maps' },
  { key: 'ai_visibility', label: 'LLM Visibility' },
  { key: 'cross', label: 'Cross-channel' },
]

export function StrategyPlan() {
  const { id: clientId } = useParams<{ id: string }>()
  const qc = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })
  const { data: engagement } = useQuery<Engagement | null>({
    queryKey: ['engagement', clientId],
    queryFn: () => api.get<Engagement | null>(`/clients/${clientId}/engagement`),
    enabled: Boolean(clientId),
  })
  const eid = engagement?.id
  const { data: plan, isLoading: planLoading } = useQuery<StrategyPlan | null>({
    queryKey: ['strategy-plan', eid],
    queryFn: () => api.get<StrategyPlan | null>(`/engagements/${eid}/plan`),
    enabled: Boolean(eid),
  })

  const startEngagement = useMutation({
    mutationFn: () => api.post<Engagement>(`/clients/${clientId}/engagements`, { autonomy_level: 'assisted' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['engagement', clientId] }),
  })
  const refresh = useMutation({
    mutationFn: () => api.post<StrategyPlan>(`/engagements/${eid}/plan/refresh`, {}),
    onSuccess: (p) => qc.setQueryData(['strategy-plan', eid], p),
  })

  return (
    <div style={{ maxWidth: 820, margin: '0 auto', padding: '24px 20px' }}>
      <Link to={`/clients/${clientId}`} style={backLinkStyle}>
        <ArrowLeft size={16} /> Back to workspace
      </Link>

      <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, margin: '12px 0 20px' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sparkles size={20} color="#6366f1" /> Strategy
          </h1>
          <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
            One prioritized, cross-module plan for <strong>{client?.name ?? 'this client'}</strong> —
            organic, Maps & LLM. Recommend-only.
          </p>
        </div>
        {engagement && (
          <button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            style={{ ...buttonStyle, background: '#fff', color: '#0f172a', border: '1px solid #e2e8f0' }}
          >
            {refresh.isPending ? <Loader2 size={15} /> : <RefreshCw size={15} />}
            {refresh.isPending ? 'Refreshing…' : 'Refresh plan'}
          </button>
        )}
      </header>

      {!engagement && (
        <div style={{ ...box, textAlign: 'center', padding: '32px 20px' }}>
          <p style={{ fontSize: 14, color: '#475569', margin: '0 0 16px' }}>
            No active engagement yet. Start one to generate this client's strategy plan.
          </p>
          <button onClick={() => startEngagement.mutate()} disabled={startEngagement.isPending} style={buttonStyle}>
            {startEngagement.isPending ? <Loader2 size={15} /> : <Sparkles size={15} />}
            Start engagement
          </button>
        </div>
      )}

      {engagement && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 18, fontSize: 12 }}>
            <span style={chip}>stage: <strong>{engagement.status}</strong></span>
            <span style={chip}>autonomy: <strong>{engagement.autonomy_level}</strong></span>
            {plan?.summary?.headline && <span style={{ ...chip, color: '#6366f1' }}>{plan.summary.headline}</span>}
          </div>

          {planLoading && <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading plan…</div>}

          {!planLoading && (!plan || plan.actions.length === 0) && (
            <div style={{ ...box, color: '#64748b', fontSize: 14 }}>
              No recommendations yet. Add keywords and run the trackers, then{' '}
              <button onClick={() => refresh.mutate()} style={linkButton}>refresh the plan</button>.
            </div>
          )}

          {plan && plan.actions.length > 0 && MODULES.map(m => {
            const actions = plan.actions.filter(a => a.module === m.key)
            if (actions.length === 0) return null
            return (
              <section key={m.key} style={{ marginBottom: 22 }}>
                <h2 style={sectionTitle}>{m.label} <span style={{ color: '#94a3b8', fontWeight: 600 }}>· {actions.length}</span></h2>
                <div style={{ display: 'grid', gap: 10 }}>
                  {actions.map(a => <ActionRow key={a.id} a={a} />)}
                </div>
              </section>
            )
          })}
        </>
      )}
    </div>
  )
}

function ActionRow({ a }: { a: StrategyAction }) {
  return (
    <div style={box}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{a.title}</div>
          {a.rationale && <div style={{ fontSize: 13, color: '#64748b', marginTop: 3 }}>{a.rationale}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <span style={tag}>{a.execution_mode}</span>
            {a.assignee_role && <span style={tag}>{a.assignee_role.replace('_', ' ')}</span>}
            {a.kind && <span style={tag}>{a.kind}</span>}
          </div>
        </div>
        {a.deep_link && (
          <Link to={`/${a.deep_link}`} style={{ ...openLink, flexShrink: 0 }}>
            Open <ArrowRight size={14} />
          </Link>
        )}
      </div>
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none' }
const buttonStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '9px 16px', borderRadius: 10, border: 'none', background: '#6366f1', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' }
const box: React.CSSProperties = { padding: '14px 16px', borderRadius: 12, border: '1px solid #e2e8f0', background: '#fff' }
const chip: React.CSSProperties = { padding: '4px 10px', borderRadius: 999, background: '#f1f5f9', color: '#475569' }
const sectionTitle: React.CSSProperties = { fontSize: 12, fontWeight: 700, color: '#0f172a', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 10px' }
const tag: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '2px 8px' }
const openLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, fontWeight: 600, color: '#6366f1', textDecoration: 'none' }
const linkButton: React.CSSProperties = { background: 'none', border: 'none', color: '#6366f1', fontWeight: 600, cursor: 'pointer', padding: 0, fontSize: 14 }
