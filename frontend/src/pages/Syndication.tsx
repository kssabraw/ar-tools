import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Share2, RefreshCw, ExternalLink, FileText, Table2, AlertTriangle, Globe, Download } from 'lucide-react'
import { api } from '../lib/api'
import { toCsv, downloadCsv } from '../lib/csv'
import type { Client } from '../lib/types'

// ── Types (mirror models/syndication.py) ────────────────────────────────────
type PublishTarget = 'doc' | 'sheet' | 'both'
interface SyndicationConfig {
  client_id: string
  enabled: boolean
  interval_days: number
  include_blog: boolean
  include_pages: boolean
  include_products: boolean
  share_mode: 'public' | 'link'
  publish_target: PublishTarget
  last_scan_date: string | null
}
type ItemStatus = 'discovered' | 'rewriting' | 'published' | 'failed' | 'skipped'
interface SyndicationItem {
  id: string
  source_url: string
  content_type: 'blog_post' | 'page' | 'product'
  title: string | null
  status: ItemStatus
  rewritten_title: string | null
  doc_url: string | null
  sheet_url: string | null
  error: string | null
  first_seen_at: string | null
  published_at: string | null
}
interface Counts { all: number; published: number; not_published: number; failed: number }
interface ItemsResponse { items: SyndicationItem[]; counts: Counts }

type Filter = 'all' | 'published' | 'not_published' | 'failed'
const PAGE_SIZE = 50
const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'published', label: 'Published' },
  { key: 'not_published', label: 'Not published' },
  { key: 'failed', label: 'Failed' },
]

const TYPE_LABEL: Record<SyndicationItem['content_type'], string> = {
  blog_post: 'Blog post',
  page: 'Page',
  product: 'Product',
}
// Items the user can still pick + publish (published / in-flight are excluded).
const PUBLISHABLE: ItemStatus[] = ['discovered', 'failed', 'skipped']

// Turn a source URL into a readable label when we don't yet have the page's real
// title (that's captured when the page is rewritten). Falls back to the URL.
function displayTitle(item: SyndicationItem): string {
  if (item.rewritten_title || item.title) return (item.rewritten_title || item.title) as string
  try {
    const u = new URL(item.source_url)
    const seg = u.pathname.split('/').filter(Boolean).pop()
    if (!seg) return u.hostname
    return decodeURIComponent(seg).replace(/[-_]+/g, ' ').replace(/\.\w+$/, '').trim() || u.hostname
  } catch {
    return item.source_url
  }
}

