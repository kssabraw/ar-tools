import { ExternalLink, FileText } from 'lucide-react'
import type { PublishItem, useBulkPublish } from './useBulkPublish'

interface Props {
  // The full set of selectable items in view (used for select-all + to know what
  // "publish selected" should send).
  items: PublishItem[]
  bulk: ReturnType<typeof useBulkPublish>
}

// A sticky action bar for multi-select "publish to Google Docs": a select-all
// toggle, the publish button, live progress, and a per-item outcome list with
// links to the created Docs. Renders nothing until something is selected or a
// batch has produced results.
export function BulkPublishBar({ items, bulk }: Props) {
  const { selected, publishing, results, start, clear, setSelection } = bulk
  const selectedCount = selected.size
  const resultEntries = Object.entries(results)
  const done = resultEntries.filter(([, r]) => r.status === 'done').length
  const failed = resultEntries.filter(([, r]) => r.status === 'failed').length
  const total = resultEntries.length
  const finished = done + failed
  const allSelected = items.length > 0 && items.every(i => selected.has(i.key))

  if (selectedCount === 0 && total === 0) return null

  // Outcomes are keyed by item key — pair them back with labels for display.
  const byKey = new Map(items.map(i => [i.key, i]))
  const succeeded = resultEntries
    .filter(([, r]) => r.status === 'done')
    .map(([key, r]) => ({ key, label: byKey.get(key)?.label ?? key, docUrl: r.docUrl }))
  const failures = resultEntries
    .filter(([, r]) => r.status === 'failed')
    .map(([key, r]) => ({ key, label: byKey.get(key)?.label ?? key, error: r.error }))

  return (
    <div style={barStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <button
          onClick={() => (allSelected ? clear() : setSelection(items.map(i => i.key)))}
          disabled={publishing || items.length === 0}
          style={linkBtn}
        >
          {allSelected ? 'Deselect all' : `Select all (${items.length})`}
        </button>
        <span style={{ fontSize: 13, color: '#475569', fontWeight: 600 }}>
          {selectedCount} selected
        </span>

        {publishing && total > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 4 }}>
            <div style={{ display: 'flex', gap: 3, width: 140 }}>
              {Array.from({ length: total }).map((_, idx) => (
                <div key={idx} style={{
                  height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                  background: idx < done ? '#16a34a' : idx < finished ? '#dc2626' : '#e2e8f0',
                }} />
              ))}
            </div>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              {finished} / {total}{failed > 0 ? ` · ${failed} failed` : ''}
            </span>
          </div>
        )}

        <button
          onClick={() => void start(items)}
          disabled={publishing || selectedCount === 0}
          style={{ ...primaryBtn, marginLeft: 'auto', opacity: publishing || selectedCount === 0 ? 0.6 : 1 }}
          title="Publish each selected item to a Google Doc in the client's Drive folder"
        >
          <ExternalLink size={15} />
          {publishing
            ? 'Publishing…'
            : `Publish ${selectedCount} to Google Docs`}
        </button>
      </div>

      {!publishing && (succeeded.length > 0 || failures.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
          {succeeded.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#16a34a' }}>
                {succeeded.length} published to Google Docs
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {succeeded.map(s => (
                  s.docUrl ? (
                    <a key={s.key} href={s.docUrl} target="_blank" rel="noreferrer" style={docChip}>
                      <FileText size={12} /> {s.label}
                    </a>
                  ) : (
                    <span key={s.key} style={{ ...docChip, color: '#16a34a' }}>
                      <FileText size={12} /> {s.label}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}
          {failures.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#dc2626' }}>
                {failures.length} failed — still selected, click publish to retry
              </span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {failures.map(f => (
                  <span key={f.key} style={{ fontSize: 12, color: '#dc2626' }}>
                    {f.label}: {f.error}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const barStyle: React.CSSProperties = {
  position: 'sticky', bottom: 16, zIndex: 10,
  background: '#fff', border: '1px solid #c7d2fe', borderRadius: 12,
  boxShadow: '0 8px 24px rgba(15,23,42,0.12)', padding: 14, marginTop: 16,
}
const primaryBtn: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '9px 16px',
  background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8,
  fontWeight: 600, fontSize: 13, cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  fontSize: 12, fontWeight: 600, color: '#6366f1',
}
const docChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px',
  background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6,
  fontSize: 12, color: '#16a34a', textDecoration: 'none', maxWidth: 240,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
