import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType } from '../lib/types'
import { ArrowLeft, CheckCircle, XCircle, Clock, Loader } from 'lucide-react'

const MODULES = [
  { key: 'brief_output', label: 'Brief Generator' },
  { key: 'sie_output', label: 'SIE' },
  { key: 'research_output', label: 'Research & Citations' },
  { key: 'writer_output', label: 'Content Writer' },
  { key: 'sources_output', label: 'Sources Cited' },
] as const

function ModuleStatus({ data, isRunning }: { data: unknown; isRunning: boolean }) {
  if (data) return <CheckCircle size={16} color="#22c55e" />
  if (isRunning) return <Loader size={16} color="#6366f1" style={{ animation: 'spin 1s linear infinite' }} />
  return <Clock size={16} color="#94a3b8" />
}

export function RunDetail() {
  const { id } = useParams<{ id: string }>()

  const { data: run, isLoading } = useQuery<RunDetailType>({
    queryKey: ['run', id],
    queryFn: () => api.get<RunDetailType>(`/runs/${id}`),
    refetchInterval: run =>
      run.state.data?.status === 'running' || run.state.data?.status === 'pending' ? 3000 : false,
  })

  if (isLoading) return <div style={{ padding: 40, color: '#64748b' }}>Loading…</div>
  if (!run) return <div style={{ padding: 40, color: '#dc2626' }}>Run not found</div>

  const isRunning = run.status === 'running' || run.status === 'pending'

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20 }}>
        <ArrowLeft size={14} /> Back to Runs
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>{run.keyword}</h1>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            Started {new Date(run.created_at).toLocaleString()}
            {run.completed_at && ` · Completed ${new Date(run.completed_at).toLocaleString()}`}
          </div>
        </div>
        <StatusChip status={run.status} />
      </div>

      <div style={cardStyle}>
        <h2 style={sectionTitle}>Pipeline Progress</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {MODULES.map((m, i) => {
            const data = run[m.key]
            const prevDone = i === 0 || run[MODULES[i - 1].key] !== null
            const active = isRunning && prevDone && !data
            return (
              <div key={m.key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <ModuleStatus data={data} isRunning={active} />
                <span style={{ fontSize: 14, color: data ? '#0f172a' : '#94a3b8', fontWeight: data ? 500 : 400 }}>
                  {m.label}
                </span>
              </div>
            )
          })}
        </div>
        {run.error_message && (
          <div style={{ marginTop: 16, padding: '12px 14px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
            <strong>Error:</strong> {run.error_message}
          </div>
        )}
      </div>

      {run.article_markdown && (
        <div style={cardStyle}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <h2 style={sectionTitle}>Generated Article</h2>
            <button
              onClick={() => navigator.clipboard.writeText(run.article_markdown!)}
              style={ghostBtn}
            >
              Copy Markdown
            </button>
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
            {run.article_markdown}
          </pre>
        </div>
      )}

      {run.status === 'failed' && !run.article_markdown && (
        <div style={{ ...cardStyle, textAlign: 'center', padding: 48, color: '#64748b' }}>
          <XCircle size={32} color="#dc2626" style={{ marginBottom: 12 }} />
          <div>This run failed. Check the error message above.</div>
        </div>
      )}
    </div>
  )
}

function StatusChip({ status }: { status: RunDetailType['status'] }) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    pending: { bg: '#fef3c7', color: '#92400e', label: 'Pending' },
    running: { bg: '#dbeafe', color: '#1e40af', label: 'Running' },
    completed: { bg: '#dcfce7', color: '#166534', label: 'Completed' },
    failed: { bg: '#fee2e2', color: '#991b1b', label: 'Failed' },
  }
  const s = map[status]
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: 999, padding: '4px 14px', fontSize: 13, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#0f172a', margin: '0 0 16px' }
const ghostBtn: React.CSSProperties = { padding: '7px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
