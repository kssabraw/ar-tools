import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, ExternalLink, GitBranch, Loader2 } from 'lucide-react'
import { card } from '../localseo/shared'
import {
  CONTENT_TYPE_LABEL,
  schedulerApi,
  type CalendarItem,
  type ContentType,
  type ItemStatus,
} from './api'

// A month-grid view of exactly what content is scheduled to generate on which
// day, across BOTH the suite Content Scheduler and the Topic Fan-out scheduler.
// scope='client' shows one client (in its workspace); scope='agency' shows every
// client at once (the sidebar Content Calendar page), labelling each item with
// its client.

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// Chips are coloured by content type (what kind of page), with a small status
// dot (where it is in its lifecycle). A calendar answers "what runs when", so the
// content type is the primary signal.
const TYPE_STYLE: Record<string, { bg: string; fg: string }> = {
  blog_post: { bg: '#eef2ff', fg: '#4338ca' },
  service_page: { bg: '#ecfdf5', fg: '#047857' },
  location_page: { bg: '#fffbeb', fg: '#b45309' },
  local_seo_page: { bg: '#eff6ff', fg: '#1d4ed8' },
  ecommerce: { bg: '#fdf2f8', fg: '#be185d' },
}
const TYPE_FALLBACK = { bg: '#f1f5f9', fg: '#475569' }

const STATUS_DOT: Record<ItemStatus, string> = {
  scheduled: '#94a3b8',
  queued: '#3b82f6',
  running: '#6366f1',
  complete: '#16a34a',
  failed: '#dc2626',
  cancelled: '#cbd5e1',
}
const STATUS_LABEL: Record<ItemStatus, string> = {
  scheduled: 'Scheduled', queued: 'Queued', running: 'Writing',
  complete: 'Generated', failed: 'Failed', cancelled: 'Cancelled',
}

function typeStyle(t: string) {
  return TYPE_STYLE[t] ?? TYPE_FALLBACK
}
function typeLabel(t: string): string {
  return CONTENT_TYPE_LABEL[t as ContentType] ?? t.replace(/_/g, ' ')
}

/** Local 'YYYY-MM-DD' key for a Date (the day the item shows on, in the viewer's
 *  timezone — matching how the rest of the app renders scheduled times). */
function dayKey(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function itemDayKey(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : dayKey(d)
}

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** The 42-day (6-week) Sunday-anchored grid covering `anchor`'s month. */
function monthGrid(anchor: Date): Date[] {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const start = new Date(first)
  start.setDate(1 - first.getDay())
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    return d
  })
}

