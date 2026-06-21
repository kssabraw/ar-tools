import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Check, Pencil, RefreshCw, Sparkles, Target, User, Users, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client, DetectedIcp, Differentiator, IcpResponse, IcpSegment } from '../lib/types'
import { icpApi } from '../components/icp/api'
import { Spinner } from '../components/localseo/Spinner'
import {
  backLink, card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime,
} from '../components/localseo/shared'

const textarea: React.CSSProperties = {
  ...input, minHeight: 170, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.6,
}

function hasContent(icp: DetectedIcp | null | undefined, diffs: Differentiator[] | null | undefined): boolean {
  return Boolean((icp && (icp.raw_text || icp.segments?.length)) || diffs?.length)
}

export function Icp() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data, isLoading } = useQuery<IcpResponse>({
    queryKey: ['icp', clientId],
    queryFn: () => icpApi.get(clientId),
    enabled: Boolean(clientId),
  })

  const icp = data?.detected_icp ?? null
  const diffs = data?.differentiators ?? null

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['icp', clientId] })
    queryClient.invalidateQueries({ queryKey: ['client', clientId] })
  }

  const scanMut = useMutation({
    mutationFn: (force: boolean) => icpApi.scan(clientId, force),
    onSuccess: () => { invalidate(); setEditing(false) },
  })
  const saveMut = useMutation({
    mutationFn: (raw_text: string) => icpApi.update(clientId, { raw_text }),
    onSuccess: () => { invalidate(); setEditing(false) },
  })

  const startEdit = () => { setDraft(icp?.raw_text ?? ''); setEditing(true) }
  const busyError = scanMut.error || saveMut.error

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Users size={20} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>ICP &amp; Differentiators</h1>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 24px' }}>
        Who <strong style={{ color: '#64748b' }}>{client?.name ?? 'this client'}</strong> serves, and what sets them
        apart — used by both the Blog Writer and Local SEO. Your own input always wins.
      </p>

      {busyError && <div style={{ ...errorBox, marginBottom: 16 }}>{String((busyError as Error).message)}</div>}

      {isLoading ? (
        <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading…</div>
      ) : scanMut.isPending ? (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 12 }}>
          <Spinner size={18} />
          <span style={{ fontSize: 14, color: '#475569' }}>Analyzing your business…</span>
        </div>
      ) : editing ? (
        <Editor
          draft={draft} setDraft={setDraft} saving={saveMut.isPending}
          onSave={() => saveMut.mutate(draft)} onCancel={() => setEditing(false)}
        />
      ) : !hasContent(icp, diffs) ? (
        <EmptyState onDetect={() => scanMut.mutate(false)} onWriteOwn={startEdit} />
      ) : (
        <IcpDisplay
          icp={icp} diffs={diffs}
          onEdit={startEdit} onRescan={() => scanMut.mutate(true)}
        />
      )}
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────────

function EmptyState({ onDetect, onWriteOwn }: { onDetect: () => void; onWriteOwn: () => void }) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: 36 }}>
      <div style={{
        width: 48, height: 48, borderRadius: 12, background: '#eef2ff', color: '#6366f1',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14,
      }}>
        <Users size={24} />
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>
        No ICP yet
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 auto 20px', maxWidth: 460, lineHeight: 1.6 }}>
        Write your own customer profile, or let the app analyze the business and website to detect customer
        segments and differentiators. You can always edit or replace it.
      </p>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
        <button style={primaryBtn} onClick={onDetect}><Sparkles size={15} /> Detect ICP</button>
        <button style={outlineBtn} onClick={onWriteOwn}><Pencil size={14} /> Write your own</button>
      </div>
    </div>
  )
}

// ── Freeform editor (manual-supersede path) ──────────────────────────────────

function Editor({ draft, setDraft, saving, onSave, onCancel }: {
  draft: string; setDraft: (v: string) => void; saving: boolean; onSave: () => void; onCancel: () => void
}) {
  return (
    <div style={card}>
      <label style={label}>Your ideal customer profile</label>
      <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 10px', lineHeight: 1.5 }}>
        Describe who this business serves — their situation, what triggers them to search, their fears and
        motivations, and what makes this business the right choice. Supersedes any app-detected ICP.
      </p>
      <textarea
        style={textarea} value={draft} onChange={e => setDraft(e.target.value)}
        placeholder="e.g. Homeowners 35-65 facing an urgent plumbing failure. They search at the worst moment, fear water damage and being overcharged, and choose the first trustworthy, fast responder…"
        autoFocus
      />
      <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
        <button style={{ ...primaryBtn, opacity: saving || !draft.trim() ? 0.6 : 1 }}
          disabled={saving || !draft.trim()} onClick={onSave}>
          {saving ? <Spinner size={15} color="#fff" /> : <Check size={15} />} Save ICP
        </button>
        <button style={outlineBtn} onClick={onCancel} disabled={saving}><X size={14} /> Cancel</button>
      </div>
    </div>
  )
}

// ── Display ──────────────────────────────────────────────────────────────────

