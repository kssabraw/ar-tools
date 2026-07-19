import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Download, Loader2, Upload, Zap } from 'lucide-react'
import { card, errorBox, input, label, outlineBtn, primaryBtn } from '../localseo/shared'
import { parseSchedulerCsv, toCsv, downloadCsv } from '../../lib/csv'
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
// The standardized CSV column layout per page type (headers required).
const CSV_COLUMNS: Record<ContentType, string[]> = {
  blog_post: ['Keyword', 'Notes'],
  service_page: ['Service', 'Notes'],
  location_page: ['Location', 'Notes'],
  local_seo_page: ['Location', 'Service', 'Notes'],
  ecommerce: ['Product', 'Notes'],
}
const CSV_EXAMPLE: Record<ContentType, string[]> = {
  blog_post: ['how to unblock a drain', 'Friendly DIY tone; note when to call a pro'],
  service_page: ['emergency plumbing', 'Emphasise 24/7 availability'],
  location_page: ['Parramatta', 'Cover the whole metro area'],
  local_seo_page: ['Newtown NSW', 'blocked drains', 'Same-day service angle'],
  ecommerce: ['stainless steel water bottle', 'Highlight BPA-free + 24h cold'],
}

// One term per line, trimmed, blanks dropped, deduped (case-insensitive). Split
// on newlines only — a term may legitimately contain a comma (e.g. "Newtown, NSW").
function parseTerms(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  text.split(/\r\n|\r|\n/).forEach(line => {
    const t = line.trim()
    if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t) }
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

  // Per-row params, keyed by lowercased term. `notesByTerm` applies to every type
  // (CSV "Notes" column, fed into generation); `serviceByTerm` is the local SEO
  // "Service" column (a local page is "<service> in <location>").
  const [notesByTerm, setNotesByTerm] = useState<Record<string, string>>({})
  const [serviceByTerm, setServiceByTerm] = useState<Record<string, string>>({})
  const [allNotes, setAllNotes] = useState('')
  const [allService, setAllService] = useState('')

  const [notice, setNotice] = useState<string | null>(null)

  const terms = useMemo(() => parseTerms(raw), [raw])
  const isLocalSeo = contentType === 'local_seo_page'

  const items: BatchItemInput[] = useMemo(() => terms.map(term => {
    const k = term.toLowerCase()
    const notes = (notesByTerm[k] || '').trim() || null
    if (isLocalSeo) {
      // Column A is the location; the Service column becomes the page's head term.
      return { keyword: (serviceByTerm[k] || '').trim(), location: term, notes }
    }
    return { keyword: term, notes }
  }).filter(it => it.keyword.trim().length > 0), [terms, isLocalSeo, notesByTerm, serviceByTerm])

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
      items.length],
    queryFn: () => schedulerApi.estimate(clientId, estimateBody()),
    enabled: items.length > 0,
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
      setRaw(''); setNotesByTerm({}); setServiceByTerm({}); setAllNotes(''); setAllService('')
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
    const parsed = parseSchedulerCsv(text, contentType)
    if (!parsed.length) return
    setRaw(prev => (prev.trim() ? prev.trimEnd() + '\n' : '') + parsed.map(r => r.term).join('\n'))
    setNotesByTerm(prev => {
      const next = { ...prev }
      parsed.forEach(r => { if (r.notes) next[r.term.toLowerCase()] = r.notes })
      return next
    })
    if (isLocalSeo) {
      setServiceByTerm(prev => {
        const next = { ...prev }
        parsed.forEach(r => { if (r.service) next[r.term.toLowerCase()] = r.service })
        return next
      })
    }
  }

  const downloadTemplate = () => {
    downloadCsv(
      `content-scheduler-${contentType}-template.csv`,
      toCsv(CSV_COLUMNS[contentType], [CSV_EXAMPLE[contentType]]),
    )
  }

  const applyAll = (value: string, setter: (m: Record<string, string>) => void) => {
    const next: Record<string, string> = {}
    terms.forEach(t => { next[t.toLowerCase()] = value })
    setter(next)
  }

  const canSubmit = items.length > 0 && !createMut.isPending

  const cols = CSV_COLUMNS[contentType]

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
        <label style={label}>{TERM_LABEL[contentType]}s</label>
        <textarea value={raw} onChange={e => setRaw(e.target.value)} rows={6}
          placeholder={TERM_PLACEHOLDER[contentType]}
          style={{ ...input, resize: 'vertical', fontFamily: 'inherit' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, flexWrap: 'wrap' }}>
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
          CSV columns (with headers): {cols.map((c, i) => `${String.fromCharCode(65 + i)} = ${c}`).join(' · ')}
        </div>
      </div>

      {terms.length > 0 && (
        <div>
          <label style={label}>
            Per-page details{isLocalSeo ? ' — Service required, Notes optional' : ' — Notes optional'}
          </label>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            {isLocalSeo && (
              <>
                <input value={allService} onChange={e => setAllService(e.target.value)}
                  placeholder="Service for all rows, e.g. blocked drains" style={input} />
                <button type="button" style={outlineBtn}
                  onClick={() => applyAll(allService, setServiceByTerm)}>Apply service to all</button>
              </>
            )}
            <input value={allNotes} onChange={e => setAllNotes(e.target.value)}
              placeholder="Notes for all rows (optional)" style={input} />
            <button type="button" style={outlineBtn}
              onClick={() => applyAll(allNotes, setNotesByTerm)}>Apply notes to all</button>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
            {terms.map(term => {
              const k = term.toLowerCase()
              return (
                <div key={term} style={{
                  display: 'grid',
                  gridTemplateColumns: isLocalSeo ? '1fr 1fr 1.4fr' : '1fr 1.6fr',
                  gap: 8,
                }}>
                  <span style={{ fontSize: 13, color: '#0f172a', alignSelf: 'center' }}>{term}</span>
                  {isLocalSeo && (
                    <input value={serviceByTerm[k] ?? ''}
                      onChange={e => setServiceByTerm(prev => ({ ...prev, [k]: e.target.value }))}
                      placeholder="service" style={{ ...input, padding: '7px 10px' }} />
                  )}
                  <input value={notesByTerm[k] ?? ''}
                    onChange={e => setNotesByTerm(prev => ({ ...prev, [k]: e.target.value }))}
                    placeholder="notes (optional)" style={{ ...input, padding: '7px 10px' }} />
                </div>
              )
            })}
          </div>
          {isLocalSeo && items.length < terms.length && (
            <div style={{ fontSize: 12, color: '#b45309', marginTop: 6 }}>
              {terms.length - items.length} location{terms.length - items.length === 1 ? '' : 's'} with no
              service will be skipped.
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
