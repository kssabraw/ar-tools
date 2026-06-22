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
