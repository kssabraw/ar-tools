import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunListResponse } from '../lib/types'
import { Download, Copy, FileText, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { sectionsToMarkdown } from '../lib/sectionsToMarkdown'
import { sectionsToHtml } from '../lib/sectionsToHtml'
import { FeedbackButton } from '../components/FeedbackButton'

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function ArticleCard({ run }: { run: any }) {
  const [expanded, setExpanded] = useState(false)
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)
  const [fmt, setFmt] = useState<'markdown' | 'html'>('markdown')

  const publishMutation = useMutation({
    mutationFn: () => api.post<{ doc_url: string }>(`/runs/${run.id}/publish`, {}),
    onSuccess: (data) => {
      setPublishedUrl(data.doc_url)
      window.open(data.doc_url, '_blank')
    },
  })

  const { data: detail, isLoading } = useQuery({
    queryKey: ['run', run.id],
    queryFn: () => api.get<any>(`/runs/${run.id}`),
    enabled: expanded,
    staleTime: Infinity,
  })

  const scPayload = detail?.module_outputs?.sources_cited?.output_payload
  const writerPayload = detail?.module_outputs?.writer?.output_payload
  const briefPayload = detail?.module_outputs?.brief_generator?.output_payload
  const articleSections = (scPayload?.enriched_article as any)?.article as unknown[] | undefined
  const articleTitle: string | undefined =
    writerPayload?.title || briefPayload?.title || undefined
  const markdown = articleSections ? sectionsToMarkdown(articleSections, articleTitle) : null
  const html = articleSections ? sectionsToHtml(articleSections, articleTitle) : null
  // The card header above already shows the article title (line ~94).
  // Stripping the leading H1 from the preview keeps the user from
  // reading the headline twice; copy / download / publish still use
  // `markdown` so the exported file remains self-contained.
  const markdownPreview = markdown
    ? markdown.replace(/^# [^\n]*\n+/, '')
    : null
  const slug = run.keyword.replace(/\s+/g, '-').toLowerCase()

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <FileText size={15} color="#6366f1" style={{ flexShrink: 0 }} />
            <span style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {run.title ?? run.keyword}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>
            {run.title && <>“{run.keyword}” · </>}
            {run.client_name} · {new Date(run.completed_at ?? run.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            {run.total_cost_usd != null && ` · $${Number(run.total_cost_usd).toFixed(4)}`}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
          {markdown && (
            <>
              <div style={{ display: 'inline-flex', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
                {(['markdown', 'html'] as const).map(f => (
                  <button key={f} onClick={() => setFmt(f)} style={{
                    padding: '5px 10px', fontSize: 12, fontWeight: 600, border: 'none', cursor: 'pointer',
                    background: fmt === f ? '#6366f1' : '#fff', color: fmt === f ? '#fff' : '#64748b',
                  }}>
                    {f === 'markdown' ? 'MD' : 'HTML'}
                  </button>
                ))}
              </div>
              <FeedbackButton
                baseStyle={ghostBtn}
                doneLabel="Copied!"
                onAction={() => { const content = fmt === 'html' ? html : markdown; if (content) navigator.clipboard.writeText(content) }}
              >
                <Copy size={13} /> Copy {fmt === 'html' ? 'HTML' : 'MD'}
              </FeedbackButton>
              {fmt === 'html' ? (
                <FeedbackButton
                  baseStyle={ghostBtn}
                  doneLabel="Saved!"
                  onAction={() => downloadFile(html ?? '', `${slug}.html`, 'text/html')}
                >
                  <Download size={13} /> .html
                </FeedbackButton>
              ) : (
                <>
                  <FeedbackButton
                    baseStyle={ghostBtn}
                    doneLabel="Saved!"
                    onAction={() => downloadFile(markdown, `${slug}.md`, 'text/markdown')}
                  >
                    <Download size={13} /> .md
                  </FeedbackButton>
                  <FeedbackButton
                    baseStyle={ghostBtn}
                    doneLabel="Saved!"
                    onAction={() => downloadFile(markdown, `${slug}.txt`, 'text/plain')}
                  >
                    <Download size={13} /> .txt
                  </FeedbackButton>
                </>
              )}
              {publishedUrl ? (
                <a href={publishedUrl} target="_blank" rel="noreferrer"
                  style={{ ...ghostBtn, textDecoration: 'none', color: '#16a34a', borderColor: '#bbf7d0' }}>
                  <ExternalLink size={13} /> Open Doc
                </a>
              ) : (
                <button
                  onClick={() => publishMutation.mutate()}
                  disabled={publishMutation.isPending}
                  style={{ ...ghostBtn, color: '#6366f1', borderColor: '#c7d2fe' }}
                  title="Publish to the client's Google Drive folder"
                >
                  <ExternalLink size={13} /> {publishMutation.isPending ? 'Publishing…' : 'Publish to Google Docs'}
                </button>
              )}
            </>
          )}
          <Link to={`/runs/${run.id}`} style={{ ...ghostBtn, textDecoration: 'none' }}>
            View run
          </Link>
          <button onClick={() => setExpanded(e => !e)} style={iconBtn}>
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {publishMutation.error && (
        <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', borderRadius: 6, color: '#dc2626', fontSize: 12 }}>
          {(publishMutation.error as Error).message}
        </div>
      )}

      {expanded && (
        <div style={{ marginTop: 16 }}>
          {isLoading && <div style={{ color: '#94a3b8', fontSize: 13 }}>Loading article…</div>}
          {!isLoading && !markdown && <div style={{ color: '#94a3b8', fontSize: 13 }}>Article content not available.</div>}
          {markdown && (
            <pre style={{
              background: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: 8,
              padding: 20,
              fontSize: 13,
              lineHeight: 1.7,
              color: '#374151',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              maxHeight: 500,
              overflowY: 'auto',
              margin: 0,
            }}>
              {fmt === 'html' ? html : markdownPreview}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

export function Articles() {
  const [search, setSearch] = useState('')

  const { data: runsResp, isLoading } = useQuery<RunListResponse>({
    queryKey: ['runs', 'complete'],
    queryFn: () => api.get<RunListResponse>('/runs?status=complete&page_size=200'),
    staleTime: 60_000,
  })

  const runs = (runsResp?.data ?? []).filter(r =>
    search === '' || r.keyword.toLowerCase().includes(search.toLowerCase()) || r.client_name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Saved Articles</h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>All completed content runs. Click the arrow to preview or download.</p>
        </div>
      </div>

      <div style={{ marginBottom: 20 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by keyword or client…"
          style={{ padding: '9px 14px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, width: 300, color: '#0f172a' }}
        />
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading articles…</div>
      ) : runs.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          {search ? 'No articles match your search.' : 'No completed articles yet. Start a run to generate content.'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {runs.map(run => <ArticleCard key={run.id} run={run} />)}
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 20 }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px 8px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer' }
