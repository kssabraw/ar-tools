import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, AlertTriangle, Calculator, Download, ExternalLink, OctagonAlert, RefreshCw, Send, Wallet,
} from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type { Client } from '../lib/types'

// Task Plan — the Recipe Engine's surface (docs/sops/Link_Building_Recipe_Engine.md).
// Turns the client's budget + auto-diagnosis into a costed, assigned monthly task
// plan: deployable = retainer × margin (66% target → ×0.34; drop months may run
// at 50%), minus reporting + the baseline stack, remainder Diagnose-and-Fund.
// Recommend-only — the plan is a work order for the team, nothing auto-executes.

interface PlanTask {
  task_type: string
  label: string
  quantity: number
  unit_cost: number
  line_cost: number
  assignee: string | null
  priority_rank: number
  rationale: string
}
interface PlanBody {
  margin_used: number
  deployable: number
  spent: number
  remaining: number
  tasks: PlanTask[]
  flags: string[]
  diagnosis: Record<string, unknown> & { signals?: Record<string, unknown> }
  margin_suggestion?: number
}
interface PlanRow {
  id: string
  month: string
  margin_used: number
  deployable: number
  spent: number
  remaining: number
  flags: string[]
  plan: PlanBody
  asana_push: Record<string, { gid: string; url: string; name: string }> | null
  created_at: string
}
interface PushStatus {
  status: 'pending' | 'running' | 'complete' | 'failed'
  result: { status: string; created?: number; skipped?: number; errors?: string[]; reason?: string } | null
  error: string | null
}
interface PlansResponse {
  latest: PlanRow | null
  history: PlanRow[]
}

const FLAG_META: Record<string, { label: string; color: string; bg: string }> = {
  under_funded: { label: 'Under-funded — baseline exceeds budget', color: '#b91c1c', bg: '#fef2f2' },
  escalate_margin_below_50: { label: 'Margin below 50% — escalate to Kyle/Ryan', color: '#b91c1c', bg: '#fef2f2' },
  frozen: { label: 'Client frozen — all output paused', color: '#b91c1c', bg: '#fef2f2' },
  no_retainer_configured: { label: 'No budget set on the client', color: '#b45309', bg: '#fffbeb' },
  capacity_capped: { label: 'Content pages capped by production capacity', color: '#0369a1', bg: '#f0f9ff' },
  unstaffed_task: { label: 'A task has no assignee — flag, don’t guess', color: '#b45309', bg: '#fffbeb' },
}

function money(n: number | null | undefined): string {
  return n == null ? '—' : `$${Math.round(n).toLocaleString()}`
}

