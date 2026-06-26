import { ArrowRight, ExternalLink } from 'lucide-react'
import type { RelatedPageItem } from './types'
import { outlineBtn, scoreColor } from './shared'

// Known relationship groups from the /related-pages flow — rendered first and
// in this order, with friendly labels. The Plan Silo flow passes free-form silo
// labels, which render after these (in first-seen order) using the label as-is.
const KNOWN_ORDER = ['parents', 'siblings', 'children']
const GROUP_LABEL: Record<string, string> = {
  parents: 'Parent Pages', siblings: 'Sibling Pages', children: 'Child Pages',
}

// Distinct groups present in `items`, known relationship groups first (in their
// canonical order), then any silo labels in the order they first appear.
function orderedGroups(items: RelatedPageItem[]): string[] {
  const seen = new Set(items.map(i => i.group))
  const known = KNOWN_ORDER.filter(g => seen.has(g))
  const rest: string[] = []
  for (const i of items) {
    if (!KNOWN_ORDER.includes(i.group) && !rest.includes(i.group)) rest.push(i.group)
  }
  return [...known, ...rest]
}

interface SelectionMode {
  // When provided, `missing` items render a checkbox (for bulk creation) instead
  // of an individual "Create new" button. `found` items keep their action button.
  selected: Set<string>
  onToggle: (keyword: string, checked: boolean) => void
  disabled?: boolean
}

interface Props {
  items: RelatedPageItem[]
  // Called when the user acts on an item (Reoptimize for found, Create new for missing).
  onAction: (item: RelatedPageItem) => void
  selection?: SelectionMode
}

// Shared presentation for the parent/sibling/child silo. Used both by the
// post-generation "Related Pages" tab and the standalone "Plan Silo" research view.
export function RelatedPagesList({ items, onAction, selection }: Props) {
  return (
    <>
      {orderedGroups(items).map(group => {
        const groupItems = items.filter(i => i.group === group)
        if (!groupItems.length) return null
        return (
          <div key={group} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <h3 style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', margin: 0 }}>{GROUP_LABEL[group] ?? group}</h3>
            <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              {groupItems.map((item, idx) => (
                <div key={item.keyword} style={{ padding: '12px 16px', background: '#fff', borderTop: idx ? '1px solid #f1f5f9' : 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{item.keyword}</span>
                        <span style={{
                          fontSize: 11, borderRadius: 4, padding: '1px 6px',
                          background: item.status === 'found' ? '#dcfce7' : item.status === 'on_site' ? '#dbeafe' : '#f1f5f9',
                          color: item.status === 'found' ? '#166534' : item.status === 'on_site' ? '#1e40af' : '#64748b',
                        }}>{item.status === 'found' ? 'Found' : item.status === 'on_site' ? 'On site' : 'Missing'}</span>
                        {item.composite_score != null && (
                          <span style={{ fontSize: 12, fontWeight: 600, color: scoreColor(item.composite_score) }}>{Math.round(item.composite_score)}/100</span>
                        )}
                      </div>
                      {item.supporting_keywords && item.supporting_keywords.length > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                          <span style={{ fontSize: 11, color: '#94a3b8' }}>also targets</span>
                          {item.supporting_keywords.map((sk, i) => (
                            <span key={i} style={{ fontSize: 11, color: '#475569', background: '#f1f5f9', borderRadius: 4, padding: '1px 6px' }}>{sk}</span>
                          ))}
                        </div>
                      )}
                      {(item.status === 'found' || item.status === 'on_site') && item.url && (
                        <a href={item.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b', marginTop: 2, maxWidth: '100%' }}>
                          <ExternalLink size={12} style={{ flexShrink: 0 }} />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.status === 'on_site' ? `Live page — ${item.url}` : (item.page_title || item.url)}</span>
                        </a>
                      )}
                      {item.deficiencies && item.deficiencies.length > 0 && (
                        <ul style={{ margin: '6px 0 0', paddingLeft: 0, listStyle: 'none' }}>
                          {item.deficiencies.slice(0, 3).map((d, i) => (
                            <li key={i} style={{ fontSize: 12, color: '#64748b' }}><b style={{ color: '#0f172a' }}>{d.engine}:</b> {(d.issues ?? []).join('; ')}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {selection && item.status === 'missing' ? (
                      <label style={{ flexShrink: 0, display: 'inline-flex', alignItems: 'center', cursor: selection.disabled ? 'not-allowed' : 'pointer' }} title="Select for bulk create">
                        <input
                          type="checkbox"
                          checked={selection.selected.has(item.keyword)}
                          disabled={selection.disabled}
                          onChange={e => selection.onToggle(item.keyword, e.target.checked)}
                          style={{ width: 16, height: 16, cursor: selection.disabled ? 'not-allowed' : 'pointer', accentColor: '#6366f1' }}
                        />
                      </label>
                    ) : item.status === 'on_site' ? (
                      // Already a generic location page on the live site — nothing to
                      // create; the live page is linked above.
                      <span style={{ flexShrink: 0, fontSize: 12, color: '#1e40af', fontWeight: 600 }}>Already on site</span>
                    ) : (
                      <button
                        style={{ ...outlineBtn, flexShrink: 0, padding: '6px 12px', fontSize: 12 }}
                        onClick={() => onAction(item)}
                      >
                        {item.status === 'found' ? 'Reoptimize' : 'Create new'} <ArrowRight size={13} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </>
  )
}