function IcpDisplay({ icp, diffs, onEdit, onRescan }: {
  icp: DetectedIcp | null; diffs: Differentiator[] | null; onEdit: () => void; onRescan: () => void
}) {
  // raw_text is only ever user-authored (manual entry / seed), and it's what's
  // displayed when present — so its presence means the active ICP is the user's,
  // even if a later app scan enriched structured segments around it.
  const isUser = Boolean(icp?.raw_text) || icp?.source === 'user'
  const ts = icp?.edited_at || icp?.generated_at
  const segments = icp?.segments ?? []
  const ordered = [...segments].sort((a, b) => (a.primary ? 0 : 1) - (b.primary ? 0 : 1))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600,
            borderRadius: 999, padding: '4px 10px',
            background: isUser ? '#eef2ff' : '#f0fdf4', color: isUser ? '#4338ca' : '#15803d',
          }}>
            {isUser ? <User size={12} /> : <Sparkles size={12} />}
            {isUser ? 'Set by you' : 'AI-detected'}
          </span>
          {ts && <span style={{ fontSize: 12, color: '#94a3b8' }}>Updated {relativeTime(ts)}</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={outlineBtn} onClick={onEdit}><Pencil size={14} /> {isUser ? 'Edit' : 'Write your own'}</button>
          <button style={outlineBtn} onClick={onRescan}><RefreshCw size={14} /> Re-analyze</button>
        </div>
      </div>

      {/* Freeform ICP (user wrote it) */}
      {icp?.raw_text ? (
        <div style={card}>
          <label style={label}>Ideal customer profile</label>
          <p style={{ whiteSpace: 'pre-wrap', fontSize: 14, color: '#334155', lineHeight: 1.6, margin: 0 }}>
            {icp.raw_text}
          </p>
        </div>
      ) : (
        ordered.map((seg, i) => <SegmentCard key={i} seg={seg} />)
      )}

      {icp?.reasoning && (
        <div style={{ ...card, background: '#f8fafc' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}>Why these segments</div>
          <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.5, margin: 0 }}>{icp.reasoning}</p>
        </div>
      )}

      {diffs?.length ? (
        <div style={card}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, marginBottom: 12 }}>
            <Target size={15} color="#6366f1" />
            <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Differentiators</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {diffs.map((d, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                {d.type && <span style={{ fontSize: 11, fontWeight: 600, color: '#4338ca', background: '#eef2ff', borderRadius: 999, padding: '2px 8px', flexShrink: 0 }}>{d.type}</span>}
                <span style={{ fontSize: 14, color: '#334155', lineHeight: 1.5 }}>
                  <strong style={{ color: '#0f172a' }}>{d.claim}</strong>
                  {d.mechanism && <span style={{ color: '#64748b' }}> — {d.mechanism}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function SegmentCard({ seg }: { seg: IcpSegment }) {
  const psy = seg.psychographics ?? {}
  const msg = seg.messaging ?? {}
  const demo = seg.demographics ?? {}
  return (
    <div style={{ ...card, ...(seg.primary ? { borderColor: '#c7d2fe' } : {}) }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{seg.label || 'Customer'}</span>
        {seg.primary && <span style={{ fontSize: 11, fontWeight: 700, color: '#4338ca', background: '#eef2ff', borderRadius: 999, padding: '2px 8px' }}>PRIMARY</span>}
        {typeof seg.confidence === 'number' && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{Math.round(seg.confidence * 100)}% confidence</span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
        {demo.description && <Field label="Demographics" value={demo.description} />}
        {demo.situation && <Field label="Situation" value={demo.situation} />}
        {psy.trigger && <Field label="Search trigger" value={psy.trigger} />}
        {psy.fears?.length ? <Chips label="Fears" items={psy.fears} tone="bad" /> : null}
        {psy.motivations?.length ? <Chips label="Motivations" items={psy.motivations} tone="good" /> : null}
        {psy.buying_behavior && <Field label="Buying behavior" value={psy.buying_behavior} />}
        {msg.tone && <Field label="Messaging tone" value={msg.tone} />}
        {msg.hooks?.length ? <Chips label="Headline hooks" items={msg.hooks} /> : null}
        {msg.trust_signals?.length ? <Chips label="Trust signals" items={msg.trust_signals} /> : null}
      </div>
    </div>
  )
}

function Field({ label: l, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 3 }}>{l}</div>
      <div style={{ fontSize: 14, color: '#334155', lineHeight: 1.5 }}>{value}</div>
    </div>
  )
}

function Chips({ label: l, items, tone }: { label: string; items: string[]; tone?: 'good' | 'bad' }) {
  const bg = tone === 'good' ? '#f0fdf4' : tone === 'bad' ? '#fef2f2' : '#f1f5f9'
  const fg = tone === 'good' ? '#15803d' : tone === 'bad' ? '#b91c1c' : '#475569'
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 5 }}>{l}</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {items.map((it, i) => (
          <span key={i} style={{ fontSize: 13, color: fg, background: bg, borderRadius: 999, padding: '3px 10px' }}>{it}</span>
        ))}
      </div>
    </div>
  )
}
