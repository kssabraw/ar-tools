import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CalendarClock, Download, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, ClientReport, ReportPeriod, ReportSettings } from '../lib/types'

const PERIOD_LABELS: [ReportPeriod, string][] = [
  ['30d', 'Last 30 days'],
  ['60d', 'Last 60 days'],
  ['90d', 'Last 90 days'],
  ['120d', 'Last 120 days'],
  ['1y', 'Last year'],
  ['all', 'Since campaign start'],
]

// Client Reporting (Phase 6 UI + Phase 5 delivery/scheduling) — generate
// on-demand PDF reports (monthly SEO or AI Visibility), list history, download,
// and configure recipients + a monthly/weekly schedule. PDFs are assembled
// server-side and stored in the private `reports` bucket; the detail endpoint
// re-signs the download URL on read so it never goes stale. Scheduled runs
// deliver automatically (email + Drive copy); on-demand runs opt in.
export function ClientReports() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [downloading, setDownloading] = useState<string | null>(null)
  const [reportType, setReportType] = useState<'monthly' | 'ai_visibility'>('monthly')
  const [period, setPeriod] = useState<ReportPeriod>('30d')
  const [deliver, setDeliver] = useState(false)

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
    mutationFn: () => api.post<ClientReport>(`/clients/${clientId}/reports`, { report_type: reportType, period, deliver }),
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
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <select style={select} value={reportType} onChange={(e) => setReportType(e.target.value as 'monthly' | 'ai_visibility')}>
              <option value="monthly">Monthly SEO report</option>
              <option value="ai_visibility">AI Visibility report</option>
            </select>
            <select style={select} value={period} onChange={(e) => setPeriod(e.target.value as ReportPeriod)}>
              {PERIOD_LABELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <button style={primaryBtn} onClick={() => generate.mutate()} disabled={generate.isPending}>
              <RefreshCw size={14} style={generate.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
              {generate.isPending ? 'Starting…' : 'Generate report'}
            </button>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#475569', cursor: 'pointer' }}>
            <input type="checkbox" checked={deliver} onChange={(e) => setDeliver(e.target.checked)} />
            Email &amp; save to Drive when done
          </label>
        </div>
      </div>

      <SettingsCard clientId={clientId!} />

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : reports.length === 0 ? (
        <div style={emptyBox}>No reports yet — click <strong>Generate report</strong> to build the first one.</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 18 }}>
          <thead>
            <tr>
              <th style={th}>Generated</th>
              <th style={th}>Type</th>
              <th style={th}>Period</th>
              <th style={th}>Includes</th>
              <th style={th}>Status</th>
              <th style={th}>Delivered</th>
              <th style={{ ...th, textAlign: 'right' }}>PDF</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => (
              <tr key={r.id}>
                <td style={td}>{new Date(r.created_at).toLocaleString()}</td>
                <td style={td}>{TYPE_NAMES[r.report_type] ?? r.report_type}</td>
                <td style={td}>{r.period_start && r.period_end ? `${r.period_start} – ${r.period_end}` : '—'}</td>
                <td style={td}>{sectionsLabel(r)}</td>
                <td style={td}><StatusBadge status={r.status} error={r.error} /></td>
                <td style={td}><DeliveryBadges delivery={r.delivery} /></td>
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

// ── Phase 5 — delivery & schedule settings ───────────────────────────────────
const DOW = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function SettingsCard({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const { data: saved } = useQuery<ReportSettings>({
    queryKey: ['report-settings', clientId],
    queryFn: () => api.get<ReportSettings>(`/clients/${clientId}/report-settings`),
    enabled: Boolean(clientId),
  })
  const [form, setForm] = useState<ReportSettings | null>(null)
  const [recipientsText, setRecipientsText] = useState<string | null>(null)
  const s = form ?? saved
  const save = useMutation({
    // recipients goes up as the raw comma-separated string; the backend parses it.
    mutationFn: (body: Omit<Partial<ReportSettings>, 'recipients'> & { recipients: string }) =>
      api.put<ReportSettings>(`/clients/${clientId}/report-settings`, body),
    onSuccess: (r) => {
      setForm(r)
      setRecipientsText(null)
      void queryClient.invalidateQueries({ queryKey: ['report-settings', clientId] })
    },
  })
  if (!s) return null
  const set = (patch: Partial<ReportSettings>) => setForm({ ...s, ...patch })
  const recipients = recipientsText ?? s.recipients.join(', ')

  return (
    <div style={settingsCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <CalendarClock size={15} color="#6366f1" />
        <strong style={{ fontSize: 13.5, color: '#0f172a' }}>Delivery &amp; schedule</strong>
        {s.next_run_at && s.cadence !== 'disabled' && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>next run {new Date(s.next_run_at).toLocaleString()}</span>
        )}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        <div style={{ flex: '1 1 260px' }}>
          <div style={fieldLabel}>Recipients (account manager — comma-separated)</div>
          <input
            style={{ ...select, width: '100%' }}
            placeholder="am@agency.com"
            value={recipients}
            onChange={(e) => setRecipientsText(e.target.value)}
          />
        </div>
        <div>
          <div style={fieldLabel}>Schedule</div>
          <select style={select} value={s.cadence} onChange={(e) => set({ cadence: e.target.value as ReportSettings['cadence'] })}>
            <option value="disabled">Off</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
        {s.cadence === 'weekly' && (
          <div>
            <div style={fieldLabel}>Day</div>
            <select style={select} value={s.day_of_week ?? 0} onChange={(e) => set({ day_of_week: Number(e.target.value) })}>
              {DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </div>
        )}
        {s.cadence === 'monthly' && (
          <div>
            <div style={fieldLabel}>Day of month</div>
            <select style={select} value={s.day_of_month ?? 1} onChange={(e) => set({ day_of_month: Number(e.target.value) })}>
              {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        )}
        {s.cadence !== 'disabled' && (
          <div>
            <div style={fieldLabel}>Hour (UTC)</div>
            <select style={select} value={s.hour_utc} onChange={(e) => set({ hour_utc: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, i) => i).map((h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
            </select>
          </div>
        )}
        {s.cadence !== 'disabled' && (
          <div>
            <div style={fieldLabel}>Report covers</div>
            <select style={select} value={s.period} onChange={(e) => set({ period: e.target.value as ReportSettings['period'] })}>
              <option value="auto">Auto ({s.cadence === 'weekly' ? '7' : '30'} days)</option>
              {PERIOD_LABELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
        )}
        <label style={toggleLabel}>
          <input type="checkbox" checked={s.email_enabled} onChange={(e) => set({ email_enabled: e.target.checked })} /> Email
        </label>
        <label style={toggleLabel}>
          <input type="checkbox" checked={s.drive_enabled} onChange={(e) => set({ drive_enabled: e.target.checked })} /> Drive copy
        </label>
        <button
          style={{ ...primaryBtn, padding: '8px 14px' }}
          disabled={save.isPending}
          onClick={() => save.mutate({
            recipients, cadence: s.cadence, day_of_week: s.day_of_week, day_of_month: s.day_of_month,
            hour_utc: s.hour_utc, period: s.period, email_enabled: s.email_enabled, drive_enabled: s.drive_enabled,
          })}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>
      {save.isError && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 8 }}>{(save.error as Error).message}</div>}
      <div style={{ fontSize: 11.5, color: '#94a3b8', marginTop: 8 }}>
        Scheduled reports email the recipients (PDF attached) and save a copy to the client's Drive folder.
        Email needs SMTP configured on the server; the Drive copy needs the updated Apps Script deployment.
      </div>
    </div>
  )
}

function DeliveryBadges({ delivery }: { delivery: Record<string, string> | null }) {
  if (!delivery) return <span style={{ color: '#cbd5e1' }}>—</span>
  const mark = (v?: string) => (v === 'ok' ? '✓' : v === 'failed' ? '✗' : '—')
  const color = (v?: string) => (v === 'ok' ? '#15803d' : v === 'failed' ? '#b91c1c' : '#94a3b8')
  return (
    <span style={{ fontSize: 12 }}>
      <span style={{ color: color(delivery.email) }} title={delivery.email_error}>email {mark(delivery.email)}</span>
      {' · '}
      <span style={{ color: color(delivery.drive) }} title={delivery.drive_error}>drive {mark(delivery.drive)}</span>
    </span>
  )
}

function sectionsLabel(r: ClientReport): string {
  const s = r.sections
  if (!s) return '—'
  const ok = Object.entries(s).filter(([, v]) => v === 'ok').map(([k]) => SECTION_NAMES[k] ?? k)
  return ok.length ? ok.join(', ') : 'no data'
}

const SECTION_NAMES: Record<string, string> = {
  organic: 'Organic', geogrid: 'Maps', gbp: 'GBP', ai_visibility: 'AI Visibility',
}

const TYPE_NAMES: Record<string, string> = {
  monthly: 'Monthly SEO', weekly: 'Weekly SEO', ai_visibility: 'AI Visibility',
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
const select: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', fontSize: 13,
  color: '#0f172a', background: '#fff', outline: 'none',
}
const settingsCard: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, background: '#fff', marginTop: 18,
}
const fieldLabel: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 5,
}
const toggleLabel: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569',
  cursor: 'pointer', paddingBottom: 8,
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
