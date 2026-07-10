import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Loader2, Upload, Zap } from 'lucide-react'
import { card, errorBox, input, label, outlineBtn, primaryBtn } from '../localseo/shared'
import { parseKeywordsFromCsv } from '../../lib/csv'
import {
  CONTENT_TYPE_LABEL,
  schedulerApi,
  type BatchItemInput,
  type CadenceBody,
  type ContentType,
  type CreateBody,
  type EstimateBody,
  type ScheduleMode,
} from './api'

const CONTENT_TYPES: ContentType[] = ['blog_post', 'service_page', 'location_page', 'local_seo_page']
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] // 0..6
const PERIODIC = new Set<ScheduleMode>(['drip', 'weekly', 'monthly_date', 'monthly_weekday'])
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

// One keyword per line (or comma-separated), trimmed, blanks dropped, deduped.
function parseKeywords(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  text.split(/\r\n|\r|\n/).forEach(line => {
    line.split(',').forEach(part => {
      const kw = part.trim()
      if (kw && !seen.has(kw.toLowerCase())) { seen.add(kw.toLowerCase()); out.push(kw) }
    })
  })
  return out
}

function segStyle(active: boolean): React.CSSProperties {
  return {
    padding: '7px 12px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
    border: `1px solid ${active ? '#6366f1' : '#e2e8f0'}`,
    background: active ? '#eef2ff' : '#fff', color: active ? '#4338ca' : '#0f172a',
  }
}

