import type { CSSProperties, ReactNode } from 'react'

// Dependency-free Markdown renderer for the suite (no react-markdown / marked).
// Parses a constrained GFM subset into real React elements (never
// dangerouslySetInnerHTML): #/##/### headings, **bold**, `* `/`- ` bullet lists,
// pipe tables with a `|---|` separator (and per-column `:` right-align), `---`
// horizontal rules, and blank-line-separated paragraphs. Emojis render as text.

const h1: CSSProperties = { fontSize: 20, fontWeight: 700, color: '#0f172a', margin: '20px 0 10px' }
const h2: CSSProperties = { fontSize: 16, fontWeight: 600, color: '#0f172a', margin: '18px 0 8px' }
const h3: CSSProperties = { fontSize: 14, fontWeight: 600, color: '#0f172a', margin: '14px 0 6px' }
const pStyle: CSSProperties = { fontSize: 13, color: '#334155', lineHeight: 1.6, margin: '0 0 10px' }
const ulStyle: CSSProperties = { fontSize: 13, color: '#334155', lineHeight: 1.6, margin: '0 0 10px', paddingLeft: 20 }
const hrStyle: CSSProperties = { border: 'none', borderTop: '1px solid #e2e8f0', margin: '16px 0' }
const tableStyle: CSSProperties = { borderCollapse: 'collapse', width: '100%', margin: '0 0 12px', fontSize: 12.5 }
const thBase: CSSProperties = { border: '1px solid #e2e8f0', padding: '6px 10px', fontWeight: 600, color: '#0f172a', background: '#f8fafc' }
const tdBase: CSSProperties = { border: '1px solid #e2e8f0', padding: '6px 10px', color: '#334155' }

// Inline: split a string on **bold** spans into <strong> + text nodes.
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\*\*([^*]+)\*\*/g
  let last = 0
  let m: RegExpExecArray | null
  let key = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(<strong key={`b${key++}`}>{m[1]}</strong>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

// Split a GFM table row "| a | b |" into trimmed cell strings.
function splitRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map(c => c.trim())
}

const isTableLine = (l: string) => l.trim().startsWith('|')
const isSeparatorRow = (l: string) => /^\s*\|?[\s:|-]+\|?\s*$/.test(l) && l.includes('-')

export function Markdown({ children }: { children: string }): React.ReactElement | null {
  if (!children || !children.trim()) return null

  const lines = children.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let key = 0
  let i = 0

  // Accumulate consecutive non-blank lines into a paragraph.
  let para: string[] = []
  const flushPara = () => {
    if (para.length === 0) return
    blocks.push(<p key={`p${key++}`} style={pStyle}>{inline(para.join(' '))}</p>)
    para = []
  }

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Blank line ends a paragraph.
    if (trimmed === '') {
      flushPara()
      i += 1
      continue
    }

    // Horizontal rule (--- alone on a line).
    if (/^-{3,}$/.test(trimmed)) {
      flushPara()
      blocks.push(<hr key={`hr${key++}`} style={hrStyle} />)
      i += 1
      continue
    }

    // Headings.
    const hm = /^(#{1,3})\s+(.*)$/.exec(trimmed)
    if (hm) {
      flushPara()
      const level = hm[1].length
      const content = inline(hm[2])
      if (level === 1) blocks.push(<h1 key={`h${key++}`} style={h1}>{content}</h1>)
      else if (level === 2) blocks.push(<h2 key={`h${key++}`} style={h2}>{content}</h2>)
      else blocks.push(<h3 key={`h${key++}`} style={h3}>{content}</h3>)
      i += 1
      continue
    }

    // Tables: a run of consecutive `|...|` lines, with a separator row second.
    if (isTableLine(line) && i + 1 < lines.length && isTableLine(lines[i + 1]) && isSeparatorRow(lines[i + 1])) {
      flushPara()
      const headerCells = splitRow(line)
      const aligns = splitRow(lines[i + 1]).map(c => (c.endsWith(':') ? 'right' : 'left') as 'left' | 'right')
      i += 2
      const bodyRows: string[][] = []
      while (i < lines.length && isTableLine(lines[i]) && lines[i].trim() !== '') {
        bodyRows.push(splitRow(lines[i]))
        i += 1
      }
      const alignOf = (idx: number) => aligns[idx] ?? 'left'
      blocks.push(
        <table key={`t${key++}`} style={tableStyle}>
          <thead>
            <tr>
              {headerCells.map((c, ci) => (
                <th key={ci} style={{ ...thBase, textAlign: alignOf(ci) }}>{inline(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, ri) => (
              <tr key={ri}>
                {row.map((c, ci) => (
                  <td key={ci} style={{ ...tdBase, textAlign: alignOf(ci) }}>{inline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      )
      continue
    }

    // Unordered lists: a run of `* ` / `- ` lines.
    if (/^[*-]\s+/.test(trimmed)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^[*-]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[*-]\s+/, ''))
        i += 1
      }
      blocks.push(
        <ul key={`ul${key++}`} style={ulStyle}>
          {items.map((it, idx) => <li key={idx}>{inline(it)}</li>)}
        </ul>,
      )
      continue
    }

    // Otherwise, accumulate into the current paragraph.
    para.push(trimmed)
    i += 1
  }
  flushPara()

  if (blocks.length === 0) return null
  return <div>{blocks}</div>
}
