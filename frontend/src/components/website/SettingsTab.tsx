import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Save } from 'lucide-react'
import { api } from '../../lib/api'
import { ACCENT, btn, card, input, label } from './shared'
import type { Website } from './shared'

// Settings tab — a site's business facts (PRD §4.10).
//
// These render straight into the site (contact NAP, schema, footer, forms,
// analytics) from site.config.json. They auto-fill from the client's GBP at
// provision; this tab is the override for when a site differs from its GBP.
//
// The one thing that makes editing safe over the auto-fill is provenance: a
// field you set is stamped "you", and a later GBP re-scan leaves it alone —
// while a field you clear goes back to GBP. Each field shows where its current
// value came from, so you're never guessing whether you're overriding GBP or
// filling a blank.
//
// Not disabled while frozen: correcting a phone number is not content output,
// and a frozen client may well need its NAP fixed. Staff-gated like every write.

type Perms = { isStaff: boolean; isAdmin: boolean; frozen: boolean }

type Provenance = 'user' | 'gbp' | null

interface Facts {
  business: Record<string, string | string[]>
  provenance: Record<string, Provenance>
  tagline: string
  description: string
  forms: { web3formsKey: string }
  analytics: { ga4: string; callrailSnippet: string }
  provisioned: boolean
}

const BUSINESS_FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: 'name', label: 'Business name', placeholder: 'Acme Roofing' },
  { key: 'phoneReal', label: 'Phone', placeholder: '(714) 555-0100' },
  { key: 'street', label: 'Street address', placeholder: '123 Main St' },
  { key: 'city', label: 'City', placeholder: 'Anaheim' },
  { key: 'region', label: 'State / region', placeholder: 'CA' },
  { key: 'postalCode', label: 'Postal code', placeholder: '92801' },
  { key: 'country', label: 'Country', placeholder: 'US' },
]

