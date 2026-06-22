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
