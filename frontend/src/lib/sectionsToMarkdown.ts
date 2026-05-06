const TITLE_CASE_MINOR_WORDS = new Set([
  'a', 'an', 'the',
  'and', 'as', 'but', 'for', 'if', 'nor', 'or', 'so', 'yet',
  'at', 'by', 'in', 'of', 'off', 'on', 'per', 'to', 'up', 'via', 'vs',
])

export function toTitleCase(str: string): string {
  if (!str) return str
  const tokens = str.split(/(\s+)/)
  const wordPositions: number[] = []
  tokens.forEach((t, i) => { if (t.trim()) wordPositions.push(i) })
  if (wordPositions.length === 0) return str
  const firstIdx = wordPositions[0]
  const lastIdx = wordPositions[wordPositions.length - 1]
  return tokens.map((piece, i) => {
    if (!piece.trim()) return piece
    if (/[a-z][A-Z]/.test(piece)) return piece
    if (piece.length >= 2 && piece === piece.toUpperCase() && /[A-Z]/.test(piece)) return piece
    const isFirstOrLast = i === firstIdx || i === lastIdx
    const cleaned = piece.toLowerCase().replace(/[^a-z']/g, '')
    if (!isFirstOrLast && TITLE_CASE_MINOR_WORDS.has(cleaned)) {
      return piece.toLowerCase()
    }
    return piece.replace(/^([^A-Za-z]*)([A-Za-z])(.*)$/, (_m, lead, first, rest) =>
      lead + first.toUpperCase() + rest.toLowerCase()
    )
  }).join('')
}

const HEADING_PREFIX: Record<string, string> = {
  H1: '# ',
  H2: '## ',
  H3: '### ',
  H4: '#### ',
  H5: '##### ',
  H6: '###### ',
}

export function sectionsToMarkdown(article: unknown[], title?: string): string {
  if (!Array.isArray(article)) return ''

  const sorted = article
    .slice()
    .sort((a: any, b: any) => (a.order ?? 0) - (b.order ?? 0))

  const parts: string[] = []
  if (title) parts.push(`# ${toTitleCase(title)}`)

  for (const s of sorted as any[]) {
    // Skip the H1 section body if we've already rendered the title
    if (title && s.level === 'H1' && !(s.body ?? '').trim()) continue

    // key-takeaways has level="none" but must always render as ## heading
    if (s.type === 'key-takeaways') {
      const body = (s.body ?? '').trim()
      if (body) parts.push(`## Key Takeaways\n\n${body}`)
      continue
    }

    const prefix = HEADING_PREFIX[s.level] ?? ''
    const heading = s.heading ? `${prefix}${toTitleCase(s.heading)}` : ''
    const body = s.body ?? ''

    if (heading && body) parts.push(`${heading}\n\n${body}`)
    else if (heading) parts.push(heading)
    else if (body) parts.push(body)
  }

  return parts.join('\n\n')
}
