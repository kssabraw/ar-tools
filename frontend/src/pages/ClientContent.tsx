import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, FileText, MapPin } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, RunListResponse } from '../lib/types'
import { localSeoApi } from '../components/localseo/api'
import type { LocalSeoPageListItem } from '../components/localseo/types'
import { useBulkPublish, type PublishItem } from '../components/publish/useBulkPublish'
import { BulkPublishBar } from '../components/publish/BulkPublishBar'

// Per-client "publish existing content to Google Docs": one place that lists
// this client's completed pipeline runs (blog / service / location) and its
// saved Local SEO pages, each with a checkbox, and a shared bulk-publish bar.
export function ClientContent() {
  const { id } = useParams<{ id: string }>()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: runsResp, isLoading: runsLoading } = useQuery<RunListResponse>({
    queryKey: ['client-runs-complete', id],
    queryFn: () => api.get<RunListResponse>(`/runs?client_id=${id}&status=complete&page_size=200`),
    enabled: Boolean(id),
    staleTime: 60_000,
  })

  const { data: pages, isLoading: pagesLoading } = useQuery<LocalSeoPageListItem[]>({
    queryKey: ['client-local-seo-pages', id],
    queryFn: () => localSeoApi.listPages(id as string),
    enabled: Boolean(id),
    staleTime: 60_000,
  })

  const runs = runsResp?.data ?? []
  const localSeoPages = pages ?? []

  const bulk = useBulkPublish()

  // One unified item list spanning both content types — drives select-all and
  // the bulk-publish action; each item carries the endpoint type to call.
  const items: PublishItem[] = [
    ...runs.map((r): PublishItem => ({
      key: `run:${r.id}`,
      type: 'run',
      id: r.id,
      label: r.title ?? r.keyword,
    })),
    ...localSeoPages.map((p): PublishItem => ({
      key: `lsp:${p.id}`,
      type: 'local_seo_page',
      id: p.id,
      label: p.page_title ?? p.keyword,
    })),
  ]

  const loading = runsLoading || pagesLoading
  const isEmpty = !loading && items.length === 0

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <Link to={`/clients/${id}`} style={backLink}>
        <ArrowLeft size={15} /> Back to client
      </Link>

      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
          Publish content
        </h1>
        <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>
          Select existing content for {client?.name ?? 'this client'} and publish it to a Google Doc
          in their Drive folder, straight to their website, or both.
        </p>
      </div>

      {loading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading content…</div>
      ) : isEmpty ? (
        <div style={emptyCard}>No published-ready content yet. Generate articles or Local SEO pages first.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {runs.length > 0 && (
            <ContentSection
              title="Articles & pages"
              subtitle="Blog posts, service & location pages from the content pipeline."
              rows={runs.map(r => ({
                key: `run:${r.id}`,
                icon: <FileText size={15} color="#6366f1" />,
                title: r.title ?? r.keyword,
                meta: `${labelForContentType(r.content_type)} · ${formatDate(r.completed_at ?? r.created_at)}`,
                publishedUrl: r.published_doc_url ?? null,
              }))}
              bulk={bulk}
            />
          )}
          {localSeoPages.length > 0 && (
            <ContentSection
              title="Local SEO pages"
              subtitle="Location-specific service pages generated in the Local SEO tool."
              rows={localSeoPages.map(p => ({
                key: `lsp:${p.id}`,
                icon: <MapPin size={15} color="#0ea5e9" />,
                title: p.page_title ?? p.keyword,
                meta: `${p.location || 'Local SEO'} · ${formatDate(p.created_at)}`,
              }))}
              bulk={bulk}
            />
          )}
        </div>
      )}

      <BulkPublishBar items={items} bulk={bulk} wordpressConfigured={Boolean(client?.wordpress_site_url && client?.wordpress_app_password_set)} />
    </div>
  )
}

interface Row {
  key: string
  icon: React.ReactNode
  title: string
  meta: string
  // A previously-published Google Doc URL (persisted), shown when this row
  // hasn't been (re)published in the current session.
  publishedUrl?: string | null
}

function ContentSection({ title, subtitle, rows, bulk }: {
  title: string
  subtitle: string
  rows: Row[]
  bulk: ReturnType<typeof useBulkPublish>
}) {
  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: '#0f172a', margin: '0 0 2px' }}>{title}</h2>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: 0 }}>{subtitle}</p>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map(row => {
          const checked = bulk.selected.has(row.key)
          const result = bulk.results[row.key]
          return (
            <label key={row.key} style={{ ...rowStyle, borderColor: checked ? '#c7d2fe' : '#e2e8f0' }}>
              <input
                type="checkbox"
                checked={checked}
                onChange={e => bulk.toggle(row.key, e.target.checked)}
                disabled={bulk.publishing}
                style={{ width: 16, height: 16, cursor: 'pointer', accentColor: '#6366f1' }}
              />
              <span style={{ flexShrink: 0, display: 'flex' }}>{row.icon}</span>
              <span style={{ fontWeight: 600, fontSize: 14, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {row.title}
              </span>
              <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto', flexShrink: 0, whiteSpace: 'nowrap' }}>
                {result?.status === 'done' ? (
                  result.docUrl || result.siteUrl ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      {result.docUrl && <a href={result.docUrl} target="_blank" rel="noreferrer" style={{ color: '#16a34a', fontWeight: 600, textDecoration: 'none' }}>Open Doc ↗</a>}
                      {result.siteUrl && <a href={result.siteUrl} target="_blank" rel="noreferrer" style={{ color: '#2563eb', fontWeight: 600, textDecoration: 'none' }}>Open page ↗</a>}
                    </span>
                  ) : <span style={{ color: '#16a34a', fontWeight: 600 }}>Published</span>
                ) : result?.status === 'failed' ? (
                  <span style={{ color: '#dc2626' }} title={result.error}>Failed</span>
                ) : result?.status === 'publishing' ? (
                  <span style={{ color: '#6366f1' }}>Publishing…</span>
                ) : row.publishedUrl ? (
                  <a href={row.publishedUrl} target="_blank" rel="noreferrer" style={{ color: '#16a34a', fontWeight: 600, textDecoration: 'none' }} title="Already published to Google Docs">Published · Open Doc ↗</a>
                ) : row.meta}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

function labelForContentType(t: string): string {
  if (t === 'service_page') return 'Service page'
  if (t === 'location_page') return 'Location page'
  return 'Blog post'
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#6366f1',
  textDecoration: 'none', fontWeight: 600, marginBottom: 16,
}
const rowStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, cursor: 'pointer',
}
const emptyCard: React.CSSProperties = {
  background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 48,
  textAlign: 'center', color: '#64748b', fontSize: 14,
}