function Chip({ it, showClient }: { it: CalendarItem; showClient: boolean }) {
  const st = typeStyle(it.content_type)
  const parts = [showClient && it.client_name, it.label].filter(Boolean).join(' · ')
  return (
    <div
      title={`${fmtTime(it.scheduled_at)} · ${typeLabel(it.content_type)} · ${STATUS_LABEL[it.status] ?? it.status}${it.client_name ? ` · ${it.client_name}` : ''}\n${it.label}`}
      style={{
        display: 'flex', alignItems: 'center', gap: 4, padding: '2px 6px',
        borderRadius: 5, background: st.bg, color: st.fg, fontSize: 11,
        fontWeight: 600, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
      }}
    >
      <span style={{
        width: 6, height: 6, borderRadius: 999, background: STATUS_DOT[it.status] ?? '#94a3b8',
        flexShrink: 0,
      }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{parts || it.label}</span>
    </div>
  )
}

const MAX_CHIPS = 3

export function ContentCalendar({
  scope, clientId,
}: { scope: 'client' | 'agency'; clientId?: string }) {
  const [anchor, setAnchor] = useState(() => new Date())
  const [selected, setSelected] = useState<string | null>(null)

  const grid = useMemo(() => monthGrid(anchor), [anchor])
  const rangeStart = dayKey(grid[0])
  const rangeEnd = dayKey(grid[grid.length - 1])
  const monthLabel = anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })

  const q = useQuery({
    queryKey: ['content-calendar', scope, clientId ?? 'agency', rangeStart, rangeEnd],
    queryFn: () =>
      scope === 'agency'
        ? schedulerApi.agencyCalendar(rangeStart, rangeEnd)
        : schedulerApi.clientCalendar(clientId!, rangeStart, rangeEnd),
    enabled: scope === 'agency' || Boolean(clientId),
    refetchInterval: 30000,
  })

  // Bucket every item onto its local day.
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>()
    for (const it of q.data?.items ?? []) {
      const k = itemDayKey(it.scheduled_at)
      if (!k) continue
      const arr = map.get(k)
      if (arr) arr.push(it)
      else map.set(k, [it])
    }
    return map
  }, [q.data])

  const todayKey = dayKey(new Date())
  const showClient = scope === 'agency'
  const total = q.data?.items?.length ?? 0
  const selectedItems = selected ? byDay.get(selected) ?? [] : []

  const goMonth = (delta: number) => {
    setSelected(null)
    setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1))
  }
  const goToday = () => { setSelected(null); setAnchor(new Date()) }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Header: month nav + count */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button onClick={() => goMonth(-1)} aria-label="Previous month" style={navBtn}>
            <ChevronLeft size={16} />
          </button>
          <button onClick={() => goMonth(1)} aria-label="Next month" style={navBtn}>
            <ChevronRight size={16} />
          </button>
        </div>
        <strong style={{ fontSize: 16, color: '#0f172a', minWidth: 150 }}>{monthLabel}</strong>
        <button onClick={goToday} style={{ ...navBtn, width: 'auto', padding: '5px 12px', fontSize: 13 }}>
          Today
        </button>
        <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {q.isFetching && <Loader2 size={12} className="spin" />}
          {total} scheduled this view
        </span>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 11, color: '#64748b' }}>
        {(Object.keys(TYPE_STYLE) as string[]).map(t => {
          const st = typeStyle(t)
          return (
            <span key={t} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: st.bg, border: `1px solid ${st.fg}33` }} />
              {typeLabel(t)}
            </span>
          )
        })}
      </div>

      {q.isError && (
        <div style={{ ...card, color: '#b91c1c', fontSize: 13 }}>Couldn't load the calendar.</div>
      )}

      {/* Weekday header */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 6 }}>
        {WEEKDAYS.map(w => (
          <div key={w} style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textAlign: 'center', padding: '2px 0' }}>
            {w}
          </div>
        ))}
      </div>

      {/* The grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 6 }}>
        {grid.map(d => {
          const k = dayKey(d)
          const items = byDay.get(k) ?? []
          const inMonth = d.getMonth() === anchor.getMonth()
          const isToday = k === todayKey
          const isSelected = k === selected
          const extra = items.length - MAX_CHIPS
          return (
            <button
              key={k}
              onClick={() => setSelected(items.length ? (isSelected ? null : k) : null)}
              style={{
                textAlign: 'left', border: isSelected ? '2px solid #6366f1' : '1px solid #e2e8f0',
                borderRadius: 8, background: inMonth ? '#fff' : '#f8fafc',
                minHeight: 92, padding: 6, display: 'flex', flexDirection: 'column', gap: 3,
                cursor: items.length ? 'pointer' : 'default',
                opacity: inMonth ? 1 : 0.6,
              }}
            >
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                fontSize: 12, fontWeight: 700,
                color: isToday ? '#4338ca' : inMonth ? '#334155' : '#94a3b8',
              }}>
                <span style={isToday ? {
                  background: '#6366f1', color: '#fff', borderRadius: 999,
                  width: 20, height: 20, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                } : undefined}>{d.getDate()}</span>
                {items.length > 0 && (
                  <span style={{ fontSize: 10, color: '#94a3b8', fontWeight: 600 }}>{items.length}</span>
                )}
              </div>
              {items.slice(0, MAX_CHIPS).map(it => (
                <Chip key={`${it.source}:${it.item_id}`} it={it} showClient={showClient} />
              ))}
              {extra > 0 && (
                <span style={{ fontSize: 10, color: '#64748b', fontWeight: 600, paddingLeft: 2 }}>
                  +{extra} more
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Selected-day detail list */}
      {selected && (
        <div style={{ ...card, padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <strong style={{ fontSize: 14, color: '#0f172a' }}>
              {new Date(selected + 'T00:00:00').toLocaleDateString(undefined, {
                weekday: 'long', month: 'long', day: 'numeric',
              })}
            </strong>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>{selectedItems.length} scheduled</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {selectedItems.map(it => {
              const st = typeStyle(it.content_type)
              return (
                <div key={`${it.source}:${it.item_id}`} style={{
                  display: 'grid',
                  gridTemplateColumns: showClient ? '64px 1fr 130px 100px' : '64px 1fr 130px',
                  alignItems: 'center', gap: 10, padding: '7px 8px', borderRadius: 6,
                  background: '#fff', border: '1px solid #f1f5f9', fontSize: 13,
                }}>
                  <span style={{ color: '#64748b', fontSize: 12 }}>{fmtTime(it.scheduled_at)}</span>
                  <span style={{ color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={it.label}>
                    {it.label}
                    {it.location ? <span style={{ color: '#94a3b8' }}> · {it.location}</span> : null}
                  </span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 999, background: st.bg, color: st.fg }}>
                      {typeLabel(it.content_type)}
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11, color: '#64748b' }}
                      title={`${STATUS_LABEL[it.status] ?? it.status} · ${it.source === 'fanout' ? 'Fan-out' : 'Content Scheduler'}`}>
                      <span style={{ width: 7, height: 7, borderRadius: 999, background: STATUS_DOT[it.status] ?? '#94a3b8' }} />
                      {STATUS_LABEL[it.status] ?? it.status}
                    </span>
                    {it.source === 'fanout'
                      ? <GitBranch size={11} color="#16a34a" aria-label="Fan-out" />
                      : null}
                  </span>
                  {showClient && (
                    it.client_id ? (
                      <Link to={`/clients/${it.client_id}`} style={{ fontSize: 12, color: '#4338ca', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {it.client_name ?? 'Client'} <ExternalLink size={10} />
                      </Link>
                    ) : <span style={{ fontSize: 12, color: '#94a3b8' }}>{it.client_name ?? '—'}</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

const navBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  width: 30, height: 30, borderRadius: 8, border: '1px solid #e2e8f0',
  background: '#fff', color: '#334155', cursor: 'pointer',
}
