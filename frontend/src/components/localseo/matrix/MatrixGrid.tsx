import { AlertTriangle, CheckCircle2, ExternalLink, FileText } from 'lucide-react'
import { Spinner } from '../Spinner'
import { COVERED, RUNNABLE } from './types'
import type { MatrixCell, MatrixCellStatus, MatrixDetail } from './types'

interface Props {
  matrix: MatrixDetail
  selected: Set<string>
  onToggle: (cellId: string, checked: boolean) => void
  onOpenPage: (pageId: string) => void
  disabled?: boolean
}

const STATUS: Record<MatrixCellStatus, { label: string; bg: string; fg: string }> = {
  missing:         { label: 'Missing',        bg: '#f1f5f9', fg: '#64748b' },
  found:           { label: 'In tool',        bg: '#dcfce7', fg: '#166534' },
  on_site:         { label: 'On site',        bg: '#dbeafe', fg: '#1e40af' },
  queued:          { label: 'Queued',         bg: '#fef3c7', fg: '#92400e' },
  generating:      { label: 'Generating',     bg: '#fef3c7', fg: '#92400e' },
  done:            { label: 'Done',           bg: '#dcfce7', fg: '#166534' },
  failed:          { label: 'Failed',         bg: '#fee2e2', fg: '#991b1b' },
  publishing:      { label: 'Publishing',     bg: '#fef3c7', fg: '#92400e' },
  published:       { label: 'Published',      bg: '#d1fae5', fg: '#065f46' },
  publish_failed:  { label: 'Publish failed', bg: '#fee2e2', fg: '#991b1b' },
  publish_blocked: { label: 'Blocked',        bg: '#fee2e2', fg: '#991b1b' },
  skipped:         { label: 'Parked',         bg: '#f8fafc', fg: '#94a3b8' },
}

function selectable(cell: MatrixCell): boolean {
  return RUNNABLE.has(cell.status) || COVERED.has(cell.status)
}

// The N×M grid: services as rows, locations as columns, one status chip per
// cell. Runnable cells (and, opt-in, already-covered ones) carry a checkbox for
// the run bar; a cell with a page opens it, a live cell links out.
export function MatrixGrid({ matrix, selected, onToggle, onOpenPage, disabled }: Props) {
  const services = [...matrix.services]
  const locations = [...matrix.locations]
  const byKey = new Map<string, MatrixCell>()
  for (const c of matrix.cells) byKey.set(`${c.service_slug}|${c.location_slug}`, c)

  const columnIds = (locSlug: string) =>
    matrix.cells.filter(c => c.location_slug === locSlug && selectable(c)).map(c => c.id)
  const rowIds = (svcSlug: string) =>
    matrix.cells.filter(c => c.service_slug === svcSlug && selectable(c)).map(c => c.id)
  const toggleMany = (ids: string[]) => {
    const all = ids.length > 0 && ids.every(id => selected.has(id))
    ids.forEach(id => onToggle(id, !all))
  }

  const th: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#475569', padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }
  const td: React.CSSProperties = { padding: 6, borderBottom: '1px solid #f1f5f9', verticalAlign: 'top' }

  return (
    <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 10 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 160 + locations.length * 170 }}>
        <thead>
          <tr>
            <th style={{ ...th, position: 'sticky', left: 0, zIndex: 1 }}>Service ↓ / Location →</th>
            {locations.map(l => (
              <th key={l.slug} style={th}>
                <button type="button" onClick={() => toggleMany(columnIds(l.slug))} disabled={disabled} title="Select / deselect this column" style={{ background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit', cursor: 'pointer' }}>
                  {l.name}
                </button>
                {l.location_code ? <span title={`Pinned to ${l.canonical ?? l.name}`} style={{ marginLeft: 6, fontSize: 10, color: '#6366f1' }}>●</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {services.map(s => (
            <tr key={s.slug}>
              <td style={{ ...td, position: 'sticky', left: 0, background: '#fff', fontSize: 13, fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', padding: '10px 10px' }}>
                <button type="button" onClick={() => toggleMany(rowIds(s.slug))} disabled={disabled} title="Select / deselect this row" style={{ background: 'none', border: 'none', padding: 0, font: 'inherit', color: 'inherit', cursor: 'pointer', textAlign: 'left' }}>
                  {s.label}
                </button>
              </td>
              {locations.map(l => {
                const cell = byKey.get(`${s.slug}|${l.slug}`)
                if (!cell) return <td key={l.slug} style={td} />
                const st = STATUS[cell.status] ?? STATUS.missing
                const busy = cell.status === 'queued' || cell.status === 'generating' || cell.status === 'publishing'
                const canPick = selectable(cell)
                const link = cell.published_url || ((cell.status === 'on_site' || cell.status === 'published') ? cell.url : null)
                return (
                  <td key={l.slug} style={td}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minHeight: 28 }}>
                      {canPick ? (
                        <input type="checkbox" checked={selected.has(cell.id)} disabled={disabled} onChange={e => onToggle(cell.id, e.target.checked)} title={COVERED.has(cell.status) ? 'Already covered — tick to generate anyway' : 'Generate this page'} />
                      ) : <span style={{ width: 13 }} />}
                      <span
                        title={cell.error ? `${st.label}: ${cell.error}` : cell.keyword}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5, background: st.bg, color: st.fg, whiteSpace: 'nowrap' }}
                      >
                        {busy ? <Spinner size={10} color={st.fg} /> : cell.status === 'failed' || cell.status === 'publish_failed' || cell.status === 'publish_blocked' ? <AlertTriangle size={11} /> : cell.status === 'done' || cell.status === 'published' ? <CheckCircle2 size={11} /> : null}
                        {st.label}
                      </span>
                      {cell.page_id && (
                        <button type="button" onClick={() => onOpenPage(cell.page_id as string)} title={cell.page_title ?? 'Open page'} style={{ background: 'none', border: 'none', padding: 2, cursor: 'pointer', color: '#6366f1', display: 'inline-flex' }}>
                          <FileText size={13} />
                        </button>
                      )}
                      {link && (
                        <a href={link} target="_blank" rel="noreferrer" title={link} style={{ color: '#64748b', display: 'inline-flex' }}><ExternalLink size={12} /></a>
                      )}
                      {cell.composite_score != null && (
                        <span style={{ fontSize: 11, color: cell.composite_score >= 80 ? '#16a34a' : cell.composite_score >= 60 ? '#d97706' : '#dc2626', fontVariantNumeric: 'tabular-nums' }}>{Math.round(cell.composite_score)}</span>
                      )}
                      {cell.link_coverage && cell.link_coverage.missing?.length > 0 && (
                        <span title="Some sibling links are missing on this page" style={{ fontSize: 10, color: '#d97706' }}>links</span>
                      )}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
