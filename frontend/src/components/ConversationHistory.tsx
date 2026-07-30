import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { History, Trash2 } from 'lucide-react'

// Saved-conversation picker shared by the two assistant chats (SerMaStr's
// /assistant and PACE's /pace). Both surfaces store threads in the same tables
// behind the same endpoint shape, so the only difference is the base path and
// the accent colour — hence one component rather than two near-identical
// dropdowns.
//
// Threads are private to their author (an admin can read one via the API when
// diagnosing a bad answer, but it never shows up in anyone else's list here).

export type ConversationSummary = {
  id: string
  title?: string | null
  client_id?: string | null
  client_name?: string | null
  updated_at?: string | null
}

export type ConversationDetail = {
  id: string
  title?: string | null
  client_id?: string | null
  messages: { role: 'user' | 'assistant'; content: string }[]
}

function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const mins = Math.round((Date.now() - then) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return days < 7 ? `${days}d ago` : new Date(iso).toLocaleDateString()
}

export function ConversationHistory({
  basePath,
  accent,
  activeId,
  onOpen,
  onArchiveActive,
}: {
  /** '/assistant' or '/pace' — the surface's endpoint root. */
  basePath: string
  accent: string
  activeId: string | null
  onOpen: (detail: ConversationDetail) => void
  /** Called when the thread being deleted is the one on screen, so the caller
   *  can reset to an empty chat instead of showing an archived thread. */
  onArchiveActive: () => void
}) {
  const [open, setOpen] = useState(false)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const listKey = [basePath, 'conversations']

  const { data, isLoading } = useQuery<{ conversations: ConversationSummary[] }>({
    queryKey: listKey,
    queryFn: () => api.get<{ conversations: ConversationSummary[] }>(`${basePath}/conversations`),
    enabled: open,
    staleTime: 10_000,
  })

  // Close on an outside click / Escape, like the other dropdowns in the suite.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function openConversation(id: string) {
    setLoadingId(id)
    try {
      const detail = await api.get<ConversationDetail>(`${basePath}/conversations/${id}`)
      onOpen(detail)
      setOpen(false)
    } catch {
      /* a thread that won't load shouldn't break the chat — leave it open */
    } finally {
      setLoadingId(null)
    }
  }

  async function archive(id: string, e: React.MouseEvent) {
    e.stopPropagation() // don't open the thread we're deleting
    try {
      await api.delete(`${basePath}/conversations/${id}`)
      if (id === activeId) onArchiveActive()
      qc.invalidateQueries({ queryKey: listKey })
    } catch { /* ignore — the row stays listed until the next refetch */ }
  }

  const rows = data?.conversations ?? []

  return (
    <div ref={boxRef} style={{ position: 'relative' }}>
      <button onClick={() => setOpen(o => !o)} style={btn} title="Saved conversations">
        <History size={12} /> History
      </button>
      {open && (
        <div style={panel}>
          {isLoading && <div style={empty}>Loading…</div>}
          {!isLoading && rows.length === 0 && (
            <div style={empty}>No saved conversations yet.</div>
          )}
          {rows.map(c => (
            <div
              key={c.id}
              onClick={() => openConversation(c.id)}
              style={{
                ...row,
                background: c.id === activeId ? '#f1f5f9' : 'transparent',
                opacity: loadingId === c.id ? 0.5 : 1,
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={rowTitle}>{c.title || 'Untitled conversation'}</div>
                <div style={rowMeta}>
                  {c.client_name && <span style={{ color: accent }}>{c.client_name} · </span>}
                  {relativeTime(c.updated_at)}
                </div>
              </div>
              <button
                onClick={e => archive(c.id, e)}
                style={del}
                title="Delete this conversation"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const btn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px',
  fontSize: 11, fontWeight: 600, color: '#64748b', background: '#f8fafc',
  border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer',
}

const panel: React.CSSProperties = {
  position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 30,
  width: 300, maxHeight: 340, overflowY: 'auto', background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 10,
  boxShadow: '0 8px 24px rgba(15,23,42,0.12)', padding: 4,
}

const row: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '7px 8px',
  borderRadius: 7, cursor: 'pointer',
}

const rowTitle: React.CSSProperties = {
  fontSize: 12.5, color: '#0f172a', whiteSpace: 'nowrap',
  overflow: 'hidden', textOverflow: 'ellipsis',
}

const rowMeta: React.CSSProperties = { fontSize: 11, color: '#94a3b8', marginTop: 1 }

const del: React.CSSProperties = {
  display: 'inline-flex', padding: 3, color: '#94a3b8', background: 'transparent',
  border: 'none', borderRadius: 5, cursor: 'pointer',
}

const empty: React.CSSProperties = { padding: '10px 8px', fontSize: 12, color: '#94a3b8' }
