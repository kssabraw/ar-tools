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
  const [addingProject, setAddingProject] = useState(false)
  const [addingOffers, setAddingOffers] = useState(false)
  const [addingWarranty, setAddingWarranty] = useState(false)

  // Offers and warranty are singletons (one per site at /specials/ and
  // /warranty/), so their Add button is disabled once the page exists rather
  // than letting the operator hit a 409.
  const hasOffers = pages.some((p) => p.page_type === 'offers')
  const hasWarranty = pages.some((p) => p.page_type === 'warranty')

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

  // Every engine the backend can write a body for is generable here: nlp
  // (service/location/matrix, with SERP + scoring), core_pages (home/about/contact
  // + FAQ + hubs), run (blog posts/pillars/comparison/problem), and the structured
  // singletons (project/offers/warranty). Only 'template' and null are not — the
  // template renders one from data and nothing writes the other.
  const generable = useMemo(
    () => pages.filter((p) => selected.has(p.id) && p.plan?.engine != null && p.plan?.engine !== 'template'),
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

        <button
          onClick={() => setAddingProject(true)}
          disabled={Boolean(addDeny)}
          title={addDeny ?? 'Add a case study — real completed-job facts you enter (stats, photos, testimonial). Nothing is invented.'}
          style={{ ...btn(addDeny ? '#e2e8f0' : '#fff', addDeny ? '#94a3b8' : ACCENT) }}
        >
          <Plus size={14} /> Add project
        </button>

        <button
          onClick={() => setAddingOffers(true)}
          disabled={Boolean(addDeny) || hasOffers}
          title={addDeny ?? (hasOffers ? 'This site already has an offers page (/specials/).' : 'Add the offers / specials page — coupons, promos and financing you enter. Terms and expiry are never invented.')}
          style={{ ...btn(addDeny || hasOffers ? '#e2e8f0' : '#fff', addDeny || hasOffers ? '#94a3b8' : ACCENT) }}
        >
          <Plus size={14} /> Add offers
        </button>

        <button
          onClick={() => setAddingWarranty(true)}
          disabled={Boolean(addDeny) || hasWarranty}
          title={addDeny ?? (hasWarranty ? 'This site already has a warranty page (/warranty/).' : 'Add the warranty / guarantee page — coverage, claim steps and FAQ you enter. Terms are never invented.')}
          style={{ ...btn(addDeny || hasWarranty ? '#e2e8f0' : '#fff', addDeny || hasWarranty ? '#94a3b8' : ACCENT) }}
        >
          <Plus size={14} /> Add warranty
        </button>

        <div style={{ width: 1, height: 22, background: '#e2e8f0' }} />

        <button
          onClick={() => generate.mutate()}
          disabled={genDisabled}
          title={generateDeny ?? approveDeny ?? (generable.length === 0 ? 'Select pages an engine can write.' : `Writes ${generable.length} page(s). Service/location pages cost a SERP analysis each; blog runs a full pipeline; core, project, offers and warranty pages are cheap or free.`)}
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

      {addingProject && (
        <ProjectModal
          websiteId={website.id}
          onClose={() => setAddingProject(false)}
          onDone={() => { setAddingProject(false); refresh() }}
        />
      )}

      {addingOffers && (
        <OffersModal
          websiteId={website.id}
          onClose={() => setAddingOffers(false)}
          onDone={() => { setAddingOffers(false); refresh() }}
        />
      )}

      {addingWarranty && (
        <WarrantyModal
          websiteId={website.id}
          onClose={() => setAddingWarranty(false)}
          onDone={() => { setAddingWarranty(false); refresh() }}
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
  serviceLabel?: string
  hint: string
}

// The writable page types, grouped. `fields` are the required axes; `subLabel` /
// `serviceLabel` rename the shared "subservice" / "service" axes to what they
// mean for that type.
const TYPE_DEFS: TypeDef[] = [
  { value: 'service', label: 'Service page', group: 'Service', fields: ['service'], hint: '/{service}/' },
  { value: 'sub_service', label: 'Sub-service page', group: 'Service', fields: ['service', 'subservice'], subLabel: 'Sub-service', hint: '/{service}/{sub-service}/ — e.g. Oak Tree Removal under Tree Removal' },
  { value: 'brand_service', label: 'Brand × service page', group: 'Service', fields: ['service', 'subservice'], subLabel: 'Brand', hint: '/{service}/{brand}/ — e.g. Carrier under AC Repair' },
  { value: 'cost', label: 'Cost / pricing page', group: 'Service', fields: ['service'], hint: '/{service}/cost/ — real ranges + cost factors (needs price sign-off)' },
  { value: 'location', label: 'City page', group: 'Geo', fields: ['city'], hint: '/{city}/' },
  { value: 'neighborhood', label: 'Neighborhood page', group: 'Geo', fields: ['city', 'subservice'], subLabel: 'Neighborhood', hint: '/{city}/{neighborhood}/' },
  { value: 'local_landing', label: 'Service × city page', group: 'Geo', fields: ['city', 'service'], hint: '/{city}/{service}/' },
  { value: 'hyper_local', label: 'Hyper-local page', group: 'Geo', fields: ['city', 'service', 'subservice'], subLabel: 'Sub-service', hint: '/{city}/{service}/{sub-service}/ — the granular escalation page' },
  { value: 'post', label: 'Blog post', group: 'Blog', fields: ['title'], hint: '/blog/{slug}/ — a one-off post, not tied to a pillar' },
  { value: 'pillar', label: 'Pillar / hub page', group: 'Blog', fields: ['title'], hint: '/{slug}/ — a topic hub at the site root' },
  { value: 'comparison', label: 'Comparison page', group: 'Other', fields: ['service', 'subservice'], serviceLabel: 'Option A', subLabel: 'Option B', hint: '/compare/{a}-vs-{b}/ — verdict-first X vs Y' },
  { value: 'faq', label: 'Standalone FAQ page', group: 'Other', fields: [], hint: '/faq/ — one Q&A hub for the site (title optional)' },
  { value: 'problem', label: 'Problem / symptom page', group: 'Other', fields: ['title'], hint: '/blog/{symptom-slug}/ — diagnostic triage; never geo-targeted (add SME cause notes under optional)' },
]

const ADD_ERRORS: Record<string, string> = {
  unsupported_page_type: 'That page type can’t be added here.',
  missing_service: 'Enter the service name.',
  missing_city: 'Enter the city name.',
  missing_subservice: 'Enter the sub-service, brand, neighborhood, or comparison option.',
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
  // A problem/symptom page is a blog run too, so it takes the blog affordances:
  // the editorial-angle textarea (where SME cause notes go), a keyword override,
  // and no location field (it is never geo-targeted).
  const isBlog = type === 'post' || type === 'pillar' || type === 'problem'

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

  const grouped = ['Service', 'Geo', 'Blog', 'Other'].map((g) => ({ g, defs: TYPE_DEFS.filter((d) => d.group === g) }))

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
          <Field label={def.serviceLabel ?? 'Service'} value={service} onChange={setService}
                 placeholder={def.value === 'comparison' ? 'Tankless water heater' : 'Tree Removal'} />
        )}
        {def.fields.includes('subservice') && (
          <Field label={def.subLabel ?? 'Sub-service'} value={subservice} onChange={setSubservice}
                 placeholder={def.value === 'brand_service' ? 'Carrier' : def.value === 'neighborhood' ? 'Ballard' : def.value === 'comparison' ? 'Tank water heater' : 'Oak Trees'} />
        )}
        {(def.fields.includes('title') || type === 'faq') && (
          <Field label={type === 'faq' ? 'Title (optional)' : type === 'problem' ? 'Symptom' : 'Title'} value={title} onChange={setTitle}
                 placeholder={type === 'pillar' ? 'Roof Maintenance Guide' : type === 'faq' ? 'Frequently Asked Questions' : type === 'problem' ? 'AC blowing warm air' : 'How to spot storm roof damage'} />
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
                <label style={label}>{type === 'problem' ? 'Known causes / SME notes' : 'Editorial angle'}</label>
                <textarea value={angle} onChange={(e) => setAngle(e.target.value)} rows={2}
                          placeholder={type === 'problem'
                            ? 'SME-verified causes, severity, and fixes — the writer uses only these, never invents causes.'
                            : "The angle / who it's for — threaded into the writer brief."}
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

// --- Add project (case study) --------------------------------------------

interface StatRow { label: string; value: string }
interface PhotoRow { url: string; alt: string; caption: string }

const PROJECT_ADD_ERRORS: Record<string, string> = {
  missing_title: 'Enter a project headline.',
  reserved_slug: 'That URL collides with a reserved page. Pick a different headline.',
  page_route_exists: 'A project already exists at that URL.',
}

function ProjectModal({ websiteId, onClose, onDone }: { websiteId: string; onClose: () => void; onDone: () => void }) {
  const [headline, setHeadline] = useState('')
  const [location, setLocation] = useState('')
  const [challenge, setChallenge] = useState('')
  const [work, setWork] = useState('')
  const [outcome, setOutcome] = useState('')
  const [tQuote, setTQuote] = useState('')
  const [tAuthor, setTAuthor] = useState('')
  const [serviceSlug, setServiceSlug] = useState('')
  const [locationSlug, setLocationSlug] = useState('')
  const [stats, setStats] = useState<StatRow[]>([{ label: '', value: '' }])
  const [photos, setPhotos] = useState<PhotoRow[]>([{ url: '', alt: '', caption: '' }])

  const add = useMutation({
    mutationFn: () => api.post(`/websites/${websiteId}/pages`, {
      page_type: 'project',
      title: headline,
      project: {
        headline,
        location: location || undefined,
        stats: stats.filter((s) => s.label.trim() && s.value.trim()),
        challenge: challenge || undefined,
        work: work || undefined,
        outcome: outcome || undefined,
        testimonial_quote: tQuote || undefined,
        testimonial_author: tAuthor || undefined,
        photos: photos.filter((p) => p.url.trim()),
        service_slug: serviceSlug || undefined,
        location_slug: locationSlug || undefined,
      },
    }),
    onSuccess: onDone,
  })

  const errMsg = add.error
    ? (PROJECT_ADD_ERRORS[(add.error as Error).message] ?? (add.error as Error).message)
    : null
  const ta: React.CSSProperties = { ...input, resize: 'vertical', minHeight: 60 }
  const rowStyle: React.CSSProperties = { display: 'flex', gap: 6, alignItems: 'center' }

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <strong style={{ fontSize: 15 }}>Add a project / case study</strong>
          <button onClick={onClose} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={15} /></button>
        </div>
        <div style={{ fontSize: 11, color: '#64748b' }}>
          Real completed-job facts only — everything here is what you enter. The writer narrates your
          challenge/work/result notes into prose and never invents a number, name, or result.
        </div>

        <Field label="Job headline" value={headline} onChange={setHeadline} placeholder="Emergency oak removal in Anaheim" />
        <Field label="Location (optional)" value={location} onChange={setLocation} placeholder="Anaheim, CA" />

        <div>
          <label style={label}>Job facts (stats)</label>
          {stats.map((s, i) => (
            <div key={i} style={{ ...rowStyle, marginBottom: 6 }}>
              <input value={s.label} placeholder="Label — e.g. Completed in"
                     onChange={(e) => setStats(stats.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} style={input} />
              <input value={s.value} placeholder="Value — e.g. 1 day"
                     onChange={(e) => setStats(stats.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} style={input} />
              <button onClick={() => setStats(stats.filter((_, j) => j !== i))} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
            </div>
          ))}
          {stats.length < 4 && (
            <button onClick={() => setStats([...stats, { label: '', value: '' }])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
              <Plus size={12} /> Add stat
            </button>
          )}
        </div>

        <div>
          <label style={label}>The challenge</label>
          <textarea value={challenge} onChange={(e) => setChallenge(e.target.value)} rows={2} placeholder="The situation and what made it hard." style={ta} />
        </div>
        <div>
          <label style={label}>What we did</label>
          <textarea value={work} onChange={(e) => setWork(e.target.value)} rows={2} placeholder="Exactly what was done." style={ta} />
        </div>
        <div>
          <label style={label}>The result</label>
          <textarea value={outcome} onChange={(e) => setOutcome(e.target.value)} rows={2} placeholder="The measurable outcome." style={ta} />
        </div>

        <div>
          <label style={label}>Photos (upload a file or paste a URL — both are hosted on the site)</label>
          {photos.map((p, i) => (
            <ProjectPhotoRow
              key={i}
              websiteId={websiteId}
              photo={p}
              onChange={(np) => setPhotos(photos.map((x, j) => (j === i ? np : x)))}
              onRemove={() => setPhotos(photos.filter((_, j) => j !== i))}
            />
          ))}
          <button onClick={() => setPhotos([...photos, { url: '', alt: '', caption: '' }])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
            <Plus size={12} /> Add photo
          </button>
        </div>

        <Field label="Testimonial quote (optional)" value={tQuote} onChange={setTQuote} placeholder="They saved our garage." />
        <Field label="Testimonial author (optional)" value={tAuthor} onChange={setTAuthor} placeholder="M. Reyes" />

        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}><Field label="Link to service slug (optional)" value={serviceSlug} onChange={setServiceSlug} placeholder="tree-removal" /></div>
          <div style={{ flex: 1 }}><Field label="Link to city slug (optional)" value={locationSlug} onChange={setLocationSlug} placeholder="anaheim" /></div>
        </div>

        {errMsg && <div style={{ fontSize: 12, color: '#b91c1c' }}>{errMsg}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={btn('#fff', '#64748b')}>Cancel</button>
          <button onClick={() => add.mutate()} disabled={!headline.trim() || add.isPending}
                  style={btn(!headline.trim() ? '#e2e8f0' : ACCENT, !headline.trim() ? '#94a3b8' : '#fff')}>
            {add.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add project
          </button>
        </div>
      </div>
    </div>
  )
}

// One project photo: uploaded or pasted-then-rehosted, so the URL committed to
// the site is always a stable self-hosted asset. Its own component so each row
// owns its upload/fetch state independently.
const PHOTO_ERRORS: Record<string, string> = {
  unsupported_image_type: 'Use a JPG, PNG, or WebP image.',
  image_too_large: 'That image is over 15 MB. Use a smaller file.',
  image_dimensions_too_small: 'That image is too small — use at least 200×200px.',
  invalid_image: 'That file isn’t a readable image.',
  empty_image: 'That file is empty.',
  invalid_image_url: 'Enter a valid http(s) image URL.',
  image_fetch_failed: 'Couldn’t fetch that URL. Check it’s public and try again.',
  image_upload_failed: 'Upload failed — try again.',
}

function ProjectPhotoRow({ websiteId, photo, onChange, onRemove }: {
  websiteId: string
  photo: PhotoRow
  onChange: (p: PhotoRow) => void
  onRemove: () => void
}) {
  const [urlInput, setUrlInput] = useState('')
  const upload = useMutation({
    mutationFn: (file: File) => { const f = new FormData(); f.append('file', file); return api.upload<{ url: string }>(`/websites/${websiteId}/photo`, f) },
    onSuccess: (r) => onChange({ ...photo, url: r.url }),
  })
  const fromUrl = useMutation({
    mutationFn: (u: string) => api.post<{ url: string }>(`/websites/${websiteId}/photo-from-url`, { url: u }),
    onSuccess: (r) => { onChange({ ...photo, url: r.url }); setUrlInput('') },
  })
  const busy = upload.isPending || fromUrl.isPending
  const err = (upload.error || fromUrl.error) as Error | undefined

  return (
    <div style={{ display: 'grid', gap: 6, marginBottom: 8, padding: 8, background: '#f8fafc', borderRadius: 8 }}>
      {photo.url ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <img src={photo.url} alt="" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0' }} />
          <div style={{ flex: 1, fontSize: 11, color: '#16a34a' }}>Hosted on the site ✓</div>
          <button onClick={() => onChange({ ...photo, url: '' })} style={{ ...btn('#fff', '#64748b'), padding: '4px 8px', fontSize: 12 }}>Replace</button>
          <button onClick={onRemove} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 6 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <label style={{ ...btn('#fff', ACCENT), cursor: busy ? 'wait' : 'pointer', padding: '6px 10px', fontSize: 12 }}>
              <Upload size={13} /> {upload.isPending ? 'Uploading…' : 'Upload photo'}
              <input type="file" accept="image/jpeg,image/png,image/webp" hidden
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f) }} />
            </label>
            <span style={{ fontSize: 11, color: '#94a3b8' }}>or paste a URL</span>
            <button onClick={onRemove} style={{ ...btn('#fff', '#64748b'), padding: 6, marginLeft: 'auto' }}><X size={13} /></button>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input value={urlInput} onChange={(e) => setUrlInput(e.target.value)} placeholder="https://…/photo.jpg" style={{ ...input, flex: 1 }} />
            <button onClick={() => { const u = urlInput.trim(); if (u) fromUrl.mutate(u) }} disabled={!urlInput.trim() || busy}
                    style={{ ...btn(!urlInput.trim() || busy ? '#e2e8f0' : '#fff', !urlInput.trim() || busy ? '#94a3b8' : ACCENT), padding: '6px 10px', fontSize: 12 }}>
              {fromUrl.isPending ? <Loader2 size={13} className="spin" /> : 'Fetch'}
            </button>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={photo.alt} placeholder="Alt text" onChange={(e) => onChange({ ...photo, alt: e.target.value })} style={input} />
        <input value={photo.caption} placeholder="Caption (optional)" onChange={(e) => onChange({ ...photo, caption: e.target.value })} style={input} />
      </div>
      {err && <div style={{ fontSize: 11, color: '#b91c1c' }}>{PHOTO_ERRORS[err.message] ?? err.message}</div>}
    </div>
  )
}

// --- Add offers / specials -----------------------------------------------

interface OfferRow { title: string; value: string; terms: string; expiry: string; cta_label: string; cta_href: string }

const SINGLETON_ADD_ERRORS: Record<string, string> = {
  reserved_slug: 'That URL collides with a reserved page.',
  page_route_exists: 'This site already has that page.',
}

function OffersModal({ websiteId, onClose, onDone }: { websiteId: string; onClose: () => void; onDone: () => void }) {
  const [intro, setIntro] = useState('')
  const [financing, setFinancing] = useState('')
  const [finePrint, setFinePrint] = useState('')
  const [offers, setOffers] = useState<OfferRow[]>([{ title: '', value: '', terms: '', expiry: '', cta_label: '', cta_href: '' }])

  const cleanOffers = offers.filter((o) => o.title.trim())

  const add = useMutation({
    mutationFn: () => api.post(`/websites/${websiteId}/pages`, {
      page_type: 'offers',
      offers: {
        intro: intro || undefined,
        financing: financing || undefined,
        fine_print: finePrint || undefined,
        offers: cleanOffers,
      },
    }),
    onSuccess: onDone,
  })

  const errMsg = add.error ? (SINGLETON_ADD_ERRORS[(add.error as Error).message] ?? (add.error as Error).message) : null
  const ta: React.CSSProperties = { ...input, resize: 'vertical', minHeight: 52 }
  const rowStyle: React.CSSProperties = { display: 'flex', gap: 6, alignItems: 'center' }

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <strong style={{ fontSize: 15 }}>Add the offers / specials page</strong>
          <button onClick={onClose} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={15} /></button>
        </div>
        <div style={{ fontSize: 11, color: '#64748b' }}>
          One offers page per site, at <code>/specials/</code>. Every offer’s value, terms and expiry is
          what you enter — nothing is invented. Keep it current: expired offers left live are the one thing to avoid.
        </div>

        <div>
          <label style={label}>Intro (optional)</label>
          <textarea value={intro} onChange={(e) => setIntro(e.target.value)} rows={2} placeholder="A short lede for the page." style={ta} />
        </div>

        <div>
          <label style={label}>Offers</label>
          {offers.map((o, i) => (
            <div key={i} style={{ display: 'grid', gap: 4, marginBottom: 8, padding: 8, background: '#f8fafc', borderRadius: 8 }}>
              <div style={rowStyle}>
                <input value={o.title} placeholder="Title — e.g. $50 off first service"
                       onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} style={input} />
                <button onClick={() => setOffers(offers.filter((_, j) => j !== i))} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
              </div>
              <div style={rowStyle}>
                <input value={o.value} placeholder="Value — e.g. Save $50" onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} style={input} />
                <input value={o.expiry} placeholder="Expiry — e.g. Dec 31, 2026" onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, expiry: e.target.value } : x))} style={input} />
              </div>
              <input value={o.terms} placeholder="Terms — e.g. New customers only, one per household" onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, terms: e.target.value } : x))} style={input} />
              <div style={rowStyle}>
                <input value={o.cta_label} placeholder="Button label (optional)" onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, cta_label: e.target.value } : x))} style={input} />
                <input value={o.cta_href} placeholder="Button link (optional) — /contact-us/" onChange={(e) => setOffers(offers.map((x, j) => j === i ? { ...x, cta_href: e.target.value } : x))} style={input} />
              </div>
            </div>
          ))}
          <button onClick={() => setOffers([...offers, { title: '', value: '', terms: '', expiry: '', cta_label: '', cta_href: '' }])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
            <Plus size={12} /> Add offer
          </button>
        </div>

        <div>
          <label style={label}>Financing block (optional)</label>
          <textarea value={financing} onChange={(e) => setFinancing(e.target.value)} rows={2} placeholder="Financing options you offer." style={ta} />
        </div>
        <div>
          <label style={label}>Fine print (optional)</label>
          <textarea value={finePrint} onChange={(e) => setFinePrint(e.target.value)} rows={2} placeholder="Disclaimers and conditions." style={ta} />
        </div>

        {errMsg && <div style={{ fontSize: 12, color: '#b91c1c' }}>{errMsg}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={btn('#fff', '#64748b')}>Cancel</button>
          <button onClick={() => add.mutate()} disabled={cleanOffers.length === 0 || add.isPending}
                  title={cleanOffers.length === 0 ? 'Add at least one offer with a title.' : 'Adds the offers page as a draft.'}
                  style={btn(cleanOffers.length === 0 ? '#e2e8f0' : ACCENT, cleanOffers.length === 0 ? '#94a3b8' : '#fff')}>
            {add.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add offers page
          </button>
        </div>
      </div>
    </div>
  )
}

// --- Add warranty / guarantee ---------------------------------------------

interface CoverageRow { item: string; detail: string; duration: string }
interface FaqRow { q: string; a: string }

function WarrantyModal({ websiteId, onClose, onDone }: { websiteId: string; onClose: () => void; onDone: () => void }) {
  const [headline, setHeadline] = useState('')
  const [promise, setPromise] = useState('')
  const [explainer, setExplainer] = useState('')
  const [coverage, setCoverage] = useState<CoverageRow[]>([{ item: '', detail: '', duration: '' }])
  const [steps, setSteps] = useState<string[]>([''])
  const [faq, setFaq] = useState<FaqRow[]>([{ q: '', a: '' }])

  const cleanCoverage = coverage.filter((c) => c.item.trim())
  const cleanSteps = steps.map((s) => s.trim()).filter(Boolean)
  const cleanFaq = faq.filter((f) => f.q.trim() && f.a.trim())
  const canAdd = Boolean(promise.trim()) || cleanCoverage.length > 0

  const add = useMutation({
    mutationFn: () => api.post(`/websites/${websiteId}/pages`, {
      page_type: 'warranty',
      title: headline || undefined,
      warranty: {
        headline: headline || undefined,
        promise: promise || undefined,
        manufacturer_vs_workmanship: explainer || undefined,
        coverage: cleanCoverage,
        claim_steps: cleanSteps,
        faq: cleanFaq,
      },
    }),
    onSuccess: onDone,
  })

  const errMsg = add.error ? (SINGLETON_ADD_ERRORS[(add.error as Error).message] ?? (add.error as Error).message) : null
  const ta: React.CSSProperties = { ...input, resize: 'vertical', minHeight: 52 }
  const rowStyle: React.CSSProperties = { display: 'flex', gap: 6, alignItems: 'center' }

  return (
    <div onClick={onClose} style={overlay}>
      <div onClick={(e) => e.stopPropagation()} style={{ ...card, width: 560, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto', display: 'grid', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <strong style={{ fontSize: 15 }}>Add the warranty / guarantee page</strong>
          <button onClick={onClose} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={15} /></button>
        </div>
        <div style={{ fontSize: 11, color: '#64748b' }}>
          One warranty page per site, at <code>/warranty/</code>. Coverage terms, claim steps and FAQ answers are
          facts you enter (get legal sign-off). Only the promise and the manufacturer-vs-workmanship explainer are
          rewritten into plain prose — never the terms, and never overpromised.
        </div>

        <Field label="Headline" value={headline} onChange={setHeadline} placeholder="Our 100% workmanship guarantee" />
        <div>
          <label style={label}>The promise (plain language)</label>
          <textarea value={promise} onChange={(e) => setPromise(e.target.value)} rows={2} placeholder="What you guarantee, stated plainly and up front." style={ta} />
        </div>

        <div>
          <label style={label}>Coverage</label>
          {coverage.map((c, i) => (
            <div key={i} style={{ ...rowStyle, marginBottom: 6 }}>
              <input value={c.item} placeholder="Item — e.g. Workmanship" onChange={(e) => setCoverage(coverage.map((x, j) => j === i ? { ...x, item: e.target.value } : x))} style={input} />
              <input value={c.detail} placeholder="Details" onChange={(e) => setCoverage(coverage.map((x, j) => j === i ? { ...x, detail: e.target.value } : x))} style={input} />
              <input value={c.duration} placeholder="Coverage — e.g. 10 years" onChange={(e) => setCoverage(coverage.map((x, j) => j === i ? { ...x, duration: e.target.value } : x))} style={input} />
              <button onClick={() => setCoverage(coverage.filter((_, j) => j !== i))} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
            </div>
          ))}
          <button onClick={() => setCoverage([...coverage, { item: '', detail: '', duration: '' }])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
            <Plus size={12} /> Add coverage row
          </button>
        </div>

        <div>
          <label style={label}>Claim process (steps)</label>
          {steps.map((s, i) => (
            <div key={i} style={{ ...rowStyle, marginBottom: 6 }}>
              <input value={s} placeholder={`Step ${i + 1}`} onChange={(e) => setSteps(steps.map((x, j) => j === i ? e.target.value : x))} style={input} />
              <button onClick={() => setSteps(steps.filter((_, j) => j !== i))} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
            </div>
          ))}
          <button onClick={() => setSteps([...steps, ''])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
            <Plus size={12} /> Add step
          </button>
        </div>

        <div>
          <label style={label}>Manufacturer vs. workmanship (optional)</label>
          <textarea value={explainer} onChange={(e) => setExplainer(e.target.value)} rows={2} placeholder="What the manufacturer covers vs. what your workmanship covers." style={ta} />
        </div>

        <div>
          <label style={label}>FAQ (optional)</label>
          {faq.map((f, i) => (
            <div key={i} style={{ display: 'grid', gap: 4, marginBottom: 8, padding: 8, background: '#f8fafc', borderRadius: 8 }}>
              <div style={rowStyle}>
                <input value={f.q} placeholder="Question" onChange={(e) => setFaq(faq.map((x, j) => j === i ? { ...x, q: e.target.value } : x))} style={input} />
                <button onClick={() => setFaq(faq.filter((_, j) => j !== i))} style={{ ...btn('#fff', '#64748b'), padding: 6 }}><X size={13} /></button>
              </div>
              <textarea value={f.a} placeholder="Answer" rows={2} onChange={(e) => setFaq(faq.map((x, j) => j === i ? { ...x, a: e.target.value } : x))} style={ta} />
            </div>
          ))}
          <button onClick={() => setFaq([...faq, { q: '', a: '' }])} style={{ ...btn('#fff', ACCENT), padding: '4px 8px', fontSize: 12 }}>
            <Plus size={12} /> Add question
          </button>
        </div>

        {errMsg && <div style={{ fontSize: 12, color: '#b91c1c' }}>{errMsg}</div>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button onClick={onClose} style={btn('#fff', '#64748b')}>Cancel</button>
          <button onClick={() => add.mutate()} disabled={!canAdd || add.isPending}
                  title={!canAdd ? 'Enter a promise or at least one coverage row.' : 'Adds the warranty page as a draft.'}
                  style={btn(!canAdd ? '#e2e8f0' : ACCENT, !canAdd ? '#94a3b8' : '#fff')}>
            {add.isPending ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add warranty page
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
