import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Copy, Check, Download, ExternalLink, Ban, CheckCircle, XCircle, Loader } from 'lucide-react'
import { api } from '../lib/api'
import type { RunDetail as RunDetailType, ServiceWriterOutput } from '../lib/types'

const TERMINAL = ['complete', 'failed', 'cancelled']

type Fmt = 'markdown' | 'html' | 'wordpress'

function download(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      style={btnStyle}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function StageChip({ label, status }: { label: string; status?: string | null }) {
  const s = status ?? 'pending'
  const color = s === 'complete' ? '#16a34a' : s === 'failed' ? '#dc2626' : s === 'running' ? '#6366f1' : '#94a3b8'
  const Icon = s === 'complete' ? CheckCircle : s === 'failed' ? XCircle : s === 'running' ? Loader : Loader
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color, padding: '4px 10px', border: `1px solid ${color}33`, borderRadius: 8, background: `${color}11` }}>
      <Icon size={14} /> {label}: {s}
    </span>
  )
}

export function ServicePageRunView({ run }: { run: RunDetailType }) {
  const queryClient = useQueryClient()
  const [fmt, setFmt] = useState<Fmt>('wordpress')
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)

  const publishMutation = useMutation({
    mutationFn: () => api.post<{ doc_url: string }>(`/runs/${run.id}/publish`, {}),
    onSuccess: (data) => {
      setPublishedUrl(data.doc_url)
      window.open(data.doc_url, '_blank')
    },
  })
  const cancelMutation = useMutation({
    mutationFn: () => api.post(`/runs/${run.id}/cancel`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['run', run.id] }),
  })

  const sw = (run.module_outputs?.service_writer?.output_payload ?? null) as unknown as ServiceWriterOutput | null
  const isLive = !TERMINAL.includes(run.status)
  const rendering = sw ? sw.renderings?.[fmt] ?? '' : ''
  const ext = fmt === 'markdown' ? 'md' : fmt === 'html' ? 'html' : 'html'

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={`/clients/${run.client_id}/service-pages`} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to Service Pages
      </Link>

      <div style={{ marginTop: 16, marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#6366f1', textTransform: 'uppercase', letterSpacing: 0.5 }}>Service Page</span>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '4px 0 0' }}>
          {sw?.title || run.title || run.keyword}
        </h1>
        {sw?.meta_description && <p style={{ color: '#64748b', margin: '6px 0 0', fontSize: 14 }}>{sw.meta_description}</p>}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '16px 0' }}>
        <StageChip label="Brief" status={run.module_outputs?.service_brief?.status} />
        <StageChip label="Writer" status={run.module_outputs?.service_writer?.status} />
        {isLive && (
          <button type="button" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending} style={btnStyle}>
            <Ban size={14} /> Cancel
          </button>
        )}
      </div>

      {run.status === 'failed' && (
        <div style={{ padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
          {run.error_message || 'Generation failed.'}
        </div>
      )}

      {isLive && <div style={{ color: '#64748b', fontSize: 14 }}>Generating… this page refreshes automatically.</div>}

      {sw && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '8px 0 12px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4, border: '1px solid #e2e8f0', borderRadius: 8, padding: 3 }}>
              {(['wordpress', 'html', 'markdown'] as Fmt[]).map((f) => (
                <button key={f} type="button" onClick={() => setFmt(f)}
                  style={{ ...tabStyle, ...(fmt === f ? tabActiveStyle : {}) }}>
                  {f === 'wordpress' ? 'WordPress' : f === 'html' ? 'HTML' : 'Markdown'}
                </button>
              ))}
            </div>
            <CopyButton text={rendering} />
            <button type="button" onClick={() => download(rendering, `${run.keyword}.${ext}`, 'text/plain')} style={btnStyle}>
              <Download size={14} /> Download
            </button>
            <button type="button" onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending} style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1' }}>
              {publishMutation.isPending ? 'Publishing…' : 'Publish to Google Doc'}
            </button>
            {publishedUrl && (
              <a href={publishedUrl} target="_blank" rel="noreferrer" style={{ ...btnStyle, textDecoration: 'none' }}>
                <ExternalLink size={14} /> Open Doc
              </a>
            )}
          </div>
          {fmt === 'wordpress' && (
            <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 8px' }}>
              Gutenberg block markup — paste into the WordPress block editor (Code editor) and it converts to native blocks.
            </p>
          )}
          <pre style={preStyle}>{rendering}</pre>

          {sw.schema_jsonld && (
            <details style={{ marginTop: 16 }}>
              <summary style={{ cursor: 'pointer', fontSize: 14, fontWeight: 600, color: '#334155' }}>
                JSON-LD structured data (Service + FAQPage)
              </summary>
              <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '8px 0' }}>
                <CopyButton text={sw.schema_jsonld} />
              </div>
              <pre style={preStyle}>{sw.schema_jsonld}</pre>
            </details>
          )}
        </>
      )}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }
const btnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '6px 12px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer' }
const tabStyle: React.CSSProperties = { fontSize: 13, padding: '5px 12px', border: 'none', borderRadius: 6, background: 'transparent', color: '#64748b', cursor: 'pointer' }
const tabActiveStyle: React.CSSProperties = { background: '#eef2ff', color: '#6366f1', fontWeight: 600 }
const preStyle: React.CSSProperties = { background: '#0f172a', color: '#e2e8f0', padding: 16, borderRadius: 10, overflow: 'auto', maxHeight: 480, fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }
