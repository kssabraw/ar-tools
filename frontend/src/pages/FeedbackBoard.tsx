import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bug, Lightbulb, Plus, X, Trash2, MessageSquare, Send, Tag, Loader2,
} from 'lucide-react'
import { api } from '../lib/api'
import type {
  FeedbackItem, FeedbackItemDetail, FeedbackKind, FeedbackPriority, FeedbackStatus,
} from '../lib/types'

// Internal, admin-only board for logging bugs and a wishlist of new modules /
// capabilities. Suite-level (not client-scoped). Deliberately separate from the
// client task board — this is agency product feedback, not delivery work.

const STATUS_COLUMNS: { key: FeedbackStatus; label: string; color: string; bg: string }[] = [
  { key: 'new', label: 'New', color: '#475569', bg: '#f1f5f9' },
  { key: 'triaged', label: 'Triaged', color: '#0369a1', bg: '#eff6ff' },
  { key: 'in_progress', label: 'In Progress', color: '#a16207', bg: '#fefce8' },
  { key: 'done', label: 'Done', color: '#15803d', bg: '#f0fdf4' },
  { key: 'declined', label: 'Declined', color: '#b91c1c', bg: '#fef2f2' },
]

const PRIORITY_META: Record<FeedbackPriority, { label: string; color: string; bg: string }> = {
  low: { label: 'Low', color: '#64748b', bg: '#f1f5f9' },
  medium: { label: 'Medium', color: '#0369a1', bg: '#eff6ff' },
  high: { label: 'High', color: '#c2410c', bg: '#fff7ed' },
  critical: { label: 'Critical', color: '#b91c1c', bg: '#fef2f2' },
}

const KIND_META: Record<FeedbackKind, { label: string; icon: ReactNode; color: string; bg: string }> = {
  bug: { label: 'Bug', icon: <Bug size={13} />, color: '#b91c1c', bg: '#fef2f2' },
  wishlist: { label: 'Wishlist', icon: <Lightbulb size={13} />, color: '#7c3aed', bg: '#f5f3ff' },
}

const PRIORITIES: FeedbackPriority[] = ['low', 'medium', 'high', 'critical']
const STATUSES: FeedbackStatus[] = ['new', 'triaged', 'in_progress', 'done', 'declined']

type KindFilter = 'all' | FeedbackKind

function Chip({ label, color, bg, icon }: { label: string; color: string; bg: string; icon?: ReactNode }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
      borderRadius: 999, fontSize: 11, fontWeight: 600, color, background: bg,
    }}>
      {icon}{label}
    </span>
  )
}

