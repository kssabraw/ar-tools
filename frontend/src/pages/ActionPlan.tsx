import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, GitMerge, Sparkles,
  CheckCircle2, MapPin, Users, Star, Link2,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client, ReoptAction, ReoptPlan } from '../lib/types'

// Action Plan — the reoptimization planner's surface. Reads the latest stored
// plan and lets the user rebuild it on demand. Every action deep-links into the
// tool that does the work; nothing is auto-executed (recommend-only).
export function ActionPlan() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: plan, isLoading } = useQuery<ReoptPlan | null>({
    queryKey: ['action-plan', id],
    queryFn: () => api.get<ReoptPlan | null>(`/clients/${id}/action-plan`),
    enabled: Boolean(id),
  })

  const refresh = useMutation({
    mutationFn: () => api.post<ReoptPlan>(`/clients/${id}/action-plan/refresh`, {}),
    onSuccess: (fresh) => {
      queryClient.setQueryData(['action-plan', id], fresh)
    },
  })

  const actions = plan?.items ?? []

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Action Plan</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
            Prioritized reoptimization recommendations from this client’s rank-tracker signals — organic drops to
            fix, winnable keywords, Search Console opportunities, and local-pack declines from the Maps geo-grid.
            Each routes you into the tool that does it.
          </p>
        </div>
        <button style={refreshBtn} onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw size={14} style={refresh.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
          {refresh.isPending ? 'Rebuilding…' : 'Rebuild'}
        </button>
      </div>

      {plan && (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 20 }}>
          {plan.summary} · last built {new Date(plan.created_at).toLocaleString()}
          {plan.trigger !== 'manual' && ` · ${triggerLabel(plan.trigger)}`}
        </div>
      )}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : !plan ? (
        <div style={emptyBox}>
          No plan built yet. Click <strong>Rebuild</strong> to generate one from this client’s current signals.
        </div>
      ) : actions.length === 0 ? (
        <div style={{ ...emptyBox, color: '#16a34a', borderColor: '#bbf7d0', background: '#f0fdf4' }}>
          <CheckCircle2 size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
          No actions right now — rankings look healthy.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {actions.map((a, i) => (
            <ActionRow key={`${a.kind}-${a.keyword}-${i}`} action={a} onGo={() => navigate('/' + a.cta_path.replace(/^\//, ''))} />
          ))}
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function ActionRow({ action, onGo }: { action: ReoptAction; onGo: () => void }) {
  const c = sev(action.severity)
  const meta = kindMeta(action.kind)
  return (
    <div style={{ ...row, borderLeft: `3px solid ${c.bar}` }}>
      <div style={{ color: c.bar, flexShrink: 0, marginTop: 2 }}>{meta.icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ ...pill, color: c.fg, background: c.bg }}>{meta.label}</span>
          <span style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>{action.keyword || '—'}</span>
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{action.diagnosis}</div>
        <div style={{ fontSize: 13, color: '#334155', marginTop: 4, lineHeight: 1.5 }}>{action.recommendation}</div>
      </div>
      <button style={goBtn} onClick={onGo}>
        {action.cta_label} <ArrowRight size={13} />
      </button>
    </div>
  )
}

function kindMeta(kind: string): { label: string; icon: React.ReactNode } {
  switch (kind) {
    case 'rank_drop': return { label: 'Ranking drop', icon: <AlertTriangle size={18} /> }
    case 'quick_win': return { label: 'Quick win', icon: <Sparkles size={18} /> }
    case 'cannibalization': return { label: 'Cannibalization', icon: <GitMerge size={18} /> }
    case 'maps_decline': return { label: 'Local pack decline', icon: <MapPin size={18} /> }
    case 'maps_competitor': return { label: 'Local competitor', icon: <Users size={18} /> }
    case 'maps_weak_area': return { label: 'Weak coverage area', icon: <MapPin size={18} /> }
    case 'gbp_gap': return { label: 'GBP gap', icon: <MapPin size={18} /> }
    case 'review_gap': return { label: 'Reviews', icon: <Star size={18} /> }
    case 'backlink_gap': return { label: 'Backlinks', icon: <Link2 size={18} /> }
    case 'maps_solv_drop': return { label: 'Local share loss', icon: <TrendingDown size={18} /> }
    case 'brand_search_decline': return { label: 'Brand search down', icon: <TrendingDown size={18} /> }
    default: return { label: 'Opportunity', icon: <TrendingUp size={18} /> }
  }
}

function triggerLabel(trigger: string): string {
  switch (trigger) {
    case 'drop': return 'after a ranking drop'
    case 'maps_drop': return 'after a local-pack drop'
    default: return 'weekly digest'
  }
}

function sev(severity: string): { bar: string; fg: string; bg: string } {
  switch (severity) {
    case 'critical': return { bar: '#dc2626', fg: '#b91c1c', bg: '#fef2f2' }
    case 'warning': return { bar: '#f59e0b', fg: '#b45309', bg: '#fffbeb' }
    default: return { bar: '#6366f1', fg: '#4338ca', bg: '#eef2ff' }
  }
}

const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const row: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px',
  border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff',
}
const pill: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px',
  textTransform: 'uppercase', letterSpacing: '0.03em',
}
const goBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
  fontSize: 12, fontWeight: 600, color: '#6366f1', background: '#eef2ff',
  border: 'none', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', alignSelf: 'center',
}
const refreshBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  fontSize: 13, fontWeight: 600, color: '#334155', background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', cursor: 'pointer',
}
const emptyBox: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center',
}
