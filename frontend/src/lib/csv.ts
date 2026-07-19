// Minimal CSV builder + browser download. RFC-4180-ish quoting: wrap a field in
// double quotes when it contains a comma, quote, or newline, and double any
// internal quotes.
function escapeCell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const s = String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(headers: string[], rows: (string | number | null)[][]): string {
  const lines = [headers, ...rows].map(row => row.map(escapeCell).join(','))
  return lines.join('\n')
}

// First field of a CSV line, handling a leading quoted field with embedded
// commas / doubled quotes.
function firstCsvField(line: string): string {
  if (line[0] === '"') {
    let i = 1
    let val = ''
    while (i < line.length) {
      const c = line[i]
      if (c === '"') {
        if (line[i + 1] === '"') { val += '"'; i += 2; continue }
        break
      }
      val += c
      i++
    }
    return val
  }
  const comma = line.indexOf(',')
  return comma === -1 ? line : line.slice(0, comma)
}

const _CSV_HEADER_NAMES = new Set(['keyword', 'keywords', 'term', 'terms', 'query', 'queries'])

// Extract keywords from an uploaded CSV: the first column of each row, skipping
// blanks, a header row, and case-insensitive duplicates. Tolerant of a plain
// one-keyword-per-line list too.
export function parseKeywordsFromCsv(text: string): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  text.split(/\r\n|\r|\n/).forEach((line, idx) => {
    if (!line.trim()) return
    const value = firstCsvField(line).trim()
    if (!value) return
    if (idx === 0 && _CSV_HEADER_NAMES.has(value.toLowerCase())) return
    const key = value.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(value)
  })
  return out
}

// Tokenize a full CSV document into records (rows) of fields, honoring
// double-quoted fields — including embedded commas, doubled ("") quotes, AND
// embedded newlines (a quoted cell can span lines, which Excel/Sheets produce
// whenever a cell contains a line break). A record only ends on a newline that is
// NOT inside quotes. Fully-blank records are dropped. RFC-4180-ish.
function parseCsvRecords(text: string): string[][] {
  const records: string[][] = []
  let field = ''
  let record: string[] = []
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ }   // escaped quote
        else inQuotes = false                            // closing quote
      } else if (c !== '\r') {                            // keep \n, drop lone \r
        field += c
      }
      continue
    }
    if (c === '"') inQuotes = true
    else if (c === ',') { record.push(field); field = '' }
    else if (c === '\n') { record.push(field); records.push(record); field = ''; record = [] }
    else if (c !== '\r') field += c                       // ignore CR outside quotes
  }
  record.push(field)
  records.push(record)
  // Drop fully-blank records (trailing newline, blank lines).
  return records.filter(r => r.some(f => f.trim() !== ''))
}

// Recognized header labels — used only to detect + skip a header row. The
// standardized Content Scheduler CSV requires headers, but the parser stays
// tolerant of a header-less file (a first row that isn't a known label is data).
const _SCHED_HEADER_TOKENS = new Set([
  'keyword', 'keywords', 'term', 'terms', 'query', 'queries',
  'location', 'locations', 'service', 'services', 'product', 'products',
  'notes', 'note', 'date', 'dates',
])

export interface SchedulerCsvRow {
  term: string          // column A (keyword / service / location / product)
  service?: string      // local_seo_page only — column B
  notes?: string        // free-text writing guidance
  date?: string         // column D — ISO YYYY-MM-DD; when to generate + publish
}

// Validate + normalize an ISO date (YYYY-MM-DD). Returns the canonical string or
// undefined for anything that isn't a real calendar date, so a typo in the CSV
// silently falls back to the batch schedule instead of corrupting the calendar.
export function parseIsoDate(raw: string): string | undefined {
  const s = (raw || '').trim()
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return undefined
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const dt = new Date(Date.UTC(y, mo - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) {
    return undefined  // e.g. 2026-02-30
  }
  return s
}

// The standardized Content Scheduler CSV. Column A is the head term (its meaning
// depends on the page type: Keyword / Service / Location / Product). Notes is
// column B (or C for Local SEO, which adds a Service column). The optional
// publish Date is ALWAYS column D (index 3), so column C is unused for the types
// that have no Service column:
//   blog_post / service_page / location_page / ecommerce : A=term,     B=Notes,             D=Date
//   local_seo_page                                        : A=Location, B=Service, C=Notes,  D=Date
export function parseSchedulerCsv(text: string, contentType: string): SchedulerCsvRow[] {
  const isLocalSeo = contentType === 'local_seo_page'
  const out: SchedulerCsvRow[] = []
  const seen = new Set<string>()
  parseCsvRecords(text).forEach((cols, idx) => {
    const c = cols.map(x => x.trim())
    const term = c[0] ?? ''
    if (idx === 0 && _SCHED_HEADER_TOKENS.has(term.toLowerCase())) return // header row
    if (!term) return
    const row: SchedulerCsvRow = { term }
    if (isLocalSeo) {
      const svc = (c[1] ?? '').replace(/[|;]/g, ', ').trim()
      const notes = (c[2] ?? '').trim()
      if (svc) row.service = svc
      if (notes) row.notes = notes
    } else {
      const notes = (c[1] ?? '').trim()
      if (notes) row.notes = notes
    }
    const date = parseIsoDate(c[3] ?? '')  // column D — always, for every type
    if (date) row.date = date
    // Identity: term (+ service for local SEO, since one location can host many
    // services). Case-insensitive de-dupe.
    const key = `${term}|${row.service ?? ''}`.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(row)
  })
  return out
}

export function downloadCsv(filename: string, csv: string): void {
  // Prepend a BOM so Excel detects UTF-8.
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
