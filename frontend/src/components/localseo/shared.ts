import type { CSSProperties } from 'react'

// ── Score helpers ───────────────────────────────────────────────────────────

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return '#94a3b8'
  if (score >= 80) return '#16a34a'
  if (score >= 60) return '#d97706'
  return '#dc2626'
}

export function scoreBg(score: number | null | undefined): string {
  if (score == null) return '#f1f5f9'
  if (score >= 80) return '#f0fdf4'
  if (score >= 60) return '#fffbeb'
  return '#fef2f2'
}

export function scoreBorder(score: number | null | undefined): string {
  if (score == null) return '#e2e8f0'
  if (score >= 80) return '#bbf7d0'
  if (score >= 60) return '#fde68a'
  return '#fecaca'
}

export function statusLabel(status: string | null | undefined): string {
  if (!status) return ''
  return status.replace(/_/g, ' ')
}

// ── HTML pretty-printer (ported verbatim from ShowUP — framework-agnostic) ───

export function formatHtml(html: string): string {
  const INDENT = '  '
  const BLOCK = new Set([
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'div', 'section', 'article', 'header', 'footer', 'nav', 'main', 'aside',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
    'blockquote', 'pre', 'figure', 'figcaption', 'script', 'style',
    'form', 'fieldset', 'details', 'summary',
  ])
  const SPACER = new Set([
    'section', 'article', 'header', 'footer', 'nav', 'main', 'aside',
    'div', 'table', 'ul', 'ol', 'blockquote', 'figure',
    'h1', 'h2', 'h3',
  ])
  const VOID = new Set([
    'br', 'hr', 'img', 'input', 'link', 'meta',
    'area', 'base', 'col', 'embed', 'param', 'source', 'track', 'wbr',
  ])

  function serialize(node: Node, depth: number): string {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.textContent ?? '').replace(/\s+/g, ' ').trim()
      return text ? INDENT.repeat(depth) + text : ''
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const el = node as Element
    const tag = el.tagName.toLowerCase()
    const attrs = Array.from(el.attributes).map(a => ` ${a.name}="${a.value}"`).join('')
    const pad = INDENT.repeat(depth)
    const spacer = SPACER.has(tag) ? '\n' : ''

    if (VOID.has(tag)) return `${spacer}${pad}<${tag}${attrs}>`

    const children = Array.from(el.childNodes)
    const hasBlockChild = children.some(
      c => c.nodeType === Node.ELEMENT_NODE && BLOCK.has((c as Element).tagName.toLowerCase()),
    )

    if (!hasBlockChild) {
      const inner = el.innerHTML.replace(/\s+/g, ' ').trim()
      return `${spacer}${pad}<${tag}${attrs}>${inner}</${tag}>`
    }

    const childLines = children
      .map(c => serialize(c, depth + 1))
      .filter(s => s.trim() !== '')
    return `${spacer}${pad}<${tag}${attrs}>\n${childLines.join('\n')}\n${pad}</${tag}>`
  }

  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
  const lines = Array.from(doc.body.childNodes)
    .map(n => serialize(n, 0))
    .filter(s => s.trim() !== '')

  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

export function htmlToText(html: string): string {
  return new DOMParser().parseFromString(html, 'text/html').body.innerText
}

export function wordCount(html: string): number {
  return (html ?? '').replace(/<[^>]+>/g, ' ').split(/\s+/).filter(Boolean).length
}

export function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Shared inline styles (suite palette) ─────────────────────────────────────

export const card: CSSProperties = {
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 24,
}

export const label: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: '#0f172a',
  display: 'block',
  marginBottom: 6,
}

export const input: CSSProperties = {
  width: '100%',
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 8,
  padding: '10px 12px',
  fontSize: 14,
  color: '#0f172a',
  outline: 'none',
}

export const primaryBtn: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  background: '#6366f1',
  color: '#fff',
  border: 'none',
  borderRadius: 8,
  padding: '11px 16px',
  fontSize: 14,
  fontWeight: 600,
  cursor: 'pointer',
}

export const outlineBtn: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  background: '#fff',
  color: '#0f172a',
  border: '1px solid #e2e8f0',
  borderRadius: 8,
  padding: '9px 14px',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
}

export const errorBox: CSSProperties = {
  background: '#fef2f2',
  border: '1px solid #fecaca',
  borderRadius: 8,
  padding: '10px 14px',
  fontSize: 13,
  color: '#991b1b',
}

export const backLink: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  color: '#6366f1',
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 13,
  padding: 0,
  marginBottom: 8,
}