export function FeedbackBoard() {
  const queryClient = useQueryClient()
  const [kindFilter, setKindFilter] = useState<KindFilter>('all')
  const [includeResolved, setIncludeResolved] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const { data: items, isLoading } = useQuery<FeedbackItem[]>({
    queryKey: ['feedback', kindFilter, includeResolved],
    queryFn: () => {
      const params = new URLSearchParams()
      if (kindFilter !== 'all') params.set('kind', kindFilter)
      params.set('include_resolved', String(includeResolved))
      return api.get<FeedbackItem[]>(`/feedback?${params.toString()}`)
    },
  })

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items ?? []
    return (items ?? []).filter((it) =>
      it.title.toLowerCase().includes(q) ||
      (it.body ?? '').toLowerCase().includes(q) ||
      it.labels.some((l) => l.toLowerCase().includes(q)),
    )
  }, [items, search])

  const byStatus = (status: FeedbackStatus) => filtered.filter((it) => it.status === status)

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: FeedbackStatus }) =>
      api.put<FeedbackItemDetail>(`/feedback/${id}`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['feedback'] }),
  })

  return (
    <div style={{ padding: 32, maxWidth: 1400, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#0f172a' }}>Feedback Board</h1>
          <p style={{ margin: '6px 0 0', color: '#64748b', fontSize: 14, maxWidth: 640 }}>
            Log bugs and a wishlist of new modules or capabilities you want. Admin-only, agency-internal.
          </p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '9px 16px',
            borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff',
            fontSize: 14, fontWeight: 600, cursor: 'pointer',
          }}
        >
          <Plus size={16} /> New item
        </button>
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', margin: '20px 0' }}>
        <div style={{ display: 'inline-flex', background: '#f1f5f9', borderRadius: 8, padding: 3 }}>
          {(['all', 'bug', 'wishlist'] as KindFilter[]).map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              style={{
                padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: 600, textTransform: 'capitalize',
                background: kindFilter === k ? '#fff' : 'transparent',
                color: kindFilter === k ? '#0f172a' : '#64748b',
                boxShadow: kindFilter === k ? '0 1px 2px rgba(15,23,42,0.1)' : 'none',
              }}
            >
              {k === 'all' ? 'All' : KIND_META[k].label}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search title, description, labels…"
          style={{
            flex: '1 1 240px', maxWidth: 360, padding: '8px 12px', borderRadius: 8,
            border: '1px solid #e2e8f0', fontSize: 13,
          }}
        />
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#475569', cursor: 'pointer' }}>
          <input type="checkbox" checked={includeResolved} onChange={(e) => setIncludeResolved(e.target.checked)} />
          Show done / declined
        </label>
      </div>

      {isLoading ? (
        <div style={{ padding: 60, textAlign: 'center', color: '#64748b' }}>
          <Loader2 size={20} className="spin" /> Loading…
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 14, overflowX: 'auto', paddingBottom: 12, alignItems: 'flex-start' }}>
          {STATUS_COLUMNS.map((col) => {
            const cards = byStatus(col.key)
            return (
              <div key={col.key} style={{ flex: '1 0 260px', minWidth: 260, maxWidth: 340 }}>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '8px 10px', borderRadius: 8, background: col.bg, marginBottom: 10,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: col.color }}>{col.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: col.color, opacity: 0.8 }}>{cards.length}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {cards.map((it) => (
                    <FeedbackCard
                      key={it.id}
                      item={it}
                      onOpen={() => setSelectedId(it.id)}
                      onStatusChange={(status) => updateStatus.mutate({ id: it.id, status })}
                    />
                  ))}
                  {cards.length === 0 && (
                    <div style={{ padding: '14px 10px', textAlign: 'center', color: '#cbd5e1', fontSize: 12 }}>
                      Nothing here
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showForm && <CreateModal onClose={() => setShowForm(false)} />}
      {selectedId && <DetailModal itemId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}

function FeedbackCard({
  item, onOpen, onStatusChange,
}: {
  item: FeedbackItem
  onOpen: () => void
  onStatusChange: (status: FeedbackStatus) => void
}) {
  const kind = KIND_META[item.kind]
  const prio = PRIORITY_META[item.priority]
  return (
    <div
      onClick={onOpen}
      style={{
        background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: 12,
        cursor: 'pointer', boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
      }}
    >
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <Chip label={kind.label} icon={kind.icon} color={kind.color} bg={kind.bg} />
        <Chip label={prio.label} color={prio.color} bg={prio.bg} />
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', lineHeight: 1.35 }}>{item.title}</div>
      {item.labels.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
          {item.labels.map((l) => (
            <span key={l} style={{
              display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10, color: '#64748b',
              background: '#f1f5f9', padding: '1px 6px', borderRadius: 4,
            }}>
              <Tag size={9} /> {l}
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 10, gap: 8 }}>
        <select
          value={item.status}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => onStatusChange(e.target.value as FeedbackStatus)}
          style={{
            fontSize: 11, padding: '3px 6px', borderRadius: 6, border: '1px solid #e2e8f0',
            color: '#475569', background: '#fff', cursor: 'pointer',
          }}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>{STATUS_COLUMNS.find((c) => c.key === s)?.label}</option>
          ))}
        </select>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 11, color: '#94a3b8' }}>
          {item.comment_count > 0 && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <MessageSquare size={11} /> {item.comment_count}
            </span>
          )}
          {item.created_by_name && <span>{item.created_by_name}</span>}
        </span>
      </div>
    </div>
  )
}

function LabelEditor({ labels, onChange }: { labels: string[]; onChange: (l: string[]) => void }) {
  const [input, setInput] = useState('')
  const add = () => {
    const v = input.trim()
    if (!v) return
    if (!labels.some((l) => l.toLowerCase() === v.toLowerCase())) onChange([...labels, v])
    setInput('')
  }
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: labels.length ? 8 : 0 }}>
        {labels.map((l) => (
          <span key={l} style={{
            display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#475569',
            background: '#f1f5f9', padding: '2px 8px', borderRadius: 6,
          }}>
            <Tag size={11} /> {l}
            <X size={12} style={{ cursor: 'pointer' }} onClick={() => onChange(labels.filter((x) => x !== l))} />
          </span>
        ))}
      </div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        onBlur={add}
        placeholder="Add a label (module, area…) — Enter"
        style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13 }}
      />
    </div>
  )
}

