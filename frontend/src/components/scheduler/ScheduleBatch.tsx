import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Download, Loader2, Plus, Upload, X, Zap } from 'lucide-react'
import { card, errorBox, input, label, outlineBtn, primaryBtn } from '../localseo/shared'
import { parseSchedulerCsv, parseIsoDate, toCsv, downloadCsv } from '../../lib/csv'
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

const CONTENT_TYPES: ContentType[] =
  ['blog_post', 'service_page', 'location_page', 'local_seo_page', 'ecommerce']
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] // 0..6
const PERIODIC = new Set<ScheduleMode>(['drip', 'weekly', 'monthly_date', 'monthly_weekday'])
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

// The head term in column A means something different per page type.
const TERM_LABEL: Record<ContentType, string> = {
  blog_post: 'Keyword',
  service_page: 'Service',
  location_page: 'Location',
  local_seo_page: 'Location',
  ecommerce: 'Product',
}
const TERM_PLACEHOLDER: Record<ContentType, string> = {
  blog_post: 'One keyword per line…',
  service_page: 'One service per line…',
  location_page: 'One location per line…',
  local_seo_page: 'One location per line…',
  ecommerce: 'One product per line…',
}
// The standardized CSV column layout per page type (headers required). The
// optional publish Date is ALWAYS column D (index 3), so column C is unused (null)
// for the types with no Service column.
const CSV_COLUMNS: Record<ContentType, (string | null)[]> = {
  blog_post: ['Keyword', 'Notes', null, 'Date'],
  service_page: ['Service', 'Notes', null, 'Date'],
  location_page: ['Location', 'Notes', null, 'Date'],
  local_seo_page: ['Location', 'Service', 'Notes', 'Date'],
  ecommerce: ['Product', 'Notes', null, 'Date'],
}
const CSV_EXAMPLE: Record<ContentType, string[]> = {
  blog_post: ['how to unblock a drain', 'Friendly DIY tone; note when to call a pro', '', '2026-08-15'],
  service_page: ['emergency plumbing', 'Emphasise 24/7 availability', '', '2026-08-15'],
  location_page: ['Parramatta', 'Cover the whole metro area', '', '2026-08-15'],
  local_seo_page: ['Newtown NSW', 'blocked drains', 'Same-day service angle', '2026-08-15'],
  ecommerce: ['stainless steel water bottle', 'Highlight BPA-free + 24h cold', '', '2026-08-15'],
}

// One draft row = one requested page. Rows (not term-keyed maps) are the source of
// truth so a single Local SEO location can host several services (each its own
// row) without silently collapsing.
interface DraftRow { key: string; term: string; service: string; notes: string; date: string }

function segStyle(active: boolean): React.CSSProperties {
  return {
    padding: '7px 12px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
    border: `1px solid ${active ? '#6366f1' : '#e2e8f0'}`,
    background: active ? '#eef2ff' : '#fff', color: active ? '#4338ca' : '#0f172a',
  }
}

const TODAY_ISO = new Date().toISOString().slice(0, 10)

