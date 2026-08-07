import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Check, Loader2, Palette, RefreshCw, Upload } from 'lucide-react'
import { api } from '../../lib/api'
import { ACCENT, btn, card, denyReason, input, label } from './shared'
import type { Website } from './shared'

// Theme tab — upload a Claude Design export, compile it, apply it to the site.
//
// A theme is fleet-level, not per-client: the same design often starts several
// sites, and re-uploading it per site produces themes that drift apart under
// separate compiles.
//
// What the compile does, and why the screen says so: it MEASURES the design
// (which colours, how often; which families, sizes, radii) and then asks a model
// only which measured value plays which role. A value the design never contained
// fails the compile rather than shipping as a client's brand — so what you are
// reviewing below is an assignment, not an invention.

export interface Theme {
  id: string
  name: string
  source_kind: 'default' | 'upload' | 'url'
  status: 'compiling' | 'ready' | 'failed'
  approved_at: string | null
  error: string | null
  created_at: string
  tokens: {
    colors?: Record<string, string>
    fontDisplay?: string
    fontBody?: string
    webFonts?: string[]
    selfHostedFonts?: number
    notes?: string
    screens?: string[]
    imageSlots?: { label: string; promptSeed: string; screen: string | null; isHero: boolean }[]
    builtFiles?: string[]
  }
}

type Perms = { isStaff: boolean; isAdmin: boolean; frozen: boolean }

