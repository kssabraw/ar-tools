import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType, RunStatus } from '../lib/types'
import { ArrowLeft, CheckCircle, XCircle, Clock, Loader, Download, Copy } from 'lucide-react'

function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']

const MODULES: { key: keyof RunDetailType['module_outputs']; label: string; runningStatus: RunStatus }[] = [
  { key: 'brief',         label: 'Brief Generator',    runningStatus: 'brief_running' },
  { key: 'sie',           label: 'SIE',                runningStatus: 'sie_running' },
  { key: 'research',      label: 'Research',           runningStatus: 'research_running' },
  { key: 'writer',        label: 'Content Writer',     runningStatus: 'writer_running' },
  { key: 'sources_cited', label: 'Sources Cited',      runningStatus: 'sources_cited_running' },
]

function sectionsToMarkdown(article: unknown[]): string {
  if (!Array.isArray(article)) return ''
  return article
    .slice()
    .sort((a: any, b: any) => (a.order ?? 0) - (b.order ?? 0))
    .map((s: any) => {
      const heading = s.heading ? `## ${s.heading}\n\n` : ''
      return `${heading}${s.body ?? ''}`
    })
    .join('\n\n')
}

function StatusIcon({ status, runStatus, moduleStatus }: {
  status: RunStatus
  runStatus: RunStatus
  moduleStatus: string | undefined
}) {
  if (moduleStatus === 'complete') return <CheckCircle size={16} color="#22c55e" />
  if (moduleStatus === 'failed') return <XCircle size={16} color="#dc2626" />
  if (status === runStatus) return <Loader size={16} color="#6366f1" style={{ animation: 'spin 1s linear infinite' }} />
  return <Clock size={16} color="#94a3b8" />
}

function StatusChip({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, { bg: string; color: string; label: string }> = {
    queued:                  { bg: '#f1f5f9', color: '#475569', label: 'Queued' },
    brief_running:           { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    sie_running:             { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    research_running:        { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    writer_running:          { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    sources_cited_running:   { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    complete:                { bg: '#dcfce7', color: '#166534', label: 'Complete' },
    failed:                  { bg: '#fee2e2', color: '#991b1b', label: 'Failed' },
    cancelled:               { bg: '#f1f5f9', color: '#475569', label: 'Cancelled' },
  }
  const s = map[status] ?? { bg: '#f1f5f9', color: '#475569', label: status }
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '4px 14px', fontSize: 13, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

export function RunDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: run, isLoading } = useQuery<RunDetailType>({
    queryKey: ['run', id],
    queryFn: () => api.get<RunDetailType>(`/runs/${id}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && !TERMINAL.includes(status) ? 3000 : false
    },
  })

  if (isLoading) return <div style={{ padding: 40, color: '#64748b' }}>Loading…</div>
  if (!run) return <div style={{ padding: 40, color: '#dc2626' }}>Run not found</div>

  const scPayload = run.module_outputs?.sources_cited?.output_payload
  const enrichedArticle = scPayload?.enriched_article as Record<string, unknown> | undefined
  const articleSections = enrichedArticle?.article as unknown[] | undefined
  const articleMarkdown = articleSections ? sectionsToMarkdown(articleSections) : null

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>

      <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20 }}>
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>{run.keyword}</h1>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            {run.started_at
              ? `Started ${new Date(run.started_at).toLocaleString()}`
              : `Created ${new Date(run.created_at).toLocaleString()}`}
            {run.completed_at && ` · Completed ${new Date(run.completed_at).toLocaleString()}`}
            {run.total_cost_usd != null && ` · $${run.total_cost_usd.toFixed(4)}`}
          </div>
        </div>
        <StatusChip status={run.status} />
      </div>

      <div style={cardStyle}>
        <h2 style={sectionTitle}>Pipeline Progress</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {MODULES.map((m) => {
            const mo = run.module_outputs?.[m.key]
            const moduleStatus = mo?.status
            const done = moduleStatus === 'complete'
            return (
              <div key={m.key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <StatusIcon status={run.status} runStatus={m.runningStatus} moduleStatus={moduleStatus} />
                <span style={{ fontSize: 14, color: done ? '#0f172a' : '#94a3b8', fontWeight: done ? 500 : 400, flex: 1 }}>
                  {m.label}
                </span>
                {mo?.duration_ms != null && (
                  <span style={{ fontSize: 12, color: '#94a3b8' }}>{(mo.duration_ms / 1000).toFixed(1)}s</span>
                )}
                {mo?.cost_usd != null && (
                  <span style={{ fontSize: 12, color: '#94a3b8' }}>${mo.cost_usd.toFixed(4)}</span>
                )}
              </div>
            )
          })}
        </div>

        {run.error_message && (
          <div style={{ marginTop: 16, padding: '12px 14px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
            <strong>Error{run.error_stage ? ` (${run.error_stage})` : ''}:</strong> {run.error_message}
          </div>
        )}
      </div>

      {articleMarkdown && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2 style={sectionTitle}>Generated Article</h2>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => navigator.clipboard.writeText(articleMarkdown)} style={ghostBtn}>
                <Copy size={13} /> Copy
              </button>
              <button
                onClick={() => downloadFile(articleMarkdown, `${run.keyword.replace(/\s+/g, '-')}.md`, 'text/markdown')}
                style={ghostBtn}
              >
                <Download size={13} /> Download .md
              </button>
              <button
                onClick={() => downloadFile(articleMarkdown, `${run.keyword.replace(/\s+/g, '-')}.txt`, 'text/plain')}
                style={ghostBtn}
              >
                <Download size={13} /> .txt
              </button>
            </div>
          </div>
          <pre style={{
            background: '#f8fafc',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            padding: 20,
            overflowX: 'auto',
            fontSize: 13,
            lineHeight: 1.7,
            color: '#374151',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 600,
            overflowY: 'auto',
          }}>
            {articleMarkdown}
          </pre>
        </div>
      )}

      {run.status === 'failed' && !articleMarkdown && (
        <div style={{ ...cardStyle, textAlign: 'center', padding: 48, color: '#64748b' }}>
          <XCircle size={32} color="#dc2626" style={{ marginBottom: 12 }} />
          <div>This run failed. Check the error message above.</div>
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#0f172a', margin: '0 0 16px' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
