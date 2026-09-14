import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, Loader2, ExternalLink, CheckCircle2, AlertCircle } from 'lucide-react'
import { api } from '../lib/api'

// On-demand "generate now" for the weekly department-head board reports (PACE /
// DORA / Client Health). They normally run on the shared scheduler (Monday);
// this admin page triggers a run any time (e.g. right before a meeting). Delivery
// follows the server config — a PDF to the Drive folder, plus Slack only when
// board_reports_slack_enabled. Mirrors POST/GET /board-reports/* .

interface Status {
  enabled: boolean
  slack_enabled: boolean
  drive_folder_id: string | null
  drive_folder_url: string | null
  pdf_configured: boolean
  weekday: number
}

interface PdfResult {
  published: boolean
  file_url?: string | null
  reason?: string | null
}
interface ReportResult {
  emitted: boolean
  deduped?: boolean
  rag?: string
  pdf?: PdfResult
  slack?: boolean
  reason?: string
}
interface RunResult {
  emitted: boolean
  reason?: string
  reports?: Record<string, ReportResult>
}

const LABELS: Record<string, string> = {
  pace: 'PACE — Delivery & Operations',
  director: 'DORA — Operating-model health',
  client: 'Client Health',
}

export function BoardReports() {
  const [result, setResult] = useState<RunResult | null>(null)
  const { data: status } = useQuery<Status>({
    queryKey: ['board-reports-status'],
    queryFn: () => api.get<Status>('/board-reports/status'),
    staleTime: 60_000,
  })

  const run = useMutation({
    mutationFn: () => api.post<RunResult>('/board-reports/run', {}),
    onSuccess: (data) => setResult(data),
  })

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <FileText size={22} />
        <h1 style={{ margin: 0, fontSize: 22 }}>Board reports</h1>
      </div>
      <p style={{ color: '#57606a', marginTop: 0 }}>
        Generate the three department-head reports (PACE, DORA, Client Health) on demand and
        publish each as a PDF to the Drive folder. They also run automatically every Monday.
      </p>

      {status && (
        <div style={{ fontSize: 13, color: '#57606a', margin: '12px 0 20px', lineHeight: 1.7 }}>
          <div>Weekly schedule: {status.enabled ? 'on' : 'off'} (Mondays)</div>
          <div>
            PDF delivery:{' '}
            {status.pdf_configured ? (
              <>
                configured →{' '}
                {status.drive_folder_url ? (
                  <a href={status.drive_folder_url} target="_blank" rel="noreferrer">
                    open Drive folder <ExternalLink size={12} style={{ verticalAlign: 'middle' }} />
                  </a>
                ) : (
                  'set'
                )}
              </>
            ) : (
              <span style={{ color: '#cf222e' }}>not configured (no Drive folder / webhook)</span>
            )}
          </div>
          <div>Slack + in-app copy: {status.slack_enabled ? 'on' : 'off (PDF only)'}</div>
        </div>
      )}

      <button
        onClick={() => run.mutate()}
        disabled={run.isPending}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px',
          fontSize: 15, fontWeight: 600, color: '#fff', background: '#1f6feb',
          border: 'none', borderRadius: 6, cursor: run.isPending ? 'default' : 'pointer',
          opacity: run.isPending ? 0.7 : 1,
        }}
      >
        {run.isPending ? <Loader2 size={16} className="spin" /> : <FileText size={16} />}
        {run.isPending ? 'Generating…' : 'Generate now'}
      </button>

      {run.isError && (
        <p style={{ color: '#cf222e', marginTop: 16 }}>
          <AlertCircle size={14} style={{ verticalAlign: 'middle' }} /> Failed to generate — try again.
        </p>
      )}

      {result && (
        <div style={{ marginTop: 24 }}>
          <h2 style={{ fontSize: 15, borderBottom: '1px solid #d0d7de', paddingBottom: 4 }}>
            Result
          </h2>
          {Object.entries(result.reports || {}).map(([key, r]) => {
            const ok = r.pdf?.published
            return (
              <div
                key={key}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0',
                  borderBottom: '1px solid #eaeef2',
                }}
              >
                {ok ? (
                  <CheckCircle2 size={16} color="#1a7f37" />
                ) : (
                  <AlertCircle size={16} color="#9a6700" />
                )}
                <span style={{ fontWeight: 600, minWidth: 260 }}>{LABELS[key] || key}</span>
                <span style={{ fontSize: 13, color: '#57606a' }}>
                  {ok ? (
                    r.pdf?.file_url ? (
                      <a href={r.pdf.file_url} target="_blank" rel="noreferrer">
                        open PDF <ExternalLink size={12} style={{ verticalAlign: 'middle' }} />
                      </a>
                    ) : (
                      'PDF published'
                    )
                  ) : (
                    `PDF not published (${r.pdf?.reason || 'unknown'})`
                  )}
                </span>
              </div>
            )
          })}
          {!result.reports && (
            <p style={{ color: '#9a6700' }}>Nothing generated ({result.reason || 'unknown'}).</p>
          )}
          <p style={{ fontSize: 12, color: '#57606a', marginTop: 12 }}>
            PDFs are saved to the Drive folder. Delivery is PDF-only unless the Slack copy is turned on.
          </p>
        </div>
      )}
    </div>
  )
}
