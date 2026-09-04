// Shared date/time formatting helpers.
//
// The agency operates on Pacific time, so notification timestamps are shown in
// PST/PDT (America/Los_Angeles) regardless of the viewer's own timezone — a
// failed GBP post at "8/11/2026, 2:05 PM PDT" reads the same for everyone on
// the team. The zone abbreviation is appended so the timezone is unambiguous.

const PT_ZONE = 'America/Los_Angeles'

// Date + time in Pacific time, e.g. "8/11/2026, 2:05 PM PDT".
export function formatPacificDateTime(value: string | number | Date): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const formatted = d.toLocaleString(undefined, {
    timeZone: PT_ZONE,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  return `${formatted} ${pacificAbbrev(d)}`
}

// The Pacific timezone abbreviation (PST or PDT) for a given instant.
function pacificAbbrev(d: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: PT_ZONE,
    timeZoneName: 'short',
  }).formatToParts(d)
  return parts.find(p => p.type === 'timeZoneName')?.value ?? 'PT'
}
