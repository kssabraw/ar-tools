import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Link2, RefreshCw, Loader2, Check, X, ExternalLink, UploadCloud } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Mirrors internal_link_edits (services/internal_linking.py).
interface LinkEdit {
  id: string
  source_url: string
  source_post_id: string | null
  target_url: string
  anchor_text: string
  context: string | null
  match_score: number | null
  injectable: boolean
  status: string
  result: { edit_link?: string; reason?: string } | null
}
interface EditsResponse {
  edits: LinkEdit[]
  running: string[]
}

const STATUS_COLOR: Record<string, string> = {
  proposed: '#475569', approved: '#1d4ed8', denied: '#94a3b8',
  applied: '#15803d', failed: '#b91c1c', superseded: '#94a3b8',
}

function pathOf(url: string): string {
  try { return new URL(url).pathname || url } catch { return url }
}

export function InternalLinks() {
  const { id: clientId } = useParams<{ id: string }>()
  const qc = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data, isLoading } = useQuery<EditsResponse>({
    queryKey: ['internal-links', clientId],
    queryFn: () => api.get<EditsResponse>(`/clients/${clientId}/internal-links`),
    enabled: Boolean(clientId),
    refetchInterval: (q) => ((q.state.data?.running ?? []).length > 0 ? 4000 : false),
  })

  const analyze = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/internal-links/analyze`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['internal-links', clientId] }),
  })
  const applyApproved = useMutation({
    mutationFn: () => api.post(`/clients/${clientId}/internal-links/apply`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['internal-links', clientId] }),
  })
  const setStatus = useMutation({
    mutationFn: (vars: { id: string; action: 'approve' | 'deny' }) =>
      api.post(`/internal-link-edits/${vars.id}/${vars.action}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['internal-links', clientId] }),
  })

  const edits = data?.edits ?? []
  const running = data?.running ?? []
  const analyzing = running.includes('internal_link_analyze') || analyze.isPending
  const applying = running.includes('internal_link_apply') || applyApproved.isPending
  const injectable = edits.some(e => e.injectable)
  const approvedInjectable = edits.filter(e => e.status === 'approved' && e.injectable).length

  // Group by source page.
  const bySource = new Map<string, LinkEdit[]>()
  for (const e of edits) {
    const arr = bySource.get(e.source_url) ?? []
    arr.push(e)
    bySource.set(e.source_url, arr)
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '24px 20px' }}>
      <Link to={`/clients/${clientId}`} style={backLinkStyle}><ArrowLeft size={16} /> Back to workspace</Link>

      <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, margin: '12px 0 18px' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Link2 size={20} color="#6366f1" /> Internal links
          </h1>
          <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
            Topical link suggestions across <strong>{client?.name ?? 'this client'}</strong>'s pages.{' '}
            {injectable
              ? 'WordPress — approved links are written to the live site.'
              : 'Recommend-only — apply approved links by hand.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          {injectable && approvedInjectable > 0 && (
            <button onClick={() => applyApproved.mutate()} disabled={applying} style={buttonStyle}>
              {applying ? <Loader2 size={15} /> : <UploadCloud size={15} />}
              Apply {approvedInjectable} approved
            </button>
          )}
          <button onClick={() => analyze.mutate()} disabled={analyzing}
            style={{ ...buttonStyle, background: '#fff', color: '#0f172a', border: '1px solid #e2e8f0' }}>
            {analyzing ? <Loader2 size={15} /> : <RefreshCw size={15} />}
            {analyzing ? 'Analyzing…' : 'Analyze now'}
          </button>
        </div>
      </header>

      {isLoading && <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading…</div>}

      {!isLoading && edits.length === 0 && (
        <div style={{ ...box, color: '#64748b', fontSize: 14 }}>
          No suggestions yet. Click <strong>Analyze now</strong> to scan the client's pages for internal-link
          opportunities. {applying || analyzing ? 'A run is in progress…' : ''}
        </div>
      )}

      {[...bySource.entries()].map(([source, group]) => (
        <section key={source} style={{ marginBottom: 18 }}>
          <h2 style={sectionTitle}>
            On <span style={{ color: '#0f172a' }}>{pathOf(source)}</span>
            <span style={{ color: '#94a3b8', fontWeight: 600 }}> · {group.length}</span>
          </h2>
          <div style={{ display: 'grid', gap: 8 }}>
            {group.map(e => (
              <div key={e.id} style={box}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, color: '#0f172a' }}>
                      Link “<strong>{e.anchor_text}</strong>” → <span style={{ color: '#6366f1' }}>{pathOf(e.target_url)}</span>
                    </div>
                    {e.context && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4, fontStyle: 'italic' }}>“{e.context}”</div>}
                    <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                      <span style={{ ...tag, color: STATUS_COLOR[e.status] ?? '#475569' }}>{e.status}</span>
                      {!e.injectable && <span style={tag}>recommend-only</span>}
                      {e.result?.reason && <span style={{ ...tag, color: '#b91c1c' }}>{e.result.reason}</span>}
                      {e.result?.edit_link && (
                        <a href={e.result.edit_link} target="_blank" rel="noreferrer" style={openLink}>
                          View in WordPress <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </div>
                  {e.status === 'proposed' && (
                    <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                      <button onClick={() => setStatus.mutate({ id: e.id, action: 'approve' })}
                        disabled={setStatus.isPending} style={{ ...miniBtn, color: '#15803d', background: '#f0fdf4' }}>
                        <Check size={13} /> Approve
                      </button>
                      <button onClick={() => setStatus.mutate({ id: e.id, action: 'deny' })}
                        disabled={setStatus.isPending} style={{ ...miniBtn, color: '#94a3b8' }}>
                        <X size={13} /> Deny
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none' }
const buttonStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 8, padding: '9px 16px', borderRadius: 10, border: 'none', background: '#6366f1', color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' }
const box: React.CSSProperties = { padding: '14px 16px', borderRadius: 12, border: '1px solid #e2e8f0', background: '#fff' }
const sectionTitle: React.CSSProperties = { fontSize: 12, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 10px' }
const tag: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#475569', background: '#f1f5f9', borderRadius: 6, padding: '2px 8px' }
const openLink: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#6366f1', textDecoration: 'none' }
const miniBtn: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#475569', background: '#f1f5f9', border: 'none', borderRadius: 6, padding: '5px 10px', cursor: 'pointer' }
