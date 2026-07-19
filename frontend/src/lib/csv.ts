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

// Split a full CSV line into fields, honoring double-quoted fields with embedded
// commas and doubled ("") quotes. RFC-4180-ish.
function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') { cur += '"'; i++; continue }
        inQuotes = false; continue
      }
      cur += c
      continue
    }
    if (c === '"') { inQuotes = true; continue }
    if (c === ',') { out.push(cur); cur = ''; continue }
    cur += c
  }
  out.push(cur)
  return out
}

// Recognized header labels — used only to detect + skip a header row. The
// standardized Content Scheduler CSV requires headers, but the parser stays
// tolerant of a header-less file (a first row that isn't a known label is data).
const _SCHED_HEADER_TOKENS = new Set([
  'keyword', 'keywords', 'term', 'terms', 'query', 'queries',
  'location', 'locations', 'service', 'services', 'product', 'products',
  'notes', 'note',
])

export interface SchedulerCsvRow {
  term: string          // column A (keyword / service / location / product)
  service?: string      // local_seo_page only — column B
  notes?: string        // free-text writing guidance
}

// The standardized Content Scheduler CSV. Column A is the head term (its meaning
// depends on the page type: Keyword / Service / Location / Product). Notes is the
// last column; Local SEO pages carry an extra Service column between them:
//   blog_post / service_page / location_page / ecommerce : A=term,     B=Notes
//   local_seo_page                                        : A=Location, B=Service, C=Notes
export function parseSchedulerCsv(text: string, contentType: string): SchedulerCsvRow[] {
  const isLocalSeo = contentType === 'local_seo_page'
  const out: SchedulerCsvRow[] = []
  const seen = new Set<string>()
  text.split(/\r\n|\r|\n/).forEach((line, idx) => {
    if (!line.trim()) return
    const cols = splitCsvLine(line).map(c => c.trim())
    const term = cols[0] ?? ''
    if (idx === 0 && _SCHED_HEADER_TOKENS.has(term.toLowerCase())) return // header row
    if (!term) return
    const row: SchedulerCsvRow = { term }
    if (isLocalSeo) {
      const svc = (cols[1] ?? '').replace(/[|;]/g, ', ').trim()
      const notes = (cols[2] ?? '').trim()
      if (svc) row.service = svc
      if (notes) row.notes = notes
    } else {
      const notes = (cols[1] ?? '').trim()
      if (notes) row.notes = notes
    }
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
