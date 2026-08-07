import { ContentCalendar as CalendarGrid } from '../components/scheduler/ContentCalendar'

// Agency-wide content calendar: every piece of scheduled content across all
// clients, on the day it's set to generate — suite Content Scheduler items and
// Topic Fan-out runs alike. The per-client version lives inside each client's
// Content Scheduler page; this is the whole-agency read.

export function ContentCalendar() {
  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
        Content Calendar
      </h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Everything scheduled to generate across every client — Content Scheduler batches and
        Topic Fan-out runs — on the day it runs. Click a day to see the details.
      </p>
      <CalendarGrid scope="agency" />
    </div>
  )
}
