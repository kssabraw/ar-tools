import { Sparkles } from 'lucide-react'
import type { RelatedPageItem } from './types'
import type { useBulkCreate } from './useBulkCreate'
import { Spinner } from './Spinner'
import { card, primaryBtn } from './shared'

interface Props {
  items: RelatedPageItem[]
  bulk: ReturnType<typeof useBulkCreate>
  location: string
  locationCode: number | null
  onViewSaved?: () => void
}

// Multi-select bulk-create controls for a silo plan: a select-all summary, the
// "create N selected" action, live progress, and an outcome summary. Pair it
// with a <RelatedPagesList selection={...}> (which renders the per-row
// checkboxes). Shared by the Plan Silo and per-page Related Pages flows.
export function BulkCreateBar({ items, bulk, location, locationCode, onViewSaved }: Props) {
  const { selected, creating, detached, total, done, failed, start, leave, setSelection, clear } = bulk
  const missingKws = items.filter(r => r.status === 'missing').map(r => r.keyword)
  const allMissingSelected = missingKws.length > 0 && missingKws.every(kw => selected.has(kw))
  const selectedCount = selected.size
  const finished = done + failed

  const handleCreate = () => {
    const queue = items
      .filter(r => r.status === 'missing' && selected.has(r.keyword))
      .map(r => r.keyword)
    void start(queue, location, locationCode)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {missingKws.length > 0 && !creating && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#94a3b8', flexWrap: 'wrap' }}>
          <span>Tick the missing pages you want, then create them in one batch.</span>
          <button
            onClick={() => (allMissingSelected ? clear() : setSelection(missingKws))}
            style={{ marginLeft: 'auto', background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1' }}
          >
            {allMissingSelected ? 'Deselect all' : 'Select all missing'}
          </button>
        </div>
      )}

      {creating ? (
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, background: '#f8fafc' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={16} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
              Generating in the background…
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#64748b', flexShrink: 0 }}>
              {finished} / {total} done{failed > 0 ? ` · ${failed} failed` : ''}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {Array.from({ length: total }).map((_, idx) => (
              <div key={idx} style={{
                height: 6, flex: 1, borderRadius: 999, transition: 'background 0.3s',
                background: idx < done ? '#16a34a' : idx < finished ? '#dc2626' : '#e2e8f0',
              }} />
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, flex: 1 }}>
              Each page is saved to Saved Pages as it finishes — you don’t need to wait here.
            </p>
            <button onClick={leave} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#6366f1', flexShrink: 0 }}>
              Leave &amp; finish in the background
            </button>
          </div>
        </div>
      ) : (
        <>
          {detached && total > 0 && (
            <p style={{ fontSize: 13, color: '#6366f1', fontWeight: 600, margin: 0 }}>
              {total} page{total === 1 ? '' : 's'} generating in the background — they’ll appear in Saved Pages as they finish.
            </p>
          )}
          {!detached && (done > 0 || failed > 0) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {done > 0 && (
                <p style={{ fontSize: 13, color: '#16a34a', fontWeight: 600, margin: 0 }}>
                  {done} page{done === 1 ? '' : 's'} created and saved{onViewSaved ? <> — <button onClick={onViewSaved} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#16a34a', fontWeight: 600, textDecoration: 'underline' }}>view in Saved Pages</button></> : ''}.
                </p>
              )}
              {failed > 0 && (
                <p style={{ fontSize: 13, color: '#dc2626', fontWeight: 600, margin: 0 }}>
                  {failed} page{failed === 1 ? '' : 's'} failed to generate. Re-select to retry.
                </p>
              )}
            </div>
          )}

          {selectedCount > 0 && (
            <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12, background: '#f8fafc' }}>
              <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
                Competitor SERP analysis runs for every page so each one targets the right terms and entities.
              </p>
              <button style={{ ...primaryBtn, width: '100%' }} onClick={handleCreate}>
                <Sparkles size={16} /> Create {selectedCount} selected page{selectedCount === 1 ? '' : 's'}
              </button>
              <p style={{ fontSize: 11, color: '#94a3b8', margin: 0, textAlign: 'center' }}>
                Each page takes ~2–4 minutes and runs in the background — you can leave once they start.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