export function SettingsTab({ website, perms }: { website: Website; perms: Perms }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<Facts>({
    queryKey: ['website-facts', website.id],
    queryFn: () => api.get<Facts>(`/websites/${website.id}/facts`),
  })

  // Local draft; seeded from the server once, then the user owns it.
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [area, setArea] = useState('')
  const [seeded, setSeeded] = useState(false)
  useEffect(() => {
    if (!data || seeded) return
    const next: Record<string, string> = {}
    for (const f of BUSINESS_FIELDS) next[f.key] = String(data.business[f.key] ?? '')
    next.tagline = data.tagline
    next.description = data.description
    next.web3formsKey = data.forms.web3formsKey
    next.ga4 = data.analytics.ga4
    next.callrailSnippet = data.analytics.callrailSnippet
    setDraft(next)
    setArea((data.business.areaServed as string[] | undefined)?.join(', ') ?? '')
    setSeeded(true)
  }, [data, seeded])

  const save = useMutation({
    mutationFn: () =>
      // `facts` is absent on the no-op response the server sends when nothing
      // was actually set, hence optional.
      api.put<{ committed: boolean; deploy_id: string | null; facts?: Facts }>(
        `/websites/${website.id}/facts`,
        {
          business: {
            ...Object.fromEntries(BUSINESS_FIELDS.map((f) => [f.key, draft[f.key] ?? ''])),
            areaServed: area.split(',').map((s) => s.trim()).filter(Boolean),
          },
          tagline: draft.tagline ?? '',
          description: draft.description ?? '',
          forms: { web3formsKey: draft.web3formsKey ?? '' },
          analytics: { ga4: draft.ga4 ?? '', callrailSnippet: draft.callrailSnippet ?? '' },
        },
      ),
    onSuccess: (res) => {
      // The PUT returns the post-save view, so seed the cache with it rather
      // than invalidating and making the server rebuild the same answer.
      if (res?.facts) qc.setQueryData(['website-facts', website.id], res.facts)
      else qc.invalidateQueries({ queryKey: ['website-facts', website.id] })
      // The deploy list did change, so that one is a real refetch.
      qc.invalidateQueries({ queryKey: ['website', website.id] })
    },
  })

  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: v }))
  const deny = !perms.isStaff ? 'Staff and admins only.' : null

  if (isLoading) return <div style={{ color: '#64748b', fontSize: 13 }}>Loading…</div>

  return (
    <div style={{ display: 'grid', gap: 16, maxWidth: 680 }}>
      <div style={{ ...card, background: '#f8fafc', fontSize: 12, color: '#64748b' }}>
        These facts render straight into the site — contact details, schema, footer, forms
        and analytics. They auto-fill from the client's Google Business Profile; edit here only
        where the site differs.{' '}
        {data?.provisioned
          ? <strong style={{ color: '#0369a1' }}>Saving redeploys the live site.</strong>
          : 'Saving stores them; provisioning will commit them with the first build.'}
      </div>

      <Section title="Business identity">
        {BUSINESS_FIELDS.map((f) => (
          <Field
            key={f.key}
            label={f.label}
            placeholder={f.placeholder}
            value={draft[f.key] ?? ''}
            source={data?.provenance[f.key] ?? null}
            onChange={(v) => set(f.key, v)}
            disabled={Boolean(deny)}
          />
        ))}
        <Field
          label="Areas served"
          hint="Comma-separated; used on service-area businesses. Up to 12."
          placeholder="Brea, Fullerton, Yorba Linda"
          value={area}
          source={data?.provenance.areaServed ?? null}
          onChange={setArea}
          disabled={Boolean(deny)}
        />
      </Section>

      <BrandVoiceSection website={website} deny={deny} />

      <Section title="Positioning">
        <Field label="Tagline" placeholder="Roofs done right, the first time"
               value={draft.tagline ?? ''} onChange={(v) => set('tagline', v)} disabled={Boolean(deny)} />
        <Field label="Description" placeholder="One line describing the business."
               value={draft.description ?? ''} onChange={(v) => set('description', v)} disabled={Boolean(deny)} />
      </Section>

      <Section title="Forms & analytics">
        <Field label="Web3Forms key" hint="Powers the contact form's submissions."
               placeholder="xxxxxxxx-xxxx-…" value={draft.web3formsKey ?? ''}
               onChange={(v) => set('web3formsKey', v)} disabled={Boolean(deny)} />
        <Field label="GA4 measurement ID" placeholder="G-XXXXXXXXXX"
               value={draft.ga4 ?? ''} onChange={(v) => set('ga4', v)} disabled={Boolean(deny)} />
        <Field label="CallRail snippet" hint="Paste the DNI script if this site uses call tracking."
               placeholder="<script>…</script>" value={draft.callrailSnippet ?? ''}
               onChange={(v) => set('callrailSnippet', v)} disabled={Boolean(deny)} />
      </Section>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button onClick={() => save.mutate()} disabled={Boolean(deny) || save.isPending}
                title={deny ?? undefined}
                style={btn(deny ? '#e2e8f0' : ACCENT, deny ? '#94a3b8' : '#fff')}>
          {save.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Save
        </button>
        {save.isSuccess && !save.isPending && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#15803d' }}>
            <Check size={13} /> Saved{save.data?.committed ? ' — redeploying the live site' : ''}
          </span>
        )}
        {deny && <span style={{ fontSize: 12, color: '#94a3b8' }}>{deny}</span>}
      </div>
      {save.error && (
        <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {(save.error as Error).message}
        </div>
      )}
    </div>
  )
}

interface Brand {
  editable: boolean
  kind: string
  brand_voice: string
  icp: string
  has_context: boolean
}