export function ScheduleBatch({ clientId, fixedType, onCreated }: {
  clientId: string
  fixedType?: ContentType
  onCreated?: () => void
}) {
  const queryClient = useQueryClient()
  const [contentType, setContentType] = useState<ContentType>(fixedType ?? 'blog_post')
  const [rows, setRows] = useState<DraftRow[]>([])
  const [bulk, setBulk] = useState('')
  const [when, setWhen] = useState<'now' | 'schedule'>('now')
  const fileRef = useRef<HTMLInputElement>(null)
  const keyRef = useRef(0)

  // Cadence (only used when scheduling).
  const [mode, setMode] = useState<ScheduleMode>('drip')
  const [perDay, setPerDay] = useState(1)
  const [weekdays, setWeekdays] = useState<number[]>([0])
  const [weekday, setWeekday] = useState(0)
  const [weekOfMonth, setWeekOfMonth] = useState(1)
  const [dayOfMonth, setDayOfMonth] = useState(1)
  const [startDate, setStartDate] = useState('')
  const [timeOfDay, setTimeOfDay] = useState('09:00')

  // Quick-fill inputs for the whole list.
  const [allNotes, setAllNotes] = useState('')
  const [allService, setAllService] = useState('')
  const [allDate, setAllDate] = useState('')

  const [notice, setNotice] = useState<string | null>(null)

  const isLocalSeo = contentType === 'local_seo_page'

  const mkRow = (p: Partial<DraftRow> = {}): DraftRow =>
    ({ key: `r${keyRef.current++}`, term: '', service: '', notes: '', date: '', ...p })

  const items: BatchItemInput[] = useMemo(() => {
    const seen = new Set<string>()
    const out: BatchItemInput[] = []
    for (const r of rows) {
      const term = r.term.trim()
      if (!term) continue
      const keyword = isLocalSeo ? r.service.trim() : term
      if (!keyword) continue                       // local SEO row with no service
      const location = isLocalSeo ? term : undefined
      const dedup = `${keyword}|${location ?? ''}`.toLowerCase()
      if (seen.has(dedup)) continue                // matches the backend's identity
      seen.add(dedup)
      const it: BatchItemInput = {
        keyword,
        notes: r.notes.trim() || null,
        scheduled_date: parseIsoDate(r.date) || null,
      }
      if (location !== undefined) it.location = location
      out.push(it)
    }
    return out
  }, [rows, isLocalSeo])

  // Rows dropped for lack of a service (local SEO) — surfaced so nothing vanishes silently.
  const missingService = isLocalSeo
    ? rows.filter(r => r.term.trim() && !r.service.trim()).length
    : 0
  // Rows whose publish date is in the past — those fire immediately; warn the user.
  const pastDated = rows.filter(r => {
    const d = parseIsoDate(r.date)
    return d !== undefined && d < TODAY_ISO
  }).length

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

  // Signature of the per-row dates so the finish-date preview refreshes when a
  // date changes (the count alone wouldn't).
  const datesSig = items.map(i => i.scheduled_date || '').join(',')

  const estQ = useQuery({
    queryKey: ['content-batch-estimate', clientId, contentType, effectiveMode, perDay,
      JSON.stringify(weekdays), weekday, weekOfMonth, dayOfMonth, startDate, timeOfDay,
      items.length, datesSig],
    queryFn: () => schedulerApi.estimate(clientId, estimateBody()),
    enabled: items.length > 0,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['scheduled-content', clientId] })
    queryClient.invalidateQueries({ queryKey: ['content-batches', clientId] })
  }

  const resetForm = () => {
    setRows([]); setBulk(''); setAllNotes(''); setAllService(''); setAllDate('')
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
      resetForm()
      if (when === 'now') {
        // Future-dated rows aren't created now — the scheduler releases them on
        // their date. Split the message so the count isn't overstated.
        const later = res.count - res.enqueued
        setNotice(later > 0
          ? `Creating ${res.enqueued} now; ${later} scheduled for their dates. They'll appear in Scheduled Content.`
          : `Creating ${res.count} page${res.count === 1 ? '' : 's'} now — they'll appear in Scheduled Content.`)
      } else {
        setNotice(`Scheduled ${res.count} page${res.count === 1 ? '' : 's'}.`)
      }
      invalidate()
      onCreated?.()
    },
    onError: (e: Error) => setNotice(e.message),
  })

  const addBulk = () => {
    const lines = bulk.split(/\r\n|\r|\n/).map(l => l.trim()).filter(Boolean)
    if (!lines.length) return
    setRows(prev => [...prev, ...lines.map(term => mkRow({ term }))])
    setBulk('')
  }

  const onCsv = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    const parsed = parseSchedulerCsv(text, contentType)
    if (!parsed.length) return
    setRows(prev => [...prev, ...parsed.map(r => mkRow({
      term: r.term, service: r.service ?? '', notes: r.notes ?? '', date: r.date ?? '',
    }))])
  }

  const downloadTemplate = () => {
    const headers = CSV_COLUMNS[contentType].map(c => c ?? '')  // blank header for the unused column
    downloadCsv(
      `content-scheduler-${contentType}-template.csv`,
      toCsv(headers, [CSV_EXAMPLE[contentType]]),
    )
  }

  const updateRow = (key: string, patch: Partial<DraftRow>) =>
    setRows(prev => prev.map(r => (r.key === key ? { ...r, ...patch } : r)))
  const removeRow = (key: string) => setRows(prev => prev.filter(r => r.key !== key))
  const applyAll = (patch: Partial<DraftRow>) => setRows(prev => prev.map(r => ({ ...r, ...patch })))

  const canSubmit = items.length > 0 && !createMut.isPending

  // "A = Keyword · B = Notes · D = Date" — skip the unused column, keep letters.
  const colHint = CSV_COLUMNS[contentType]
    .map((c, i) => (c ? `${String.fromCharCode(65 + i)} = ${c}` : null))
    .filter(Boolean)
    .join(' · ')

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
        <label style={label}>Add {TERM_LABEL[contentType].toLowerCase()}s</label>
        <textarea value={bulk} onChange={e => setBulk(e.target.value)} rows={4}
          placeholder={TERM_PLACEHOLDER[contentType]}
          style={{ ...input, resize: 'vertical', fontFamily: 'inherit' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, flexWrap: 'wrap' }}>
          <button type="button" style={outlineBtn} onClick={addBulk} disabled={!bulk.trim()}>
            <Plus size={14} /> Add to list
          </button>
          <button type="button" style={outlineBtn} onClick={() => fileRef.current?.click()}>
            <Upload size={14} /> Upload CSV
          </button>
          <input ref={fileRef} type="file" accept=".csv,text/csv"
            style={{ display: 'none' }} onChange={onCsv} />
          <button type="button" style={outlineBtn} onClick={downloadTemplate}>
            <Download size={14} /> CSV template
          </button>
          <span style={{ fontSize: 13, color: '#64748b' }}>
            {items.length} page{items.length === 1 ? '' : 's'}
          </span>
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>
          CSV columns (with headers): {colHint}. Date is optional (YYYY-MM-DD) —
          a dated row posts on that date, the rest follow the schedule below.
        </div>
      </div>

      {rows.length > 0 && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label style={label}>
              Pages{isLocalSeo ? ' — Service required, Notes optional' : ' — Notes optional'}
            </label>
            <button type="button" style={{ ...outlineBtn, padding: '4px 10px', fontSize: 12 }}
              onClick={() => setRows([])}>Clear all</button>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            {isLocalSeo && (
              <>
                <input value={allService} onChange={e => setAllService(e.target.value)}
                  placeholder="Service for all rows, e.g. blocked drains" style={input} />
                <button type="button" style={outlineBtn}
                  onClick={() => applyAll({ service: allService })}>Apply service to all</button>
              </>
            )}
            <input value={allNotes} onChange={e => setAllNotes(e.target.value)}
              placeholder="Notes for all rows (optional)" style={input} />
            <button type="button" style={outlineBtn}
              onClick={() => applyAll({ notes: allNotes })}>Apply notes to all</button>
            <input type="date" value={allDate} min={TODAY_ISO}
              onChange={e => setAllDate(e.target.value)} style={{ ...input, maxWidth: 170 }} />
            <button type="button" style={outlineBtn}
              onClick={() => applyAll({ date: allDate })}>Apply date to all</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 300, overflowY: 'auto' }}>
            {rows.map(r => (
              <div key={r.key} style={{
                display: 'grid',
                gridTemplateColumns: isLocalSeo
                  ? 'minmax(0,1fr) minmax(0,1fr) minmax(0,1.3fr) 150px 30px'
                  : 'minmax(0,1.2fr) minmax(0,1.6fr) 150px 30px',
                gap: 8,
              }}>
                <input value={r.term}
                  onChange={e => updateRow(r.key, { term: e.target.value })}
                  placeholder={TERM_LABEL[contentType].toLowerCase()}
                  style={{ ...input, padding: '7px 10px' }} />
                {isLocalSeo && (
                  <input value={r.service}
                    onChange={e => updateRow(r.key, { service: e.target.value })}
                    placeholder="service" style={{ ...input, padding: '7px 10px' }} />
                )}
                <input value={r.notes}
                  onChange={e => updateRow(r.key, { notes: e.target.value })}
                  placeholder="notes (optional)" style={{ ...input, padding: '7px 10px' }} />
                <input type="date" value={r.date} min={TODAY_ISO}
                  onChange={e => updateRow(r.key, { date: e.target.value })}
                  style={{ ...input, padding: '7px 10px' }} />
                <button type="button" onClick={() => removeRow(r.key)}
                  title="Remove"
                  style={{ ...outlineBtn, padding: '0', justifyContent: 'center' }}>
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
          {missingService > 0 && (
            <div style={{ fontSize: 12, color: '#b45309', marginTop: 6 }}>
              {missingService} location{missingService === 1 ? '' : 's'} with no service will be skipped.
            </div>
          )}
          {pastDated > 0 && (
            <div style={{ fontSize: 12, color: '#b45309', marginTop: 6 }}>
              {pastDated} row{pastDated === 1 ? '' : 's'} dated in the past — those will be created immediately.
            </div>
          )}
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
                <input type="date" value={startDate} min={TODAY_ISO}
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