export function TaskPlan() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [margin, setMargin] = useState<'0.34' | '0.5'>('0.34')
  const [specialProjects, setSpecialProjects] = useState('')
  const [viewPlanId, setViewPlanId] = useState<string | null>(null)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data, isLoading } = useQuery<PlansResponse>({
    queryKey: ['task-plans', id],
    queryFn: () => api.get<PlansResponse>(`/clients/${id}/task-plan`),
    enabled: Boolean(id),
  })

  const generateMut = useMutation({
    mutationFn: (overrideMargin?: number) =>
      api.post<PlanRow>(`/clients/${id}/task-plan`, {
        margin: overrideMargin ?? Number(margin),
        special_projects_cost: specialProjects.trim() !== '' ? Number(specialProjects) : 0,
      }),
    onSuccess: (row) => {
      setViewPlanId(row.id)
      queryClient.invalidateQueries({ queryKey: ['task-plans', id] })
    },
  })

  const history = data?.history ?? []
  const shown: PlanRow | null =
    (viewPlanId && history.find((p) => p.id === viewPlanId)) || data?.latest || null
  const body = shown?.plan

  // Push the shown plan's lines into the client's Asana project (async job;
  // idempotent per line — a re-push creates only tasks that don't exist yet).
  const [pushJobId, setPushJobId] = useState<string | null>(null)
  const pushMut = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${id}/task-plan/${shown!.id}/push`, {}),
    onSuccess: (r) => setPushJobId(r.job_id),
  })
  const { data: pushStatus } = useQuery<PushStatus>({
    queryKey: ['task-plan-push', id, pushJobId],
    queryFn: () => api.get<PushStatus>(`/clients/${id}/task-plan/push/${pushJobId}`),
    enabled: Boolean(pushJobId),
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'complete' || s === 'failed' ? false : 2500
    },
  })
  const pushing = pushMut.isPending || (Boolean(pushJobId) && pushStatus?.status !== 'complete' && pushStatus?.status !== 'failed')
  useEffect(() => {
    if (pushStatus?.status === 'complete') {
      queryClient.invalidateQueries({ queryKey: ['task-plans', id] })
    }
  }, [pushStatus?.status, id, queryClient])

  const exportCsv = () => {
    if (!body || !shown) return
    const csv = toCsv(
      ['priority', 'task', 'quantity', 'unit_cost', 'line_cost', 'assignee', 'rationale'],
      body.tasks.map((t) => [
        t.priority_rank, t.label, t.quantity, t.unit_cost, t.line_cost,
        t.assignee ?? 'UNSTAFFED', t.rationale,
      ]),
    )
    downloadCsv(`task-plan-${client?.name ?? 'client'}-${shown.month}.csv`, csv)
  }

  return (
    <div style={{ padding: 32, maxWidth: 1000 }}>
      <Link to={`/clients/${id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#6366f1', textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Calculator size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Monthly Task Plan</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 20 }}>
        The Recipe Engine: budget + diagnosis → a costed, assigned month of work. Deployable =
        budget × margin, minus $150 reporting and the baseline stack; the remainder funds whatever
        the diagnosis says is deficient. Recommend-only.
      </p>

      {/* Budget context + controls */}
      {client && client.retainer_monthly == null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 10, marginBottom: 16, fontSize: 13, color: '#92400e' }}>
          <Wallet size={16} />
          No monthly budget set for this client — plans will be empty.{' '}
          <Link to={`/clients/${id}/edit`} style={{ color: '#b45309', fontWeight: 600 }}>Set it on the client form →</Link>
        </div>
      )}
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 24 }}>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Margin</label>
          <select value={margin} onChange={(e) => setMargin(e.target.value as '0.34' | '0.5')}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}>
            <option value="0.34">66% margin target (34% deployable)</option>
            <option value="0.5">50% margin — stagnating / drop month</option>
          </select>
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }}>Special projects this month ($)</label>
          <input type="number" min="0" value={specialProjects} onChange={(e) => setSpecialProjects(e.target.value)}
            placeholder="0"
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13, width: 160 }} />
        </div>
        <button
          onClick={() => generateMut.mutate(undefined)}
          disabled={generateMut.isPending}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 18px', borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
        >
          <RefreshCw size={14} /> {generateMut.isPending ? 'Generating…' : 'Generate plan'}
        </button>
        {body && (
          <button onClick={exportCsv}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
            <Download size={14} /> CSV
          </button>
        )}
        {body && body.tasks.length > 0 && (
          <button
            onClick={() => { setPushJobId(null); pushMut.mutate() }}
            disabled={pushing}
            title="Create the plan's tasks in the client's Asana project (already-pushed lines are skipped)"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: pushing ? 0.6 : 1 }}>
            <Send size={14} /> {pushing ? 'Pushing…' : 'Push to Asana'}
          </button>
        )}
      </div>

      {/* Push outcome */}
      {pushMut.isError && (
        <div style={{ padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, marginBottom: 14, fontSize: 13, color: '#b91c1c' }}>
          {(pushMut.error as Error).message === 'no_project_mapping'
            ? 'This client has no Asana project mapped — set it on the Asana Tasks page first.'
            : (pushMut.error as Error).message}
        </div>
      )}
      {pushJobId && pushStatus && (pushStatus.status === 'complete' || pushStatus.status === 'failed') && (
        <div style={{ padding: '10px 14px', background: pushStatus.status === 'complete' ? '#f0fdf4' : '#fef2f2', border: `1px solid ${pushStatus.status === 'complete' ? '#bbf7d0' : '#fecaca'}`, borderRadius: 10, marginBottom: 14, fontSize: 13, color: pushStatus.status === 'complete' ? '#166534' : '#b91c1c' }}>
          {pushStatus.status === 'complete' && pushStatus.result
            ? <>Asana push: {pushStatus.result.created ?? 0} task{(pushStatus.result.created ?? 0) === 1 ? '' : 's'} created{(pushStatus.result.skipped ?? 0) > 0 && <>, {pushStatus.result.skipped} already pushed</>}{(pushStatus.result.errors?.length ?? 0) > 0 && <> · {pushStatus.result.errors!.length} failed (retry pushes just the missing ones)</>}{pushStatus.result.reason && <> — {pushStatus.result.reason}</>}</>
            : <>Asana push failed{pushStatus.error ? `: ${pushStatus.error}` : ''}</>}
        </div>
      )}

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : !shown ? (
        <div style={{ color: '#94a3b8', fontSize: 13, padding: '24px 0' }}>
          No plan yet — generate the first one above.
        </div>
      ) : (
        <>
          {/* Summary strip */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
            <Stat label="Month" value={new Date(shown.month + 'T00:00:00').toLocaleDateString(undefined, { month: 'long', year: 'numeric' })} />
            <Stat label="Deployable" value={money(shown.deployable)} sub={`${Math.round(shown.margin_used * 100)}% of budget`} />
            <Stat label="Allocated" value={money(shown.spent)} />
            <Stat label="Remaining" value={money(shown.remaining)} warn={shown.remaining < 0} />
          </div>

          {/* Flags */}
          {shown.flags.length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              {shown.flags.map((f) => {
                const meta = FLAG_META[f] ?? { label: f, color: '#475569', bg: '#f8fafc' }
                return (
                  <span key={f} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 999, background: meta.bg, color: meta.color, fontSize: 12, fontWeight: 600 }}>
                    {f === 'frozen' ? <OctagonAlert size={12} /> : <AlertTriangle size={12} />} {meta.label}
                  </span>
                )
              })}
            </div>
          )}

          {/* Drop-month margin suggestion */}
          {body?.margin_suggestion && shown.margin_used < body.margin_suggestion && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: '#eef2ff', border: '1px solid #c7d2fe', borderRadius: 10, marginBottom: 14, fontSize: 13, color: '#3730a3' }}>
              Open drops detected — the SOP allows a 50% margin this month for extra firepower.
              <button
                onClick={() => generateMut.mutate(body.margin_suggestion)}
                disabled={generateMut.isPending}
                style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #6366f1', background: '#fff', color: '#4f46e5', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}
              >
                Regenerate at 50%
              </button>
            </div>
          )}

          {/* Diagnosis signals */}
          {body?.diagnosis?.signals && Object.keys(body.diagnosis.signals).length > 0 && (
            <div style={{ padding: '10px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, marginBottom: 18, fontSize: 12.5, color: '#475569' }}>
              <strong style={{ color: '#334155' }}>Diagnosis:</strong>{' '}
              {Object.entries(body.diagnosis.signals).map(([k, v]) => (
                <span key={k} style={{ marginRight: 12 }}>
                  <span style={{ fontWeight: 600 }}>{k.replace(/_/g, ' ')}:</span>{' '}
                  {typeof v === 'string' ? v : JSON.stringify(v)}
                </span>
              ))}
            </div>
          )}

          {/* Task table */}
          {body && body.tasks.length > 0 ? (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>
                  <th style={{ padding: '8px 6px', width: 30 }}>#</th>
                  <th style={{ padding: '8px 6px' }}>Task</th>
                  <th style={{ padding: '8px 6px', width: 50 }}>Qty</th>
                  <th style={{ padding: '8px 6px', width: 80 }}>Line</th>
                  <th style={{ padding: '8px 6px', width: 120 }}>Assignee</th>
                  <th style={{ padding: '8px 6px' }}>Why</th>
                </tr>
              </thead>
              <tbody>
                {body.tasks.map((t, i) => (
                  <tr key={t.priority_rank} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '8px 6px', color: '#94a3b8' }}>{t.priority_rank}</td>
                    <td style={{ padding: '8px 6px', fontWeight: 600, color: '#0f172a' }}>
                      {t.label}
                      {shown.asana_push?.[`${i}:${t.task_type}`]?.url && (
                        <a href={shown.asana_push[`${i}:${t.task_type}`].url} target="_blank" rel="noreferrer"
                          title="Open in Asana"
                          style={{ marginLeft: 6, color: '#6366f1', verticalAlign: 'middle', display: 'inline-flex' }}>
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </td>
                    <td style={{ padding: '8px 6px' }}>{t.quantity}</td>
                    <td style={{ padding: '8px 6px' }}>{money(t.line_cost)}</td>
                    <td style={{ padding: '8px 6px', color: t.assignee ? '#334155' : '#b45309', fontWeight: t.assignee ? 400 : 600 }}>
                      {t.assignee ?? 'UNSTAFFED'}
                    </td>
                    <td style={{ padding: '8px 6px', color: '#64748b', fontSize: 12.5 }}>{t.rationale}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: 13, padding: '12px 0' }}>
              {shown.flags.includes('frozen')
                ? 'Client is frozen — no tasks are planned while a freeze is active.'
                : 'No tasks in this plan.'}
            </div>
          )}

          {/* History */}
          {history.length > 1 && (
            <div style={{ marginTop: 28 }}>
              <h2 style={{ fontSize: 14, fontWeight: 700, color: '#334155', marginBottom: 8 }}>History</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {history.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setViewPlanId(p.id)}
                    style={{
                      display: 'flex', gap: 14, alignItems: 'center', textAlign: 'left', padding: '8px 12px',
                      borderRadius: 8, border: '1px solid ' + (shown.id === p.id ? '#c7d2fe' : '#f1f5f9'),
                      background: shown.id === p.id ? '#eef2ff' : '#fff', cursor: 'pointer', fontSize: 12.5, color: '#475569',
                    }}
                  >
                    <span style={{ fontWeight: 600, color: '#334155' }}>
                      {new Date(p.created_at).toLocaleString()}
                    </span>
                    <span>{money(p.spent)} / {money(p.deployable)}</span>
                    <span>{Math.round(p.margin_used * 100)}% deployed</span>
                    {p.flags.length > 0 && <span style={{ color: '#b45309' }}>{p.flags.join(', ')}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, sub, warn }: { label: string; value: ReactNode; sub?: string; warn?: boolean }) {
  return (
    <div style={{ padding: '10px 16px', borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff', minWidth: 130 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: warn ? '#b91c1c' : '#0f172a' }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: '#94a3b8' }}>{sub}</div>}
    </div>
  )
}