export function ThemeTab({ website, perms }: { website: Website; perms: Perms }) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const deny = denyReason('staff', perms)

  const { data, isLoading } = useQuery<{ themes: Theme[] }>({
    queryKey: ['website-themes'],
    queryFn: () => api.get<{ themes: Theme[] }>('/website-themes'),
    // A compile is an LLM call plus a font download; poll while one is running
    // so the row settles without a reload.
    refetchInterval: (q) => {
      const rows = (q.state.data as { themes?: Theme[] } | undefined)?.themes ?? []
      return rows.some((t) => t.status === 'compiling') ? 4000 : false
    },
  })
  const themes = data?.themes ?? []
  const current = themes.find((t) => t.id === website.theme_id)

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <UploadCard deny={deny} onUploaded={() => qc.invalidateQueries({ queryKey: ['website-themes'] })} />

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>
      ) : themes.length === 0 ? (
        <div style={{ ...card, fontSize: 13, color: '#64748b' }}>
          No designs uploaded yet. Until one is, sites build in the neutral house theme
          that ships with the template.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {themes.map((t) => (
            <ThemeRow
              key={t.id}
              theme={t}
              website={website}
              isCurrent={current?.id === t.id}
              expanded={selected === t.id}
              onToggle={() => setSelected(selected === t.id ? null : t.id)}
              deny={deny}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function UploadCard({ deny, onUploaded }: { deny: string | null; onUploaded: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const send = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('file', file!)
      if (name.trim()) form.append('name', name.trim())
      return api.upload<{ theme_id: string }>('/website-themes', form)
    },
    onSuccess: () => {
      setFile(null)
      setName('')
      if (fileRef.current) fileRef.current.value = ''
      onUploaded()
    },
  })

  return (
    <div style={{ ...card, maxWidth: 620 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Palette size={16} color={ACCENT} />
        <strong style={{ fontSize: 15, color: '#0f172a' }}>Upload a design</strong>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 14px' }}>
        A Claude Design export — the <code>.dc.html</code> on its own, or the whole zip.
        The compile measures every colour, family, size and radius the design uses, then
        asks a model only which measured value plays which role. A colour the design never
        contained fails the compile instead of shipping as a brand.
      </p>

      <div style={{ marginBottom: 10 }}>
        <label style={label}>Design file</label>
        <input ref={fileRef} type="file" accept=".html,.htm,.zip" disabled={Boolean(deny)}
               onChange={(e) => setFile(e.target.files?.[0] ?? null)}
               style={{ fontSize: 13 }} />
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={label}>Name (optional)</label>
        <input style={input} value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Defaults to the filename" disabled={Boolean(deny)} />
      </div>

      <button onClick={() => send.mutate()} disabled={Boolean(deny) || !file || send.isPending}
              title={deny ?? undefined}
              style={btn(deny || !file ? '#e2e8f0' : ACCENT, deny || !file ? '#94a3b8' : '#fff')}>
        {send.isPending ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
        Upload &amp; compile
      </button>
      {deny && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>{deny}</div>}
      {send.error && <ErrorNote error={send.error as Error} />}
    </div>
  )
}

function ThemeRow({ theme, website, isCurrent, expanded, onToggle, deny }: {
  theme: Theme
  website: Website
  isCurrent: boolean
  expanded: boolean
  onToggle: () => void
  deny: string | null
}) {
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['website-themes'] })
    qc.invalidateQueries({ queryKey: ['website', website.id] })
  }

  const approve = useMutation({
    mutationFn: () => api.post(`/website-themes/${theme.id}/approve`, {}),
    onSuccess: refresh,
  })
  const recompile = useMutation({
    mutationFn: () => api.post(`/website-themes/${theme.id}/recompile`, {}),
    onSuccess: refresh,
  })
  const apply = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/theme`, { theme_id: theme.id }),
    onSuccess: refresh,
  })

  const colors = theme.tokens?.colors ?? {}
  const ready = theme.status === 'ready'
  const approved = Boolean(theme.approved_at)

  return (
    <div style={{ ...card, borderColor: isCurrent ? ACCENT : '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button onClick={onToggle} style={{ border: 'none', background: 'none', padding: 0, cursor: 'pointer', fontSize: 14, fontWeight: 700, color: '#0f172a' }}>
          {theme.name}
        </button>
        {isCurrent && <Pill fg="#0369a1" bg="#f0f9ff">In use</Pill>}
        {theme.status === 'compiling' && <Pill fg="#0369a1" bg="#f0f9ff">Compiling…</Pill>}
        {theme.status === 'failed' && <Pill fg="#b91c1c" bg="#fef2f2">Failed</Pill>}
        {ready && (approved ? <Pill fg="#15803d" bg="#f0fdf4">Approved</Pill> : <Pill fg="#b45309" bg="#fffbeb">Needs review</Pill>)}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {ready && !approved && (
            <button onClick={() => approve.mutate()} disabled={Boolean(deny) || approve.isPending}
                    title={deny ?? undefined} style={btn(deny ? '#e2e8f0' : ACCENT, deny ? '#94a3b8' : '#fff')}>
              {approve.isPending ? <Loader2 size={13} className="spin" /> : <Check size={13} />} Approve
            </button>
          )}
          {ready && approved && !isCurrent && (
            <button onClick={() => apply.mutate()} disabled={Boolean(deny) || apply.isPending}
                    title={deny ?? undefined} style={btn(deny ? '#e2e8f0' : ACCENT, deny ? '#94a3b8' : '#fff')}>
              {apply.isPending ? <Loader2 size={13} className="spin" /> : <Palette size={13} />} Use on this site
            </button>
          )}
          {theme.status !== 'compiling' && (
            <button onClick={() => recompile.mutate()} disabled={Boolean(deny) || recompile.isPending}
                    title={deny ?? 'Re-run the compile on the design already uploaded'} style={btn('#fff', '#475569')}>
              {recompile.isPending ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />} Recompile
            </button>
          )}
        </div>
      </div>

      {theme.error && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {explainThemeError(theme.error)}
        </div>
      )}

      {ready && (
        <>
          <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
            {Object.entries(colors).map(([role, value]) => (
              <div key={role} title={`${role}: ${value}`}
                   style={{ width: 34, height: 34, borderRadius: 7, background: value, border: '1px solid #e2e8f0' }} />
            ))}
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 10 }}>
            {theme.tokens?.fontDisplay && (
              <span>Headings <strong>{stripStack(theme.tokens.fontDisplay)}</strong> · body{' '}
                <strong>{stripStack(theme.tokens.fontBody ?? '')}</strong> · </span>
            )}
            {(theme.tokens?.screens ?? []).length} screens ·{' '}
            {(theme.tokens?.imageSlots ?? []).length} image slots
          </div>
          <FontNote tokens={theme.tokens} />
          {expanded && <Detail themeId={theme.id} tokens={theme.tokens} />}
        </>
      )}
    </div>
  )
}

function FontNote({ tokens }: { tokens: Theme['tokens'] }) {
  const named = tokens?.webFonts ?? []
  const hosted = tokens?.selfHostedFonts ?? 0
  if (named.length === 0 || hosted > 0) return null
  // Worth surfacing: the theme names families nothing loads, so the site will
  // render in the fallback stack and look like a deliberate choice.
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginTop: 8, fontSize: 12, color: '#b45309' }}>
      <AlertTriangle size={13} style={{ marginTop: 1, flexShrink: 0 }} />
      <span>
        {named.join(' and ')} could not be downloaded, so the site will render in the
        fallback system font. Recompile to try again.
      </span>
    </div>
  )
}

function Detail({ themeId, tokens }: { themeId: string; tokens: Theme['tokens'] }) {
  const { data } = useQuery<{ theme: Theme; tokens_css: string }>({
    queryKey: ['website-theme', themeId],
    queryFn: () => api.get(`/website-themes/${themeId}`),
  })
  const slots = tokens?.imageSlots ?? []

  return (
    <div style={{ marginTop: 14, borderTop: '1px solid #f1f5f9', paddingTop: 12 }}>
      {tokens?.notes && <p style={{ fontSize: 13, color: '#475569', marginTop: 0 }}>{tokens.notes}</p>}
      {slots.length > 0 && (
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
          <strong style={{ color: '#475569' }}>Imagery the design asks for:</strong>{' '}
          {slots.map((s) => s.promptSeed).join(' · ')}
        </div>
      )}
      <pre style={{
        margin: 0, padding: 12, borderRadius: 8, background: '#0f172a', color: '#e2e8f0',
        fontSize: 11, lineHeight: 1.6, overflowX: 'auto', maxHeight: 320,
      }}>{data?.tokens_css ?? 'Loading…'}</pre>
      <p style={{ fontSize: 11, color: '#94a3b8', margin: '8px 0 0' }}>
        These exact bytes are committed to <code>src/theme/</code> in the site repo — what
        you approve is what ships, not a fresh compile that might assign a role differently.
      </p>
    </div>
  )
}

function Pill({ fg, bg, children }: { fg: string; bg: string; children: React.ReactNode }) {
  return (
    <span style={{ padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700, color: fg, background: bg }}>
      {children}
    </span>
  )
}

function ErrorNote({ error }: { error: Error }) {
  return (
    <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
      {explainThemeError(error.message)}
    </div>
  )
}

/** The compiler's error codes are stable strings; this is where they become English. */
function explainThemeError(code: string): string {
  if (code.startsWith('multiple_designs:')) {
    const names = code.slice('multiple_designs:'.length).split(',').join(', ')
    return `That export contains more than one design (${names}). Upload the single design you want, rather than having one picked for you.`
  }
  if (code.startsWith('token_not_measured:')) {
    return `The compile produced a ${code.split(':')[1]} colour the design never contained, so it was refused. Recompile — this is a model slip, not a problem with the design.`
  }
  if (code.startsWith('token_role_missing:')) {
    return `The compile left ${code.split(':')[1]} unassigned. Recompile.`
  }
  const map: Record<string, string> = {
    upload_is_canvas_only: 'That file is a Claude Design canvas — the document holding several design options per turn — not a design. Open the design itself and export that.',
    no_design_in_upload: 'No Claude Design file found in that upload.',
    no_html_in_upload: 'That zip contains no HTML.',
    bad_zip: 'That file is not a readable zip.',
    empty_upload: 'That file is empty.',
    upload_too_large: 'That file is larger than a design export should be.',
    design_doc_is_canvas: 'That file is a canvas of options rather than a single design.',
    no_screens_found: 'That design declares no screens, so there are no pages to read from it.',
    theme_not_ready: 'That theme has not finished compiling.',
    theme_not_approved: 'Approve the theme before putting it on a site.',
    theme_commit_failed: 'The theme compiled, and the site is now pointed at it, but committing it to the repo failed — the live site has not changed yet. Try again.',
  }
  return map[code] ?? code
}

function stripStack(value: string): string {
  return value.split(',')[0].replace(/['"]/g, '').trim()
}
