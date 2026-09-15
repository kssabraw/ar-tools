import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileBarChart, Download, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import type { ClientReport } from '../lib/types'
import { ErrorDetails } from './ErrorDetails'

/**
 * Prospect Snapshot — a one-click combined PDF for a prospect that aggregates
 * the latest Organic (Domain Intelligence), Maps, AI-visibility and
 * Competitive-Intel data into one deliverable. Reuses the client_reports
 * pipeline with report_type='prospect_snapshot'; the detail endpoint re-signs
 * the download URL on read, so a stale link never 404s.
 */
export function ProspectSnapshotCard({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const [downloading, setDownloading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { data: reports = [] } = useQuery<ClientReport[]>({
    queryKey: ['client-reports', clientId],
    queryFn: () => api.get<ClientReport[]>(`/clients/${clientId}/reports`),
    enabled: Boolean(clientId),
    // Poll while a snapshot is still rendering so it flips to "complete" live.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.report_type === 'prospect_snapshot' && (r.status === 'pending' || r.status === 'running'))
        ? 4000 : false,
  })
  const snapshots = reports.filter((r) => r.report_type === 'prospect_snapshot')

  const generate = useMutation({
    mutationFn: () => api.post<ClientReport>(`/clients/${clientId}/reports`, { report_type: 'prospect_snapshot' }),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['client-reports', clientId] })
    },
    onError: (e: unknown) => setError((e as Error).message),
  })

  async function download(reportId: string) {
    setDownloading(reportId)
    try {
      const fresh = await api.get<ClientReport>(`/clients/${clientId}/reports/${reportId}`)
      if (fresh.pdf_url) window.open(fresh.pdf_url, '_blank', 'noopener')
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 40, height: 40, borderRadius: 10, background: '#eef2ff', color: '#6366f1' }}>
            <FileBarChart size={20} />
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a' }}>Prospect Snapshot</div>
            <div style={{ fontSize: 13, color: '#94a3b8' }}>
              One combined PDF — organic, maps, AI visibility & competitors — from whatever you've run above.
            </div>
          </div>
        </div>
        <button style={primaryBtn} onClick={() => generate.mutate()} disabled={generate.isPending}>
          <RefreshCw size={14} style={generate.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
          {generate.isPending ? 'Starting…' : 'Generate snapshot'}
        </button>
      </div>

      {error && <div style={{ marginTop: 12 }}><ErrorDetails message={error} /></div>}

      {snapshots.length > 0 && (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {snapshots.slice(0, 5).map((r) => (
            <div key={r.id} style={row}>
              <span style={{ fontSize: 13, color: '#334155' }}>{new Date(r.created_at).toLocaleString()}</span>
              <span style={{ flex: 1 }} />
              <StatusBadge status={r.status} error={r.error} />
              {r.status === 'complete' ? (
                <button style={linkBtn} onClick={() => download(r.id)} disabled={downloading === r.id}>
                  <Download size={13} /> {downloading === r.id ? 'Opening…' : 'Download'}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function StatusBadge({ status, error }: { status: ClientReport['status']; error: string | null }) {
  const c = {
    complete: { fg: '#166534', bg: '#f0fdf4' },
    failed: { fg: '#b91c1c', bg: '#fef2f2' },
    running: { fg: '#b45309', bg: '#fffbeb' },
    pending: { fg: '#475569', bg: '#f1f5f9' },
  }[status]
  return (
    <span title={status === 'failed' && error ? error : undefined}
      style={{ fontSize: 11, fontWeight: 600, color: c.fg, background: c.bg, borderRadius: 999, padding: '2px 9px' }}>
      {status === 'running' || status === 'pending' ? 'Generating…' : status}
    </span>
  )
}

const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', padding: 20, marginBottom: 24,
}
const row: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderTop: '1px solid #f1f5f9',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '9px 16px', cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#6366f1',
  background: '#eef2ff', border: 'none', borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
}
