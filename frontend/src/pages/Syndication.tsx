import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Share2, RefreshCw, ExternalLink, FileText, Table2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// ── Types (mirror models/syndication.py) ────────────────────────────────────
interface SyndicationConfig {
  client_id: string
  enabled: boolean
  interval_days: number
  include_blog: boolean
  include_pages: boolean
  include_products: boolean
  share_mode: 'public' | 'link'
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

const TYPE_LABEL: Record<SyndicationItem['content_type'], string> = {
  blog_post: 'Blog post',
  page: 'Page',
  product: 'Product',
}

export function Syndication() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

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

  const { data: items } = useQuery<SyndicationItem[]>({
    queryKey: ['syndication-items', clientId],
    queryFn: () => api.get<SyndicationItem[]>(`/clients/${clientId}/syndication/items`),
    enabled: Boolean(clientId),
    // Poll while any item is still being processed so results land live.
    refetchInterval: (query) => {
      const data = query.state.data as SyndicationItem[] | undefined
      const busy = (data ?? []).some(i => i.status === 'discovered' || i.status === 'rewriting')
      return busy ? 5000 : false
    },
  })

  const saveConfig = useMutation({
    mutationFn: (patch: Partial<SyndicationConfig>) =>
      api.put<SyndicationConfig>(`/clients/${clientId}/syndication/config`, patch),
    onSuccess: (data) => queryClient.setQueryData(['syndication-config', clientId], data),
  })

  const scan = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/syndication/scan`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['syndication-items', clientId] }),
  })

  const retry = useMutation({
    mutationFn: (itemId: string) => api.post(`/clients/${clientId}/syndication/items/${itemId}/retry`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['syndication-items', clientId] }),
  })

  const rows = items ?? []
  const publishedCount = rows.filter(i => i.status === 'published').length
  const busy = rows.some(i => i.status === 'discovered' || i.status === 'rewriting')

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <button onClick={() => navigate(`/clients/${clientId}`)} style={backBtn}>
        <ArrowLeft size={14} /> Back to workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Share2 size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Content Syndication</h1>
        {busy && <span style={pill}>Working…</span>}
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 20px', maxWidth: 760 }}>
        {client?.name ?? 'This client'} · automatically watches the site for new blog posts, pages &amp; products,
        rewrites each into a unique version, and publishes it as a public Google Doc + Google Sheet that links back to the original page.
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
            <span style={{ fontWeight: 600, color: '#0f172a' }}>
              Auto-syndicate daily
            </span>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              {config?.last_scan_date ? `Last scan ${config.last_scan_date}` : 'Never scanned'}
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

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 16 }}>
          <span style={{ fontSize: 13, color: '#475569' }}>Sharing:</span>
          <select
            value={config?.share_mode ?? 'public'}
            disabled={!config || saveConfig.isPending}
            onChange={(e) => saveConfig.mutate({ share_mode: e.target.value as 'public' | 'link' })}
            style={select}
          >
            <option value="public">Anyone on the internet can find &amp; view (discoverable)</option>
            <option value="link">Anyone with the link can view</option>
          </select>
        </div>
      </div>

      {scan.isError && <Banner>{(scan.error as Error).message}</Banner>}

      {/* ── Items ────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', margin: '8px 2px 12px' }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', margin: 0 }}>
          Discovered content
        </h2>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>
          {rows.length} item{rows.length === 1 ? '' : 's'} · {publishedCount} published
        </span>
      </div>

      {rows.length === 0 ? (
        <div style={empty}>
          No content discovered yet. Run a scan — new blog posts, pages &amp; products found on the site will appear here and be syndicated automatically.
        </div>
      ) : (
        <div style={tableWrap}>
          <table style={table}>
            <thead>
              <tr>
                <th style={th}>Source page</th>
                <th style={th}>Type</th>
                <th style={th}>Status</th>
                <th style={th}>Outputs</th>
                <th style={th} />
              </tr>
            </thead>
            <tbody>
              {rows.map(item => (
                <tr key={item.id}>
                  <td style={td}>
                    <a href={item.source_url} target="_blank" rel="noreferrer" style={link}>
                      {item.title || item.source_url} <ExternalLink size={12} />
                    </a>
                  </td>
                  <td style={td}>{TYPE_LABEL[item.content_type]}</td>
                  <td style={td}><StatusBadge status={item.status} error={item.error} /></td>
                  <td style={td}>
                    <div style={{ display: 'flex', gap: 10 }}>
                      {item.doc_url && (
                        <a href={item.doc_url} target="_blank" rel="noreferrer" style={outLink}>
                          <FileText size={13} /> Doc
                        </a>
                      )}
                      {item.sheet_url && (
                        <a href={item.sheet_url} target="_blank" rel="noreferrer" style={outLink}>
                          <Table2 size={13} /> Sheet
                        </a>
                      )}
                      {!item.doc_url && !item.sheet_url && <span style={{ color: '#cbd5e1' }}>—</span>}
                    </div>
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}>
                    {item.status === 'failed' && (
                      <button
                        style={retryBtn}
                        disabled={retry.isPending}
                        onClick={() => retry.mutate(item.id)}
                      >
                        <RefreshCw size={12} /> Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Small components ─────────────────────────────────────────────────────────
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
    discovered: { bg: '#f1f5f9', fg: '#475569', label: 'Queued' },
    rewriting: { bg: '#eff6ff', fg: '#1d4ed8', label: 'Rewriting…' },
    published: { bg: '#ecfdf5', fg: '#047857', label: 'Published' },
    failed: { bg: '#fef2f2', fg: '#b91c1c', label: 'Failed' },
    skipped: { bg: '#f8fafc', fg: '#94a3b8', label: 'Skipped' },
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
const card: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, marginBottom: 24 }
const runBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 7, background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }
const retryBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, background: '#fff', color: '#b91c1c', border: '1px solid #fecaca', borderRadius: 7, padding: '5px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const select: React.CSSProperties = { padding: '7px 10px', borderRadius: 8, border: '1px solid #cbd5e1', fontSize: 13, color: '#0f172a', background: '#fff' }
const empty: React.CSSProperties = { background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: 12, padding: 28, textAlign: 'center', color: '#64748b', fontSize: 14 }
const tableWrap: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', background: '#fff' }
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13 }
const th: React.CSSProperties = { textAlign: 'left', padding: '11px 14px', background: '#f8fafc', color: '#64748b', fontWeight: 600, fontSize: 12, borderBottom: '1px solid #e2e8f0' }
const td: React.CSSProperties = { padding: '11px 14px', borderBottom: '1px solid #f1f5f9', color: '#334155', verticalAlign: 'top' }
const link: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, color: '#4f46e5', textDecoration: 'none', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
const outLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, color: '#0f172a', textDecoration: 'none', fontWeight: 600 }
