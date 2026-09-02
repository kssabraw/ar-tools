import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Play, Square } from 'lucide-react'
import { ErrorDetails } from '../../ErrorDetails'
import { Spinner } from '../Spinner'
import { card, input, label, primaryBtn } from '../shared'
import { matrixApi } from './api'
import type { MatrixDetail, MatrixReleaseBody } from './types'

interface Props {
  clientId: string
  matrix: MatrixDetail
  onChanged: () => void
}

const select: React.CSSProperties = { ...input, appearance: 'auto' as React.CSSProperties['appearance'] }
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const smallBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 7, padding: '5px 10px', cursor: 'pointer', color: '#334155' }

function fmt(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

// The drip release: an immediate batch now, then N cells per day / week /
// month until the grid is filled. Each release GENERATES then PUBLISHES its
// cells to the matrix's destination, so nothing is written ahead of its slot.
export function MatrixReleaseCard({ clientId, matrix, onChanged }: Props) {
  const queryClient = useQueryClient()
  const key = ['local-seo-matrix-release', clientId, matrix.id]
  const { data: state, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => matrixApi.getRelease(clientId, matrix.id),
  })
  const refresh = () => { void queryClient.invalidateQueries({ queryKey: key }); onChanged() }

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<MatrixReleaseBody['mode']>('daily')
  const [weekday, setWeekday] = useState<number>(new Date().getDay() === 0 ? 6 : new Date().getDay() - 1)
  const [dayOfMonth, setDayOfMonth] = useState<number>(Math.min(28, new Date().getDate()))
  const [immediate, setImmediate] = useState(0)
  const [perRelease, setPerRelease] = useState(1)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const schedule = state?.schedule
  const active = Boolean(schedule?.enabled && schedule?.status === 'active')
  const releasable = state?.releasable ?? 0

  const openForm = () => {
    if (schedule) {
      setMode(schedule.mode)
      if (schedule.weekday != null) setWeekday(schedule.weekday)
      if (schedule.day_of_month != null) setDayOfMonth(schedule.day_of_month)
      setPerRelease(schedule.per_release_count || 1)
    }
    setImmediate(0)
    setOpen(true)
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await matrixApi.setRelease(clientId, matrix.id, {
        mode,
        weekday: mode === 'weekly' ? weekday : null,
        day_of_month: mode === 'monthly' ? dayOfMonth : null,
        immediate_count: immediate,
        per_release_count: perRelease,
        enabled: true,
      })
      setOpen(false)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the schedule')
    } finally {
      setSaving(false)
    }
  }

  const stop = async () => {
    setSaving(true)
    setError('')
    try {
      await matrixApi.clearRelease(clientId, matrix.id)
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not stop the schedule')
    } finally {
      setSaving(false)
    }
  }

  const runNow = async () => {
    setRunning(true)
    setError('')
    try {
      await matrixApi.runRelease(clientId, matrix.id, Math.max(1, perRelease))
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not release')
    } finally {
      setRunning(false)
    }
  }

  const cadence = schedule
    ? schedule.mode === 'weekly' ? `every ${WEEKDAYS[schedule.weekday ?? 0]}`
      : schedule.mode === 'monthly' ? `on day ${schedule.day_of_month ?? 1} each month`
      : 'daily'
    : ''

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h3 style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <CalendarClock size={15} /> Release schedule
          </h3>
          <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0' }}>
            Drip the grid out instead of all at once: a batch now, then a few cells per day, week or month. Each release
            generates <em>then publishes</em> its pages to <strong>{matrix.publish_destination.replace('_', ' ')}</strong> as{' '}
            <strong>{matrix.publish_status}</strong> (change these in the matrix settings).
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {!open && <button type="button" style={smallBtn} onClick={openForm} disabled={saving}><CalendarClock size={13} /> {active ? 'Change' : 'Schedule…'}</button>}
          {active && <button type="button" style={{ ...smallBtn, color: '#b91c1c' }} onClick={stop} disabled={saving}><Square size={12} /> Stop</button>}
          <button type="button" style={smallBtn} onClick={runNow} disabled={running || releasable === 0} title="Generate + publish the next batch now, outside the cadence">
            {running ? <Spinner size={12} /> : <Play size={12} />} Release next {Math.max(1, perRelease)} now
          </button>
        </div>
      </div>

      {isLoading ? <Spinner size={14} /> : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#64748b', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 600, padding: '1px 8px', borderRadius: 5, background: active ? '#dcfce7' : schedule?.status === 'complete' ? '#eef2ff' : '#f1f5f9', color: active ? '#166534' : schedule?.status === 'complete' ? '#4338ca' : '#64748b' }}>
            {active ? `Active · ${schedule?.per_release_count} per release, ${cadence}` : schedule?.status === 'complete' ? 'Complete — every cell released' : 'Not scheduled'}
          </span>
          <span>{releasable} cell{releasable === 1 ? '' : 's'} left to release</span>
          {active && <span>Next: {fmt(schedule?.next_run_at)}</span>}
          {schedule?.last_run_at && <span>Last: {fmt(schedule.last_run_at)}</span>}
        </div>
      )}

      {error && <ErrorDetails message={error} />}

      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12 }}>
            <div>
              <label style={label}>Cadence</label>
              <select style={select} value={mode} onChange={e => setMode(e.target.value as MatrixReleaseBody['mode'])} disabled={saving}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </select>
            </div>
            {mode === 'weekly' && (
              <div>
                <label style={label}>On</label>
                <select style={select} value={weekday} onChange={e => setWeekday(Number(e.target.value))} disabled={saving}>
                  {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                </select>
              </div>
            )}
            {mode === 'monthly' && (
              <div>
                <label style={label}>Day of month</label>
                <input type="number" min={1} max={28} style={input} value={dayOfMonth} onChange={e => setDayOfMonth(Math.max(1, Math.min(28, Number(e.target.value) || 1)))} disabled={saving} />
              </div>
            )}
            <div>
              <label style={label}>Per release</label>
              <input type="number" min={1} style={input} value={perRelease} onChange={e => setPerRelease(Math.max(1, Number(e.target.value) || 1))} disabled={saving} />
            </div>
            <div>
              <label style={label}>Release now</label>
              <input type="number" min={0} style={input} value={immediate} onChange={e => setImmediate(Math.max(0, Number(e.target.value) || 0))} disabled={saving} />
            </div>
          </div>
          <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>
            Cells go out location by location (every service for one suburb before the next), so each suburb’s silo completes sooner.
            {releasable > 0 && perRelease > 0 && mode === 'daily' && ` At ${perRelease}/day the remaining ${releasable} take about ${Math.ceil(releasable / perRelease)} days.`}
          </p>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button style={{ ...primaryBtn, opacity: saving ? 0.6 : 1 }} disabled={saving} onClick={save}>
              {saving ? <Spinner size={16} color="#fff" /> : <CalendarClock size={16} />} {active ? 'Update schedule' : 'Start schedule'}
            </button>
            <button type="button" onClick={() => setOpen(false)} disabled={saving} style={{ background: 'none', border: 'none', color: '#64748b', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
