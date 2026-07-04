import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookMarked, CheckCircle2, HelpCircle, RefreshCw, ShieldAlert, Trash2, XCircle } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Citation liveness (offpage agent). Paste the citation URLs from vendor
// deliverables; the weekly sweep flags listings that stop resolving
// (SOP §A.8 "citations still live"). Consistency stays with the external
// Citation Audit tool — this page tracks liveness only.

type CitationStatus = 'live' | 'dead' | 'blocked' | 'unknown'
interface Citation {
  id: string
  url: string
  status: CitationStatus
  consecutive_failures: number
  nap_found: boolean | null
  http_status: number | null
  last_checked_at: string | null
  created_at: string
}
interface CitationsResponse {
  citations: Citation[]
  counts: Partial<Record<CitationStatus, number>>
}

const STATUS_META: Record<CitationStatus, { label: string; color: string; bg: string; icon: JSX.Element }> = {
  live: { label: 'Live', color: '#15803d', bg: '#f0fdf4', icon: <CheckCircle2 size={13} /> },
  dead: { label: 'Dead', color: '#b91c1c', bg: '#fef2f2', icon: <XCircle size={13} /> },
  blocked: { label: 'Bot-blocked', color: '#b45309', bg: '#fffbeb', icon: <ShieldAlert size={13} /> },
  unknown: { label: 'Unknown', color: '#64748b', bg: '#f8fafc', icon: <HelpCircle size={13} /> },
}

export function Citations() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [pasteText, setPasteText] = useState('')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data, isLoading } = useQuery<CitationsResponse>({
    queryKey: ['citations', id],
    queryFn: () => api.get<CitationsResponse>(`/clients/${id}/citations`),
    enabled: Boolean(id),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['citations', id] })
  const addMut = useMutation({
    mutationFn: () => api.post(`/clients/${id}/citations`, { urls_text: pasteText }),
    onSuccess: () => {
      setPasteText('')
      invalidate()
    },
  })
  const deleteMut = useMutation({
    mutationFn: (citationId: string) => api.delete(`/citations/${citationId}`),
    onSuccess: invalidate,
  })
  const checkMut = useMutation({
    mutationFn: () => api.post<{ status: string }>(`/clients/${id}/citations/check`, {}),
  })

  const citations = data?.citations ?? []
  const counts = data?.counts ?? {}

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={`/clients/${id}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#6366f1', textDecoration: 'none', marginBottom: 16 }}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'client'}
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <BookMarked size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Citations</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', marginTop: 0, marginBottom: 20 }}>
        Liveness tracking for ordered citations. Paste URLs from the vendor deliverables; a weekly sweep
        flags listings that stop resolving. Bot-blocked directories count as alive.
      </p>

      {/* Paste-in */}
      <div style={{ marginBottom: 24 }}>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder={'Paste citation URLs — one per line (or comma/space separated)…'}
          rows={4}
          style={{ width: '100%', padding: 10, borderRadius: 10, border: '1px solid #e2e8f0', fontSize: 13, fontFamily: 'inherit', resize: 'vertical' }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button
            onClick={() => addMut.mutate()}
            disabled={!pasteText.trim() || addMut.isPending}
            style={{ padding: '8px 16px', borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: !pasteText.trim() ? 0.5 : 1 }}
          >
            {addMut.isPending ? 'Adding…' : 'Add citations'}
          </button>
          <button
            onClick={() => checkMut.mutate()}
            disabled={checkMut.isPending || citations.length === 0}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#334155', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            <RefreshCw size={13} /> {checkMut.isPending ? 'Queuing…' : checkMut.data?.status === 'already_running' ? 'Check running…' : 'Check now'}
          </button>
        </div>
      </div>

      {/* Status counts */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        {(Object.keys(STATUS_META) as CitationStatus[]).map((s) => (
          <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 10px', borderRadius: 999, background: STATUS_META[s].bg, color: STATUS_META[s].color, fontSize: 12, fontWeight: 600 }}>
            {STATUS_META[s].icon} {STATUS_META[s].label}: {counts[s] ?? 0}
          </span>
        ))}
      </div>

      {/* List */}
      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : citations.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 13, padding: '24px 0' }}>
          No citations yet — paste the URLs from your citation orders above.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: '8px 6px' }}>URL</th>
              <th style={{ padding: '8px 6px', width: 110 }}>Status</th>
              <th style={{ padding: '8px 6px', width: 70 }}>NAP</th>
              <th style={{ padding: '8px 6px', width: 110 }}>Last check</th>
              <th style={{ padding: '8px 6px', width: 40 }} />
            </tr>
          </thead>
          <tbody>
            {citations.map((c) => {
              const meta = STATUS_META[c.status] ?? STATUS_META.unknown
              return (
                <tr key={c.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 6px', maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <a href={c.url} target="_blank" rel="noreferrer" style={{ color: '#334155', textDecoration: 'none' }}>{c.url}</a>
                  </td>
                  <td style={{ padding: '8px 6px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: meta.color, fontWeight: 600 }}>
                      {meta.icon} {meta.label}
                    </span>
                  </td>
                  <td style={{ padding: '8px 6px', color: '#64748b' }}>
                    {c.nap_found === true ? '✓' : c.nap_found === false ? '—' : ''}
                  </td>
                  <td style={{ padding: '8px 6px', color: '#94a3b8' }}>
                    {c.last_checked_at ? new Date(c.last_checked_at).toLocaleDateString() : 'never'}
                  </td>
                  <td style={{ padding: '8px 6px' }}>
                    <button
                      onClick={() => deleteMut.mutate(c.id)}
                      title="Remove"
                      style={{ border: 'none', background: 'none', color: '#cbd5e1', cursor: 'pointer', padding: 2 }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
