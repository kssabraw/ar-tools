import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sparkles, RefreshCw, ArrowRight, Loader2, Check } from 'lucide-react'
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
interface AuditRun {
  id: string
  kind: string
  status: string
  score: number | null
  result: Record<string, any> | null
  created_at: string | null
}

const AUDIT_KINDS: { key: string; label: string }[] = [
  { key: 'site_technical', label: 'Site / technical' },
  { key: 'backlink_gap', label: 'Backlink gap' },
  { key: 'local_citation', label: 'Local citations' },
]

function auditSummary(a: AuditRun): string {
  const r = a.result || {}
  if (a.status !== 'complete') return a.status
  if (a.kind === 'site_technical') return `score ${r.score ?? '—'} · ${r.issue_count ?? 0} issues · ${r.pages_scanned ?? 0} pages`
  if (a.kind === 'backlink_gap') return `${r.gap_count ?? 0} link prospects · ${r.competitors_analyzed ?? 0} competitors`
  if (a.kind === 'local_citation') return `${r.missing_count ?? 0} missing · ${r.listed_count ?? 0} listed`
  return 'complete'
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

  const { data: audits } = useQuery<AuditRun[]>({
    queryKey: ['audits', eid],
    queryFn: () => api.get<AuditRun[]>(`/engagements/${eid}/audits`),
    enabled: Boolean(eid),
    // Poll while anything is in flight so completed results appear without a manual refresh.
    refetchInterval: (q) =>
      (q.state.data ?? []).some(a => a.status === 'pending' || a.status === 'running') ? 4000 : false,
  })
  const runAudits = useMutation({
    mutationFn: async () => {
      await Promise.all([
        api.post(`/engagements/${eid}/audits/site`, {}),
        api.post(`/engagements/${eid}/audits/backlinks`, {}),
        api.post(`/engagements/${eid}/audits/citations`, {}),
      ])
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['audits', eid] }),
  })

  const latestAudits = AUDIT_KINDS.map(k => ({
    ...k,
    run: (audits ?? []).find(a => a.kind === k.key),
  }))

  const approve = useMutation({
    mutationFn: () => api.post(`/engagements/${eid}/plan/approve`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['strategy-plan', eid] })
      qc.invalidateQueries({ queryKey: ['engagement', clientId] })
    },
  })
  const setStatus = useMutation({
    mutationFn: (vars: { actionId: string; status: string }) =>
      api.post(`/strategy-actions/${vars.actionId}/status`, { status: vars.status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['strategy-plan', eid] }),
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
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            {plan?.status === 'proposed' && plan.actions.length > 0 && (
              <button onClick={() => approve.mutate()} disabled={approve.isPending} style={buttonStyle}>
                {approve.isPending ? <Loader2 size={15} /> : <Check size={15} />} Approve plan
              </button>
            )}
            <button
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending}
              style={{ ...buttonStyle, background: '#fff', color: '#0f172a', border: '1px solid #e2e8f0' }}
            >
              {refresh.isPending ? <Loader2 size={15} /> : <RefreshCw size={15} />}
              {refresh.isPending ? 'Refreshing…' : 'Refresh plan'}
            </button>
          </div>
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
            {plan && <span style={chip}>plan: <strong>{plan.status}</strong></span>}
            {plan?.summary?.headline && <span style={{ ...chip, color: '#6366f1' }}>{plan.summary.headline}</span>}
          </div>

          <section style={{ marginBottom: 22 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <h2 style={sectionTitle}>Audits</h2>
              <button onClick={() => runAudits.mutate()} disabled={runAudits.isPending} style={{ ...buttonStyle, padding: '7px 12px', fontSize: 13, background: '#fff', color: '#0f172a', border: '1px solid #e2e8f0' }}>
                {runAudits.isPending ? <Loader2 size={14} /> : <RefreshCw size={14} />} Run audits
              </button>
            </div>
            <div style={{ display: 'grid', gap: 8 }}>
              {latestAudits.map(({ key, label, run }) => (
                <div key={key} style={{ ...box, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '10px 14px' }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{label}</span>
                  <span style={{ fontSize: 12, color: run?.status === 'complete' ? '#475569' : run ? '#b45309' : '#94a3b8' }}>
                    {run ? auditSummary(run) : 'not run yet'}
                  </span>
                </div>
              ))}
            </div>
          </section>

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
                  {actions.map(a => (
                    <ActionRow
                      key={a.id}
                      a={a}
                      onStatus={(status) => setStatus.mutate({ actionId: a.id, status })}
                      busy={setStatus.isPending}
                    />
                  ))}
                </div>
              </section>
            )
          })}
        </>
      )}
    </div>
  )
}

function ActionRow({ a, onStatus, busy }: { a: StrategyAction; onStatus: (status: string) => void; busy: boolean }) {
  const closed = a.status === 'done' || a.status === 'skipped'
  return (
    <div style={{ ...box, opacity: closed ? 0.6 : 1 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', textDecoration: a.status === 'skipped' ? 'line-through' : 'none' }}>{a.title}</div>
          {a.rationale && <div style={{ fontSize: 13, color: '#64748b', marginTop: 3 }}>{a.rationale}</div>}
          <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
            <span style={{ ...tag, color: a.status === 'done' ? '#15803d' : '#475569' }}>{a.status}</span>
            <span style={tag}>{a.execution_mode}</span>
            {a.assignee_role && <span style={tag}>{a.assignee_role.replace('_', ' ')}</span>}
            {a.kind && <span style={tag}>{a.kind}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, flexShrink: 0 }}>
          {a.deep_link && (
            <Link to={`/${a.deep_link}`} style={openLink}>Open <ArrowRight size={14} /></Link>
          )}
          {!closed && (
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => onStatus('done')} disabled={busy} style={miniBtn}>Done</button>
              <button onClick={() => onStatus('skipped')} disabled={busy} style={{ ...miniBtn, color: '#94a3b8' }}>Skip</button>
            </div>
          )}
        </div>
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
const miniBtn: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: 'none', borderRadius: 6, padding: '4px 10px', cursor: 'pointer' }
const linkButton: React.CSSProperties = { background: 'none', border: 'none', color: '#6366f1', fontWeight: 600, cursor: 'pointer', padding: 0, fontSize: 14 }
