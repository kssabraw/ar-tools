import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Check, Pencil, RefreshCw, Sparkles, ThumbsDown, ThumbsUp, User, X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { BrandVoice, BrandVoiceResponse, Client, VoiceProfile } from '../lib/types'
import { brandVoiceApi } from '../components/brandvoice/api'
import { Spinner } from '../components/localseo/Spinner'
import {
  backLink, card, errorBox, input, label, outlineBtn, primaryBtn, relativeTime,
} from '../components/localseo/shared'

const textarea: React.CSSProperties = {
  ...input, minHeight: 170, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.6,
}

function hasContent(bv: BrandVoice | null | undefined): boolean {
  return Boolean(bv && (bv.raw_text || bv.current_voice || bv.recommended_voice))
}

export function BrandVoice() {
  const { id } = useParams<{ id: string }>()
  const clientId = id as string
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: bvData, isLoading } = useQuery<BrandVoiceResponse>({
    queryKey: ['brand-voice', clientId],
    queryFn: () => brandVoiceApi.get(clientId),
    enabled: Boolean(clientId),
  })

  const bv = bvData?.brand_voice ?? null
  const hasWebsite = Boolean(client?.website_url)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['brand-voice', clientId] })
    queryClient.invalidateQueries({ queryKey: ['client', clientId] })
  }

  const scanMut = useMutation({
    mutationFn: (force: boolean) => brandVoiceApi.scan(clientId, force),
    onSuccess: () => { invalidate(); setEditing(false) },
  })

  const saveMut = useMutation({
    mutationFn: (raw_text: string) => brandVoiceApi.update(clientId, { raw_text }),
    onSuccess: () => { invalidate(); setEditing(false) },
  })

  const recMut = useMutation({
    mutationFn: (accepted: boolean) => brandVoiceApi.update(clientId, { recommended_accepted: accepted }),
    onSuccess: invalidate,
  })

  const startEdit = () => { setDraft(bv?.raw_text ?? ''); setEditing(true) }
  const busyError = scanMut.error || saveMut.error || recMut.error

  return (
    <div style={{ padding: 32, maxWidth: 820 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <Sparkles size={20} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Brand Voice</h1>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 24px' }}>
        One voice for <strong style={{ color: '#64748b' }}>{client?.name ?? 'this client'}</strong> — used by
        both the Blog Writer and Local SEO. Your own input always wins; if you don’t set it, the app generates one.
      </p>

      {busyError && (
        <div style={{ ...errorBox, marginBottom: 16 }}>
          {String((busyError as Error).message)}
        </div>
      )}

      {isLoading ? (
        <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading…</div>
      ) : scanMut.isPending ? (
        <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 12 }}>
          <Spinner size={18} />
          <span style={{ fontSize: 14, color: '#475569' }}>
            {hasWebsite
              ? 'Scanning website for brand voice signals…'
              : 'Generating brand voice from business category…'}
          </span>
        </div>
      ) : editing ? (
        <Editor
          draft={draft}
          setDraft={setDraft}
          saving={saveMut.isPending}
          onSave={() => saveMut.mutate(draft)}
          onCancel={() => setEditing(false)}
        />
      ) : !hasContent(bv) ? (
        <EmptyState
          hasWebsite={hasWebsite}
          onGenerate={() => scanMut.mutate(false)}
          onWriteOwn={startEdit}
        />
      ) : (
        <VoiceDisplay
          bv={bv!}
          onEdit={startEdit}
          onRescan={() => scanMut.mutate(true)}
          onAccept={() => recMut.mutate(true)}
          onReject={() => recMut.mutate(false)}
          recPending={recMut.isPending}
        />
      )}
    </div>
  )
}

// ── Empty state ──────────────────────────────────────────────────────────────

function EmptyState({ hasWebsite, onGenerate, onWriteOwn }: {
  hasWebsite: boolean; onGenerate: () => void; onWriteOwn: () => void
}) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: 36 }}>
      <div style={{
        width: 48, height: 48, borderRadius: 12, background: '#eef2ff', color: '#6366f1',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 14,
      }}>
        <Sparkles size={24} />
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, color: '#0f172a', marginBottom: 6 }}>
        No brand voice yet
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 auto 20px', maxWidth: 440, lineHeight: 1.6 }}>
        Add your own brand voice, or let the app analyze {hasWebsite ? 'the website' : 'the business category'} and
        draft one for you. You can always edit or replace it.
      </p>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
        <button style={primaryBtn} onClick={onGenerate}>
          <Sparkles size={15} /> {hasWebsite ? 'Scan website' : 'Generate from category'}
        </button>
        <button style={outlineBtn} onClick={onWriteOwn}>
          <Pencil size={14} /> Write your own
        </button>
      </div>
    </div>
  )
}

// ── Freeform editor (the manual-supersede path) ──────────────────────────────