export function Syndication() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [scanning, setScanning] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const [page, setPage] = useState(0)
  // Ids the user just submitted to Publish — used to keep polling until each one
  // reaches a terminal state (published/failed), so progress shows live.
  const [queued, setQueued] = useState<Set<string>>(new Set())

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: config } = useQuery<SyndicationConfig>({
    queryKey: ['syndication-config', clientId],
    queryFn: () => api.get<SyndicationConfig>(`/clients/${clientId}/syndication/config`),
    enabled: Boolean(clientId),
  })

  const { data } = useQuery<ItemsResponse>({
    queryKey: ['syndication-items', clientId, filter, page],
    queryFn: () => api.get<ItemsResponse>(
      `/clients/${clientId}/syndication/items?filter=${filter}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`,
    ),
    enabled: Boolean(clientId),
    // Poll while a scan is in flight (new rows appear) or any just-published item
    // on this page hasn't reached a terminal state yet (so the list updates live).
    refetchInterval: (query) => {
      const items = (query.state.data as ItemsResponse | undefined)?.items ?? []
      const working = items.some(
        i => (queued.has(i.id) || i.status === 'rewriting') && i.status !== 'published' && i.status !== 'failed',
      )
      return scanning || working ? 4000 : false
    },
  })

  const rows = data?.items ?? []
  const counts = data?.counts
  const tabTotal =
    filter === 'published' ? counts?.published
    : filter === 'failed' ? counts?.failed
    : filter === 'not_published' ? counts?.not_published
    : counts?.all
  const total = tabTotal ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const invalidateItems = () => queryClient.invalidateQueries({ queryKey: ['syndication-items', clientId] })

  const saveConfig = useMutation({
    mutationFn: (patch: Partial<SyndicationConfig>) =>
      api.put<SyndicationConfig>(`/clients/${clientId}/syndication/config`, patch),
    onSuccess: (d) => queryClient.setQueryData(['syndication-config', clientId], d),
  })

  const scan = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/syndication/scan`, {}),
    onSuccess: () => {
      setScanning(true)
      window.setTimeout(() => setScanning(false), 45000)
      invalidateItems()
    },
  })

  const publish = useMutation({
    mutationFn: (ids: string[]) => api.post<{ queued: number }>(`/clients/${clientId}/syndication/publish`, { item_ids: ids }),
    onSuccess: (_d, ids) => {
      setQueued(prev => new Set([...prev, ...ids]))
      setSelected(new Set())
      invalidateItems()
    },
  })

  const retry = useMutation({
    mutationFn: (itemId: string) => api.post(`/clients/${clientId}/syndication/items/${itemId}/retry`, {}),
    onSuccess: (_d, itemId) => {
      setQueued(prev => new Set([...prev, itemId]))
      invalidateItems()
    },
  })

  // Drop ids from `queued` once their item leaves this page's non-terminal set
  // (published/failed, or filtered off) so the "Publishing…" indicator + polling
  // stop exactly when the visible work finishes.
  useEffect(() => {
    setQueued(prev => {
      if (prev.size === 0) return prev
      const next = new Set<string>()
      for (const it of (data?.items ?? [])) {
        if (prev.has(it.id) && it.status !== 'published' && it.status !== 'failed') next.add(it.id)
      }
      return next.size === prev.size ? prev : next
    })
  }, [data])

  // Keep the page in range as counts shift (e.g. items move to the Published tab).
  useEffect(() => {
    if (page > 0 && page >= pageCount) setPage(pageCount - 1)
  }, [page, pageCount])

  const activeCount = rows.filter(
    i => (queued.has(i.id) || i.status === 'rewriting') && i.status !== 'published' && i.status !== 'failed',
  ).length
  const publishableRows = rows.filter(i => PUBLISHABLE.includes(i.status))
  const allSelected = publishableRows.length > 0 && publishableRows.every(i => selected.has(i.id))
  const target = config?.publish_target ?? 'both'
  const targetLabel = target === 'both' ? 'Google Doc + Sheet' : target === 'doc' ? 'Google Doc' : 'Google Sheet'

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(publishableRows.map(i => i.id)))
  }
  const pick = (f: Filter) => { setFilter(f); setPage(0) }

  // Export all published rows (across pages) to CSV.
  const exportPublished = async () => {
    setExporting(true)
    try {
      const all: SyndicationItem[] = []
      for (let off = 0; off < 10000; off += 500) {
        const res = await api.get<ItemsResponse>(
          `/clients/${clientId}/syndication/items?filter=published&limit=500&offset=${off}`,
        )
        const batch = res.items ?? []
        all.push(...batch)
        if (batch.length < 500) break
      }
      const headers = ['Title', 'Source URL', 'Type', 'Doc URL', 'Sheet URL', 'Published at']
      const body = all.map(i => [
        i.rewritten_title || i.title || '', i.source_url, TYPE_LABEL[i.content_type],
        i.doc_url || '', i.sheet_url || '', i.published_at || '',
      ])
      downloadCsv(`syndication-published-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, body))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <button onClick={() => navigate(`/clients/${clientId}`)} style={backBtn}>
        <ArrowLeft size={14} /> Back to workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Share2 size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Content Syndication</h1>
        {(scanning || activeCount > 0) && (
          <span style={pill}>{scanning ? 'Scanning…' : `Publishing ${activeCount}…`}</span>
        )}
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px', maxWidth: 780 }}>
        {client?.name ?? 'This client'} · scan the site for content, then pick the pages to rewrite into unique versions and
        publish as public, search-discoverable Google Docs / Sheets — each linking back to the original page.
      </p>

      {/* ── Settings ─────────────────────────────────────────────────────── */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={config?.enabled ?? false}
              disabled={!config || saveConfig.isPending}
              onChange={(e) => saveConfig.mutate({ enabled: e.target.checked })}
            />
            <span style={{ fontWeight: 600, color: '#0f172a' }}>Auto-scan daily for new content</span>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              {config?.last_scan_date ? `Last scan ${config.last_scan_date}` : 'Never scanned'} · never publishes on its own
            </span>
          </label>
          <button
            style={{ ...runBtn, opacity: scan.isPending ? 0.6 : 1 }}
            disabled={scan.isPending}
            onClick={() => scan.mutate()}
          >
            <RefreshCw size={15} /> {scan.isPending ? 'Starting…' : 'Scan now'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 16 }}>
          <ToggleRow label="Blog posts" checked={config?.include_blog ?? true} disabled={!config}
            onChange={(v) => saveConfig.mutate({ include_blog: v })} />
          <ToggleRow label="Pages" checked={config?.include_pages ?? true} disabled={!config}
            onChange={(v) => saveConfig.mutate({ include_pages: v })} />
          <ToggleRow label="Products" checked={config?.include_products ?? true} disabled={!config}
            onChange={(v) => saveConfig.mutate({ include_products: v })} />
        </div>

        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginTop: 16 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: '#475569' }}>Publish to:</span>
            <select
              value={config?.publish_target ?? 'both'}
              disabled={!config || saveConfig.isPending}
              onChange={(e) => saveConfig.mutate({ publish_target: e.target.value as PublishTarget })}
              style={select}
            >
              <option value="both">Google Docs + Sheets</option>
              <option value="doc">Google Docs only</option>
              <option value="sheet">Google Sheets only</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: '#475569' }}>Sharing:</span>
            <select
              value={config?.share_mode ?? 'public'}
              disabled={!config || saveConfig.isPending}
              onChange={(e) => saveConfig.mutate({ share_mode: e.target.value as 'public' | 'link' })}
              style={select}
            >
              <option value="public">Anyone can find &amp; view (discoverable)</option>
              <option value="link">Anyone with the link can view</option>
            </select>
          </label>
        </div>
      </div>

      {(scan.isError || publish.isError) && (
        <Banner>{((scan.error || publish.error) as Error).message}</Banner>
      )}

      {/* ── Bulk publish bar ─────────────────────────────────────────────── */}
      {publishableRows.length > 0 && (
        <div style={bulkBar}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, color: '#0f172a' }}>
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            Select all ({publishableRows.length})
          </label>
          <span style={{ fontSize: 13, color: '#64748b' }}>{selected.size} selected</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: '#94a3b8' }}>→ {targetLabel} · {config?.share_mode === 'link' ? 'link-only' : 'public'}</span>
          <button
            style={{ ...runBtn, opacity: selected.size === 0 || publish.isPending ? 0.5 : 1 }}
            disabled={selected.size === 0 || publish.isPending}
            onClick={() => publish.mutate(Array.from(selected))}
          >
            <Globe size={15} /> Publish {selected.size || ''}
          </button>
        </div>
      )}

      {/* ── Filter tabs ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '18px 2px 12px', flexWrap: 'wrap' }}>
        {FILTERS.map(f => {
          const n = f.key === 'all' ? counts?.all : f.key === 'published' ? counts?.published : f.key === 'failed' ? counts?.failed : counts?.not_published
          return (
            <button key={f.key} onClick={() => pick(f.key)} style={filter === f.key ? tabActive : tab}>
              {f.label} {n !== undefined ? `(${n})` : ''}
            </button>
          )
        })}
        <span style={{ flex: 1 }} />
        {(counts?.published ?? 0) > 0 && (
          <button style={{ ...ghostBtn, opacity: exporting ? 0.6 : 1 }} disabled={exporting} onClick={exportPublished}>
            <Download size={14} /> {exporting ? 'Exporting…' : 'Export published CSV'}
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <div style={empty}>
          {filter === 'all'
            ? <>No pages discovered yet. Hit <strong>Scan now</strong> — the site's blog posts, pages &amp; products (from its sitemap) will be listed here for you to pick and publish.</>
            : 'Nothing in this view.'}
        </div>
      ) : (
        <>
          <div style={tableWrap}>
            <table style={table}>
              <thead>
                <tr>
                  <th style={{ ...th, width: 34 }} />
                  <th style={th}>Page</th>
                  <th style={th}>Type</th>
                  <th style={th}>Status</th>
                  <th style={th} />
                </tr>
              </thead>
              <tbody>
                {rows.map(item => {
                  const selectable = PUBLISHABLE.includes(item.status)
                  return (
                    <tr key={item.id}>
                      <td style={{ ...td, textAlign: 'center' }}>
                        {selectable && (
                          <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} />
                        )}
                      </td>
                      <td style={td}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 2 }}>
                          <span style={{ fontWeight: 500, color: '#0f172a' }}>{displayTitle(item)}</span>
                          {item.doc_url && <OutChip href={item.doc_url} icon={<FileText size={11} />} label="Doc" />}
                          {item.sheet_url && <OutChip href={item.sheet_url} icon={<Table2 size={11} />} label="Sheet" />}
                        </div>
                        <a href={item.source_url} target="_blank" rel="noreferrer" style={link}>
                          {item.source_url} <ExternalLink size={11} />
                        </a>
                      </td>
                      <td style={td}>{TYPE_LABEL[item.content_type]}</td>
                      <td style={td}><StatusBadge status={item.status} error={item.error} /></td>
                      <td style={{ ...td, textAlign: 'right' }}>
                        {item.status === 'failed' && (
                          <button style={retryBtn} disabled={retry.isPending} onClick={() => retry.mutate(item.id)}>
                            <RefreshCw size={12} /> Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* ── Pagination ─────────────────────────────────────────────── */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              {total === 0 ? '0' : `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, total)}`} of {total}
            </span>
            {pageCount > 1 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button style={{ ...pageBtn, opacity: page === 0 ? 0.4 : 1 }} disabled={page === 0} onClick={() => setPage(p => Math.max(0, p - 1))}>Prev</button>
                <span style={{ fontSize: 12, color: '#64748b' }}>Page {page + 1} of {pageCount}</span>
                <button style={{ ...pageBtn, opacity: page + 1 >= pageCount ? 0.4 : 1 }} disabled={page + 1 >= pageCount} onClick={() => setPage(p => p + 1)}>Next</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── Small components ─────────────────────────────────────────────────────────
function OutChip({ href, icon, label }: { href: string; icon: React.ReactNode; label: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 3, padding: '1px 7px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: '#ecfdf5', color: '#047857', textDecoration: 'none', border: '1px solid #a7f3d0' }}>
      {icon} {label}
    </a>
  )
}

function ToggleRow({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: '#334155' }}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

function StatusBadge({ status, error }: { status: ItemStatus; error: string | null }) {
  const map: Record<ItemStatus, { bg: string; fg: string; label: string }> = {
    discovered: { bg: '#f1f5f9', fg: '#475569', label: 'Not published' },
    skipped: { bg: '#f1f5f9', fg: '#475569', label: 'Not published' },
    rewriting: { bg: '#eff6ff', fg: '#1d4ed8', label: 'Publishing…' },
    published: { bg: '#ecfdf5', fg: '#047857', label: 'Published' },
    failed: { bg: '#fef2f2', fg: '#b91c1c', label: 'Failed' },
  }
  const s = map[status]
  return (
    <span title={status === 'failed' && error ? error : undefined}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 9px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: s.bg, color: s.fg }}>
      {status === 'failed' && <AlertTriangle size={11} />}
      {s.label}
    </span>
  )
}