export function ScheduleBatch({ clientId, fixedType, onCreated }: {
  clientId: string
  fixedType?: ContentType
  onCreated?: () => void
}) {
  const queryClient = useQueryClient()
  const [contentType, setContentType] = useState<ContentType>(fixedType ?? 'blog_post')
  const [raw, setRaw] = useState('')
  const [when, setWhen] = useState<'now' | 'schedule'>('now')
  const fileRef = useRef<HTMLInputElement>(null)

  // Cadence (only used when scheduling).
  const [mode, setMode] = useState<ScheduleMode>('drip')
  const [perDay, setPerDay] = useState(1)
  const [weekdays, setWeekdays] = useState<number[]>([0])
  const [weekday, setWeekday] = useState(0)
  const [weekOfMonth, setWeekOfMonth] = useState(1)
  const [dayOfMonth, setDayOfMonth] = useState(1)
  const [startDate, setStartDate] = useState('')
  const [timeOfDay, setTimeOfDay] = useState('09:00')

  // Per-type params.
  const [batchLocation, setBatchLocation] = useState('')            // local_seo_page
  const [servicesByKw, setServicesByKw] = useState<Record<string, string>>({}) // location_page
  const [allServices, setAllServices] = useState('')

  const [notice, setNotice] = useState<string | null>(null)

  const keywords = useMemo(() => parseKeywords(raw), [raw])
  const isLocalSeo = contentType === 'local_seo_page'
  const isLocationPage = contentType === 'location_page'

  const splitServices = (s: string) => s.split(/[|,;]/).map(x => x.trim()).filter(Boolean)

  const items: BatchItemInput[] = useMemo(() => keywords.map(kw => {
    const it: BatchItemInput = { keyword: kw }
    if (isLocalSeo) it.location = batchLocation.trim() || null
    if (isLocationPage) it.services = splitServices(servicesByKw[kw.toLowerCase()] ?? '')
    return it
  }), [keywords, isLocalSeo, isLocationPage, batchLocation, servicesByKw])

  const effectiveMode: ScheduleMode = when === 'now' ? 'now' : mode
  const isPeriodic = when === 'schedule' && PERIODIC.has(mode)

  const cadence = (): CadenceBody => {
    const c: CadenceBody = { mode: effectiveMode, timezone: TZ }
    if (when === 'now') return c
    if (isPeriodic) c.per_day = perDay
    if (mode === 'weekly') c.weekdays = weekdays
    if (mode === 'monthly_weekday') { c.weekday = weekday; c.week_of_month = weekOfMonth }
    if (mode === 'monthly_date') c.day_of_month = dayOfMonth
    if (isPeriodic || mode === 'fixed') {
      if (startDate) c.start_date = startDate
      c.time_of_day = timeOfDay
    }
    return c
  }

  const estimateBody = (): EstimateBody => ({ ...cadence(), content_type: contentType, items })

  // Live estimate (only with valid input). Keyed on everything that changes it.
  const estQ = useQuery({
    queryKey: ['content-batch-estimate', clientId, contentType, effectiveMode, perDay,
      JSON.stringify(weekdays), weekday, weekOfMonth, dayOfMonth, startDate, timeOfDay,
      items.length, isLocalSeo ? batchLocation : ''],
    queryFn: () => schedulerApi.estimate(clientId, estimateBody()),
    enabled: items.length > 0 && (!isLocalSeo || batchLocation.trim().length > 0),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['scheduled-content', clientId] })
    queryClient.invalidateQueries({ queryKey: ['content-batches', clientId] })
  }

  const createMut = useMutation({
    mutationFn: () => {
      const body: CreateBody = { ...estimateBody() }
      return schedulerApi.create(clientId, body)
    },
    onSuccess: (res) => {
      if (res.status === 'requires_approval') {
        setNotice(`This batch (~$${res.estimate?.cost_estimate_usd?.toFixed(2)}) exceeds the ` +
          `$${res.estimate?.approval_threshold_usd} approval limit — ask a senior operator to run it.`)
        return
      }
      setRaw(''); setServicesByKw({}); setAllServices('')
      setNotice(when === 'now'
        ? `Creating ${res.count} page${res.count === 1 ? '' : 's'} now — they'll appear in Scheduled Content.`
        : `Scheduled ${res.count} page${res.count === 1 ? '' : 's'}.`)
      invalidate()
      onCreated?.()
    },
    onError: (e: Error) => setNotice(e.message),
  })

  const onCsv = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    const kws = parseKeywordsFromCsv(text)
    if (kws.length) setRaw(prev => (prev.trim() ? prev.trimEnd() + '\n' : '') + kws.join('\n'))
    // Location pages: also lift an optional per-row services column (col 2,
    // pipe/semicolon-separated inside the cell).
    if (isLocationPage) {
      const map: Record<string, string> = {}
      text.split(/\r\n|\r|\n/).forEach(line => {
        const cols = line.split(',')
        const kw = (cols[0] ?? '').trim()
        const svc = (cols[1] ?? '').trim()
        if (kw && svc) map[kw.toLowerCase()] = svc.replace(/[|;]/g, ', ')
      })
      if (Object.keys(map).length) setServicesByKw(prev => ({ ...prev, ...map }))
    }
  }

  const canSubmit = items.length > 0 && !createMut.isPending &&
    (!isLocalSeo || batchLocation.trim().length > 0)

  return (
    <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {!fixedType && (
        <div>
          <label style={label}>Page type</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {CONTENT_TYPES.map(t => (
              <button key={t} type="button" style={segStyle(contentType === t)}
                onClick={() => setContentType(t)}>{CONTENT_TYPE_LABEL[t]}</button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label style={label}>Keywords</label>
        <textarea value={raw} onChange={e => setRaw(e.target.value)} rows={6}
          placeholder="One keyword per line (or comma-separated)…"
          style={{ ...input, resize: 'vertical', fontFamily: 'inherit' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
          <button type="button" style={outlineBtn} onClick={() => fileRef.current?.click()}>
            <Upload size={14} /> Upload CSV
          </button>
          <input ref={fileRef} type="file" accept=".csv,text/csv"
            style={{ display: 'none' }} onChange={onCsv} />
          <span style={{ fontSize: 13, color: '#64748b' }}>
            {keywords.length} keyword{keywords.length === 1 ? '' : 's'}
          </span>
        </div>
      </div>

      {isLocalSeo && (
        <div>
          <label style={label}>Target location (applied to every page)</label>
          <input value={batchLocation} onChange={e => setBatchLocation(e.target.value)}
            placeholder="e.g. Newtown, NSW" style={input} />
        </div>
      )}

      {isLocationPage && keywords.length > 0 && (
        <div>
          <label style={label}>Services per page (one section each)</label>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <input value={allServices} onChange={e => setAllServices(e.target.value)}
              placeholder="Fill all rows, e.g. drains | hot water | burst pipes" style={input} />
            <button type="button" style={outlineBtn} onClick={() => {
              const next: Record<string, string> = {}
              keywords.forEach(kw => { next[kw.toLowerCase()] = allServices })
              setServicesByKw(next)
            }}>Apply to all</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
            {keywords.map(kw => (
              <div key={kw} style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 8 }}>
                <span style={{ fontSize: 13, color: '#0f172a', alignSelf: 'center' }}>{kw}</span>
                <input value={servicesByKw[kw.toLowerCase()] ?? ''}
                  onChange={e => setServicesByKw(prev => ({ ...prev, [kw.toLowerCase()]: e.target.value }))}
                  placeholder="services (comma / | separated)" style={{ ...input, padding: '7px 10px' }} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <label style={label}>When</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" style={segStyle(when === 'now')} onClick={() => setWhen('now')}>
            <Zap size={13} style={{ verticalAlign: -2, marginRight: 4 }} />Create now
          </button>
          <button type="button" style={segStyle(when === 'schedule')} onClick={() => setWhen('schedule')}>
            <CalendarClock size={13} style={{ verticalAlign: -2, marginRight: 4 }} />Schedule
          </button>
        </div>
      </div>

      {when === 'schedule' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label style={label}>Cadence</label>
            <select value={mode} onChange={e => setMode(e.target.value as ScheduleMode)}
              style={{ ...input, cursor: 'pointer' }}>
              <option value="all_at_once">All at once (on a date)</option>
              <option value="drip">Drip — N per day</option>
              <option value="weekly">Weekly — N per chosen weekday(s)</option>
              <option value="monthly_date">Monthly — on a day of the month</option>
              <option value="monthly_weekday">Monthly — on the Nth weekday</option>
              <option value="fixed">All on one specific date</option>
            </select>
          </div>

          {isPeriodic && (
            <div>
              <label style={label}>How many per {mode === 'drip' ? 'day' : mode === 'weekly' ? 'slot' : 'month'}</label>
              <input type="number" min={1} value={perDay}
                onChange={e => setPerDay(Math.max(1, Number(e.target.value) || 1))} style={{ ...input, maxWidth: 120 }} />
            </div>
          )}

          {mode === 'weekly' && (
            <div>
              <label style={label}>Weekday(s)</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {WEEKDAYS.map((w, i) => (
                  <button key={w} type="button" style={segStyle(weekdays.includes(i))}
                    onClick={() => setWeekdays(prev =>
                      prev.includes(i) ? prev.filter(x => x !== i) : [...prev, i].sort())}>{w}</button>
                ))}
              </div>
            </div>
          )}

          {mode === 'monthly_weekday' && (
            <div style={{ display: 'flex', gap: 12 }}>
              <div>
                <label style={label}>Weekday</label>
                <select value={weekday} onChange={e => setWeekday(Number(e.target.value))}
                  style={{ ...input, cursor: 'pointer' }}>
                  {WEEKDAYS.map((w, i) => <option key={w} value={i}>{w}</option>)}
                </select>
              </div>
              <div>
                <label style={label}>Occurrence</label>
                <select value={weekOfMonth} onChange={e => setWeekOfMonth(Number(e.target.value))}
                  style={{ ...input, cursor: 'pointer' }}>
                  <option value={1}>1st</option><option value={2}>2nd</option>
                  <option value={3}>3rd</option><option value={4}>4th</option>
                  <option value={-1}>Last</option>
                </select>
              </div>
            </div>
          )}

          {mode === 'monthly_date' && (
            <div>
              <label style={label}>Day of month</label>
              <input type="number" min={1} max={31} value={dayOfMonth}
                onChange={e => setDayOfMonth(Math.min(31, Math.max(1, Number(e.target.value) || 1)))}
                style={{ ...input, maxWidth: 120 }} />
            </div>
          )}

          {(isPeriodic || mode === 'fixed' || mode === 'all_at_once') && (
            <div style={{ display: 'flex', gap: 12 }}>
              <div>
                <label style={label}>{mode === 'fixed' ? 'Publish date' : 'Start date'}</label>
                <input type="date" value={startDate} min={new Date().toISOString().slice(0, 10)}
                  onChange={e => setStartDate(e.target.value)} style={input} />
              </div>
              {mode !== 'all_at_once' && (
                <div>
                  <label style={label}>Time</label>
                  <input type="time" value={timeOfDay} onChange={e => setTimeOfDay(e.target.value)} style={input} />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {estQ.data && items.length > 0 && (
        <div style={{ fontSize: 13, color: '#334155' }}>
          {estQ.data.count} page{estQ.data.count === 1 ? '' : 's'} · est. ${estQ.data.cost_estimate_usd.toFixed(2)}
          {estQ.data.finish_date ? ` · finishes ${estQ.data.finish_date}` : ''}
          {estQ.data.skipped > 0 ? ` · ${estQ.data.skipped} skipped (blank/dupe)` : ''}
          {estQ.data.requires_approval && (
            <span style={{ color: '#b45309' }}> · exceeds ${estQ.data.approval_threshold_usd} approval limit</span>
          )}
        </div>
      )}

      {notice && <div style={{ ...errorBox, background: '#eff6ff', border: '1px solid #bfdbfe', color: '#1e40af' }}>{notice}</div>}

      <div>
        <button type="button" disabled={!canSubmit} onClick={() => { setNotice(null); createMut.mutate() }}
          style={{ ...primaryBtn, opacity: canSubmit ? 1 : 0.5, cursor: canSubmit ? 'pointer' : 'not-allowed' }}>
          {createMut.isPending && <Loader2 size={15} className="spin" />}
          {when === 'now' ? 'Create now' : 'Schedule'}
        </button>
      </div>
    </div>
  )
}
