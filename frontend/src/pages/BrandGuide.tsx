import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, Copy, Download, ExternalLink, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { BrandGuide as Guide, Client } from '../lib/types'
import { useAuth } from '../context/AuthContext'

// Loose shapes for the guide's jsonb layers (owned by the pipeline services; the
// UI reads a known subset). Kept local so the page stays self-contained.
interface Swatch { hex?: string; name?: string; role?: string; not_brand?: boolean; share?: number }
interface DocColor { hex?: string; share?: number }
interface LogoCand { url?: string; source?: string; score?: number }
interface Descriptor { descriptor?: string; evidence?: string }
interface Flag { title?: string; detail?: string; severity?: string }
interface Synth {
  tagline?: string
  positioning_statement?: string
  mission?: string
  voice_examples?: Record<string, string>
  color?: { swatches?: Swatch[] }
  coherence?: { flags?: Flag[]; narrative?: string }
}
interface Census { colors?: DocColor[]; logo_candidates?: LogoCand[] }
interface Vibe { aesthetic_descriptors?: Descriptor[] }

type EditOp = Record<string, string>

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

// Brand Guide Generator (Phase 4 UI) — generate an on-demand brand-audit + brand-
// guide (a client-facing PDF + a structured record), list history with live status
// polling, download either render profile (internal audit / client-facing), preview
// the Documented/Proposed sections, edit the proposed layer (structured fields),
// adopt a detected logo, approve a regulated guide out of awaiting_signoff, and copy
// the refined voice into the existing Brand Voice editor (suggest-only — no auto-write).
export function BrandGuide() {
  const { id: clientId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [picked, setPicked] = useState<string | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [sourceUrl, setSourceUrl] = useState('')

  const { data: client } = useQuery<Client>({
    queryKey: ['client', clientId],
    queryFn: () => api.get<Client>(`/clients/${clientId}`),
    enabled: Boolean(clientId),
  })

  const { data: status } = useQuery<{ enabled: boolean }>({
    queryKey: ['brand-guide-status', clientId],
    queryFn: () => api.get<{ enabled: boolean }>(`/clients/${clientId}/brand-guide/status`),
    enabled: Boolean(clientId),
  })

  const { data: guides = [], isLoading } = useQuery<Guide[]>({
    queryKey: ['brand-guides', clientId],
    queryFn: () => api.get<Guide[]>(`/clients/${clientId}/brand-guide`),
    enabled: Boolean(clientId),
    // Poll while any guide is still building so the row flips to done/awaiting live.
    refetchInterval: (q) => ((q.state.data ?? []).some((g) => IN_PROGRESS.has(g.status)) ? 4000 : false),
  })

  // Newest guide is selected by default; a click overrides. Derived (no effect).
  const selectedId = picked ?? guides[0]?.id ?? null
  const enabled = status?.enabled ?? true

  const generate = useMutation({
    mutationFn: () =>
      api.post<Guide>(`/clients/${clientId}/brand-guide/generate`, {
        source_url: advanced && sourceUrl.trim() ? sourceUrl.trim() : null,
      }),
    onSuccess: (g) => {
      setPicked(g.id)
      void queryClient.invalidateQueries({ queryKey: ['brand-guides', clientId] })
    },
  })

  // Regenerating never overwrites — it always creates a NEW version — but if the
  // latest guide carries operator edits, warn before spending a fresh build (§6).
  function onGenerate() {
    if (
      guides[0]?.edited &&
      !window.confirm(
        "The latest guide has your edits. Generating creates a NEW version (your edited one is kept); it won't be overwritten. Continue?",
      )
    ) {
      return
    }
    generate.mutate()
  }

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <button style={backLink} onClick={() => navigate(`/clients/${clientId}`)}>
        <ArrowLeft size={14} /> Back to Workspace
      </button>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Brand Guide</h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '4px 0 0', maxWidth: 640 }}>
            A brand audit + brand guide for {client?.name ?? 'this client'} — the live site's colours, type
            &amp; aesthetic read against the client's voice &amp; audience, delivered as a client-facing PDF and a
            structured record. Both an internal audit and a client-facing profile are rendered.
          </p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, flexShrink: 0 }}>
          <button
            style={{ ...primaryBtn, opacity: enabled ? 1 : 0.5 }}
            onClick={onGenerate}
            disabled={generate.isPending || !enabled}
          >
            <RefreshCw size={14} style={generate.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
            {generate.isPending ? 'Starting…' : 'Generate guide'}
          </button>
          <button style={ghostLink} onClick={() => setAdvanced((v) => !v)}>
            {advanced ? 'Hide options' : 'Options'}
          </button>
          {advanced && (
            <input
              style={{ ...select, width: 300 }}
              placeholder={`Source URL (default: ${client?.website_url || 'client website'})`}
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
            />
          )}
        </div>
      </div>

      {!enabled && (
        <div style={darkBanner}>
          The Brand Guide module is turned off for this environment (<code>brand_guide_enabled</code>). History is
          readable, but new guides can't be generated until it's enabled on the server.
        </div>
      )}
      {generate.isError && (
        <div style={{ ...darkBanner, color: '#b91c1c', background: '#fef2f2', borderColor: '#fecaca' }}>
          {(generate.error as Error).message}
        </div>
      )}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : guides.length === 0 ? (
        <div style={emptyBox}>
          No brand guides yet — click <strong>Generate guide</strong> to build the first one from the client's site
          &amp; brand assets.
        </div>
      ) : (
        <div className="scroll-x">
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 18 }}>
            <thead>
              <tr>
                <th style={th}>Version</th>
                <th style={th}>Generated</th>
                <th style={th}>Status</th>
                <th style={th}>Edited</th>
                <th style={{ ...th, textAlign: 'right' }}></th>
              </tr>
            </thead>
            <tbody>
              {guides.map((g) => (
                <tr
                  key={g.id}
                  onClick={() => setPicked(g.id)}
                  style={{ cursor: 'pointer', background: g.id === selectedId ? '#f5f3ff' : undefined }}
                >
                  <td style={td}>v{g.version}</td>
                  <td style={td}>{new Date(g.generated_at ?? g.created_at).toLocaleString()}</td>
                  <td style={td}><StatusBadge status={g.status} error={g.error} /></td>
                  <td style={td}>{g.edited ? <span style={{ color: '#6366f1', fontSize: 12 }}>edited</span> : <span style={{ color: '#cbd5e1' }}>—</span>}</td>
                  <td style={{ ...td, textAlign: 'right' }}>
                    <span style={{ color: '#6366f1', fontSize: 12 }}>{g.id === selectedId ? 'Selected' : 'View'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedId && <GuideDetail clientId={clientId!} guideId={selectedId} />}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

const IN_PROGRESS = new Set(['queued', 'capturing', 'synthesizing', 'rendering'])

// ── the selected guide's detail: preview + edit + download + approve + suggest ──
function GuideDetail({ clientId, guideId }: { clientId: string; guideId: string }) {
  const queryClient = useQueryClient()
  const { isStaff } = useAuth()
  const [downloading, setDownloading] = useState<string | null>(null)

  const { data: guide } = useQuery<Guide>({
    queryKey: ['brand-guide', clientId, guideId],
    queryFn: () => api.get<Guide>(`/clients/${clientId}/brand-guide/${guideId}`),
    enabled: Boolean(guideId),
    refetchInterval: (q) => (q.state.data && IN_PROGRESS.has(q.state.data.status) ? 4000 : false),
  })

  const approve = useMutation({
    mutationFn: () => api.post<Guide>(`/clients/${clientId}/brand-guide/${guideId}/render-approve`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['brand-guide', clientId, guideId] })
      void queryClient.invalidateQueries({ queryKey: ['brand-guides', clientId] })
    },
  })

  async function download(profile: 'internal' | 'client') {
    setDownloading(profile)
    try {
      const res = await api.get<{ url: string }>(`/clients/${clientId}/brand-guide/${guideId}/download?profile=${profile}`)
      if (res.url) window.open(res.url, '_blank', 'noopener')
    } finally {
      setDownloading(null)
    }
  }

  if (!guide) return null
  const synth = (guide.synthesized ?? {}) as Synth
  const census = (guide.visual_census ?? {}) as Census
  const vibe = (guide.vibe_read ?? {}) as Vibe
  const renders = guide.renders ?? {}
  const rendered = guide.status === 'done' && Boolean(renders.client || renders.internal || guide.storage_path)

  return (
    <div style={detailCard}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <strong style={{ fontSize: 15, color: '#0f172a' }}>Guide v{guide.version}</strong>
          <StatusBadge status={guide.status} error={guide.error} />
        </div>
        {rendered && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button style={linkBtn} onClick={() => download('client')} disabled={downloading !== null}>
              <Download size={13} /> {downloading === 'client' ? 'Opening…' : 'Client PDF'}
            </button>
            <button style={{ ...linkBtn, background: '#f1f5f9', color: '#334155' }} onClick={() => download('internal')} disabled={downloading !== null}>
              <Download size={13} /> {downloading === 'internal' ? 'Opening…' : 'Internal audit'}
            </button>
          </div>
        )}
      </div>

      {guide.status === 'error' && (
        <div style={{ ...darkBanner, color: '#b91c1c', background: '#fef2f2', borderColor: '#fecaca', marginTop: 0 }}>
          Generation failed: {guide.error ?? 'unknown error'}. Re-generate to try again.
        </div>
      )}
      {IN_PROGRESS.has(guide.status) && (
        <div style={{ ...darkBanner, marginTop: 0 }}>Building this guide — capture → aesthetic read → synthesis → render…</div>
      )}

      {guide.status === 'awaiting_signoff' && (
        <div style={signoffCard}>
          <div style={{ fontSize: 13, color: '#92400e' }}>
            <strong>Awaiting sign-off.</strong> This is a regulated client — a person must approve before the PDF is
            rendered and delivered. {isStaff ? '' : 'Ask an admin or staff member to approve.'}
          </div>
          {isStaff && (
            <button style={{ ...primaryBtn, padding: '8px 14px' }} onClick={() => approve.mutate()} disabled={approve.isPending}>
              {approve.isPending ? 'Approving…' : 'Approve & render'}
            </button>
          )}
        </div>
      )}
      {approve.isError && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{(approve.error as Error).message}</div>}

      {/* Sections preview + edit — shown once there's a synthesized layer to show. */}
      {guide.synthesized && (
        <>
          <FoundationEditor clientId={clientId} guideId={guideId} synth={synth} />
          <ColorSection clientId={clientId} guideId={guideId} census={census} synth={synth} />
          <AestheticSection vibe={vibe} synth={synth} />
          <VoiceExamplesEditor clientId={clientId} guideId={guideId} synth={synth} />
          <LogoAdopt clientId={clientId} guideId={guideId} census={census} />
          <ApplicationsPreview census={census} synth={synth} />
          <VoiceSuggestSurface clientId={clientId} guideId={guideId} />
        </>
      )}
    </div>
  )
}

