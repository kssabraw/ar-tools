import { ArrowRight, ExternalLink } from 'lucide-react'
import type { RelatedPageItem } from './types'
import { outlineBtn, scoreColor } from './shared'

const GROUPS: Array<RelatedPageItem['group']> = ['parents', 'siblings', 'children']
const GROUP_LABEL: Record<RelatedPageItem['group'], string> = {
  parents: 'Parent Pages', siblings: 'Sibling Pages', children: 'Child Pages',
}

interface Props {
  items: RelatedPageItem[]
  // Called when the user acts on an item (Reoptimize for found, Create new for missing).
  onAction: (item: RelatedPageItem) => void
}

// Shared presentation for the parent/sibling/child silo. Used both by the
// post-generation "Related Pages" tab and the standalone "Plan Silo" research view.
export function RelatedPagesList({ items, onAction }: Props) {
  return (
    <>
      {GROUPS.map(group => {
        const groupItems = items.filter(i => i.group === group)
        if (!groupItems.length) return null
        return (
          <div key={group} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <h3 style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#94a3b8', margin: 0 }}>{GROUP_LABEL[group]}</h3>
            <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              {groupItems.map((item, idx) => (
                <div key={item.keyword} style={{ padding: '12px 16px', background: '#fff', borderTop: idx ? '1px solid #f1f5f9' : 'none' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{item.keyword}</span>
                        <span style={{
                          fontSize: 11, borderRadius: 4, padding: '1px 6px',
                          background: item.status === 'found' ? '#dcfce7' : '#f1f5f9',
                          color: item.status === 'found' ? '#166534' : '#64748b',
                        }}>{item.status === 'found' ? 'Found' : 'Missing'}</span>
                        {item.composite_score != null && (
                          <span style={{ fontSize: 12, fontWeight: 600, color: scoreColor(item.composite_score) }}>{Math.round(item.composite_score)}/100</span>
                        )}
                      </div>
                      {item.status === 'found' && item.url && (
                        <a href={item.url} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#64748b', marginTop: 2, maxWidth: '100%' }}>
                          <ExternalLink size={12} style={{ flexShrink: 0 }} />
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.page_title || item.url}</span>
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
                    <button
                      style={{ ...outlineBtn, flexShrink: 0, padding: '6px 12px', fontSize: 12 }}
                      onClick={() => onAction(item)}
                    >
                      {item.status === 'found' ? 'Reoptimize' : 'Create new'} <ArrowRight size={13} />
                    </button>
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
