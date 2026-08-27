import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Loader2, Save, Trash2 } from 'lucide-react'
import { ACCENT, btn, card, denyReason, input, label, Chip, WEEKDAYS } from './shared'
import type { ReleaseMode, ReleaseSchedule, Website } from './shared'
import { api } from '../../lib/api'

// The release (drip-publish) schedule. The other content-creator modules publish
// on a cadence — some now, the rest dripped out — and this gives a site the same
// option. Each release GENERATES then PUBLISHES the next planned pages just-in-
// time, so nothing has to be generated up front. It acts on every content page:
// a local site drips its service/location/matrix pages AND its blog.

interface Props {
  website: Website
  approved: boolean
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

interface ScheduleResponse {
  schedule: ReleaseSchedule | null
  releasable: number
}

const MODES: { value: ReleaseMode; label: string }[] = [
  { value: 'daily', label: 'Every day' },
  { value: 'weekly', label: 'Every week' },
  { value: 'monthly', label: 'Every month' },
]

export function ScheduleTab({ website, approved, perms }: Props) {
  const qc = useQueryClient()
  const deny = denyReason('staff', perms)
  const provisioned = Boolean(website.github_repo)

  const { data, isLoading } = useQuery<ScheduleResponse>({
    queryKey: ['website-release', website.id],
    queryFn: () => api.get<ScheduleResponse>(`/websites/${website.id}/release-schedule`),
    // Advance the "left to release" count while a live schedule ticks.
    refetchInterval: (q) => ((q.state.data as ScheduleResponse | undefined)?.schedule?.status === 'active' ? 15000 : false),
  })
  const schedule = data?.schedule ?? null

  const [enabled, setEnabled] = useState(true)
  const [mode, setMode] = useState<ReleaseMode>('daily')
  const [weekday, setWeekday] = useState(0)
  const [dayOfMonth, setDayOfMonth] = useState(1)
  const [immediate, setImmediate] = useState(0)
  const [perRelease, setPerRelease] = useState(3)

  // Seed the form from the stored schedule when it loads/changes.
  useEffect(() => {
    if (!schedule) return
    setEnabled(schedule.enabled)
    setMode(schedule.mode)
    setWeekday(schedule.weekday ?? 0)
    setDayOfMonth(schedule.day_of_month ?? 1)
    setImmediate(schedule.immediate_count)
    setPerRelease(schedule.per_release_count)
  }, [schedule])

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['website-release', website.id] })
    void qc.invalidateQueries({ queryKey: ['website', website.id] })
    void qc.invalidateQueries({ queryKey: ['website-plan', website.id] })
  }

  const save = useMutation({
    mutationFn: () => api.put(`/websites/${website.id}/release-schedule`, {
      enabled, mode, per_release_count: perRelease, immediate_count: immediate,
      weekday: mode === 'weekly' ? weekday : null,
      day_of_month: mode === 'monthly' ? dayOfMonth : null,
    }),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: () => api.delete(`/websites/${website.id}/release-schedule`),
    onSuccess: invalidate,
  })

  const notReady = !provisioned ? 'Provision the site first — a release commits pages to its repo.'
    : !approved ? 'Approve the plan first — a schedule releases planned pages.'
    : null
  const blocked = deny ?? notReady

  if (isLoading) return <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>

  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 620 }}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <CalendarClock size={16} color={ACCENT} />
          <strong style={{ fontSize: 14, color: '#0f172a' }}>Release schedule</strong>
        </div>
        <p style={{ fontSize: 12, color: '#64748b', margin: '6px 0 0' }}>
          Publish an immediate batch, then release more on a cadence. Each release generates
          then publishes the next planned pages — you don't generate them up front. It covers
          every content page: a local site drips its service/location pages and its blog.
        </p>

        {schedule && (
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginTop: 12, fontSize: 12, color: '#475569' }}>
            <span>Status <Chip status={schedule.status} /></span>
            <span><strong style={{ color: '#0f172a' }}>{data?.releasable ?? 0}</strong> page{(data?.releasable ?? 0) === 1 ? '' : 's'} left to release</span>
            {schedule.next_run_at && schedule.status === 'active' && (
              <span>Next release {new Date(schedule.next_run_at).toLocaleString()}</span>
            )}
            {schedule.last_run_at && <span>Last {new Date(schedule.last_run_at).toLocaleString()}</span>}
          </div>
        )}
      </div>

      {notReady && !deny && (
        <div style={{ ...card, borderColor: '#fed7aa', background: '#fffbeb', color: '#92400e', fontSize: 12 }}>
          {notReady}
        </div>
      )}

      <div style={card}>
        <div style={{ display: 'grid', gap: 14 }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#0f172a', fontWeight: 600 }}>
            <input type="checkbox" checked={enabled} disabled={Boolean(blocked)} onChange={(e) => setEnabled(e.target.checked)} />
            Schedule enabled
          </label>

          <Field labelText="Publish immediately" hint="Pages released the moment you save. 0 = wait for the first cadence slot.">
            <input type="number" min={0} style={{ ...input, width: 120 }} value={immediate} disabled={Boolean(blocked)}
                   onChange={(e) => setImmediate(Math.max(0, Number(e.target.value) || 0))} />
          </Field>

          <Field labelText="Release each time" hint="Pages generated + published per cadence tick until the plan is exhausted.">
            <input type="number" min={1} style={{ ...input, width: 120 }} value={perRelease} disabled={Boolean(blocked)}
                   onChange={(e) => setPerRelease(Math.max(1, Number(e.target.value) || 1))} />
          </Field>

          <Field labelText="Cadence">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <select style={{ ...input, width: 160 }} value={mode} disabled={Boolean(blocked)}
                      onChange={(e) => setMode(e.target.value as ReleaseMode)}>
                {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              {mode === 'weekly' && (
                <select style={{ ...input, width: 110 }} value={weekday} disabled={Boolean(blocked)}
                        onChange={(e) => setWeekday(Number(e.target.value))}>
                  {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                </select>
              )}
              {mode === 'monthly' && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569' }}>
                  on day
                  <input type="number" min={1} max={28} style={{ ...input, width: 70 }} value={dayOfMonth} disabled={Boolean(blocked)}
                         onChange={(e) => setDayOfMonth(Math.min(28, Math.max(1, Number(e.target.value) || 1)))} />
                </span>
              )}
            </div>
          </Field>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={() => save.mutate()} disabled={Boolean(blocked) || save.isPending}
                    title={blocked ?? undefined}
                    style={btn(blocked ? '#e2e8f0' : '#15803d', blocked ? '#94a3b8' : '#fff')}>
              {save.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
              {schedule ? 'Update schedule' : 'Start schedule'}
            </button>
            {schedule && (
              <button onClick={() => { if (window.confirm('Stop the drip? Pages already released keep going; nothing new is enqueued.')) remove.mutate() }}
                      disabled={Boolean(deny) || remove.isPending}
                      style={btn('#fff', '#b91c1c')}>
                {remove.isPending ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                Stop schedule
              </button>
            )}
            {save.isSuccess && !save.isPending && <span style={{ fontSize: 12, color: '#15803d' }}>Saved{immediate > 0 ? ' — immediate batch queued.' : '.'}</span>}
          </div>
          {save.error && <ErrorNote message={(save.error as Error).message} />}
          {remove.error && <ErrorNote message={(remove.error as Error).message} />}
        </div>
      </div>
    </div>
  )
}

function Field({ labelText, hint, children }: { labelText: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={label}>{labelText}</label>
      {children}
      {hint && <p style={{ fontSize: 11, color: '#94a3b8', margin: '4px 0 0' }}>{hint}</p>}
    </div>
  )
}

function ErrorNote({ message }: { message: string }) {
  const m = message.toLowerCase()
  const friendly = m.includes('plan_not_approved') ? 'Approve the plan first.'
    : m.includes('not_provisioned') ? 'Provision the site first.'
    : m.includes('invalid_release_mode') ? 'Pick a valid cadence.'
    : message
  return <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>{friendly}</div>
}
