import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { TaskItem } from '../../lib/types'

// Month-grid calendar: tasks placed on their due dates (PRD §6.6).
// Dependency-free; click a task chip to open its drawer.

interface TaskCalendarProps {
  tasks: TaskItem[]
  onSelect: (taskId: string) => void
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function TaskCalendar({ tasks, onSelect }: TaskCalendarProps) {
  const [anchor, setAnchor] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })

  const byDay: Record<string, TaskItem[]> = {}
  for (const t of tasks) {
    if (t.due_date) (byDay[t.due_date] ??= []).push(t)
  }

  // Build the grid: start on the Monday on/before the 1st, end on the Sunday
  // on/after the last day.
  const first = new Date(anchor)
  const start = new Date(first)
  start.setDate(first.getDate() - ((first.getDay() + 6) % 7))
  const cells: Date[] = []
  const cursor = new Date(start)
  do {
    cells.push(new Date(cursor))
    cursor.setDate(cursor.getDate() + 1)
  } while (cursor.getMonth() === anchor.getMonth() || cells.length % 7 !== 0)

  const todayKey = ymd(new Date())
  const monthLabel = anchor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })

  const navBtn: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', padding: '5px 8px', borderRadius: 7,
    border: '1px solid #e2e8f0', background: '#fff', color: '#334155', cursor: 'pointer',
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <button onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))} style={navBtn}>
          <ChevronLeft size={14} />
        </button>
        <button onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))} style={navBtn}>
          <ChevronRight size={14} />
        </button>
        <button
          onClick={() => { const now = new Date(); setAnchor(new Date(now.getFullYear(), now.getMonth(), 1)) }}
          style={{ ...navBtn, fontSize: 12, fontWeight: 600 }}
        >
          Today
        </button>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', marginLeft: 4 }}>{monthLabel}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 1, background: '#e2e8f0', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
        {WEEKDAYS.map((w) => (
          <div key={w} style={{ background: '#f8fafc', padding: '6px 8px', fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
            {w}
          </div>
        ))}
        {cells.map((d) => {
          const key = ymd(d)
          const inMonth = d.getMonth() === anchor.getMonth()
          const dayTasks = byDay[key] ?? []
          return (
            <div key={key} style={{ background: inMonth ? '#fff' : '#fbfcfe', minHeight: 92, padding: 6 }}>
              <div style={{ fontSize: 11, fontWeight: key === todayKey ? 800 : 500, color: key === todayKey ? '#4f46e5' : inMonth ? '#64748b' : '#cbd5e1', marginBottom: 4 }}>
                {d.getDate()}
              </div>
              {dayTasks.slice(0, 4).map((t) => (
                <div
                  key={t.id}
                  onClick={() => onSelect(t.id)}
                  title={t.name}
                  style={{
                    fontSize: 11, fontWeight: 600, padding: '2px 6px', borderRadius: 6, marginBottom: 3,
                    cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    background: t.completed ? '#f0fdf4' : key < todayKey ? '#fef2f2' : '#eef2ff',
                    color: t.completed ? '#15803d' : key < todayKey ? '#b91c1c' : '#4f46e5',
                    textDecoration: t.completed ? 'line-through' : 'none',
                  }}
                >
                  {t.name}
                </div>
              ))}
              {dayTasks.length > 4 && (
                <div style={{ fontSize: 10, color: '#94a3b8' }}>+{dayTasks.length - 4} more</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
