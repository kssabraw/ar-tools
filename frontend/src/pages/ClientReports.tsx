import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, ClientReport } from '../lib/types'

// Client Reporting (Phase 6) — generate on-demand PDF reports, list history,
// download. The PDF is assembled server-side (organic rankings, Maps geo-grids,
// GBP) and stored in the private `reports` bucket; the detail endpoint re-signs
// the download URL on read so it never goes stale.
export function ClientReports() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [downloading, setDownloading] = useState<string | null>(null)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: reports = [], isLoading } = useQuery<ClientReport[]>({
    queryKey: ['client-reports', clientId],
    queryFn: () => api.get<ClientReport[]>(`/clients/${clientId}/reports`),
    enabled: Boolean(clientId),
    // Poll while any report is still rendering so it flips to "complete" live.
    refetchInterval: (q) =>
      (q.state.data ?? []).some((r) => r.status === 'pending' || r.status === 'running') ? 4000 : false,
  })

  const generate = useMutation({
    mutationFn: () => api.post<ClientReport>(`/clients/${clientId}/reports`, { report_type: 'monthly' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['client-reports', clientId] }),
  })

  // Re-sign on click so an expired stored URL never 404s, then open the PDF.
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
    <div style={{ padding: 32, maxWidth: 920 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Client Reports</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0' }}>
            Generate a PDF performance report for {client?.name ?? 'this client'} — organic rankings, local-pack
            geo-grids, and Google Business Profile. (Analytics, Asana & a campaign-health summary come in later phases.)
          </p>
        </div>
        <button style={primaryBtn} onClick={() => generate.mutate()} disabled={generate.isPending}>
          <RefreshCw size={14} style={generate.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
          {generate.isPending ? 'Starting…' : 'Generate report'}
        </button>
      </div>

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : reports.length === 0 ? (
        <div style={emptyBox}>No reports yet — click <strong>Generate report</strong> to build the first one.</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 18 }}>
          <thead>
            <tr>
              <th style={th}>Generated</th>
              <th style={th}>Period</th>
              <th style={th}>Includes</th>
              <th style={th}>Status</th>
              <th style={{ ...th, textAlign: 'right' }}>PDF</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td style={td}>{new Date(r.created_at).toLocaleString()}</td>
                <td style={td}>{r.period_start && r.period_end ? `${r.period_start} – ${r.period_end}` : '—'}</td>
                <td style={td}>{sectionsLabel(r)}</td>
                <td style={td}><StatusBadge status={r.status} error={r.error} /></td>
                <td style={{ ...td, textAlign: 'right' }}>
                  {r.status === 'complete' ? (
                    <button style={linkBtn} onClick={() => download(r.id)} disabled={downloading === r.id}>
                      <Download size={13} /> {downloading === r.id ? 'Opening…' : 'Download'}
                    </button>
                  ) : (
                    <span style={{ color: '#cbd5e1' }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function sectionsLabel(r: ClientReport): string {
  const s = r.sections
  if (!s) return '—'
  const ok = Object.entries(s).filter(([, v]) => v === 'ok').map(([k]) => SECTION_NAMES[k] ?? k)
  return ok.length ? ok.join(', ') : 'no data'
}

const SECTION_NAMES: Record<string, string> = {
  organic: 'Organic', geogrid: 'Maps', gbp: 'GBP',
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

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none',
  color: '#6366f1', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0,
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '9px 16px', cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#6366f1',
  background: '#eef2ff', border: 'none', borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
}
const emptyBox: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center', marginTop: 18,
}
const th: React.CSSProperties = {
  textAlign: 'left', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#94a3b8', padding: '6px 10px', borderBottom: '1px solid #e2e8f0',
}
const td: React.CSSProperties = { fontSize: 13, color: '#334155', padding: '10px', borderBottom: '1px solid #f1f5f9' }
