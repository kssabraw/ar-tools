import { useState, useEffect } from 'react'
import { useNavigate, useParams, Link, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client, GbpProfile, PageStructureType, PageStructureEntry } from '../lib/types'
import { ArrowLeft, Check, Image as ImageIcon, RefreshCw } from 'lucide-react'
import { GbpPicker } from '../components/GbpPicker'

interface FormData {
  name: string
  website_url: string
  brand_guide_text: string
  icp_text: string
  google_drive_folder_id: string
  df_blog_post: string
  df_service_page: string
  df_location_page: string
  df_local_seo_page: string
  df_ecom_page: string
  df_use_case: string
  github_repo: string
  github_branch: string
  github_content_path: string
  wordpress_site_url: string
  wordpress_username: string
  wordpress_app_password: string
  wordpress_app_password_set: boolean
  logo_url: string
  gsc_property: string
  business_location: string
  target_cities: string
  gbp_place_id: string | null
  gbp: GbpProfile | null
  ps_local_landing: string
  ps_service: string
  ps_location: string
  ps_blog_post: string
  ps_product: string
  ps_solution: string
}

const empty: FormData = {
  name: '', website_url: '', brand_guide_text: '', icp_text: '', google_drive_folder_id: '',
  df_blog_post: '', df_service_page: '', df_location_page: '', df_local_seo_page: '', df_ecom_page: '', df_use_case: '',
  github_repo: '', github_branch: '', github_content_path: '',
  wordpress_site_url: '', wordpress_username: '', wordpress_app_password: '', wordpress_app_password_set: false,
  logo_url: '', gsc_property: '', business_location: '', target_cities: '', gbp_place_id: null, gbp: null,
  ps_local_landing: '', ps_service: '', ps_location: '', ps_blog_post: '', ps_product: '', ps_solution: '',
}

// Per-content-type Drive folders. `type` is the backend content_type slug used
// as the drive_folders map key. Reserved types have no generator yet — the
// folder is captured now so it's ready when the module ships.
const DRIVE_FOLDER_FIELDS: { key: keyof FormData; type: string; label: string; reserved?: boolean }[] = [
  { key: 'df_blog_post', type: 'blog_post', label: 'Blog posts' },
  { key: 'df_service_page', type: 'service_page', label: 'Service pages' },
  { key: 'df_location_page', type: 'location_page', label: 'Location pages' },
  { key: 'df_local_seo_page', type: 'local_seo_page', label: 'Local SEO pages' },
  { key: 'df_ecom_page', type: 'ecom_page', label: 'Ecom pages', reserved: true },
  { key: 'df_use_case', type: 'use_case', label: 'Use cases', reserved: true },
]

const PAGE_STRUCTURE_FIELDS: { key: keyof FormData; type: PageStructureType; label: string; placeholder: string; help: string }[] = [
  { key: 'ps_local_landing', type: 'local_landing', label: 'Local Landing Page URL', placeholder: 'https://acmehvac.com/ac-repair-austin', help: 'A service-in-location landing page. Used by Local SEO page generation.' },
  { key: 'ps_service', type: 'service', label: 'Service Page URL', placeholder: 'https://acmehvac.com/services/ac-repair', help: 'A core service page. Used by the Service Page writer.' },
  { key: 'ps_location', type: 'location', label: 'Location Page URL', placeholder: 'https://acmehvac.com/locations/austin', help: 'An area-served / location page. Used by Local SEO page generation.' },
  { key: 'ps_blog_post', type: 'blog_post', label: 'Blog Post URL', placeholder: 'https://acmehvac.com/blog/why-ac-fails', help: "A representative blog post. The Blog Writer mirrors its opening pattern." },
  { key: 'ps_product', type: 'product', label: 'Product Page URL', placeholder: 'https://acmestore.com/products/widget', help: 'A representative product page (ecom). Scraped and stored for reference; not yet mirrored by a writer.' },
  { key: 'ps_solution', type: 'solution', label: 'Solutions Page URL', placeholder: 'https://acmestore.com/solutions/keep-coffee-hot', help: 'A solutions page that frames a problem the product solves (ecom). Scraped and stored for reference; not yet mirrored by a writer.' },
]

