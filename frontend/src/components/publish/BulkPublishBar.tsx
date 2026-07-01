import { ExternalLink, FileText, Globe } from 'lucide-react'
import type { PublishDestination, PublishItem, useBulkPublish } from './useBulkPublish'

interface Props {
  // The full set of selectable items in view (used for select-all + to know what
  // "publish selected" should send).
  items: PublishItem[]
  bulk: ReturnType<typeof useBulkPublish>
  // Whether the (single) client these items belong to has WordPress publishing
  // configured. `false` disables the Website / Both options with a hint; leave
  // undefined when the items can span multiple clients (e.g. all saved articles),
  // where a single flag can't describe them — the per-item error covers it then.
  wordpressConfigured?: boolean
  // Where the sticky bar anchors. 'bottom' (default) keeps it pinned to the
  // bottom of the list; 'top' pins it to the top (e.g. directly under a tab row)
  // so the publish controls are the first thing in view.
  placement?: 'top' | 'bottom'
}

const DEST_OPTIONS: { value: PublishDestination; label: string }[] = [
  { value: 'google_docs', label: 'Google Docs' },
  { value: 'wordpress', label: 'Website' },
  { value: 'both', label: 'Both' },
]

// A sticky action bar for multi-select publishing: a destination picker (Google
// Docs / Website / Both), a select-all toggle, the publish button, live
// progress, and a per-item outcome list with links to whatever was created.
// Renders nothing until something is selected or a batch has produced results.
export function BulkPublishBar({ items, bulk, wordpressConfigured, placement = 'bottom' }: Props) {
  const {
    selected, publishing, results, start, clear, setSelection,
    destination, setDestination, wpStatus, setWpStatus,
  } = bulk
  const selectedCount = selected.size
  const resultEntries = Object.entries(results)
  const done = resultEntries.filter(([, r]) => r.status === 'done').length
  const failed = resultEntries.filter(([, r]) => r.status === 'failed').length
  const total = resultEntries.length
  const finished = done + failed
  const allSelected = items.length > 0 && items.every(i => selected.has(i.key))
  // Only gate when we actually know the client lacks WordPress (single-client
  // views pass the flag; multi-client views leave it undefined).
  const wpDisabled = wordpressConfigured === false
  const wantsWp = destination !== 'google_docs'

  // Stay visible whenever there's anything publishable in view (or a finished
  // batch to show), so the publish controls are discoverable without first
  // having to guess that ticking a checkbox reveals them. The button itself is
  // disabled until at least one item is selected.
  if (items.length === 0 && total === 0) return null

  // Outcomes are keyed by item key — pair them back with labels for display.
  const byKey = new Map(items.map(i => [i.key, i]))
  const succeeded = resultEntries
    .filter(([, r]) => r.status === 'done')
    .map(([key, r]) => ({ key, label: byKey.get(key)?.label ?? key, docUrl: r.docUrl, siteUrl: r.siteUrl }))
  const failures = resultEntries
    .filter(([, r]) => r.status === 'failed')
    .map(([key, r]) => ({ key, label: byKey.get(key)?.label ?? key, error: r.error, docUrl: r.docUrl, siteUrl: r.siteUrl }))

  const destNoun =
    destination === 'google_docs' ? 'Google Docs'
      : destination === 'wordpress' ? 'the website'
        : 'Docs + website'

  const barStyle: React.CSSProperties = placement === 'top'
    ? { ...barBaseStyle, top: 0, marginBottom: 16 }
    : { ...barBaseStyle, bottom: 16, marginTop: 16 }

  return (
    <div style={barStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        {/* Destination picker */}
        <div style={{ display: 'inline-flex', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
          {DEST_OPTIONS.map(opt => {
            const isWp = opt.value !== 'google_docs'
            const optDisabled = publishing || (isWp && wpDisabled)
            const active = destination === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setDestination(opt.value)}
                disabled={optDisabled}
                title={isWp && wpDisabled ? 'Connect WordPress in client settings to publish to the website' : undefined}
                style={{
                  padding: '6px 12px', fontSize: 12, fontWeight: 600, border: 'none',
                  cursor: optDisabled ? 'not-allowed' : 'pointer',
                  background: active ? '#6366f1' : '#fff',
                  color: active ? '#fff' : optDisabled ? '#cbd5e1' : '#64748b',
                }}
              >
                {opt.label}
              </button>
            )
          })}
        </div>

        {/* WordPress draft/publish selector — only when a WP target is chosen */}
        {wantsWp && !wpDisabled && (
          <select
            value={wpStatus}
            onChange={e => setWpStatus(e.target.value as 'draft' | 'publish')}
            disabled={publishing}
            style={{ border: '1px solid #c7d2fe', borderRadius: 8, background: '#fff', color: '#6366f1', fontSize: 12, fontWeight: 600, padding: '6px 8px', cursor: 'pointer' }}
            title="Draft saves to WordPress unpublished; Publish goes live"
          >
            <option value="draft">WP: Draft</option>
            <option value="publish">WP: Publish</option>
          </select>
        )}

        <button
          onClick={() => (allSelected ? clear() : setSelection(items.map(i => i.key)))}
          disabled={publishing || items.length === 0}
          style={linkBtn}
        >
          {allSelected ? 'Deselect all' : `Select all (${items.length})`}
        </button>
        <span style={{ fontSize: 13, color: selectedCount === 0 ? '#94a3b8' : '#475569', fontWeight: 600 }}>
          {selectedCount === 0 ? 'Tick pages to publish' : `${selectedCount} selected`}
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
          title={`Publish each selected item to ${destNoun}`}
        >
          <ExternalLink size={15} />
          {publishing
            ? 'Publishing…'
            : selectedCount === 0
              ? `Publish to ${destNoun}`
              : `Publish ${selectedCount} to ${destNoun}`}
        </button>
      </div>

      {!publishing && (succeeded.length > 0 || failures.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
          {succeeded.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#16a34a' }}>
                {succeeded.length} published
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {succeeded.map(s => (
                  <OutcomeChips key={s.key} label={s.label} docUrl={s.docUrl} siteUrl={s.siteUrl} />
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

// Per-item success row: a chip for the Google Doc and/or the WordPress page,
// whichever the publish produced.
function OutcomeChips({ label, docUrl, siteUrl }: {
  label: string
  docUrl?: string | null
  siteUrl?: string | null
}) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
      {docUrl ? (
        <a href={docUrl} target="_blank" rel="noreferrer" style={docChip}>
          <FileText size={12} /> {label}
        </a>
      ) : null}
      {siteUrl ? (
        <a href={siteUrl} target="_blank" rel="noreferrer" style={siteChip}>
          <Globe size={12} /> {docUrl ? 'Website' : label}
        </a>
      ) : null}
      {!docUrl && !siteUrl ? (
        <span style={{ ...docChip, color: '#16a34a' }}>
          <FileText size={12} /> {label}
        </span>
      ) : null}
    </span>
  )
}

// Position offset (top/bottom) + margin are applied per-placement at the call
// site; this is the shared appearance.
const barBaseStyle: React.CSSProperties = {
  position: 'sticky', zIndex: 10,
  background: '#fff', border: '1px solid #c7d2fe', borderRadius: 12,
  boxShadow: '0 8px 24px rgba(15,23,42,0.12)', padding: 14,
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
const siteChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px',
  background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 6,
  fontSize: 12, color: '#2563eb', textDecoration: 'none', maxWidth: 240,
  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}