function Editor({ draft, setDraft, saving, onSave, onCancel }: {
  draft: string; setDraft: (v: string) => void; saving: boolean; onSave: () => void; onCancel: () => void
}) {
  return (
    <div style={card}>
      <label style={label}>Your brand voice</label>
      <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 10px', lineHeight: 1.5 }}>
        Describe the tone, personality, words to use/avoid, and anything writers must follow.
        This supersedes any app-generated voice for both tools.
      </p>
      <textarea
        style={textarea}
        value={draft}
        onChange={e => setDraft(e.target.value)}
        placeholder="e.g. Warm, plain-spoken, and confident. Speak directly to the homeowner. Avoid jargon and hype…"
        autoFocus
      />
      <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
        <button style={{ ...primaryBtn, opacity: saving || !draft.trim() ? 0.6 : 1 }}
          disabled={saving || !draft.trim()} onClick={onSave}>
          {saving ? <Spinner size={15} color="#fff" /> : <Check size={15} />} Save voice
        </button>
        <button style={outlineBtn} onClick={onCancel} disabled={saving}>
          <X size={14} /> Cancel
        </button>
      </div>
    </div>
  )
}

// ── Voice display ────────────────────────────────────────────────────────────

function VoiceDisplay({ bv, onEdit, onRescan, onAccept, onReject, recPending }: {
  bv: BrandVoice
  onEdit: () => void
  onRescan: () => void
  onAccept: () => void
  onReject: () => void
  recPending: boolean
}) {
  // raw_text is only ever user-authored (manual entry / seed) and is what's
  // displayed when present — so its presence means the active voice is the
  // user's, even if a later app scan enriched structured fields around it.
  const isUser = Boolean(bv.raw_text) || bv.source === 'user'
  const ts = bv.edited_at || bv.generated_at
  const showRecommended = Boolean(bv.recommended_voice) && bv.recommended_accepted !== true

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Provenance + actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 600,
            borderRadius: 999, padding: '4px 10px',
            background: isUser ? '#eef2ff' : '#f0fdf4', color: isUser ? '#4338ca' : '#15803d',
          }}>
            {isUser ? <User size={12} /> : <Sparkles size={12} />}
            {isUser ? 'Set by you' : 'AI-generated'}
          </span>
          {ts && <span style={{ fontSize: 12, color: '#94a3b8' }}>Updated {relativeTime(ts)}</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={outlineBtn} onClick={onEdit}><Pencil size={14} /> {isUser ? 'Edit' : 'Write your own'}</button>
          <button
            style={outlineBtn}
            onClick={() => {
              // Re-scan force-overwrites. When the active voice is the user's
              // own, make the overwrite explicit so it can't happen by accident.
              if (
                isUser &&
                !window.confirm(
                  'Regenerate the brand voice from the website? This replaces the brand voice you set.',
                )
              ) return
              onRescan()
            }}
          >
            <RefreshCw size={14} /> {isUser ? 'Regenerate' : 'Re-scan'}
          </button>
        </div>
      </div>

      {/* Active voice */}
      {bv.raw_text ? (
        <div style={card}>
          <label style={label}>Your brand voice</label>
          <p style={{ whiteSpace: 'pre-wrap', fontSize: 14, color: '#334155', lineHeight: 1.6, margin: 0 }}>
            {bv.raw_text}
          </p>
        </div>
      ) : bv.current_voice ? (
        <ProfileCard title="Current voice" profile={bv.current_voice} />
      ) : bv.recommended_voice && bv.recommended_accepted === true ? (
        <ProfileCard title="Recommended voice (in use)" profile={bv.recommended_voice} />
      ) : null}

      {/* Recommended voice review */}
      {showRecommended && (
        <div style={{ ...card, borderColor: '#c7d2fe', background: '#f8faff' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 12 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
              <Sparkles size={15} color="#6366f1" />
              <span style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Recommended voice</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button style={{ ...primaryBtn, padding: '8px 12px', fontSize: 13, opacity: recPending ? 0.6 : 1 }}
                disabled={recPending} onClick={onAccept}>
                <ThumbsUp size={14} /> Use this
              </button>
              <button style={{ ...outlineBtn, padding: '7px 12px' }} disabled={recPending} onClick={onReject}>
                <ThumbsDown size={14} /> Keep current
              </button>
            </div>
          </div>
          <ProfileBody profile={bv.recommended_voice!} />
        </div>
      )}
    </div>
  )
}

function ProfileCard({ title, profile }: { title: string; profile: VoiceProfile }) {
  return (
    <div style={card}>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 12 }}>{title}</div>
      <ProfileBody profile={profile} />
    </div>
  )
}

function ProfileBody({ profile }: { profile: VoiceProfile }) {
  const ws = profile.writing_style
  const styleBits = ws
    ? [ws.sentence_length && `${ws.sentence_length} sentences`, ws.person, ws.formality && `${ws.formality} formality`,
       ws.jargon_level && `jargon: ${ws.jargon_level}`].filter(Boolean).join(' · ')
    : ''
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {profile.tone && <Field label="Tone" value={profile.tone} />}
      {profile.personality?.length ? <Chips label="Personality" items={profile.personality} /> : null}
      {styleBits && <Field label="Writing style" value={styleBits} />}
      {profile.vocabulary?.use?.length ? <Chips label="Words to use" items={profile.vocabulary.use} tone="good" /> : null}
      {profile.vocabulary?.avoid?.length ? <Chips label="Words to avoid" items={profile.vocabulary.avoid} tone="bad" /> : null}
      {profile.messaging_themes?.length ? <Chips label="Messaging themes" items={profile.messaging_themes} /> : null}
      {profile.sample_phrases?.length ? (
        <Field label="Sample phrases" value={profile.sample_phrases.map(p => `“${p}”`).join('  ·  ')} />
      ) : null}
      {profile.content_generation_instructions && (
        <Field label="Writer instructions" value={profile.content_generation_instructions} />
      )}
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