export function ClientForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id?: string }>()
  const { hash } = useLocation()
  const isEdit = Boolean(id)
  const qc = useQueryClient()
  const [form, setForm] = useState<FormData>(empty)
  const [saving, setSaving] = useState(false)
  const [logoUploading, setLogoUploading] = useState(false)
  const [logoError, setLogoError] = useState<string | null>(null)

  async function handleLogoSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file after an error
    if (!file) return
    if (file.type !== 'image/jpeg' && file.type !== 'image/png') {
      setLogoError('Logo must be a JPG or PNG image.')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      setLogoError('Logo must be under 2 MB.')
      return
    }
    setLogoError(null)
    setLogoUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.upload<{ logo_url: string }>('/files/logo', fd)
      setForm(f => ({ ...f, logo_url: res.logo_url }))
    } catch (err) {
      setLogoError((err as Error).message || 'Upload failed.')
    } finally {
      setLogoUploading(false)
    }
  }

  const { data: existing, isLoading } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: isEdit,
  })

  // Deep-link support (e.g. /clients/:id/edit#gbp from the workspace) —
  // scroll the targeted section into view once it has rendered.
  useEffect(() => {
    if (!hash) return
    if (isEdit && isLoading) return
    const el = document.getElementById(hash.slice(1))
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [hash, isEdit, isLoading])

  useEffect(() => {
    if (existing) {
      setForm({
        name: existing.name,
        website_url: existing.website_url,
        brand_guide_text: existing.brand_guide_text ?? '',
        icp_text: existing.icp_text ?? '',
        google_drive_folder_id: existing.google_drive_folder_id ?? '',
        df_blog_post: existing.drive_folders?.blog_post ?? '',
        df_service_page: existing.drive_folders?.service_page ?? '',
        df_location_page: existing.drive_folders?.location_page ?? '',
        df_local_seo_page: existing.drive_folders?.local_seo_page ?? '',
        df_ecom_page: existing.drive_folders?.ecom_page ?? '',
        df_use_case: existing.drive_folders?.use_case ?? '',
        github_repo: existing.github_repo ?? '',
        github_branch: existing.github_branch ?? '',
        github_content_path: existing.github_content_path ?? '',
        wordpress_site_url: existing.wordpress_site_url ?? '',
        wordpress_username: existing.wordpress_username ?? '',
        wordpress_app_password: '',
        wordpress_app_password_set: existing.wordpress_app_password_set ?? false,
        logo_url: existing.logo_url ?? '',
        gsc_property: existing.gsc_property ?? '',
        business_location: existing.business_location ?? '',
        target_cities: (existing.target_cities ?? []).join(', '),
        gbp_place_id: existing.gbp_place_id,
        gbp: existing.gbp,
        ps_local_landing: existing.page_structures?.local_landing?.url ?? '',
        ps_service: existing.page_structures?.service?.url ?? '',
        ps_location: existing.page_structures?.location?.url ?? '',
        ps_blog_post: existing.page_structures?.blog_post?.url ?? '',
        ps_product: existing.page_structures?.product?.url ?? '',
        ps_solution: existing.page_structures?.solution?.url ?? '',
      })
    }
  }, [existing])

  const createMutation = useMutation({
    mutationFn: (body: object) => api.post('/clients', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clients'] }); navigate('/clients') },
  })

  const updateMutation = useMutation({
    mutationFn: (body: object) => api.patch(`/clients/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clients'] })
      qc.invalidateQueries({ queryKey: ['client', id] })
      navigate('/clients')
    },
  })

  const error = createMutation.error ?? updateMutation.error

  // Force a fresh scrape + analysis of an already-stored reference URL (e.g. the
  // client redesigned that page). Create/update only re-scrape when a URL changes.
  const reanalyzeMutation = useMutation({
    mutationFn: (type: PageStructureType) =>
      api.post(`/clients/${id}/page-structures/reanalyze?page_type=${type}`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['client', id] }) },
  })

  function set(field: keyof FormData) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload = {
        name: form.name,
        website_url: form.website_url,
        brand_guide_source_type: 'text',
        brand_guide_text: form.brand_guide_text,
        icp_source_type: 'text',
        icp_text: form.icp_text,
        google_drive_folder_id: form.google_drive_folder_id || null,
        // Merge the form's known per-type folders onto the existing map so keys
        // we don't render (e.g. a content type added later) are preserved, not
        // dropped. Blank fields clear their key.
        drive_folders: (() => {
          const merged: Record<string, string> = { ...(existing?.drive_folders ?? {}) }
          for (const f of DRIVE_FOLDER_FIELDS) {
            const v = (form[f.key] as string).trim()
            if (v) merged[f.type] = v
            else delete merged[f.type]
          }
          return merged
        })(),
        github_repo: form.github_repo || null,
        github_branch: form.github_branch || null,
        github_content_path: form.github_content_path || null,
        wordpress_site_url: form.wordpress_site_url.trim() || null,
        wordpress_username: form.wordpress_username.trim() || null,
        // Only send the password when the user typed a new one; an empty field
        // leaves the stored secret untouched (omit the key entirely).
        ...(form.wordpress_app_password ? { wordpress_app_password: form.wordpress_app_password } : {}),
        logo_url: form.logo_url || null,
        gsc_property: form.gsc_property || null,
        business_location: form.business_location || null,
        target_cities: form.target_cities.split(',').map(s => s.trim()).filter(Boolean),
        gbp_place_id: form.gbp_place_id,
        gbp: form.gbp,
        page_structure_urls: {
          local_landing: form.ps_local_landing.trim() || null,
          service: form.ps_service.trim() || null,
          location: form.ps_location.trim() || null,
          blog_post: form.ps_blog_post.trim() || null,
          product: form.ps_product.trim() || null,
          solution: form.ps_solution.trim() || null,
        },
      }
      if (isEdit) {
        await updateMutation.mutateAsync(payload)
      } else {
        await createMutation.mutateAsync(payload)
      }
    } finally {
      setSaving(false)
    }
  }

  if (isEdit && isLoading) return <div style={{ padding: 40, color: '#64748b' }}>Loading…</div>

  return (
    <div style={{ padding: 32, maxWidth: 760 }}>
      <Link
        to="/clients"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 24 }}
      >
        <ArrowLeft size={14} /> Back to Clients
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 8px' }}>
        {isEdit ? `Edit ${existing?.name ?? 'Client'}` : 'New Client'}
      </h1>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 10px' }}>
        {isEdit
          ? "Update the client's details. Changes apply to future runs — existing runs keep the snapshot that was taken when they started."
          : "Fill in the client's details. The brand guide and ICP are used by the AI to match the client's voice and audience on every content run."}
      </p>
      <p style={{ fontSize: 12, color: '#94a3b8', margin: '0 0 32px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <ParkedBadge /> marks a field that's saved now but not read by any module yet — it activates when that feature ships. Everything else is used as soon as you save.
      </p>

      <form onSubmit={handleSubmit}>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Basic Info</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px 24px' }}>
            <div>
              <label style={labelStyle}>Client Name *</label>
              <input
                value={form.name}
                onChange={set('name')}
                required
                placeholder="e.g. Acme HVAC"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <div>
              <label style={labelStyle}>Website URL *</label>
              <input
                type="url"
                value={form.website_url}
                onChange={set('website_url')}
                required
                placeholder="https://acmehvac.com"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
              <p style={hintStyle}>
                {isEdit ? 'Changing the URL will trigger a new website analysis.' : 'We\'ll automatically analyze this homepage to extract services and locations.'}
              </p>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <label style={labelStyle}>Logo</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              {form.logo_url ? (
                <img
                  src={form.logo_url}
                  alt="Logo preview"
                  style={{ width: 56, height: 56, borderRadius: 10, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0', flexShrink: 0 }}
                />
              ) : (
                <div style={logoPlaceholder}>
                  <ImageIcon size={20} />
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <label style={{ ...uploadBtnStyle, ...(logoUploading ? { opacity: 0.6, cursor: 'default' } : {}) }}>
                    {logoUploading ? 'Uploading…' : form.logo_url ? 'Replace' : 'Upload logo'}
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      onChange={handleLogoSelect}
                      disabled={logoUploading}
                      style={{ display: 'none' }}
                    />
                  </label>
                  {form.logo_url && !logoUploading && (
                    <button
                      type="button"
                      onClick={() => { setForm(f => ({ ...f, logo_url: '' })); setLogoError(null) }}
                      style={removeBtnStyle}
                    >
                      Remove
                    </button>
                  )}
                </div>
                <p style={hintStyle}>Optional. JPG or PNG, up to 2 MB. Shown on this client's tile and workspace.</p>
              </div>
            </div>
            {logoError && <p style={{ ...hintStyle, color: '#dc2626' }}>{logoError}</p>}
          </div>
        </div>

        <div id="gbp" style={sectionStyle}>
          <h2 style={sectionTitle}>Google Business Profile</h2>
          <p style={descStyle}>
            Optional. Search Google to attach this client's business listing — address, category, rating, and top reviews. Shown on the client's workspace and used today by local-SEO content generation, brand-voice distillation, and keyword market analysis.
          </p>
          <GbpPicker
            placeId={form.gbp_place_id}
            profile={form.gbp}
            onChange={(gbp_place_id, gbp) =>
              setForm(f => ({
                ...f,
                gbp_place_id,
                gbp,
                // Auto-fill from the GBP, but only into empty fields so we
                // never overwrite something the user already typed.
                name: f.name.trim() === '' && gbp?.business_name ? gbp.business_name : f.name,
                website_url:
                  f.website_url.trim() === '' && gbp?.website ? gbp.website : f.website_url,
              }))
            }
          />
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Brand Guide</h2>
          <p style={descStyle}>
            Paste anything that describes how this client communicates — tone of voice guidelines, brand positioning, writing style rules, words to avoid, or sample copy. The more detail you provide, the more on-brand the generated content will be.
          </p>
          <label style={labelStyle}>Brand Guide Text</label>
          <textarea
            value={form.brand_guide_text}
            onChange={set('brand_guide_text')}
            rows={10}
            placeholder={`Examples of what to include:\n• Tone: approachable, confident, never pushy\n• We use "home comfort" not "HVAC"\n• Avoid technical jargon — write for homeowners, not technicians\n• Always emphasize reliability and local expertise\n• Use short sentences. Active voice.`}
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical', lineHeight: 1.6 }}
          />
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Ideal Customer Profile (ICP)</h2>
          <p style={descStyle}>
            Describe who this client's content is written for. Include demographics, pain points, what they care about, what triggers them to search, and what objections they have.
          </p>
          <label style={labelStyle}>ICP Text</label>
          <textarea
            value={form.icp_text}
            onChange={set('icp_text')}
            rows={8}
            placeholder={`Examples of what to include:\n• Homeowners aged 35–65, own their home for 5+ years\n• Concerned about unexpected repair costs and energy bills\n• Search when something breaks or before summer/winter\n• Trust local companies with reviews over national chains\n• Objections: "Can I trust them?" and "Is it worth the cost?"`}
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical', lineHeight: 1.6 }}
          />
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Search Console &amp; Local Rankings</h2>
          <div style={{ marginBottom: 16 }}>
            <div style={titleRow}>
              <label style={{ ...labelStyle, margin: 0 }}>Search Console Property</label>
              <ParkedBadge />
            </div>
            <input
              value={form.gsc_property}
              onChange={set('gsc_property')}
              placeholder="sc-domain:acmehvac.com  (or  https://acmehvac.com/)"
              style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace', marginTop: 6 }}
            />
            <p style={hintStyle}>
              The property exactly as it appears in Search Console. Not read yet — the rank tracker registers GSC properties separately from each client's workspace. Make sure the agency service account is added as a user on that property so we can pull clicks &amp; impressions.
            </p>
          </div>
          <div>
            <label style={labelStyle}>Primary Business Location</label>
            <input
              value={form.business_location}
              onChange={set('business_location')}
              placeholder="e.g. 123 Main St, Austin, TX 78701"
              style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
            />
            <p style={hintStyle}>Used today as the business address for local-SEO page generation when no Google Business Profile is attached.</p>
          </div>
          <div>
            <label style={labelStyle}>Target Cities</label>
            <input
              value={form.target_cities}
              onChange={set('target_cities')}
              placeholder="e.g. Parramatta, Penrith, Liverpool"
              style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
            />
            <p style={hintStyle}>Comma-separated. Extra cities the Local SEO silo planner should build location pages for, beyond the seed city. The planner also pulls cities from the GBP service area, this client's own site, and a ~10-mile radius — these are added on top.</p>
          </div>
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Reference Page Structures</h2>
          <p style={descStyle}>
            Optional. Paste one example URL per page type. We scrape and analyze each page's
            structure — ignoring nav, sidebars, footers, and popups — and store the layout so the
            writing modules can mirror how this client structures their own pages. We re-analyze a
            URL whenever you change it; use <strong>Re-analyze</strong> to refresh a stored URL whose
            page has since changed.
          </p>
          {PAGE_STRUCTURE_FIELDS.map(({ key, type, label, placeholder, help }) => {
            const entry = existing?.page_structures?.[type]
            const trimmed = (form[key] as string).trim()
            // Re-analyze applies to the STORED url — only offer it when the typed
            // value matches what's stored (no unsaved edit) and it's not already
            // mid-analysis.
            const canReanalyze = isEdit && !!entry?.url && entry.url === trimmed && entry.status !== 'pending'
            const rowReanalyzing = reanalyzeMutation.isPending && reanalyzeMutation.variables === type
            return (
              <div key={type} style={{ marginBottom: 16 }}>
                <div style={titleRow}>
                  <label style={{ ...labelStyle, margin: 0 }}>{label}</label>
                  {isEdit && <PageStructureStatus entry={entry} url={form[key] as string} />}
                  {(canReanalyze || rowReanalyzing) && (
                    <button
                      type="button"
                      onClick={() => reanalyzeMutation.mutate(type)}
                      disabled={rowReanalyzing}
                      style={{ ...reanalyzeBtnStyle, ...(rowReanalyzing ? { opacity: 0.6, cursor: 'default' } : {}) }}
                    >
                      <RefreshCw size={12} /> {rowReanalyzing ? 'Re-analyzing…' : 'Re-analyze'}
                    </button>
                  )}
                </div>
                <input
                  type="url"
                  value={form[key] as string}
                  onChange={set(key)}
                  placeholder={placeholder}
                  style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', marginTop: 6 }}
                />
                <p style={hintStyle}>{help}</p>
              </div>
            )
          })}
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Google Drive Publishing</h2>
          <p style={descStyle}>
            Optional. Paste this client's Google Drive folder ID to enable one-click publishing of finished articles into their folder.
          </p>
          <label style={labelStyle}>Drive Folder ID</label>
          <input
            value={form.google_drive_folder_id}
            onChange={set('google_drive_folder_id')}
            placeholder="1aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
          />
          <p style={hintStyle}>
            Find the ID in the folder's URL — the part after <code>/folders/</code>. Make sure your Apps Script account has Editor access.
          </p>

          <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
            <label style={{ ...labelStyle, fontWeight: 600 }}>Per-content-type folders (optional)</label>
            <p style={hintStyle}>
              Route each content type to its own folder. Leave a field blank to fall back to the default folder above.
            </p>
            {DRIVE_FOLDER_FIELDS.map(({ key, label, reserved }) => (
              <div key={key} style={{ marginTop: 12 }}>
                <label style={labelStyle}>
                  {label}{reserved && <span style={{ color: '#94a3b8', fontWeight: 400 }}> — reserved (no generator yet)</span>}
                </label>
                <input
                  value={form[key] as string}
                  onChange={set(key)}
                  placeholder="Folder ID (blank = use default folder)"
                  style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
                />
              </div>
            ))}
          </div>
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>WordPress Publishing</h2>
          <p style={descStyle}>
            Optional. Publish finished articles and pages straight to this client's WordPress site using an{' '}
            <strong>Application Password</strong> (WordPress 5.6+, no plugin). In WP admin go to{' '}
            <code>Users → Profile → Application Passwords</code>, create one, and paste it below.
          </p>
          <label style={labelStyle}>Site URL</label>
          <input
            type="url"
            value={form.wordpress_site_url}
            onChange={set('wordpress_site_url')}
            placeholder="https://acmehvac.com"
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
          />
          <p style={hintStyle}>The site root (must be HTTPS). The REST endpoint <code>/wp-json/wp/v2</code> is derived from it.</p>
          <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Username</label>
              <input
                value={form.wordpress_username}
                onChange={set('wordpress_username')}
                placeholder="editor"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Application Password</label>
              <input
                type="password"
                value={form.wordpress_app_password}
                onChange={set('wordpress_app_password')}
                placeholder={form.wordpress_app_password_set ? '•••• stored — type to replace' : 'xxxx xxxx xxxx xxxx xxxx xxxx'}
                autoComplete="new-password"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
            </div>
          </div>
          <p style={hintStyle}>
            {form.wordpress_app_password_set
              ? 'A password is stored. Leave blank to keep it, or type a new one to replace it.'
              : 'Stored securely and never shown again. Spaces are fine — paste it exactly as WordPress displays it.'}
          </p>
        </div>

        <div style={sectionStyle}>
          <div style={titleRow}>
            <h2 style={{ ...sectionTitle, margin: 0 }}>GitHub Publishing</h2>
            <ParkedBadge />
          </div>
          <p style={descStyle}>
            Optional. Where this client's generated articles get committed when published to a repo (Astro content). Saved on the client now, but the publish endpoints don't read it yet — it activates when GitHub publishing for the Content Scheduler / Topic Fanout tool ships.
          </p>
          <label style={labelStyle}>Repository</label>
          <input
            value={form.github_repo}
            onChange={set('github_repo')}
            placeholder="owner/repo"
            style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
          />
          <div style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Branch</label>
              <input
                value={form.github_branch}
                onChange={set('github_branch')}
                placeholder="main"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
            </div>
            <div style={{ flex: 2 }}>
              <label style={labelStyle}>Content path</label>
              <input
                value={form.github_content_path}
                onChange={set('github_content_path')}
                placeholder="src/content/blog"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
            </div>
          </div>
        </div>

        {error && (
          <div style={{ marginBottom: 20, padding: '12px 16px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
            {(error as Error).message}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10 }}>
          <button type="submit" disabled={saving} style={primaryBtn}>
            <Check size={15} /> {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Save Client'}
          </button>
          <Link to="/clients" style={ghostBtn}>Cancel</Link>
        </div>

      </form>
    </div>
  )
}

function PageStructureStatus({ entry, url }: { entry?: PageStructureEntry; url: string }) {
  const trimmed = url.trim()
  // Pending save: the typed URL differs from what's stored (or nothing stored yet).
  if (!entry?.url || entry.url !== trimmed) {
    if (!trimmed) return null
    return <span style={{ ...psBadge, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0' }}>Analyzes on save</span>
  }
  if (entry.status === 'pending')
    return <span style={{ ...psBadge, color: '#92400e', background: '#fef3c7', border: '1px solid #fde68a' }}>Analyzing…</span>
  if (entry.status === 'complete')
    return <span style={{ ...psBadge, color: '#166534', background: '#dcfce7', border: '1px solid #bbf7d0' }}>Analyzed</span>
  return (
    <span
      style={{ ...psBadge, color: '#dc2626', background: '#fef2f2', border: '1px solid #fecaca' }}
      title={entry.error ?? undefined}
    >
      Failed
    </span>
  )
}

function ParkedBadge() {
  return (
    <span
      style={parkedBadge}
      title="Saved now — activated when the module that uses it ships."
    >
      Roadmap
    </span>
  )
}

const sectionStyle: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 24, marginBottom: 20 }
const titleRow: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }
const parkedBadge: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', fontSize: 11, fontWeight: 600, color: '#92400e', background: '#fef3c7', border: '1px solid #fde68a', borderRadius: 999, padding: '2px 9px', lineHeight: 1.4, whiteSpace: 'nowrap' }
const psBadge: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', fontSize: 11, fontWeight: 600, borderRadius: 999, padding: '2px 9px', lineHeight: 1.4, whiteSpace: 'nowrap' }
const reanalyzeBtnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px', background: '#fff', color: '#4f46e5', border: '1px solid #c7d2fe', borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: 'pointer' }
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#0f172a', margin: '0 0 4px' }
const descStyle: React.CSSProperties = { fontSize: 13, color: '#64748b', margin: '0 0 16px', lineHeight: 1.6 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 6 }
const hintStyle: React.CSSProperties = { fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }
const inputStyle: React.CSSProperties = { padding: '9px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a', fontFamily: 'inherit' }
const logoPlaceholder: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'center', width: 56, height: 56, borderRadius: 10, background: '#f1f5f9', border: '1px dashed #cbd5e1', color: '#94a3b8', flexShrink: 0 }
const uploadBtnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 14px', background: '#fff', color: '#374151', border: '1px solid #d1d5db', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const removeBtnStyle: React.CSSProperties = { padding: '7px 12px', background: '#fff', color: '#dc2626', border: '1px solid #fecaca', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '9px 18px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '9px 18px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 14, textDecoration: 'none' }