// ── invalidation helper shared by the edit mutations ──────────────────────────
function useGuideMutation(clientId: string, guideId: string) {
  const queryClient = useQueryClient()
  return (body: unknown) =>
    api.put<Guide>(`/clients/${clientId}/brand-guide/${guideId}`, body).then((r) => {
      void queryClient.invalidateQueries({ queryKey: ['brand-guide', clientId, guideId] })
      void queryClient.invalidateQueries({ queryKey: ['brand-guides', clientId] })
      return r
    })
}

// ── Brand Foundation editor (tagline / positioning / mission) ─────────────────
const FIELD_ROWS: [keyof Synth, string][] = [
  ['tagline', 'Tagline'],
  ['positioning_statement', 'Positioning statement'],
  ['mission', 'Mission / promise'],
]

function FoundationEditor({ clientId, guideId, synth }: { clientId: string; guideId: string; synth: Synth }) {
  const put = useGuideMutation(clientId, guideId)
  const [draft, setDraft] = useState<Record<string, string> | null>(null)
  const save = useMutation({
    mutationFn: (edits: EditOp[]) => put({ edits }),
    onSuccess: () => setDraft(null),
  })
  const cur = (f: string) => str(synth[f as keyof Synth])
  const val = (f: string) => draft?.[f] ?? cur(f)
  const dirty = FIELD_ROWS.filter(([f]) => draft && draft[f] !== undefined && draft[f] !== cur(f))

  return (
    <Section title="Brand Foundation" subtitle="Proposed — editable">
      {FIELD_ROWS.map(([f, label]) => (
        <div key={f} style={{ marginBottom: 10 }}>
          <div style={fieldLabel}>{label}</div>
          <input
            style={{ ...select, width: '100%' }}
            value={val(f)}
            onChange={(e) => setDraft({ ...(draft ?? {}), [f]: e.target.value })}
          />
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          style={{ ...primaryBtn, padding: '7px 13px', opacity: dirty.length ? 1 : 0.5 }}
          disabled={!dirty.length || save.isPending}
          onClick={() => save.mutate(dirty.map(([f]) => ({ op: 'set_field', field: f, value: draft![f] })))}
        >
          {save.isPending ? 'Saving…' : 'Save changes'}
        </button>
        {draft && <button style={ghostLink} onClick={() => setDraft(null)}>Discard</button>}
      </div>
      {save.isError && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{(save.error as Error).message}</div>}
    </Section>
  )
}

// ── Color: documented palette + proposed named swatches (rename/drop/flag) ─────
function ColorSection({ clientId, guideId, census, synth }: { clientId: string; guideId: string; census: Census; synth: Synth }) {
  const put = useGuideMutation(clientId, guideId)
  const swatchOp = useMutation({ mutationFn: (op: EditOp) => put({ edits: [op] }) })
  const docColors = Array.isArray(census.colors) ? census.colors : []
  const swatches = Array.isArray(synth.color?.swatches) ? synth.color!.swatches! : []
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameVal, setRenameVal] = useState('')

  return (
    <Section title="Color" subtitle="Documented (measured) → Proposed (named)">
      {docColors.length > 0 && (
        <>
          <div style={fieldLabel}>Measured palette</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            {docColors.map((c, i) => (
              <div key={i} title={`${c.hex} · ${Math.round((c.share ?? 0) * 100)}%`} style={{ textAlign: 'center' }}>
                <div style={{ ...swatchBox, background: c.hex }} />
                <div style={{ fontSize: 10, color: '#64748b', fontFamily: 'monospace' }}>{c.hex}</div>
              </div>
            ))}
          </div>
        </>
      )}
      {swatches.length > 0 && (
        <>
          <div style={fieldLabel}>Named palette (proposed — curate)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {swatches.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: s.not_brand ? 0.45 : 1 }}>
                <div style={{ ...swatchBox, width: 22, height: 22, background: s.hex }} />
                {renaming === s.hex ? (
                  <>
                    <input style={{ ...select, padding: '4px 8px', flex: 1 }} value={renameVal} onChange={(e) => setRenameVal(e.target.value)} autoFocus />
                    <button style={iconBtn} title="Save name" onClick={() => { swatchOp.mutate({ op: 'swatch_rename', hex: str(s.hex), name: renameVal }); setRenaming(null) }}><Check size={14} /></button>
                  </>
                ) : (
                  <>
                    <span style={{ flex: 1, fontSize: 13, color: '#334155' }}>
                      {s.name || s.hex} <span style={{ color: '#94a3b8', fontSize: 11 }}>{s.role}{s.not_brand ? ' · not brand' : ''}</span>
                    </span>
                    <button style={iconBtn} title="Rename" onClick={() => { setRenaming(str(s.hex)); setRenameVal(s.name || '') }}>Rename</button>
                    <button style={iconBtn} title="Flag not a brand colour" onClick={() => swatchOp.mutate({ op: 'swatch_flag_not_brand', hex: str(s.hex) })}>Not brand</button>
                    <button style={{ ...iconBtn, color: '#b91c1c' }} title="Drop swatch" onClick={() => swatchOp.mutate({ op: 'swatch_drop', hex: str(s.hex) })}><Trash2 size={13} /></button>
                  </>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      {docColors.length === 0 && swatches.length === 0 && <p style={naText}>No palette recovered for this guide.</p>}
    </Section>
  )
}

// ── Aesthetic & Art Direction (read-only preview) ─────────────────────────────
function AestheticSection({ vibe, synth }: { vibe: Vibe; synth: Synth }) {
  const descriptors = Array.isArray(vibe.aesthetic_descriptors) ? vibe.aesthetic_descriptors : []
  const coherence = synth.coherence ?? {}
  const flags = Array.isArray(coherence.flags) ? coherence.flags : []
  if (!descriptors.length && !flags.length && !coherence.narrative) return null
  return (
    <Section title="Aesthetic & Art Direction" subtitle="The felt vibe read + coherence">
      {descriptors.length > 0 && (
        <ul style={{ margin: '0 0 10px', paddingLeft: 18 }}>
          {descriptors.map((d, i) => (
            <li key={i} style={{ fontSize: 13, color: '#334155', marginBottom: 3 }}>
              <strong>{d.descriptor}</strong>{d.evidence ? <span style={{ color: '#64748b' }}> — {d.evidence}</span> : null}
            </li>
          ))}
        </ul>
      )}
      {flags.length > 0 && (
        <>
          <div style={fieldLabel}>Coherence audit — where the brand is leaking</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {flags.map((f, i) => (
              <li key={i} style={{ fontSize: 12.5, color: '#b45309', marginBottom: 3 }}>
                <strong>{f.title}</strong>{f.detail ? <span style={{ color: '#64748b' }}> — {f.detail}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
      {coherence.narrative && <p style={{ fontSize: 12.5, color: '#64748b', marginTop: 8 }}>{coherence.narrative}</p>}
    </Section>
  )
}

// ── Voice worked-examples editor ──────────────────────────────────────────────
const VOICE_ROWS: [string, string][] = [
  ['headline', 'Headline'],
  ['cta', 'CTA'],
  ['product_blurb', 'Product blurb'],
  ['email_opener', 'Email opener'],
]

function VoiceExamplesEditor({ clientId, guideId, synth }: { clientId: string; guideId: string; synth: Synth }) {
  const put = useGuideMutation(clientId, guideId)
  const ve = synth.voice_examples ?? {}
  const [draft, setDraft] = useState<Record<string, string> | null>(null)
  const save = useMutation({ mutationFn: (edits: EditOp[]) => put({ edits }), onSuccess: () => setDraft(null) })
  const val = (k: string) => draft?.[k] ?? str(ve[k])
  const dirty = VOICE_ROWS.filter(([k]) => draft && draft[k] !== undefined && draft[k] !== str(ve[k]))
  return (
    <Section title="Voice — worked examples" subtitle="Proposed — editable">
      {VOICE_ROWS.map(([k, label]) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <div style={fieldLabel}>{label}</div>
          <input style={{ ...select, width: '100%' }} value={val(k)} onChange={(e) => setDraft({ ...(draft ?? {}), [k]: e.target.value })} />
        </div>
      ))}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          style={{ ...primaryBtn, padding: '7px 13px', opacity: dirty.length ? 1 : 0.5 }}
          disabled={!dirty.length || save.isPending}
          onClick={() => save.mutate(dirty.map(([k]) => ({ op: 'set_voice_example', key: k, value: draft![k] })))}
        >
          {save.isPending ? 'Saving…' : 'Save examples'}
        </button>
        {draft && <button style={ghostLink} onClick={() => setDraft(null)}>Discard</button>}
      </div>
      {save.isError && <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 6 }}>{(save.error as Error).message}</div>}
    </Section>
  )
}

// ── Logo adopt (§12 Q1) ───────────────────────────────────────────────────────
function LogoAdopt({ clientId, guideId, census }: { clientId: string; guideId: string; census: Census }) {
  const queryClient = useQueryClient()
  const cands = Array.isArray(census.logo_candidates) ? census.logo_candidates : []
  const adopt = useMutation({
    mutationFn: (body: { candidate_url: string; replace: boolean }) =>
      api.post<{ logo_url: string }>(`/clients/${clientId}/brand-guide/${guideId}/logo-adopt`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['client', clientId] })
    },
  })
  if (!cands.length) return null
  const isConflict = (adopt.error as Error | undefined)?.message?.includes('logo_exists')
  return (
    <Section title="Logo" subtitle="Detected candidates — adopt one as the client logo">
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {cands.slice(0, 6).map((c, i) => (
          <div key={i} style={{ textAlign: 'center', width: 120 }}>
            <div style={logoFrame}>
              <img src={c.url} alt="logo candidate" style={{ maxWidth: '100%', maxHeight: 48 }} />
            </div>
            <div style={{ fontSize: 10, color: '#94a3b8', margin: '4px 0' }}>{c.source} · {c.score}</div>
            <button style={{ ...linkBtn, width: '100%', justifyContent: 'center' }} onClick={() => adopt.mutate({ candidate_url: str(c.url), replace: false })} disabled={adopt.isPending}>
              Adopt
            </button>
          </div>
        ))}
      </div>
      {adopt.isSuccess && <div style={{ fontSize: 12, color: '#15803d', marginTop: 8 }}>Logo adopted — set as the client logo.</div>}
      {adopt.isError && (
        <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 8 }}>
          {isConflict ? (
            <>
              This client already has a logo.{' '}
              <button
                style={{ ...ghostLink, color: '#b91c1c', textDecoration: 'underline' }}
                onClick={() => adopt.variables && adopt.mutate({ candidate_url: adopt.variables.candidate_url, replace: true })}
              >
                Replace it anyway
              </button>
            </>
          ) : (adopt.error as Error).message}
        </div>
      )}
    </Section>
  )
}

// ── Applications / mockups preview (§9, Phase 5) ──────────────────────────────
// Read-only: the in-context mockups are assembled server-side into the PDF from the
// brand system's tokens. This surface lists what's included + a hint of the palette,
// pointing at the download buttons above — it deliberately does NOT re-render the
// mockups in React (a second rendering engine would drift from the PDF).
const APP_MOCKUPS = ['Website hero', 'Social post', 'Business card', 'Letterhead', 'Product label']

function ApplicationsPreview({ census, synth }: { census: Census; synth: Synth }) {
  const swatches = Array.isArray(synth.color?.swatches) ? synth.color!.swatches!.filter((s) => !s.not_brand) : []
  const docColors = Array.isArray(census.colors) ? census.colors : []
  // Mirror the backend gate: mockups render only when there's a usable palette.
  const hexes = (swatches.length ? swatches.map((s) => s.hex) : docColors.map((c) => c.hex)).filter(Boolean).slice(0, 5)
  if (!hexes.length) return null
  return (
    <Section title="Applications" subtitle="In-context mockups — in the PDF">
      <p style={{ fontSize: 12.5, color: '#64748b', margin: '0 0 10px' }}>
        The brand system shown in use — built from the palette, type &amp; voice above. Download the{' '}
        <strong>Client PDF</strong> (or Internal audit) to see them.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
        {APP_MOCKUPS.map((m) => (
          <span key={m} style={{ fontSize: 11.5, color: '#334155', background: '#f1f5f9', borderRadius: 999, padding: '3px 10px' }}>{m}</span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {hexes.map((h, i) => (
          <div key={i} title={str(h)} style={{ width: 26, height: 26, borderRadius: 6, border: '1px solid rgba(0,0,0,.08)', background: str(h) }} />
        ))}
      </div>
    </Section>
  )
}

// ── Suggest-only voice surface (§4.8) ─────────────────────────────────────────
function VoiceSuggestSurface({ clientId, guideId }: { clientId: string; guideId: string }) {
  const [copied, setCopied] = useState(false)
  const { data } = useQuery<{ text: string; editor_path: string; has_suggestions: boolean }>({
    queryKey: ['brand-guide-voice-suggestions', clientId, guideId],
    queryFn: () => api.get(`/clients/${clientId}/brand-guide/${guideId}/voice-suggestions`),
  })
  if (!data?.has_suggestions) return null
  async function copy() {
    try {
      await navigator.clipboard.writeText(data!.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard unavailable */ }
  }
  return (
    <Section title="Refine the brand voice" subtitle="Suggest-only — apply it yourself in the Brand Voice editor">
      <p style={{ fontSize: 12.5, color: '#64748b', margin: '0 0 8px' }}>
        This guide refined the client's voice &amp; messaging. Copy it, then paste into the Brand Voice editor — the suite
        never rewrites brand voice automatically.
      </p>
      <textarea readOnly value={data.text} style={{ ...select, width: '100%', height: 140, fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button style={{ ...primaryBtn, padding: '7px 13px' }} onClick={copy}>
          {copied ? <><Check size={13} /> Copied</> : <><Copy size={13} /> Copy</>}
        </button>
        <a href={data.editor_path} style={{ ...linkBtn, textDecoration: 'none' }}>
          <ExternalLink size={13} /> Open Brand Voice editor
        </a>
      </div>
    </Section>
  )
}

// ── shared ────────────────────────────────────────────────────────────────────
function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: '1px solid #eef2f6', paddingTop: 14, marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10 }}>
        <strong style={{ fontSize: 13.5, color: '#0f172a' }}>{title}</strong>
        {subtitle && <span style={{ fontSize: 11.5, color: '#94a3b8' }}>{subtitle}</span>}
      </div>
      {children}
    </div>
  )
}

function StatusBadge({ status, error }: { status: Guide['status']; error: string | null }) {
  const map: Record<string, { fg: string; bg: string; label: string }> = {
    done: { fg: '#166534', bg: '#f0fdf4', label: 'done' },
    error: { fg: '#b91c1c', bg: '#fef2f2', label: 'error' },
    awaiting_signoff: { fg: '#92400e', bg: '#fffbeb', label: 'awaiting sign-off' },
    rendering: { fg: '#b45309', bg: '#fffbeb', label: 'rendering…' },
    synthesizing: { fg: '#b45309', bg: '#fffbeb', label: 'synthesizing…' },
    capturing: { fg: '#b45309', bg: '#fffbeb', label: 'capturing…' },
    queued: { fg: '#475569', bg: '#f1f5f9', label: 'queued' },
  }
  const c = map[status] ?? map.queued
  return (
    <span title={status === 'error' && error ? error : undefined}
      style={{ fontSize: 11, fontWeight: 600, color: c.fg, background: c.bg, borderRadius: 999, padding: '2px 9px' }}>
      {c.label}
    </span>
  )
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none',
  color: '#6366f1', cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0,
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '9px 16px', cursor: 'pointer',
}
const linkBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: '#6366f1',
  background: '#eef2ff', border: 'none', borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11.5, fontWeight: 600, color: '#64748b',
  background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: '3px 8px', cursor: 'pointer',
}
const ghostLink: React.CSSProperties = {
  background: 'none', border: 'none', color: '#6366f1', cursor: 'pointer', fontSize: 12, padding: 0,
}
const select: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', fontSize: 13,
  color: '#0f172a', background: '#fff', outline: 'none',
}
const swatchBox: React.CSSProperties = {
  width: 40, height: 40, borderRadius: 6, border: '1px solid rgba(0,0,0,.08)', marginBottom: 3,
}
const logoFrame: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, padding: 10, background: '#f8fafc',
  display: 'flex', alignItems: 'center', justifyContent: 'center', height: 68,
}
const detailCard: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, padding: 20, background: '#fff', marginTop: 20,
}
const signoffCard: React.CSSProperties = {
  border: '1px solid #fde68a', background: '#fffbeb', borderRadius: 10, padding: 14, marginTop: 4, marginBottom: 4,
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
}
const darkBanner: React.CSSProperties = {
  border: '1px solid #e2e8f0', background: '#f8fafc', borderRadius: 10, padding: '10px 14px',
  fontSize: 12.5, color: '#64748b', marginTop: 14,
}
const emptyBox: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center', marginTop: 18,
}
const fieldLabel: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 5 }
const naText: React.CSSProperties = { fontSize: 13, color: '#94a3b8', fontStyle: 'italic' }
const th: React.CSSProperties = {
  textAlign: 'left', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em',
  color: '#94a3b8', padding: '6px 10px', borderBottom: '1px solid #e2e8f0',
}
const td: React.CSSProperties = { fontSize: 13, color: '#334155', padding: '10px', borderBottom: '1px solid #f1f5f9' }
