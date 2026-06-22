import { toTitleCase } from './sectionsToMarkdown'

// Self-contained Markdown→HTML for the writer's article sections. We render
// the HTML structurally from the section list (headings come from the
// section level/heading) and convert each section's Markdown body with a
// small, scoped converter covering exactly what the writer emits:
// paragraphs, unordered/ordered lists, GFM tables, blockquotes, and inline
// bold / italic / links / code. No external dependency (mirrors the
// hand-rolled sectionsToMarkdown).

const HEADING_TAG: Record<string, string> = {
  H1: 'h1', H2: 'h2', H3: 'h3', H4: 'h4', H5: 'h5', H6: 'h6',
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/"/g, '&quot;')
}

// Inline Markdown → HTML. Escapes first, then applies links, bold, italic,
// and inline code (order matters so markers aren't clobbered by escaping).
function inline(text: string): string {
  let out = escapeHtml(text)
  // [label](url)
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, label, url) => `<a href="${escapeAttr(url)}">${label}</a>`)
  // **bold** (before *italic*)
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // *italic* / _italic_
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  out = out.replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>')
  // `code`
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  return out
}

const UL_RE = /^\s*[-*+]\s+/
const OL_RE = /^\s*\d+\.\s+/
const BQ_RE = /^\s*>\s?/
const TABLE_SEP_RE = /^\s*\|?[\s:|-]+\|[\s:|-]*$/

function tableRowCells(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim())
}

// One Markdown block (already split on blank lines) → an HTML block.
function blockToHtml(block: string): string {
  const lines = block.split('\n').filter(l => l.trim() !== '')
  if (lines.length === 0) return ''

  // GFM table: header row + separator row (---|---) + body rows.
  if (lines.length >= 2 && lines[0].includes('|') && TABLE_SEP_RE.test(lines[1])) {
    const headers = tableRowCells(lines[0])
    const rows = lines.slice(2).map(tableRowCells)
    const thead = `<thead><tr>${headers.map(h => `<th>${inline(h)}</th>`).join('')}</tr></thead>`
    const tbody = `<tbody>${rows.map(r =>
      `<tr>${r.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody>`
    return `<table>${thead}${tbody}</table>`
  }

  if (lines.every(l => UL_RE.test(l))) {
    return `<ul>${lines.map(l => `<li>${inline(l.replace(UL_RE, ''))}</li>`).join('')}</ul>`
  }
  if (lines.every(l => OL_RE.test(l))) {
    return `<ol>${lines.map(l => `<li>${inline(l.replace(OL_RE, ''))}</li>`).join('')}</ol>`
  }
  if (lines.every(l => BQ_RE.test(l))) {
    return `<blockquote><p>${inline(lines.map(l => l.replace(BQ_RE, '')).join(' '))}</p></blockquote>`
  }
  // Default: a paragraph (soft line breaks within the block join with a space).
  return `<p>${inline(lines.join(' '))}</p>`
}

function bodyToHtml(md: string): string {
  return (md ?? '')
    .split(/\n{2,}/)
    .map(b => b.trim())
    .filter(Boolean)
    .map(blockToHtml)
    .join('\n')
}

export function sectionsToHtml(article: unknown[], title?: string): string {
  if (!Array.isArray(article)) return ''

  const sorted = article
    .slice()
    .sort((a: any, b: any) => (a.order ?? 0) - (b.order ?? 0))

  const parts: string[] = []
  if (title) parts.push(`<h1>${escapeHtml(toTitleCase(title))}</h1>`)

  for (const s of sorted as any[]) {
    if (title && s.level === 'H1' && !(s.body ?? '').trim()) continue

    if (s.type === 'key-takeaways') {
      const body = (s.body ?? '').trim()
      if (body) parts.push(`<h2>Key Takeaways</h2>\n${bodyToHtml(body)}`)
      continue
    }

    const tag = HEADING_TAG[s.level] ?? ''
    const heading = s.heading ? `<${tag}>${escapeHtml(toTitleCase(s.heading))}</${tag}>` : ''
    const body = s.body ? bodyToHtml(s.body) : ''

    if (heading && body) parts.push(`${heading}\n${body}`)
    else if (heading) parts.push(heading)
    else if (body) parts.push(body)
  }

  return parts.join('\n')
}
