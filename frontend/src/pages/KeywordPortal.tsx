import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Plus, Check, AlertTriangle, Loader2 } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// ── Types (mirror models/keyword_portal.py) ─────────────────────────────────
interface TargetResult {
  added: number
  skipped_duplicates: number
  scan: string // enqueued | skipped | blocked | error | n/a
  blocker: string | null
}
interface PortalResponse {
  organic?: TargetResult | null
  maps?: TargetResult | null
  brand?: TargetResult | null
}

type TargetKey = 'organic' | 'maps' | 'brand'

const TARGETS: { key: TargetKey; label: string; hint: string }[] = [
  { key: 'organic', label: 'Organic Rank Tracker', hint: 'Search Console + DataForSEO positions' },
  { key: 'maps', label: 'Geo-grid (Maps)', hint: 'Local-pack rank across the grid' },
  { key: 'brand', label: 'LLM Visibility', hint: 'ChatGPT, Claude, Gemini, Perplexity, Google AI' },
]

export function KeywordPortal() {
  const { id: clientId } = useParams<{ id: string }>()
  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const [text, setText] = useState('')
  const [selected, setSelected] = useState<Record<TargetKey, boolean>>({
    organic: true, maps: true, brand: true,
  })
  const [runScans, setRunScans] = useState(true)
  const [result, setResult] = useState<PortalResponse | null>(null)

  const targets = (Object.keys(selected) as TargetKey[]).filter(k => selected[k])
  const keywords = text.split(/[\n,]+/).map(s => s.trim()).filter(Boolean)
  const canSubmit = keywords.length > 0 && targets.length > 0

  const mutation = useMutation({
    mutationFn: () =>
      api.post<PortalResponse>(`/clients/${clientId}/keyword-portal/add`, {
        keywords, targets, run_scans: runScans,
      }),
    onSuccess: setResult,
  })

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 20px' }}>
      <Link to={`/clients/${clientId}`} style={backLinkStyle}>
        <ArrowLeft size={16} /> Back to workspace
      </Link>

      <header style={{ margin: '12px 0 20px' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
          Add Keywords
        </h1>
        <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
          Enter keywords once for <strong>{client?.name ?? 'this client'}</strong> and add them
          to any of the three trackers at once.
        </p>
      </header>

      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={'emergency plumber\nblocked drain near me\nhot water repair'}
        rows={6}
        style={textareaStyle}
      />
      <div style={{ fontSize: 12, color: '#94a3b8', margin: '4px 2px 18px' }}>
        One per line, or comma-separated. {keywords.length > 0 && `${keywords.length} keyword${keywords.length === 1 ? '' : 's'} detected.`}
      </div>

      <div style={{ display: 'grid', gap: 10, marginBottom: 18 }}>
        {TARGETS.map(t => (
          <label key={t.key} style={{ ...rowStyle, cursor: 'pointer', borderColor: selected[t.key] ? '#c7d2fe' : '#e2e8f0', background: selected[t.key] ? '#eef2ff' : '#fff' }}>
            <input
              type="checkbox"
              checked={selected[t.key]}
              onChange={e => setSelected(s => ({ ...s, [t.key]: e.target.checked }))}
              style={{ width: 16, height: 16 }}
            />
            <span>
              <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a' }}>{t.label}</span>
              <span style={{ display: 'block', fontSize: 12, color: '#64748b' }}>{t.hint}</span>
            </span>
          </label>
        ))}
      </div>

      <label style={{ ...rowStyle, cursor: 'pointer', marginBottom: 8 }}>
        <input type="checkbox" checked={runScans} onChange={e => setRunScans(e.target.checked)} style={{ width: 16, height: 16 }} />
        <span style={{ fontSize: 14, color: '#0f172a' }}>Run first scans now</span>
      </label>
      {runScans && (
        <div style={{ fontSize: 12, color: '#b45309', display: 'flex', gap: 6, alignItems: 'flex-start', margin: '0 2px 18px' }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          Kicks off paid scans immediately (DataForSEO for Maps; the LLM engines for AI Visibility). Organic begins its standard Search Console backfill.
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={!canSubmit || mutation.isPending}
        style={{ ...buttonStyle, opacity: !canSubmit || mutation.isPending ? 0.5 : 1, cursor: !canSubmit || mutation.isPending ? 'not-allowed' : 'pointer' }}
      >
        {mutation.isPending ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
        {mutation.isPending ? 'Adding…' : `Add to ${targets.length} tracker${targets.length === 1 ? '' : 's'}`}
      </button>

      {mutation.isError && (
        <div style={{ ...resultBox, borderColor: '#fecaca', background: '#fef2f2', color: '#b91c1c', marginTop: 16 }}>
          {(mutation.error as Error).message}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 22 }}>
          <h2 style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 10px' }}>
            Results
          </h2>
          <div style={{ display: 'grid', gap: 10 }}>
            {TARGETS.filter(t => result[t.key]).map(t => (
              <ResultRow key={t.key} label={t.label} res={result[t.key]!} clientId={clientId} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ResultRow({ label, res, clientId }: { label: string; res: TargetResult; clientId?: string }) {
  const scanLabel: Record<string, { text: string; color: string }> = {
    enqueued: { text: 'scan started', color: '#15803d' },
    skipped: { text: 'added (no scan)', color: '#64748b' },
    blocked: { text: 'added — scan blocked', color: '#b45309' },
    error: { text: 'error', color: '#b91c1c' },
    'n/a': { text: '', color: '#94a3b8' },
  }
  const s = scanLabel[res.scan] ?? scanLabel['n/a']
  return (
    <div style={resultBox}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
          {res.scan !== 'error' && <Check size={15} color="#15803d" />} {label}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: s.color }}>{s.text}</span>
      </div>
      <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
        {res.added} added{res.skipped_duplicates > 0 && `, ${res.skipped_duplicates} already tracked`}.
        {res.blocker === 'maps_not_configured' && (
          <> The geo-grid isn’t set up yet — <Link to={`/clients/${clientId}/maps`} style={{ color: '#6366f1', fontWeight: 600 }}>finish Maps setup</Link> to scan.</>
        )}
      </div>
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none' }
const textareaStyle: React.CSSProperties = { width: '100%', padding: 12, borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 14, fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box' }
const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderRadius: 10, border: '1px solid #e2e8f0' }
const buttonStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 10, border: 'none', background: '#6366f1', color: '#fff', fontSize: 14, fontWeight: 600 }
const resultBox: React.CSSProperties = { padding: '12px 14px', borderRadius: 10, border: '1px solid #e2e8f0', background: '#fff' }
