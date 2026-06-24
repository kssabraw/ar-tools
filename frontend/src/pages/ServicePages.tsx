import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileText, ArrowRight, Loader } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, RunListResponse, RunStatus } from '../lib/types'

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']

function statusColor(status: RunStatus): string {
  if (status === 'complete') return '#16a34a'
  if (status === 'failed') return '#dc2626'
  if (status === 'cancelled') return '#94a3b8'
  return '#6366f1'
}

export function ServicePages() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [keyword, setKeyword] = useState('')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: runs } = useQuery<RunListResponse>({
    queryKey: ['service-page-runs', id],
    queryFn: () => api.get<RunListResponse>(`/runs?client_id=${id}&content_type=service_page&page_size=100`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const list = query.state.data?.data ?? []
      return list.some((r) => !TERMINAL.includes(r.status)) ? 5000 : false
    },
  })

  const createRun = useMutation({
    mutationFn: (kw: string) =>
      api.post<{ run_id: string }>('/runs', { client_id: id, keyword: kw, content_type: 'service_page' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service-page-runs', id] })
      setKeyword('')
    },
  })

  const list = runs?.data ?? []

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '16px 0 4px' }}>
        <FileText size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Service Pages</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 0 }}>
        Conversion-focused service / landing pages. Enter the head commercial query — the brief and
        writer run in one pass, and you get Markdown, HTML, and WordPress-ready output.
      </p>

      {/* Create */}
      <div style={{ display: 'flex', gap: 8, margin: '16px 0 28px' }}>
        <input
          className="input"
          placeholder="e.g. emergency drain cleaning austin"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && keyword.trim()) createRun.mutate(keyword.trim()) }}
          style={inputStyle}
        />
        <button
          type="button"
          onClick={() => keyword.trim() && createRun.mutate(keyword.trim())}
          disabled={!keyword.trim() || createRun.isPending}
          style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1', opacity: keyword.trim() ? 1 : 0.5 }}
        >
          {createRun.isPending ? 'Starting…' : 'Generate'}
        </button>
      </div>
      {createRun.isError && (
        <div style={{ color: '#dc2626', fontSize: 13, marginTop: -16, marginBottom: 16 }}>
          Could not start the run. {(createRun.error as Error)?.message}
        </div>
      )}

      {/* List */}
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#334155' }}>Generated pages</h2>
      {list.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 14, padding: '12px 0' }}>No service pages yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {list.map((r) => {
            const running = !TERMINAL.includes(r.status)
            return (
              <Link key={r.id} to={`/runs/${r.id}`} style={rowStyle}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.title || r.keyword}
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>{new Date(r.created_at).toLocaleString()}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: statusColor(r.status) }}>
                    {running && <Loader size={13} />} {r.status.replace(/_/g, ' ')}
                  </span>
                  <ArrowRight size={15} color="#cbd5e1" />
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }
const inputStyle: React.CSSProperties = { flex: 1, fontSize: 14, padding: '9px 12px', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none' }
const btnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 14, padding: '9px 16px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer', fontWeight: 600 }
const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', textDecoration: 'none' }
