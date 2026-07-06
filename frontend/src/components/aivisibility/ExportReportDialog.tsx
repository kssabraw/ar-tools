import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { X, FileDown, Eye, Printer, ArrowLeft, AlertTriangle } from 'lucide-react'
import { api } from '../../lib/api'
import { downloadFile } from '../localseo/shared'
import './animations.css'

// LABS' Export Report dialog: pick a date range (presets + custom), preview the
// white-label HTML report in an iframe, then download it as .html or print /
// save-as-PDF via the browser. The report itself is built server-side
// (services/brand_report_html.py). The Google-Doc report path is untouched.

type Preset = '7d' | '30d' | '90d' | '6m' | 'custom'
const PRESETS: { key: Preset; label: string; days: number | null }[] = [
  { key: '7d', label: 'Last 7 days', days: 7 },
  { key: '30d', label: 'Last 30 days', days: 30 },
  { key: '90d', label: 'Last 90 days', days: 90 },
  { key: '6m', label: 'Last 6 months', days: 182 },
  { key: 'custom', label: 'Custom', days: null },
]

const INCLUDES = [
  'Business profile & tracked keywords',
  'Global health score & visibility share',
  'Performance by AI engine',
  'Keyword performance',
  'Competitor benchmarking',
  'Monthly visibility opportunity cost',
  'White-label agency header',
]

const isoDay = (d: Date) => d.toISOString().slice(0, 10)

export function ExportReportDialog({ clientId, clientName, onClose }: {
  clientId: string
  clientName: string
  onClose: () => void
}) {
  const [preset, setPreset] = useState<Preset>('30d')
  const today = isoDay(new Date())
  const [customStart, setCustomStart] = useState(isoDay(new Date(Date.now() - 30 * 864e5)))
  const [customEnd, setCustomEnd] = useState(today)
  const [view, setView] = useState<'settings' | 'preview'>('settings')
  const iframeRef = useRef<HTMLIFrameElement>(null)

  const range = () => {
    const p = PRESETS.find(p => p.key === preset)!
    if (p.days == null) return { start_date: customStart, end_date: customEnd }
    return { start_date: isoDay(new Date(Date.now() - p.days * 864e5)), end_date: today }
  }

  const genMut = useMutation({
    mutationFn: () => api.post<{ html: string }>(`/clients/${clientId}/brand/report-html`, range()),
  })
  const html = genMut.data?.html ?? null

  // Any range change invalidates a previously generated report — without this,
  // download() would reuse the cached HTML for the old range.
  const changePreset = (p: Preset) => {
    setPreset(p)
    genMut.reset()
  }
  const changeCustom = (setter: (v: string) => void) => (v: string) => {
    setter(v)
    genMut.reset()
  }

  const preview = async () => {
    try {
      await genMut.mutateAsync()
      setView('preview')
    } catch {
      // stay on settings — genMut.isError renders the message there
    }
  }

  const download = async () => {
    let doc = html
    if (!doc) {
      try {
        doc = (await genMut.mutateAsync()).html
      } catch {
        return // error surfaces via genMut.isError in the settings view
      }
    }
    downloadFile(doc, `ai-visibility-report-${clientName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${today}.html`, 'text/html')
  }

  const print = () => iframeRef.current?.contentWindow?.print()

  return (
    <div style={overlay} onClick={onClose}>
      <div
        style={{ ...modal, ...(view === 'preview' ? { maxWidth: 900, height: '85vh', display: 'flex', flexDirection: 'column' } : {}) }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <strong style={{ fontSize: 16, color: '#0f172a' }}>Export visibility report</strong>
          <button style={closeBtn} onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px' }}>
          A white-label, print-ready report of {clientName}'s AI visibility. Use Print → “Save as PDF” for a PDF copy.
        </p>

        {view === 'settings' ? (
          <>
            {/* date range */}
            <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>Date range</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
              {PRESETS.map(p => (
                <button
                  key={p.key}
                  onClick={() => changePreset(p.key)}
                  style={{
                    padding: '6px 12px', fontSize: 12, fontWeight: 600, borderRadius: 8, cursor: 'pointer',
                    background: preset === p.key ? '#6366f1' : '#fff',
                    color: preset === p.key ? '#fff' : '#475569',
                    border: `1px solid ${preset === p.key ? '#6366f1' : '#e2e8f0'}`,
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {preset === 'custom' && (
              <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center' }}>
                <input type="date" style={dateInput} value={customStart} max={customEnd} onChange={e => changeCustom(setCustomStart)(e.target.value)} />
                <span style={{ color: '#94a3b8', fontSize: 12 }}>to</span>
                <input type="date" style={dateInput} value={customEnd} min={customStart} max={today} onChange={e => changeCustom(setCustomEnd)(e.target.value)} />
              </div>
            )}

            {/* report includes */}
            <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 10, padding: '12px 14px', margin: '6px 0 16px' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>Report includes</div>
              {INCLUDES.map(item => (
                <div key={item} style={{ fontSize: 12.5, color: '#334155', marginBottom: 4 }}>✓ {item}</div>
              ))}
            </div>

            {genMut.isError && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12.5, color: '#b91c1c', marginBottom: 12 }}>
                <AlertTriangle size={13} /> {(genMut.error as Error).message}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button style={ghostBtn} onClick={onClose}>Cancel</button>
              <button style={ghostBtn} disabled={genMut.isPending} onClick={() => void preview()}>
                <Eye size={13} /> {genMut.isPending ? 'Building…' : 'Preview'}
              </button>
              <button style={primaryBtn} disabled={genMut.isPending} onClick={() => void download()}>
                <FileDown size={14} /> Download
              </button>
            </div>
          </>
        ) : (
          <>
            <iframe
              ref={iframeRef}
              title="Report preview"
              srcDoc={html ?? ''}
              sandbox="allow-same-origin allow-modals"
              style={{ flex: 1, border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', width: '100%' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 12 }}>
              <button style={ghostBtn} onClick={() => setView('settings')}><ArrowLeft size={13} /> Back</button>
              <div style={{ display: 'flex', gap: 8 }}>
                <button style={ghostBtn} onClick={print}><Printer size={13} /> Print / Save as PDF</button>
                <button style={primaryBtn} onClick={() => void download()}><FileDown size={14} /> Download</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.4)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, zIndex: 50,
}
const modal: React.CSSProperties = {
  background: '#fff', borderRadius: 14, padding: 22, maxWidth: 500, width: '100%',
  maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 10px 40px rgba(15,23,42,0.2)',
}
const closeBtn: React.CSSProperties = { background: 'none', border: 'none', cursor: 'pointer', color: '#64748b', padding: 2 }
const dateInput: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 10px', fontSize: 13, color: '#0f172a', background: '#fff',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: '#6366f1', color: '#fff',
  border: 'none', borderRadius: 8, padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: '#fff', color: '#475569',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 12px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
}
