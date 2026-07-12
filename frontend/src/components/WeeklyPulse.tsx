import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, RefreshCw, Send } from 'lucide-react'
import { api } from '../lib/api'

// Weekly Pulse — the copy-paste client update ("done last week / on tap this
// week"), generated weekly per client and shown here for STAFF to deliver
// (paste into their own email/message and personalize). Never auto-sent.
// Rows purge server-side after ~2 weeks.

interface Pulse {
  body: string
  week_start?: string
  created_at?: string
}

export function WeeklyPulse({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const { data, isLoading } = useQuery<Pulse>({
    queryKey: ['client-pulse', clientId],
    queryFn: () => api.get<Pulse>(`/clients/${clientId}/pulse`),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })
  const regen = useMutation({
    mutationFn: () => api.post<Pulse>(`/clients/${clientId}/pulse/regenerate`, {}),
    onSuccess: (fresh) => qc.setQueryData(['client-pulse', clientId], fresh),
  })

  const copy = async () => {
    if (!data?.body) return
    try {
      await navigator.clipboard.writeText(data.body)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard denied — the text is selectable below */
    }
  }

  return (
    <section style={wrap}>
      <button style={header} onClick={() => setOpen((o) => !o)}>
        <Send size={15} style={{ color: '#4f46e5' }} />
        <span style={{ fontWeight: 700, color: '#0f172a', fontSize: 14 }}>Weekly Pulse</span>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>
          — copy-paste client update (done last week / on tap this week)
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#4f46e5', fontWeight: 600 }}>
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px' }}>
          {isLoading ? (
            <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 0' }}>Building…</div>
          ) : data?.body ? (
            <>
              <pre style={bodyBox}>{data.body}</pre>
              <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
                <button style={primaryBtn} onClick={copy}>
                  {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy to clipboard'}
                </button>
                <button style={ghostBtn} disabled={regen.isPending} onClick={() => regen.mutate()}>
                  <RefreshCw size={13} style={regen.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
                  {regen.isPending ? 'Regenerating…' : 'Regenerate'}
                </button>
                {data.week_start && (
                  <span style={{ fontSize: 11.5, color: '#94a3b8' }}>
                    week of {data.week_start} · paste into your email &amp; personalize the greeting
                  </span>
                )}
              </div>
            </>
          ) : (
            <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 0' }}>No pulse yet.</div>
          )}
        </div>
      )}
    </section>
  )
}

const wrap: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', marginBottom: 16,
}
const header: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
  padding: '12px 14px', background: 'transparent', border: 'none', cursor: 'pointer',
}
const bodyBox: React.CSSProperties = {
  margin: 0, padding: '12px 14px', background: '#f8fafc', border: '1px solid #e2e8f0',
  borderRadius: 10, fontSize: 12.5, lineHeight: 1.55, color: '#0f172a',
  whiteSpace: 'pre-wrap', fontFamily: 'inherit', maxHeight: 320, overflowY: 'auto',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 12.5, fontWeight: 600, color: '#fff', background: '#4f46e5',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px',
  fontSize: 12.5, fontWeight: 600, color: '#4f46e5', background: '#eef2ff',
  border: 'none', borderRadius: 8, cursor: 'pointer',
}
