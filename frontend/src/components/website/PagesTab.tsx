import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, GitCommit, Loader2, Plus, RotateCcw, Sparkles, Upload, X } from 'lucide-react'
import { ACCENT, Chip, btn, card, denyReason, input, label, POST_FORMATS, useBatch } from './shared'
import type { Website, WebsitePage } from './shared'
import { api } from '../../lib/api'

// The Pages tab. Three things it must not do:
//
//  * imply that everything is generable — a page type with no engine says so on
//    its row rather than sitting at draft with no explanation;
//  * hide why a page is held. A gate reason is the whole point of holding at
//    draft instead of dropping the page, so it renders next to the row; and
//  * pretend the plan is only ever the deterministic matrix — a page can be
//    added one at a time (Add page), on top of the services × cities inventory.

// Reasons a page can be held, in the words the backend uses, translated once.
const GATE_COPY: Record<string, string> = {
  facts_consistency_failed: 'Claims a fact that is not in the business facts. Not overridable at any role.',
  voice_violation: 'Unresolved critical brand-voice finding.',
  writer_run_degraded: 'Written with zero brand context — never auto-published.',
  news_post_missing_review_date: 'A news post needs a review/sunset date.',
  seo_composite_missing: 'No SEO score — scoring failed or never ran.',
  body_not_generated: 'Nothing written yet. Generate it first.',
  content_no_brand_context: 'This client has no brand voice on file.',
}

function gateHint(error: string | null): string | null {
  if (!error) return null
  const key = error.split(':')[0]
  if (GATE_COPY[key]) return GATE_COPY[key]
  if (key === 'seo_composite_below_threshold') return `SEO composite below 75 (${error.split(':')[1]}). Reoptimize, or publish with an override.`
  if (key === 'engine_unavailable') return `No writer in the suite covers ${error.split(':')[1]} pages yet.`
  if (key === 'engine_not_built') return `The ${error.split(':')[1]} generator is specified but not built yet.`
  if (key === 'template_rendered') return 'Rendered by the template from published data — nothing to write.'
  return error
}