function Banner({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', borderRadius: 8, padding: '10px 14px', fontSize: 13, margin: '0 0 16px' }}>
      {children}
    </div>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────
const backBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', color: '#6366f1', fontSize: 13, cursor: 'pointer', padding: 0, marginBottom: 18 }
const pill: React.CSSProperties = { padding: '2px 10px', borderRadius: 999, background: '#eff6ff', color: '#1d4ed8', fontSize: 12, fontWeight: 600 }
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, marginBottom: 16 }
const bulkBar: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 14, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '12px 16px', position: 'sticky', top: 12, zIndex: 5, boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }
const runBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 7, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const retryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, background: '#fff', color: '#b91c1c', border: '1px solid #fecaca', borderRadius: 7, padding: '5px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, background: '#fff', color: '#475569', border: '1px solid #cbd5e1', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const tab: React.CSSProperties = { background: 'none', border: '1px solid transparent', borderRadius: 8, padding: '6px 12px', fontSize: 13, fontWeight: 600, color: '#64748b', cursor: 'pointer' }
const tabActive: React.CSSProperties = { ...tab, background: '#eef2ff', color: '#4f46e5', border: '1px solid #c7d2fe' }
const pageBtn: React.CSSProperties = { background: '#fff', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 7, padding: '5px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const select: React.CSSProperties = { padding: '7px 10px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, color: '#0f172a', background: '#fff' }
const empty: React.CSSProperties = { background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 12, padding: 28, textAlign: 'center', color: '#64748b', fontSize: 14 }
const tableWrap: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', background: '#fff' }
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13 }
const th: React.CSSProperties = { textAlign: 'left', padding: '11px 14px', background: '#f8fafc', color: '#64748b', fontWeight: 600, fontSize: 12, borderBottom: '1px solid #e2e8f0' }
const td: React.CSSProperties = { padding: '11px 14px', borderBottom: '1px solid #f1f5f9', color: '#334155', verticalAlign: 'top' }
const link: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, color: '#4f46e5', textDecoration: 'none', maxWidth: 460, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }
