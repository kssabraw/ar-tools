import { useMemo, useState } from 'react'
import { FileText, Table2, Globe } from 'lucide-react'

// Shared "published at a glance" controls for the content lists (Blog Articles,
// Service / Location pages, Local SEO Saved Pages): status filter tabs with
// counts, a per-row Doc/Website badge, and client-side 50-per-page pagination.
// Client-side because these lists are per-client and modest in size.

export type PubFilter = 'all' | 'published' | 'not_published'
export const PUBLISH_PAGE_SIZE = 50

export interface PubCounts { all: number; published: number; not_published: number }

// Filter + paginate a list by a caller-supplied "is published" predicate.
export function usePagedPublish<T>(items: T[], isPublished: (t: T) => boolean, pageSize = PUBLISH_PAGE_SIZE) {
  const [filter, setFilter] = useState<PubFilter>('all')
  const [page, setPage] = useState(0)

  const counts: PubCounts = useMemo(() => {
    let published = 0
    for (const it of items) if (isPublished(it)) published++
    return { all: items.length, published, not_published: items.length - published }
  }, [items, isPublished])

  const filtered = useMemo(() => {
    if (filter === 'published') return items.filter(isPublished)
    if (filter === 'not_published') return items.filter(i => !isPublished(i))
    return items
  }, [items, filter, isPublished])

  const total = filtered.length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const pageItems = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize)

  const pick = (f: PubFilter) => { setFilter(f); setPage(0) }

  return { filter, pick, page: safePage, setPage, counts, pageItems, total, pageCount, pageSize }
}

export function PublishTabs({ counts, active, onPick }: { counts: PubCounts; active: PubFilter; onPick: (f: PubFilter) => void }) {
  const tabs: { key: PubFilter; label: string; n: number }[] = [
    { key: 'all', label: 'All', n: counts.all },
    { key: 'published', label: 'Published', n: counts.published },
    { key: 'not_published', label: 'Not published', n: counts.not_published },
  ]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => onPick(t.key)} style={active === t.key ? tabActive : tab}>
          {t.label} ({t.n})
        </button>
      ))}
    </div>
  )
}

export function Pager({ page, pageCount, total, pageSize, onPage }: {
  page: number; pageCount: number; total: number; pageSize: number; onPage: (p: number) => void
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 }}>
      <span style={{ fontSize: 12, color: '#94a3b8' }}>
        {total === 0 ? '0' : `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)}`} of {total}
      </span>
      {pageCount > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button style={{ ...pageBtn, opacity: page === 0 ? 0.4 : 1 }} disabled={page === 0} onClick={() => onPage(page - 1)}>Prev</button>
          <span style={{ fontSize: 12, color: '#64748b' }}>Page {page + 1} of {pageCount}</span>
          <button style={{ ...pageBtn, opacity: page + 1 >= pageCount ? 0.4 : 1 }} disabled={page + 1 >= pageCount} onClick={() => onPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  )
}

// Per-row publish badges: a green chip per target the piece went to. `docUrl`
// is a Google Doc, `siteUrl` a live website (WordPress), `sheetUrl` a Sheet.
export function PublishBadges({ docUrl, siteUrl, sheetUrl }: { docUrl?: string | null; siteUrl?: string | null; sheetUrl?: string | null }) {
  if (!docUrl && !siteUrl && !sheetUrl) {
    return <span style={{ fontSize: 12, color: '#94a3b8' }}>Not published</span>
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {docUrl && <Chip href={docUrl} icon={<FileText size={11} />} label="Doc" />}
      {sheetUrl && <Chip href={sheetUrl} icon={<Table2 size={11} />} label="Sheet" />}
      {siteUrl && <Chip href={siteUrl} icon={<Globe size={11} />} label="Website" />}
    </span>
  )
}

function Chip({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 3, padding: '1px 7px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: '#ecfdf5', color: '#047857', textDecoration: 'none', border: '1px solid #a7f3d0' }}>
      {icon} {label}
    </a>
  )
}

const tab: React.CSSProperties = { background: 'none', border: '1px solid transparent', borderRadius: 8, padding: '6px 12px', fontSize: 13, fontWeight: 600, color: '#64748b', cursor: 'pointer' }
const tabActive: React.CSSProperties = { ...tab, background: '#eef2ff', color: '#4f46e5', border: '1px solid #c7d2fe' }
const pageBtn: React.CSSProperties = { background: '#fff', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 7, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
