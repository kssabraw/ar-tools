import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, FileUp, Plus, Trash2, Clock, ExternalLink } from 'lucide-react'
import { api } from '../../lib/api'
import type { GeneratedReport, ReportListItem, ReportMode, ReportSchedule } from '../../lib/types'
import { card, errorBox, outlineBtn, primaryBtn, relativeTime } from '../localseo/shared'

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const MODE_LABELS: Record<ReportMode, string> = {
  as_needed: 'As needed (manual only)',
  weekly: 'Weekly, on a chosen day',
  monthly: 'Monthly, on a chosen day',
  interval: 'Every N days',
}

export function RankReports({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: schedule } = useQuery<ReportSchedule>({
    queryKey: ['rank-report-schedule', clientId],
    queryFn: () => api.get<ReportSchedule>(`/clients/${clientId}/rank/report-schedule`),
  })
  const { data: reports } = useQuery<ReportListItem[]>({
    queryKey: ['rank-reports', clientId],
    queryFn: () => api.get<ReportListItem[]>(`/clients/${clientId}/rank/reports`),
  })

  // Local draft of the schedule, seeded from the server value.
  const [mode, setMode] = useState<ReportMode>('as_needed')
  const [dow, setDow] = useState(0)
  const [dom, setDom] = useState(1)
  const [interval, setIntervalDays] = useState(7)
  const [deliver, setDeliver] = useState(false)
  useEffect(() => {
    if (!schedule) return
    setMode(schedule.mode)
    setDow(schedule.day_of_week ?? 0)
    setDom(schedule.day_of_month ?? 1)
    setIntervalDays(schedule.interval_days ?? 7)
    setDeliver(schedule.deliver_google_doc)
  }, [schedule])

  const saveMut = useMutation({
    mutationFn: () => api.put<ReportSchedule>(`/clients/${clientId}/rank/report-schedule`, {
      mode,
      day_of_week: mode === 'weekly' ? dow : null,
      day_of_month: mode === 'monthly' ? dom : null,
      interval_days: mode === 'interval' ? interval : null,
      deliver_google_doc: deliver,
      last_generated_at: null,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rank-report-schedule', clientId] }),
  })
  const publishMut = useMutation({
    mutationFn: (reportId: string) => api.post(`/rank-reports/${reportId}/publish`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rank-reports', clientId] }),
  })
  const genMut = useMutation({
    mutationFn: () => api.post<GeneratedReport>(`/clients/${clientId}/rank/reports`, {}),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['rank-reports', clientId] })
      navigate(`/clients/${clientId}/rankings/report/${r.id}`)
    },
  })
  const delMut = useMutation({
    mutationFn: (id: string) => api.delete<void>(`/rank-reports/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['rank-reports', clientId] }),
  })

  return (
    <div>
      {/* Schedule */}
      <div style={{ ...card, marginBottom: 20 }}>
        <h2 style={sectionTitle}>Report schedule</h2>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px', lineHeight: 1.6 }}>
          Auto-generate a rankings report on a cadence. Generated reports land in the archive below,
          ready to open and print. Choose <strong>As needed</strong> to only ever create them manually.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(Object.keys(MODE_LABELS) as ReportMode[]).map(m => (
            <label key={m} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: '#0f172a', cursor: 'pointer' }}>
              <input type="radio" name="mode" checked={mode === m} onChange={() => setMode(m)} />
              {MODE_LABELS[m]}
              {m === 'weekly' && mode === 'weekly' && (
                <select value={dow} onChange={e => setDow(Number(e.target.value))} style={selectStyle}>
                  {WEEKDAYS.map((d, i) => <option key={i} value={i}>{d}</option>)}
                </select>
              )}
              {m === 'monthly' && mode === 'monthly' && (
                <select value={dom} onChange={e => setDom(Number(e.target.value))} style={selectStyle}>
                  {Array.from({ length: 31 }, (_, i) => i + 1).map(d => <option key={d} value={d}>{ordinal(d)}</option>)}
                </select>
              )}
              {m === 'interval' && mode === 'interval' && (
                <select value={interval} onChange={e => setIntervalDays(Number(e.target.value))} style={selectStyle}>
                  {[7, 14, 30].map(n => <option key={n} value={n}>every {n} days</option>)}
                </select>
              )}
            </label>
          ))}
        </div>

        {mode === 'monthly' && dom > 28 && (
          <p style={{ fontSize: 12, color: '#b45309', margin: '8px 0 0' }}>
            Days after the 28th fall on the last day of shorter months.
          </p>
        )}

        <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: '#0f172a', cursor: 'pointer', marginTop: 14, paddingTop: 14, borderTop: '1px solid #f1f5f9' }}>
          <input type="checkbox" checked={deliver} onChange={e => setDeliver(e.target.checked)} />
          Also deliver each report as a <strong>Google Doc</strong> in the client’s Drive folder
        </label>
        <p style={{ fontSize: 12, color: '#94a3b8', margin: '4px 0 0', paddingLeft: 26 }}>
          Requires a Drive folder on the client (Client → Edit). You can also publish any saved report to a Doc with the
          button on each report below.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
          <button style={primaryBtn} onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
            {saveMut.isPending ? 'Saving…' : 'Save schedule'}
          </button>
          {schedule?.last_generated_at && (
            <span style={{ fontSize: 12, color: '#94a3b8', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <Clock size={12} /> last generated {relativeTime(schedule.last_generated_at)}
            </span>
          )}
        </div>
      </div>

      {/* Archive */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={{ ...sectionTitle, margin: 0 }}>Reports</h2>
          <button style={outlineBtn} onClick={() => genMut.mutate()} disabled={genMut.isPending}>
            <Plus size={14} /> {genMut.isPending ? 'Generating…' : 'Generate now'}
          </button>
        </div>
        {genMut.error && <div style={errorBox}>{(genMut.error as Error).message}</div>}
        {publishMut.error && <div style={errorBox}>Couldn’t publish to Google Doc: {(publishMut.error as Error).message}. Check the client has a Drive folder set.</div>}

        {reports && reports.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {reports.map((r, i) => (
              <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 2px', borderTop: i ? '1px solid #f1f5f9' : 'none' }}>
                <FileText size={15} color="#6366f1" />
                <Link to={`/clients/${clientId}/rankings/report/${r.id}`}
                  style={{ flex: 1, color: '#0f172a', textDecoration: 'none', fontSize: 14, fontWeight: 600 }}>
                  {r.title}
                </Link>
                <span style={{ fontSize: 12, color: '#94a3b8' }}>{relativeTime(r.created_at)}</span>
                {r.doc_url ? (
                  <a href={r.doc_url} target="_blank" rel="noreferrer" style={{ ...outlineBtn, padding: '4px 9px', fontSize: 12, color: '#0369a1', textDecoration: 'none' }}>
                    <ExternalLink size={12} /> Doc
                  </a>
                ) : (
                  <button style={{ ...outlineBtn, padding: '4px 9px', fontSize: 12 }}
                    onClick={() => publishMut.mutate(r.id)}
                    disabled={publishMut.isPending && publishMut.variables === r.id}
                    title="Publish this report to a Google Doc in the client's Drive folder">
                    <FileUp size={12} /> {publishMut.isPending && publishMut.variables === r.id ? 'Publishing…' : 'To Doc'}
                  </button>
                )}
                <button style={{ ...outlineBtn, padding: '4px 7px', color: '#dc2626' }}
                  onClick={() => delMut.mutate(r.id)} title="Delete report"><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 13, color: '#94a3b8', margin: 0 }}>
            No reports yet. Generate one now, or set a schedule above.
          </p>
        )}
      </div>
    </div>
  )
}

function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'], v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

const sectionTitle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: '#0f172a', margin: '0 0 8px',
  textTransform: 'uppercase', letterSpacing: '0.04em',
}
const selectStyle: React.CSSProperties = {
  fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid #cbd5e1', marginLeft: 4,
}
