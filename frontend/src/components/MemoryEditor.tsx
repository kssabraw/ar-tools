import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'

// Curate what SerMaStr durably remembers about a client.
//
// Memories are captured automatically after a turn and then fed into every
// future answer about that client, which makes a wrong one quietly durable:
// it shapes answers indefinitely and nothing in the reply reveals where the
// bad premise came from. This is the only way to correct or forget one.
//
// They're agency knowledge about a client, not private to whoever's chat
// captured them, so any teammate can edit — same as the rest of the client's
// data.

export type Memory = {
  id: string
  content: string
  source: string | null
  created_at: string | null
  updated_at: string | null
}

export function MemoryEditor({ clientId, clientName }: { clientId: string; clientName: string | null }) {
  const [open, setOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const queryClient = useQueryClient()
  const key = ['memories', clientId]

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => api.get<{ memories: Memory[] }>(`/clients/${clientId}/memories`),
    enabled: open,
  })
  const memories = data?.memories ?? []
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const save = useMutation({
    mutationFn: (m: { id: string; content: string }) =>
      api.put<Memory>(`/memories/${m.id}`, { content: m.content }),
    onSuccess: () => { setEditingId(null); refresh() },
  })
  const add = useMutation({
    mutationFn: (content: string) => api.post<Memory>(`/clients/${clientId}/memories`, { content }),
    onSuccess: () => { setAdding(false); setDraft(''); refresh() },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete<{ ok: boolean }>(`/memories/${id}`),
    onSuccess: refresh,
  })

  function startEdit(m: Memory) {
    setAdding(false)
    setEditingId(m.id)
    setDraft(m.content)
  }

  return (
    <>
      <button
        style={btn}
        onClick={() => setOpen(true)}
        title="What SerMaStr remembers about this client — edit or forget a note"
      >
        <Brain size={12} /> Memory
      </button>

      {open && (
        <div style={backdrop} onClick={() => setOpen(false)}>
          <div style={panel} onClick={e => e.stopPropagation()}>
            <div style={head}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
                  What SerMaStr remembers
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {clientName ?? 'This client'} — these notes go into every future answer.
                </div>
              </div>
              <button style={iconBtn} onClick={() => setOpen(false)} title="Close">
                <X size={15} />
              </button>
            </div>

            <div style={{ padding: '10px 14px', overflowY: 'auto', flex: 1 }}>
              {isLoading && <div style={muted}>Loading…</div>}
              {!isLoading && memories.length === 0 && !adding && (
                <div style={muted}>
                  Nothing remembered yet. Notes are captured automatically after a
                  substantive conversation — or add one by hand.
                </div>
              )}

              {memories.map(m => (
                <div key={m.id} style={row}>
                  {editingId === m.id ? (
                    <>
                      <textarea
                        value={draft}
                        onChange={e => setDraft(e.target.value)}
                        style={area}
                        rows={3}
                        autoFocus
                      />
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button style={ghostBtn} onClick={() => setEditingId(null)}>Cancel</button>
                        <button
                          style={primaryBtn}
                          disabled={draft.trim().length < 3 || save.isPending}
                          onClick={() => save.mutate({ id: m.id, content: draft.trim() })}
                        >
                          <Check size={12} /> {save.isPending ? 'Saving…' : 'Save'}
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div style={{ fontSize: 13, color: '#0f172a', lineHeight: 1.5 }}>{m.content}</div>
                      <div style={metaRow}>
                        <span style={{ fontSize: 11, color: '#94a3b8' }}>
                          {(m.created_at ?? '').slice(0, 10)}
                          {' · '}
                          {m.source === 'user' ? 'written by a teammate' : `captured from ${m.source ?? 'chat'}`}
                          {m.updated_at ? ' · edited' : ''}
                        </span>
                        <span style={{ display: 'flex', gap: 4 }}>
                          <button style={iconBtn} onClick={() => startEdit(m)} title="Edit this note">
                            <Pencil size={13} />
                          </button>
                          <button
                            style={{ ...iconBtn, color: '#b91c1c' }}
                            onClick={() => remove.mutate(m.id)}
                            title="Forget this note"
                          >
                            <Trash2 size={13} />
                          </button>
                        </span>
                      </div>
                    </>
                  )}
                </div>
              ))}

              {adding && (
                <div style={row}>
                  <textarea
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    style={area}
                    rows={3}
                    placeholder="One short, self-contained fact or decision…"
                    autoFocus
                  />
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button style={ghostBtn} onClick={() => { setAdding(false); setDraft('') }}>Cancel</button>
                    <button
                      style={primaryBtn}
                      disabled={draft.trim().length < 3 || add.isPending}
                      onClick={() => add.mutate(draft.trim())}
                    >
                      <Check size={12} /> {add.isPending ? 'Adding…' : 'Add'}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div style={foot}>
              <button
                style={ghostBtn}
                onClick={() => { setEditingId(null); setDraft(''); setAdding(true) }}
                disabled={adding}
              >
                <Plus size={12} /> Add a note
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const btn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#7c3aed', background: '#f5f3ff',
  border: 'none', borderRadius: 8, padding: '5px 9px', cursor: 'pointer',
}
const backdrop: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.35)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60, padding: 16,
}
const panel: React.CSSProperties = {
  background: '#fff', borderRadius: 12, width: 'min(560px, 100%)', maxHeight: '80vh',
  display: 'flex', flexDirection: 'column', boxShadow: '0 12px 40px rgba(15,23,42,0.2)',
}
const head: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
  gap: 12, padding: '14px 14px 10px', borderBottom: '1px solid #e2e8f0',
}
const foot: React.CSSProperties = { padding: '10px 14px', borderTop: '1px solid #e2e8f0' }
const row: React.CSSProperties = {
  padding: '10px 0', borderBottom: '1px solid #f1f5f9',
  display: 'flex', flexDirection: 'column', gap: 6,
}
const metaRow: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
}
const area: React.CSSProperties = {
  width: '100%', fontSize: 13, lineHeight: 1.5, padding: 8, borderRadius: 8,
  border: '1px solid #cbd5e1', fontFamily: 'inherit', resize: 'vertical', boxSizing: 'border-box',
}
const muted: React.CSSProperties = { fontSize: 12, color: '#94a3b8', padding: '8px 0' }
const iconBtn: React.CSSProperties = {
  background: 'transparent', border: 'none', cursor: 'pointer', color: '#64748b',
  padding: 3, display: 'inline-flex', alignItems: 'center',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#475569', background: 'transparent',
  border: '1px solid #cbd5e1', borderRadius: 8, padding: '5px 10px', cursor: 'pointer',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#fff', background: '#7c3aed',
  border: 'none', borderRadius: 8, padding: '5px 10px', cursor: 'pointer',
}