const modalBackdrop: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', zIndex: 80,
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: 24, overflowY: 'auto',
}
const modalPanel: React.CSSProperties = {
  background: '#fff', borderRadius: 14, width: '100%', maxWidth: 560, marginTop: 40,
  boxShadow: '0 20px 50px rgba(15,23,42,0.25)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6, display: 'block' }
const inputStyle: React.CSSProperties = { width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 14, boxSizing: 'border-box' }

function CreateModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<FeedbackKind>('bug')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [priority, setPriority] = useState<FeedbackPriority>('medium')
  const [labels, setLabels] = useState<string[]>([])

  const create = useMutation({
    mutationFn: () => api.post<FeedbackItem>('/feedback', {
      kind, title: title.trim(), body: body.trim() || null, priority, labels,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback'] })
      onClose()
    },
  })

  return (
    <div style={modalBackdrop} onClick={onClose}>
      <div style={modalPanel} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '18px 20px', borderBottom: '1px solid #f1f5f9' }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: '#0f172a' }}>New feedback item</h2>
          <X size={20} style={{ cursor: 'pointer', color: '#94a3b8' }} onClick={onClose} />
        </div>
        <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <span style={fieldLabel}>Type</span>
            <div style={{ display: 'flex', gap: 8 }}>
              {(['bug', 'wishlist'] as FeedbackKind[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setKind(k)}
                  style={{
                    flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                    padding: '10px', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600,
                    border: `1px solid ${kind === k ? KIND_META[k].color : '#e2e8f0'}`,
                    background: kind === k ? KIND_META[k].bg : '#fff',
                    color: kind === k ? KIND_META[k].color : '#64748b',
                  }}
                >
                  {KIND_META[k].icon} {KIND_META[k].label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span style={fieldLabel}>Title</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle}
              placeholder={kind === 'bug' ? 'What’s broken?' : 'What do you want built?'} autoFocus />
          </div>
          <div>
            <span style={fieldLabel}>Details {kind === 'bug' ? '(steps to reproduce, what you expected)' : '(what it should do, why)'}</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5}
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
            <div style={{ flex: 1 }}>
              <span style={fieldLabel}>Priority</span>
              <select value={priority} onChange={(e) => setPriority(e.target.value as FeedbackPriority)} style={inputStyle}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <span style={fieldLabel}>Labels</span>
            <LabelEditor labels={labels} onChange={setLabels} />
          </div>
          {create.isError && (
            <div style={{ color: '#b91c1c', fontSize: 13 }}>{(create.error as Error).message}</div>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '16px 20px', borderTop: '1px solid #f1f5f9' }}>
          <button onClick={onClose} style={{ padding: '9px 16px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#475569', fontSize: 14, cursor: 'pointer' }}>Cancel</button>
          <button
            onClick={() => create.mutate()}
            disabled={!title.trim() || create.isPending}
            style={{
              padding: '9px 16px', borderRadius: 8, border: 'none', fontSize: 14, fontWeight: 600,
              background: title.trim() ? '#6366f1' : '#c7d2fe', color: '#fff',
              cursor: title.trim() ? 'pointer' : 'not-allowed',
            }}
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DetailModal({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { data: item, isLoading } = useQuery<FeedbackItemDetail>({
    queryKey: ['feedback-item', itemId],
    queryFn: () => api.get<FeedbackItemDetail>(`/feedback/${itemId}`),
  })

  const [comment, setComment] = useState('')
  const [editing, setEditing] = useState(false)
  const [eTitle, setETitle] = useState('')
  const [eBody, setEBody] = useState('')
  const [eLabels, setELabels] = useState<string[]>([])

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['feedback-item', itemId] })
    queryClient.invalidateQueries({ queryKey: ['feedback'] })
  }

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.put<FeedbackItemDetail>(`/feedback/${itemId}`, body),
    onSuccess: () => { invalidate(); setEditing(false) },
  })
  const remove = useMutation({
    mutationFn: () => api.delete(`/feedback/${itemId}`),
    onSuccess: () => { invalidate(); onClose() },
  })
  const addComment = useMutation({
    mutationFn: () => api.post(`/feedback/${itemId}/comments`, { body: comment.trim() }),
    onSuccess: () => { setComment(''); invalidate() },
  })
  const delComment = useMutation({
    mutationFn: (commentId: string) => api.delete(`/feedback/${itemId}/comments/${commentId}`),
    onSuccess: invalidate,
  })

  const startEdit = () => {
    if (!item) return
    setETitle(item.title); setEBody(item.body ?? ''); setELabels(item.labels); setEditing(true)
  }

  return (
    <div style={modalBackdrop} onClick={onClose}>
      <div style={{ ...modalPanel, maxWidth: 620 }} onClick={(e) => e.stopPropagation()}>
        {isLoading || !item ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}><Loader2 size={18} className="spin" /> Loading…</div>
        ) : (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '18px 20px', borderBottom: '1px solid #f1f5f9', gap: 12 }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                <Chip label={KIND_META[item.kind].label} icon={KIND_META[item.kind].icon} color={KIND_META[item.kind].color} bg={KIND_META[item.kind].bg} />
                <Chip label={PRIORITY_META[item.priority].label} color={PRIORITY_META[item.priority].color} bg={PRIORITY_META[item.priority].bg} />
              </div>
              <X size={20} style={{ cursor: 'pointer', color: '#94a3b8', flexShrink: 0 }} onClick={onClose} />
            </div>

            <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '55vh', overflowY: 'auto' }}>
              {editing ? (
                <>
                  <div>
                    <span style={fieldLabel}>Title</span>
                    <input value={eTitle} onChange={(e) => setETitle(e.target.value)} style={inputStyle} />
                  </div>
                  <div>
                    <span style={fieldLabel}>Details</span>
                    <textarea value={eBody} onChange={(e) => setEBody(e.target.value)} rows={5} style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
                  </div>
                  <div>
                    <span style={fieldLabel}>Labels</span>
                    <LabelEditor labels={eLabels} onChange={setELabels} />
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => patch.mutate({ title: eTitle.trim(), body: eBody.trim() || null, labels: eLabels })}
                      disabled={!eTitle.trim() || patch.isPending}
                      style={{ padding: '8px 14px', borderRadius: 8, border: 'none', background: '#6366f1', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
                    >Save</button>
                    <button onClick={() => setEditing(false)} style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#475569', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <h2 style={{ margin: 0, fontSize: 19, fontWeight: 700, color: '#0f172a', lineHeight: 1.3 }}>{item.title}</h2>
                    <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 6 }}>
                      {item.created_by_name ? `Logged by ${item.created_by_name}` : 'Logged'} · {new Date(item.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  {item.body && <p style={{ margin: 0, fontSize: 14, color: '#334155', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{item.body}</p>}
                  {item.labels.length > 0 && (
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {item.labels.map((l) => (
                        <span key={l} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#475569', background: '#f1f5f9', padding: '2px 8px', borderRadius: 6 }}>
                          <Tag size={11} /> {l}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Status + priority controls */}
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 160px' }}>
                      <span style={fieldLabel}>Status</span>
                      <select value={item.status} onChange={(e) => patch.mutate({ status: e.target.value })} style={inputStyle}>
                        {STATUSES.map((s) => <option key={s} value={s}>{STATUS_COLUMNS.find((c) => c.key === s)?.label}</option>)}
                      </select>
                    </div>
                    <div style={{ flex: '1 1 160px' }}>
                      <span style={fieldLabel}>Priority</span>
                      <select value={item.priority} onChange={(e) => patch.mutate({ priority: e.target.value })} style={inputStyle}>
                        {PRIORITIES.map((p) => <option key={p} value={p}>{PRIORITY_META[p].label}</option>)}
                      </select>
                    </div>
                  </div>

                  {/* Comments */}
                  <div>
                    <span style={{ ...fieldLabel, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <MessageSquare size={13} /> Comments ({item.comments.length})
                    </span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 8 }}>
                      {item.comments.map((c) => (
                        <div key={c.id} style={{ background: '#f8fafc', borderRadius: 8, padding: '8px 10px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <span style={{ fontSize: 12, fontWeight: 600, color: '#475569' }}>{c.author_name ?? 'Someone'}</span>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontSize: 11, color: '#94a3b8' }}>{new Date(c.created_at).toLocaleDateString()}</span>
                              <Trash2 size={12} style={{ cursor: 'pointer', color: '#cbd5e1' }} onClick={() => delComment.mutate(c.id)} />
                            </span>
                          </div>
                          <div style={{ fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{c.body}</div>
                        </div>
                      ))}
                      {item.comments.length === 0 && <div style={{ fontSize: 12, color: '#cbd5e1' }}>No comments yet.</div>}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                      <input
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter' && comment.trim()) addComment.mutate() }}
                        placeholder="Add a comment…"
                        style={{ ...inputStyle, flex: 1 }}
                      />
                      <button
                        onClick={() => addComment.mutate()}
                        disabled={!comment.trim() || addComment.isPending}
                        style={{ padding: '0 14px', borderRadius: 8, border: 'none', background: comment.trim() ? '#6366f1' : '#c7d2fe', color: '#fff', cursor: comment.trim() ? 'pointer' : 'not-allowed', display: 'inline-flex', alignItems: 'center' }}
                      >
                        <Send size={15} />
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            {!editing && (
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '14px 20px', borderTop: '1px solid #f1f5f9' }}>
                <button
                  onClick={() => { if (confirm('Delete this item permanently?')) remove.mutate() }}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8, border: '1px solid #fecaca', background: '#fff', color: '#b91c1c', fontSize: 13, cursor: 'pointer' }}
                >
                  <Trash2 size={14} /> Delete
                </button>
                <button onClick={startEdit} style={{ padding: '8px 14px', borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#475569', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>Edit</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