// Brand voice & audience — only for a standalone site (an owned property). A
// property has no client screen, so its voice is set here; generation is blocked
// until it has one. For a real client-backed site this section does not render
// (voice is edited on the client), so the tab looks the same as it always did.
function BrandVoiceSection({ website, deny }: { website: Website; deny: string | null }) {
  const qc = useQueryClient()
  const { data } = useQuery<Brand>({
    queryKey: ['website-brand', website.id],
    queryFn: () => api.get<Brand>(`/websites/${website.id}/brand`),
  })

  const [voice, setVoice] = useState('')
  const [icp, setIcp] = useState('')
  const [seeded, setSeeded] = useState(false)
  useEffect(() => {
    if (!data || seeded) return
    setVoice(data.brand_voice)
    setIcp(data.icp)
    setSeeded(true)
  }, [data, seeded])

  const save = useMutation({
    mutationFn: () => api.put<Brand>(`/websites/${website.id}/brand`, { brand_voice: voice, icp }),
    onSuccess: (res) => qc.setQueryData(['website-brand', website.id], res),
  })

  if (!data?.editable) return null

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Brand voice & audience</h3>
        {data.has_context
          ? <span style={{ padding: '1px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700, color: '#15803d', background: '#f0fdf4' }}>Ready</span>
          : <span style={{ padding: '1px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700, color: '#b45309', background: '#fffbeb' }}>Needed to generate</span>}
      </div>
      <p style={{ margin: '0 0 12px', fontSize: 12, color: '#64748b' }}>
        This site is a standalone property, so it carries its own voice. Content generation is
        blocked until a brand voice is set — describe how the business should sound and who it’s
        for. (If you entered a website URL when creating the site, a scan may fill these in.)
      </p>
      <div style={{ display: 'grid', gap: 12 }}>
        <div>
          <label style={label}>Brand voice / guide</label>
          <textarea value={voice} onChange={(e) => setVoice(e.target.value)} rows={5} disabled={Boolean(deny)}
                    placeholder="Tone, personality, words to use and avoid. Paste a brand guide, or write a few lines."
                    style={{ ...input, resize: 'vertical' }} />
        </div>
        <div>
          <label style={label}>Ideal customer (ICP)</label>
          <textarea value={icp} onChange={(e) => setIcp(e.target.value)} rows={3} disabled={Boolean(deny)}
                    placeholder="Who this business serves — their situation, needs, and what makes them buy."
                    style={{ ...input, resize: 'vertical' }} />
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
        <button onClick={() => save.mutate()} disabled={Boolean(deny) || save.isPending}
                title={deny ?? undefined}
                style={btn(deny ? '#e2e8f0' : ACCENT, deny ? '#94a3b8' : '#fff')}>
          {save.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Save voice
        </button>
        {save.isSuccess && !save.isPending && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#15803d' }}>
            <Check size={13} /> Saved
          </span>
        )}
        {deny && <span style={{ fontSize: 12, color: '#94a3b8' }}>{deny}</span>}
      </div>
      {save.error && (
        <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {(save.error as Error).message}
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={card}>
      <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{title}</h3>
      <div style={{ display: 'grid', gap: 12 }}>{children}</div>
    </div>
  )
}

function Field({ label: lbl, value, onChange, placeholder, hint, source, disabled }: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  source?: Provenance
  disabled?: boolean
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <label style={{ ...label, marginBottom: 0 }}>{lbl}</label>
        {source && <SourceBadge source={source} />}
      </div>
      <input style={input} value={value} placeholder={placeholder} disabled={disabled}
             onChange={(e) => onChange(e.target.value)} />
      {hint && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 3 }}>{hint}</div>}
    </div>
  )
}

function SourceBadge({ source }: { source: Provenance }) {
  // Shows where the CURRENT stored value came from. Once you type and save, a
  // field reads "You"; clear it and it returns to "From GBP".
  const map: Record<'user' | 'gbp', { text: string; fg: string; bg: string }> = {
    user: { text: 'You', fg: '#0369a1', bg: '#f0f9ff' },
    gbp: { text: 'From GBP', fg: '#7c3aed', bg: '#faf5ff' },
  }
  if (source !== 'user' && source !== 'gbp') return null
  const c = map[source]
  return (
    <span style={{ padding: '1px 6px', borderRadius: 999, fontSize: 10, fontWeight: 700, color: c.fg, background: c.bg }}>
      {c.text}
    </span>
  )
}