interface Props {
  website: Website
  pages: WebsitePage[]
  approved: boolean
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

export function PagesTab({ website, pages, approved, perms }: Props) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [force, setForce] = useState(false)
  const [adding, setAdding] = useState(false)

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['website', website.id] })
    void qc.invalidateQueries({ queryKey: ['website-plan', website.id] })
  }
  const batch = useBatch(`website-batch-${website.id}`, website.id, refresh)

  // VAs generate and retry — that is their work, and both are idempotent. What
  // they may not do is publish: publish here means the public internet, not a
  // reviewable Doc (PRD §2). So generation's only bar is the freeze.
  const generateDeny = perms.frozen
    ? 'This client is frozen — content output is paused until the freeze lifts.'
    : null
  const publishDeny = denyReason('staff', perms)
  // Adding a page is a plan edit, so it sits at the staff bar like build-plan.
  const addDeny = denyReason('staff', perms)
  // Approval gates generation and publishing (enforced server-side too); adding
  // a draft is allowed before approval so pages can be assembled, then approved
  // together.
  const approveDeny = approved ? null : 'Approve the plan on the Plan tab before generating or publishing.'

  // Both writing engines: nlp (service/location/matrix, with SERP + scoring) and
  // core_pages (home/about/contact, a light single call). 'template' and null
  // are not generable — the template renders one and nothing writes the other.
  const generable = useMemo(
    () => pages.filter((p) => (p.plan?.engine === 'nlp' || p.plan?.engine === 'core_pages') && selected.has(p.id)),
    [pages, selected],
  )
  const publishable = useMemo(
    () => pages.filter((p) => selected.has(p.id) && p.plan?.engine !== null),
    [pages, selected],
  )

  const generate = useMutation({
    mutationFn: () => api.post<{ job_ids: string[] }>(`/websites/${website.id}/generate`, {
      page_ids: generable.map((p) => p.id),
    }),
    onSuccess: (res) => { batch.start(res.job_ids, 'generate'); setSelected(new Set()) },
  })

  const publish = useMutation({
    mutationFn: () => api.post<{ job_ids: string[] }>(`/websites/${website.id}/publish`, {
      page_ids: publishable.map((p) => p.id), force,
    }),
    onSuccess: (res) => { batch.start(res.job_ids, 'publish'); setSelected(new Set()); setForce(false) },
  })

  const retry = useMutation({
    mutationFn: (pageId: string) => api.post(`/websites/${website.id}/pages/${pageId}/retry`, {}),
    onSuccess: refresh,
  })

  const toggle = (id: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  const genDisabled = generable.length === 0 || Boolean(generateDeny) || Boolean(approveDeny) || generate.isPending
  const pubDisabled = publishable.length === 0 || Boolean(publishDeny) || Boolean(approveDeny) || publish.isPending

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {!approved && (
        <div style={{ ...card, borderColor: '#fde68a', background: '#fffbeb', color: '#92400e', fontSize: 13 }}>
          The plan isn’t approved yet. You can add and arrange pages here, but generating and publishing
          are locked until it’s approved on the Plan tab — a local business site gets a human review
          before its first publish.
        </div>
      )}

      {batch.batch && (
        <div style={{ ...card, borderColor: '#bae6fd', background: '#f0f9ff', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Loader2 size={15} className="spin" color={ACCENT} />
          <div style={{ flex: 1, fontSize: 13, color: '#0369a1' }}>
            <strong>{batch.batch.kind === 'generate' ? 'Generating' : 'Publishing'}</strong>{' '}
            {batch.finished} of {batch.total}
            {batch.failed > 0 && <span style={{ color: '#b91c1c' }}> · {batch.failed} failed</span>}
            <div style={{ fontSize: 11, color: '#64748b' }}>
              Safe to leave — this runs server-side and picks back up when you return.
            </div>
          </div>
          <button onClick={batch.clear} style={{ ...btn('#fff', '#64748b'), padding: '6px 8px' }} title="Stop watching">
            <X size={13} />
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={() => setAdding(true)}
          disabled={Boolean(addDeny)}
          title={addDeny ?? 'Add one page by hand — a service, a city, a hyper-local page, or a one-off blog post — on top of the matrix.'}
          style={{ ...btn(addDeny ? '#e2e8f0' : '#fff', addDeny ? '#94a3b8' : ACCENT) }}
        >
          <Plus size={14} /> Add page
        </button>

        <div style={{ width: 1, height: 22, background: '#e2e8f0' }} />

        <button
          onClick={() => generate.mutate()}
          disabled={genDisabled}
          title={generateDeny ?? approveDeny ?? (generable.length === 0 ? 'Select pages an engine can write.' : `Writes ${generable.length} page(s). Service/location pages cost a SERP analysis each; home/about/contact are a single cheap call.`)}
          style={{ ...btn(genDisabled ? '#e2e8f0' : ACCENT, genDisabled ? '#94a3b8' : '#fff') }}
        >
          {generate.isPending ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
          Generate {generable.length > 0 ? `(${generable.length})` : ''}
        </button>

        <button
          onClick={() => publish.mutate()}
          disabled={pubDisabled}
          title={publishDeny ?? approveDeny ?? (publishable.length === 0 ? 'Select pages to commit.' : 'Commits each page into the site repo, which triggers a deploy.')}
          style={{ ...btn(pubDisabled ? '#e2e8f0' : '#15803d', pubDisabled ? '#94a3b8' : '#fff') }}
        >
          {publish.isPending ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
          Publish {publishable.length > 0 ? `(${publishable.length})` : ''}
        </button>

        {!publishDeny && (
          <label style={{ fontSize: 12, color: '#64748b', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                 title="Forces past an overridable gate only. A facts-consistency failure is not overridable at any role, and the override is recorded on the deploy.">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            Publish anyway
          </label>
        )}
        {publishDeny && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{publishDeny}</span>
        )}
      </div>

      {(generate.error || publish.error) && (
        <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {((generate.error ?? publish.error) as Error).message}
        </div>
      )}

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b' }}>
              <th style={{ ...th, width: 28 }}>
                <input type="checkbox"
                       checked={selected.size > 0 && selected.size === pages.length}
                       onChange={(e) => setSelected(e.target.checked ? new Set(pages.map((p) => p.id)) : new Set())} />
              </th>
              <th style={th}>Path</th><th style={th}>Type</th><th style={th}>Status</th>
              <th style={th}>Engine</th><th style={th}>Notes</th><th style={th} />
            </tr>
          </thead>
          <tbody>
            {pages.map((page) => {
              const hint = gateHint(page.error)
              const engine = page.plan?.engine
              return (
                <tr key={page.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>
                    <input type="checkbox" checked={selected.has(page.id)} onChange={() => toggle(page.id)} />
                  </td>
                  <td style={{ ...td, fontFamily: 'ui-monospace, monospace' }}>
                    {page.route}
                    {page.trigger === 'manual' && (
                      <span style={{ marginLeft: 6, padding: '1px 6px', borderRadius: 999, fontSize: 10, fontWeight: 700, color: ACCENT, background: '#e0f2fe' }}>
                        added
                      </span>
                    )}
                    {page.commit_sha && (
                      <div style={{ color: '#94a3b8', fontSize: 11, display: 'flex', alignItems: 'center', gap: 3 }}>
                        <GitCommit size={10} /> {page.commit_sha.slice(0, 7)}
                      </div>
                    )}
                  </td>
                  <td style={td}>{page.page_type}</td>
                  <td style={td}><Chip status={page.status} /></td>
                  <td style={{ ...td, color: engine ? '#475569' : '#b45309' }}>
                    {engine ?? 'none'}
                  </td>
                  <td style={{ ...td, color: page.status === 'failed' ? '#b91c1c' : '#64748b', maxWidth: 320 }}>
                    {hint && (
                      <span style={{ display: 'inline-flex', gap: 4, alignItems: 'flex-start' }}>
                        <AlertTriangle size={11} style={{ marginTop: 2, flexShrink: 0 }} /> {hint}
                      </span>
                    )}
                  </td>
                  <td style={td}>
                    {page.status === 'failed' && (
                      <button onClick={() => retry.mutate(page.id)} disabled={perms.frozen}
                              title={perms.frozen ? 'This client is frozen.' : 'Retry — idempotent, so this never creates a second commit.'}
                              style={{ ...btn('#fff', ACCENT), padding: '5px 8px' }}>
                        <RotateCcw size={12} /> Retry
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {pages.length === 0 && (
          <div style={{ color: '#64748b', fontSize: 13, padding: 8 }}>
            No pages yet — build the plan on the Plan tab, or add one with “Add page”.
          </div>
        )}
      </div>

      {adding && (
        <AddPageModal
          websiteId={website.id}
          onClose={() => setAdding(false)}
          onDone={() => { setAdding(false); refresh() }}
        />
      )}
    </div>
  )
}

const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600 }
const td: React.CSSProperties = { padding: '6px 8px', verticalAlign: 'top' }

// --- Add page ------------------------------------------------------------

type FieldKey = 'service' | 'city' | 'subservice' | 'title'

interface TypeDef {
  value: string
  label: string
  group: string
  fields: FieldKey[]
  subLabel?: string
  hint: string
}

// The writable page types, grouped. `fields` are the required axes; `subLabel`
// renames the shared "subservice" axis to what it means for that type.
const TYPE_DEFS: TypeDef[] = [
  { value: 'service', label: 'Service page', group: 'Service', fields: ['service'], hint: '/{service}/' },
  { value: 'sub_service', label: 'Sub-service page', group: 'Service', fields: ['service', 'subservice'], subLabel: 'Sub-service', hint: '/{service}/{sub-service}/ — e.g. Oak Tree Removal under Tree Removal' },
  { value: 'brand_service', label: 'Brand × service page', group: 'Service', fields: ['service', 'subservice'], subLabel: 'Brand', hint: '/{service}/{brand}/ — e.g. Carrier under AC Repair' },
  { value: 'location', label: 'City page', group: 'Geo', fields: ['city'], hint: '/{city}/' },
  { value: 'neighborhood', label: 'Neighborhood page', group: 'Geo', fields: ['city', 'subservice'], subLabel: 'Neighborhood', hint: '/{city}/{neighborhood}/' },
  { value: 'local_landing', label: 'Service × city page', group: 'Geo', fields: ['city', 'service'], hint: '/{city}/{service}/' },
  { value: 'hyper_local', label: 'Hyper-local page', group: 'Geo', fields: ['city', 'service', 'subservice'], subLabel: 'Sub-service', hint: '/{city}/{service}/{sub-service}/ — the granular escalation page' },
  { value: 'post', label: 'Blog post', group: 'Blog', fields: ['title'], hint: '/blog/{slug}/ — a one-off post, not tied to a pillar' },
  { value: 'pillar', label: 'Pillar / hub page', group: 'Blog', fields: ['title'], hint: '/{slug}/ — a topic hub at the site root' },
]

const ADD_ERRORS: Record<string, string> = {
  unsupported_page_type: 'That page type can’t be added here.',
  missing_service: 'Enter the service name.',
  missing_city: 'Enter the city name.',
  missing_subservice: 'Enter the sub-service, brand, or neighborhood.',
  missing_title: 'Enter a title.',
  invalid_format: 'Pick a valid blog format.',
  reserved_slug: 'That URL collides with a reserved page. Pick a different name.',
  page_route_exists: 'A page already exists at that URL.',
}

function AddPageModal({ websiteId, onClose, onDone }: { websiteId: string; onClose: () => void; onDone: () => void }) {
  const [type, setType] = useState('service')
  const [service, setService] = useState('')
  const [city, setCity] = useState('')
  const [subservice, setSubservice] = useState('')
  const [title, setTitle] = useState('')
  const [format, setFormat] = useState(POST_FORMATS[0].value)
  const [angle, setAngle] = useState('')
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)

  const def = TYPE_DEFS.find((d) => d.value === type) as TypeDef
  const isBlog = type === 'post' || type === 'pillar'

  const add = useMutation({
    mutationFn: () => api.post(`/websites/${websiteId}/pages`, {
      page_type: type,
      service: def.fields.includes('service') ? service : undefined,
      city: def.fields.includes('city') ? city : undefined,
      subservice: def.fields.includes('subservice') ? subservice : undefined,
      title: def.fields.includes('title') || title ? title : undefined,
      format: type === 'post' ? format : undefined,
      angle: isBlog && angle ? angle : undefined,
      keyword: keyword || undefined,
      location: !isBlog && location ? location : undefined,
    }),
    onSuccess: onDone,
  })

  const missing = def.fields.some((f) => (
    (f === 'service' && !service.trim()) ||
    (f === 'city' && !city.trim()) ||
    (f === 'subservice' && !subservice.trim()) ||
    (f === 'title' && !title.trim())
  ))

  const errMsg = add.error
    ? (ADD_ERRORS[(add.error as Error).message] ?? (add.error as Error).message)
    : null

  const grouped = ['Service', 'Geo', 'Blog'].map((g) => ({ g, defs: TYPE_DEFS.filter((d) => d.group === g) }))

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 460, maxWidth: '92vw', maxHeight: '86vh', overflowY: 'auto', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <strong style={{ fontSize: 15 }}>Add a page</strong>
          <button onClick={onClose} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={15} /></button>
        </div>

        <div>
          <label style={label}>Page type</label>
          <select value={type} onChange={(e) => setType(e.target.value)} style={{ ...input, cursor: 'pointer' }}>
            {grouped.map(({ g, defs }) => (
              <optgroup key={g} label={g}>
                {defs.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </optgroup>
            ))}
          </select>
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4, fontFamily: 'ui-monospace, monospace' }}>{def.hint}</div>
        </div>

        {def.fields.includes('city') && (
          <Field label="City" value={city} onChange={setCity} placeholder="Seattle" />
        )}
        {def.fields.includes('service') && (
          <Field label="Service" value={service} onChange={setService} placeholder="Tree Removal" />
        )}
        {def.fields.includes('subservice') && (
          <Field label={def.subLabel ?? 'Sub-service'} value={subservice} onChange={setSubservice}
                 placeholder={def.value === 'brand_service' ? 'Carrier' : def.value === 'neighborhood' ? 'Ballard' : 'Oak Trees'} />
        )}
        {def.fields.includes('title') && (
          <Field label="Title" value={title} onChange={setTitle} placeholder={type === 'pillar' ? 'Roof Maintenance Guide' : 'How to spot storm roof damage'} />
        )}
        {type === 'post' && (
          <div>
            <label style={label}>Format</label>
            <select value={format} onChange={(e) => setFormat(e.target.value)} style={{ ...input, cursor: 'pointer' }}>
              {POST_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </div>
        )}

        <button onClick={() => setShowAdvanced((s) => !s)} style={{ ...btn('#fff', '#64748b'), justifySelf: 'start', padding: '4px 8px', fontSize: 12 }}>
          {showAdvanced ? 'Hide' : 'Show'} optional
        </button>
        {showAdvanced && (
          <div style={{ display: 'grid', gap: 10, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
            {isBlog && (
              <div>
                <label style={label}>Editorial angle</label>
                <textarea value={angle} onChange={(e) => setAngle(e.target.value)} rows={2}
                          placeholder="The angle / who it's for — threaded into the writer brief."
                          style={{ ...input, resize: 'vertical' }} />
              </div>
            )}
            {!isBlog && (
              <Field label="Target keyword (override)" value={keyword} onChange={setKeyword}
                     placeholder="Leave blank to derive from the axes." />
            )}
            {isBlog && (
              <Field label="Target keyword (override)" value={keyword} onChange={setKeyword}
                     placeholder="Leave blank to use the title." />
            )}
            {!isBlog && (
              <Field label="SERP location (override)" value={location} onChange={setLocation}
                     placeholder="Leave blank to derive from the city." />
            )}
          </div>
        )}

        {errMsg && (
          <div style={{ padding: 9, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>{errMsg}</div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={btn('#fff', '#64748b')}>Cancel</button>
          <button
            onClick={() => add.mutate()}
            disabled={missing || add.isPending}
            title={missing ? 'Fill the required fields.' : 'Adds a draft page. Generate and publish it like any other.'}
            style={{ ...btn(missing ? '#e2e8f0' : ACCENT, missing ? '#94a3b8' : '#fff') }}
          >
            {add.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add page
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label: lbl, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label style={label}>{lbl}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} style={input} />
    </div>
  )
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.45)', display: 'flex',
  alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 16,
}
