import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams, Link, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client, GbpProfile, PageStructureType, PageStructureEntry, EverhourStatus, EverhourProject } from '../lib/types'
import { ArrowLeft, Check, Image as ImageIcon, RefreshCw, Upload } from 'lucide-react'
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
  gh_blog_post: string
  gh_service_page: string
  gh_location_page: string
  wordpress_site_url: string
  wordpress_username: string
  wordpress_app_password: string
  wordpress_app_password_set: boolean
  wheelhouse_cpt_enabled: boolean
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
  // Per page type, which source configures it: a live URL we scrape, or written
  // guidelines we parse (for clients with no site to scrape). Only the active
  // source is submitted for a page type — the two are mutually exclusive server-side.
  ps_mode: Record<PageStructureType, 'url' | 'guidelines'>
  ps_guidelines: Record<PageStructureType, string>
  ps_filename: Record<PageStructureType, string>
  retainer_monthly: string
  is_sab: boolean
  illustrate_content: boolean
  client_type: 'local' | 'enterprise'
  strategist_weekday: string  // '' = global default, else '0'..'6'
  slack_channel_id: string  // '' = use the master PACE channel
  everhour_project_id: string  // '' = not mapped to an Everhour project
}

const PAGE_STRUCTURE_TYPES: PageStructureType[] = [
  'local_landing', 'service', 'location', 'blog_post', 'product', 'solution',
]

function emptyPsRecord<T>(value: T): Record<PageStructureType, T> {
  return Object.fromEntries(
    PAGE_STRUCTURE_TYPES.map(t => [t, value]),
  ) as Record<PageStructureType, T>
}

const empty: FormData = {
  name: '', website_url: '', brand_guide_text: '', icp_text: '', google_drive_folder_id: '',
  df_blog_post: '', df_service_page: '', df_location_page: '', df_local_seo_page: '', df_ecom_page: '', df_use_case: '',
  github_repo: '', github_branch: '', github_content_path: '',
  gh_blog_post: '', gh_service_page: '', gh_location_page: '',
  wordpress_site_url: '', wordpress_username: '', wordpress_app_password: '', wordpress_app_password_set: false,
  wheelhouse_cpt_enabled: false,
  logo_url: '', gsc_property: '', business_location: '', target_cities: '', gbp_place_id: null, gbp: null,
  ps_local_landing: '', ps_service: '', ps_location: '', ps_blog_post: '', ps_product: '', ps_solution: '',
  ps_mode: emptyPsRecord('url'), ps_guidelines: emptyPsRecord(''), ps_filename: emptyPsRecord(''),
  retainer_monthly: '', is_sab: false, illustrate_content: false, client_type: 'local', strategist_weekday: '',
  slack_channel_id: '',
  everhour_project_id: '',
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

// Per-content-type GitHub repo content paths. `type` is the backend content_type
// slug used as the github_content_paths map key; each overrides the single
// default path below for that type when set. Only the types the run-publish path
// commits to GitHub are rendered.
const GITHUB_PATH_FIELDS: { key: keyof FormData; type: string; label: string; placeholder: string }[] = [
  { key: 'gh_blog_post', type: 'blog_post', label: 'Blog posts', placeholder: 'src/content/blog' },
  { key: 'gh_service_page', type: 'service_page', label: 'Service pages', placeholder: 'src/content/services' },
  { key: 'gh_location_page', type: 'location_page', label: 'Location pages', placeholder: 'src/content/locations' },
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
  // Page-structure guidelines upload: which page type is mid-upload, and any
  // per-page-type error. Reuses the shared /files/upload parser, so a .docx or
  // .pdf spec lands in the textarea as text the user can review and edit before
  // saving — an upload is a shortcut for typing, not a separate storage path.
  const [psUploading, setPsUploading] = useState<PageStructureType | null>(null)
  const [psUploadError, setPsUploadError] = useState<Partial<Record<PageStructureType, string>>>({})

  async function handleGuidelinesUpload(
    e: React.ChangeEvent<HTMLInputElement>, type: PageStructureType,
  ) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file after an error
    if (!file) return
    setPsUploadError(s => ({ ...s, [type]: undefined }))
    setPsUploading(type)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.upload<{ parsed_text: string }>('/files/upload', fd)
      const text = (res.parsed_text ?? '').trim()
      if (!text) {
        setPsUploadError(s => ({ ...s, [type]: "We couldn't read any text from that file." }))
        return
      }
      setForm(f => ({
        ...f,
        ps_guidelines: { ...f.ps_guidelines, [type]: text },
        ps_filename: { ...f.ps_filename, [type]: file.name },
      }))
    } catch (err) {
      setPsUploadError(s => ({ ...s, [type]: (err as Error).message || 'Upload failed.' }))
    } finally {
      setPsUploading(null)
    }
  }

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

  // Everhour time-tracking (Phase 1): the client↔project mapping picker. The
  // picker only shows once Everhour is configured; until then the field is a
  // plain id input (paste an id / leave blank), so the form is unchanged.
  const { data: everhourStatus } = useQuery<EverhourStatus>({
    queryKey: ['everhour-status'],
    queryFn: () => api.get<EverhourStatus>('/everhour/status'),
  })
  const everhourOn = !!everhourStatus?.configured
  const { data: everhourProjects } = useQuery<EverhourProject[]>({
    queryKey: ['everhour-projects'],
    queryFn: () => api.get<EverhourProject[]>('/everhour/projects'),
    enabled: everhourOn,
  })

  // Snapshot of the reference-page sources (URLs + written guidelines) as loaded
  // into the form. On save, page_structure_urls / page_structure_guidelines are
  // sent only when the fields differ from this snapshot — an untouched form omits
  // the key and the server leaves stored references as-is. Without this, a save
  // from a form loaded before the references were added (a stale tab, a
  // teammate's concurrent edit) submits blanks and silently wipes them (last
  // write wins).
  const loadedPsRef = useRef<{
    urls: Record<string, string>
    guidelines: Record<string, string>
  } | null>(null)

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
      const psUrls = Object.fromEntries(
        PAGE_STRUCTURE_TYPES.map(t => [t, existing.page_structures?.[t]?.url ?? '']),
      )
      const psGuidelines = Object.fromEntries(
        PAGE_STRUCTURE_TYPES.map(t => [t, existing.page_structures?.[t]?.guidelines_text ?? '']),
      )
      loadedPsRef.current = { urls: psUrls, guidelines: psGuidelines }
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
        gh_blog_post: existing.github_content_paths?.blog_post ?? '',
        gh_service_page: existing.github_content_paths?.service_page ?? '',
        gh_location_page: existing.github_content_paths?.location_page ?? '',
        wordpress_site_url: existing.wordpress_site_url ?? '',
        wordpress_username: existing.wordpress_username ?? '',
        wordpress_app_password: '',
        wordpress_app_password_set: existing.wordpress_app_password_set ?? false,
        wheelhouse_cpt_enabled: existing.wheelhouse_cpt_enabled ?? false,
        logo_url: existing.logo_url ?? '',
        gsc_property: existing.gsc_property ?? '',
        business_location: existing.business_location ?? '',
        target_cities: (existing.target_cities ?? []).join(', '),
        gbp_place_id: existing.gbp_place_id,
        gbp: existing.gbp,
        ps_local_landing: psUrls.local_landing,
        ps_service: psUrls.service,
        ps_location: psUrls.location,
        ps_blog_post: psUrls.blog_post,
        ps_product: psUrls.product,
        ps_solution: psUrls.solution,
        ps_mode: Object.fromEntries(
          PAGE_STRUCTURE_TYPES.map(t => [
            t, existing.page_structures?.[t]?.source === 'manual' ? 'guidelines' : 'url',
          ]),
        ) as Record<PageStructureType, 'url' | 'guidelines'>,
        ps_guidelines: psGuidelines as Record<PageStructureType, string>,
        ps_filename: Object.fromEntries(
          PAGE_STRUCTURE_TYPES.map(t => [t, existing.page_structures?.[t]?.original_filename ?? '']),
        ) as Record<PageStructureType, string>,
        retainer_monthly: existing.retainer_monthly != null ? String(existing.retainer_monthly) : '',
        is_sab: existing.is_sab ?? false,
        illustrate_content: existing.illustrate_content ?? false,
        client_type: existing.client_type ?? 'local',
        strategist_weekday: existing.strategist_weekday != null ? String(existing.strategist_weekday) : '',
        slack_channel_id: existing.slack_channel_id ?? '',
        everhour_project_id: existing.everhour_project_id ?? '',
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
        // Merge the form's known per-type paths onto the existing map so keys we
        // don't render are preserved. Blank fields clear their key.
        github_content_paths: (() => {
          const merged: Record<string, string> = { ...(existing?.github_content_paths ?? {}) }
          for (const f of GITHUB_PATH_FIELDS) {
            const v = (form[f.key] as string).trim()
            if (v) merged[f.type] = v
            else delete merged[f.type]
          }
          return merged
        })(),
        wordpress_site_url: form.wordpress_site_url.trim() || null,
        wordpress_username: form.wordpress_username.trim() || null,
        // Only send the password when the user typed a new one; an empty field
        // leaves the stored secret untouched (omit the key entirely).
        ...(form.wordpress_app_password ? { wordpress_app_password: form.wordpress_app_password } : {}),
        wheelhouse_cpt_enabled: form.wheelhouse_cpt_enabled,
        logo_url: form.logo_url || null,
        gsc_property: form.gsc_property || null,
        business_location: form.business_location || null,
        target_cities: form.target_cities.split(',').map(s => s.trim()).filter(Boolean),
        gbp_place_id: form.gbp_place_id,
        gbp: form.gbp,
        // Recipe Engine budget inputs (66% margin target → 34% deployable).
        ...(form.retainer_monthly.trim() !== '' ? { retainer_monthly: Number(form.retainer_monthly) } : {}),
        is_sab: form.is_sab,
        illustrate_content: form.illustrate_content,
        client_type: form.client_type,
        // Always send (number or null) so clearing back to the global default persists.
        strategist_weekday: form.strategist_weekday !== '' ? Number(form.strategist_weekday) : null,
        // Always send (string or empty) so clearing back to the master PACE channel persists.
        slack_channel_id: form.slack_channel_id.trim(),
        // Always send (id or empty) so clearing the Everhour mapping persists.
        everhour_project_id: form.everhour_project_id.trim(),
        // Reference-page URLs: send only when the fields differ from what the form
        // loaded (or on create). Omitting the key leaves stored references untouched
        // server-side — so a save from a form that loaded before references were
        // added elsewhere (stale tab / concurrent edit) can't silently wipe them.
        // Explicitly clearing a loaded field still sends '' → server drops it.
        ...(() => {
          const urlByType: Record<PageStructureType, string> = {
            local_landing: form.ps_local_landing.trim(),
            service: form.ps_service.trim(),
            location: form.ps_location.trim(),
            blog_post: form.ps_blog_post.trim(),
            product: form.ps_product.trim(),
            solution: form.ps_solution.trim(),
          }
          // Only the ACTIVE source is submitted per page type. The server rejects
          // a page type carrying both a URL and guidelines, and blanking the
          // inactive one is what lets a page type be switched between sources.
          const urls: Record<string, string> = {}
          const guidelines: Record<string, string> = {}
          for (const t of PAGE_STRUCTURE_TYPES) {
            const isManual = form.ps_mode[t] === 'guidelines'
            urls[t] = isManual ? '' : urlByType[t]
            guidelines[t] = isManual ? form.ps_guidelines[t].trim() : ''
          }
          const loaded = loadedPsRef.current
          const same = (cur: Record<string, string>, was: Record<string, string>) =>
            PAGE_STRUCTURE_TYPES.every(t => cur[t] === (was[t] ?? '').trim())
          const urlsUnchanged = isEdit && loaded && same(urls, loaded.urls)
          const guidesUnchanged = isEdit && loaded && same(guidelines, loaded.guidelines)
          return {
            ...(urlsUnchanged
              ? {}
              : {
                  page_structure_urls: Object.fromEntries(
                    Object.entries(urls).map(([k, v]) => [k, v || null]),
                  ),
                }),
            ...(guidesUnchanged
              ? {}
              : {
                  page_structure_guidelines: Object.fromEntries(
                    PAGE_STRUCTURE_TYPES.map(t => [
                      t,
                      guidelines[t]
                        ? { text: guidelines[t], original_filename: form.ps_filename[t] || null }
                        : { text: '' },
                    ]),
                  ),
                }),
          }
        })(),
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
          <h2 style={sectionTitle}>Budget &amp; Campaign Type</h2>
          <div style={{ marginBottom: 16 }}>
            <label style={labelStyle}>Monthly Budget (retainer)</label>
            <input
              type="number"
              min="0"
              step="50"
              value={form.retainer_monthly}
              onChange={set('retainer_monthly')}
              placeholder="e.g. 2000"
              style={{ ...inputStyle, width: 200, boxSizing: 'border-box' }}
            />
            <p style={hintStyle}>
              The client's total monthly budget. The Recipe Engine plans at the <strong>66% margin
              target</strong> — only <strong>34%</strong> is deployable on tasks
              {form.retainer_monthly.trim() !== '' && Number(form.retainer_monthly) > 0 && (
                <>
                  : <strong>${Math.round(Number(form.retainer_monthly) * 0.34).toLocaleString()}/mo deployable</strong>
                  {' '}(${Math.round(Number(form.retainer_monthly) * 0.34) - 150 >= 0
                    ? (Math.round(Number(form.retainer_monthly) * 0.34) - 150).toLocaleString()
                    : 0} after the $150 reporting line)
                </>
              )}
              . Stagnating / drop months may run at 50% margin — chosen when generating the plan, not here.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div>
              <label style={labelStyle}>Client Type</label>
              <select
                value={form.client_type}
                onChange={(e) => setForm(f => ({ ...f, client_type: e.target.value as FormData['client_type'] }))}
                style={{ ...inputStyle, width: 220, boxSizing: 'border-box' }}
              >
                <option value="local">Local (fund RD first)</option>
                <option value="enterprise">Enterprise / e-commerce (fund Entity first)</option>
              </select>
              <p style={hintStyle}>Sets the Recipe Engine's Diagnose-and-Fund order.</p>
            </div>
            <div>
              <label style={labelStyle}>Service-Area Business (SAB)</label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155', marginTop: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={form.is_sab}
                  onChange={(e) => setForm(f => ({ ...f, is_sab: e.target.checked }))}
                />
                Hidden address / service-area GBP
              </label>
              <p style={hintStyle}>SABs skip the GBP Blast in the monthly baseline stack ($130 vs $135).</p>
            </div>
            <div>
              <label style={labelStyle}>Auto-illustrate content</label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155', marginTop: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={form.illustrate_content}
                  onChange={(e) => setForm(f => ({ ...f, illustrate_content: e.target.checked }))}
                />
                Add a hero + inline images/charts to finished blog posts
              </label>
              <p style={hintStyle}>When on, a completed run auto-generates a hero and up to 2 body visuals (data charts where the article cites figures, else AI illustrations). Off by default — bulk runs are never illustrated unless enabled.</p>
            </div>
            <div>
              <label style={labelStyle}>Strategist Review Day</label>
              <select
                value={form.strategist_weekday}
                onChange={(e) => setForm(f => ({ ...f, strategist_weekday: e.target.value }))}
                style={{ ...inputStyle, width: 220, boxSizing: 'border-box' }}
              >
                <option value="">Default (global)</option>
                <option value="0">Monday</option>
                <option value="1">Tuesday</option>
                <option value="2">Wednesday</option>
                <option value="3">Thursday</option>
                <option value="4">Friday</option>
                <option value="5">Saturday</option>
                <option value="6">Sunday</option>
              </select>
              <p style={hintStyle}>Weekday this client's SerMaStr review runs — stagger clients across the week.</p>
            </div>
            <div>
              <label style={labelStyle}>PACE Slack Channel</label>
              <input
                value={form.slack_channel_id}
                onChange={set('slack_channel_id')}
                placeholder="C0ABC123XY  (or  #acme-hvac)"
                style={{ ...inputStyle, width: 260, boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
              <p style={hintStyle}>PACE posts this client's task notifications (assignments, mentions, comments, nudges, monthly plan) to this channel. Leave blank to use the master PACE channel. The PACE bot must be a member of the channel.</p>
            </div>
            <div>
              <label style={labelStyle}>Everhour Project</label>
              {everhourOn ? (
                <select
                  value={form.everhour_project_id}
                  onChange={(e) => setForm((f) => ({ ...f, everhour_project_id: e.target.value }))}
                  style={{ ...inputStyle, width: 260, boxSizing: 'border-box' }}
                >
                  <option value="">— not mapped —</option>
                  {/* Keep a stored id that's no longer in the live list selectable. */}
                  {form.everhour_project_id &&
                    !(everhourProjects ?? []).some((p) => p.everhour_project_id === form.everhour_project_id) && (
                      <option value={form.everhour_project_id}>{form.everhour_project_id} (unknown)</option>
                    )}
                  {(everhourProjects ?? []).map((p) => (
                    <option key={p.everhour_project_id ?? ''} value={p.everhour_project_id ?? ''}>
                      {p.name ?? p.everhour_project_id}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={form.everhour_project_id}
                  onChange={set('everhour_project_id')}
                  placeholder="ev:123456789  (Everhour project id)"
                  style={{ ...inputStyle, width: 260, boxSizing: 'border-box', fontFamily: 'monospace' }}
                />
              )}
              <p style={hintStyle}>The Everhour project this client's tracked time is logged against. Time logged there rolls up as this client's actual hours. Leave blank if the client isn't on Everhour yet.{!everhourOn ? ' (Connect Everhour to pick from a list.)' : ''}</p>
            </div>
          </div>
        </div>

        <div style={sectionStyle}>
          <h2 style={sectionTitle}>Reference Page Structures</h2>
          <p style={descStyle}>
            Optional. For each page type, either point us at an example URL — we scrape and analyze
            that page's structure, ignoring nav, sidebars, footers, and popups — or write out the
            structure yourself. Either way we store the layout so the writing modules can mirror how
            this client's pages are organized. Use <strong>Written guidelines</strong> when there's no
            live page to scrape: a client with no site yet, a rebuild, or a layout that only exists in
            a brand or design document. We re-analyze whenever you change the source; use{' '}
            <strong>Re-analyze</strong> to refresh a stored one.
          </p>
          {PAGE_STRUCTURE_FIELDS.map(({ key, type, label, placeholder, help }) => {
            const entry = existing?.page_structures?.[type]
            const mode = form.ps_mode[type]
            const isManual = mode === 'guidelines'
            const trimmed = (form[key] as string).trim()
            const guidelines = form.ps_guidelines[type]
            const storedGuidelines = (entry?.guidelines_text ?? '').trim()
            // Re-analyze applies to the STORED source — only offer it when the
            // form matches what's stored (no unsaved edit) and it's not already
            // mid-analysis.
            const canReanalyze = isEdit && entry?.status !== 'pending' && (
              isManual
                ? entry?.source === 'manual' && !!storedGuidelines && storedGuidelines === guidelines.trim()
                : !!entry?.url && entry.url === trimmed
            )
            const rowReanalyzing = reanalyzeMutation.isPending && reanalyzeMutation.variables === type
            return (
              <div key={type} style={{ marginBottom: 20 }}>
                <div style={titleRow}>
                  <label style={{ ...labelStyle, margin: 0 }}>{label}</label>
                  {isEdit && (
                    <PageStructureStatus
                      entry={entry}
                      value={isManual ? guidelines : (form[key] as string)}
                      mode={mode}
                    />
                  )}
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
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  {(['url', 'guidelines'] as const).map(m => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setForm(f => ({ ...f, ps_mode: { ...f.ps_mode, [type]: m } }))}
                      style={{ ...psToggleStyle, ...(mode === m ? psToggleActiveStyle : {}) }}
                    >
                      {m === 'url' ? 'Example URL' : 'Written guidelines'}
                    </button>
                  ))}
                </div>
                {isManual ? (
                  <>
                    <textarea
                      value={guidelines}
                      onChange={(e) => setForm(f => ({
                        ...f, ps_guidelines: { ...f.ps_guidelines, [type]: e.target.value },
                      }))}
                      rows={7}
                      placeholder={
                        'Describe the page section by section, e.g.\n\n' +
                        'Hero — 80-120 words. Headline, one-line value prop, CTA button.\n' +
                        'Why choose us — 150 words, 4-item bullet list.\n' +
                        'Our process — 200 words, numbered steps.\n' +
                        'FAQ — 5 questions.\n' +
                        'Closing CTA — 60 words.'
                      }
                      style={{
                        ...inputStyle, width: '100%', boxSizing: 'border-box', marginTop: 6,
                        fontFamily: 'inherit', resize: 'vertical', lineHeight: 1.5,
                      }}
                    />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
                      <label style={{ ...reanalyzeBtnStyle, cursor: psUploading === type ? 'default' : 'pointer' }}>
                        <Upload size={12} />
                        {psUploading === type ? 'Reading…' : 'Upload a document'}
                        <input
                          type="file"
                          accept=".pdf,.doc,.docx,.txt,.md,.rtf"
                          onChange={(e) => handleGuidelinesUpload(e, type)}
                          disabled={psUploading === type}
                          style={{ display: 'none' }}
                        />
                      </label>
                      {form.ps_filename[type] && (
                        <span style={{ fontSize: 12, color: '#64748b' }}>
                          from <strong>{form.ps_filename[type]}</strong>
                        </span>
                      )}
                    </div>
                    {psUploadError[type] && (
                      <p style={{ ...hintStyle, color: '#dc2626' }}>{psUploadError[type]}</p>
                    )}
                    <p style={hintStyle}>
                      {help} Give each section a length only if you want it enforced — we never
                      invent word counts, so a section without one is written to fit its purpose.
                    </p>
                  </>
                ) : (
                  <>
                    <input
                      type="url"
                      value={form[key] as string}
                      onChange={set(key)}
                      placeholder={placeholder}
                      style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', marginTop: 6 }}
                    />
                    <p style={hintStyle}>{help}</p>
                  </>
                )}
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
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#334155', marginTop: 14, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={form.wheelhouse_cpt_enabled}
              onChange={(e) => setForm(f => ({ ...f, wheelhouse_cpt_enabled: e.target.checked }))}
            />
            Enable the WheelHouse IT page poster for this client
          </label>
          <p style={hintStyle}>
            Adds a "Wheelhouse Pages" tool to this client's workspace: generate & publish location/service
            landing Pages (State → City → Service) with 33 ACF fields. Requires the ACF field group assigned to
            Pages with Show-in-REST on. Leave off for every other client.
          </p>
        </div>

        <div style={sectionStyle}>
          <div style={titleRow}>
            <h2 style={{ ...sectionTitle, margin: 0 }}>GitHub Publishing</h2>
            <ParkedBadge />
          </div>
          <p style={descStyle}>
            Optional. Where this client's published content is committed in the repo (Astro content). The content path is the default for every type; the per-type overrides below route each content type into its own collection. Dormant until a GitHub token is configured on the platform.
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
              <label style={labelStyle}>Content path (default)</label>
              <input
                value={form.github_content_path}
                onChange={set('github_content_path')}
                placeholder="src/content/blog"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
            </div>
          </div>
          <p style={{ ...descStyle, marginTop: 16, marginBottom: 8 }}>
            Per-type overrides (optional) — leave blank to use the default path above.
          </p>
          {GITHUB_PATH_FIELDS.map(f => (
            <div key={f.key} style={{ marginTop: 8 }}>
              <label style={labelStyle}>{f.label}</label>
              <input
                value={form[f.key] as string}
                onChange={set(f.key)}
                placeholder={f.placeholder}
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', fontFamily: 'monospace' }}
              />
            </div>
          ))}
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

function PageStructureStatus(
  { entry, value, mode }: { entry?: PageStructureEntry; value: string; mode: 'url' | 'guidelines' },
) {
  const trimmed = value.trim()
  // Which stored value the form's current input is compared against depends on
  // the source: a scraped entry is keyed by its URL, a manual one by its text.
  const isManual = mode === 'guidelines'
  const stored = (isManual ? entry?.guidelines_text : entry?.url) ?? ''
  const storedMatchesMode = isManual === (entry?.source === 'manual')
  // Pending save: the form differs from what's stored (or nothing stored yet,
  // or the source was switched).
  if (!entry || !storedMatchesMode || !stored || stored.trim() !== trimmed) {
    if (!trimmed) return null
    return <span style={{ ...psBadge, color: '#475569', background: '#f1f5f9', border: '1px solid #e2e8f0' }}>Analyzes on save</span>
  }
  if (entry.status === 'pending')
    return <span style={{ ...psBadge, color: '#92400e', background: '#fef3c7', border: '1px solid #fde68a' }}>Analyzing…</span>
  if (entry.status === 'complete') {
    // Completed, but the scrape captured no content sections (e.g. the page
    // blocks scraping or uses non-semantic markup) — not a usable reference.
    if (entry.empty)
      return (
        <span
          style={{ ...psBadge, color: '#92400e', background: '#fef3c7', border: '1px solid #fde68a' }}
          title={entry.note ?? 'Captured 0 content sections — try a different, content-rich reference URL.'}
        >
          {isManual ? 'No sections found' : 'Empty — try another URL'}
        </span>
      )
    return <span style={{ ...psBadge, color: '#166534', background: '#dcfce7', border: '1px solid #bbf7d0' }}>Analyzed</span>
  }
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
const psToggleStyle: React.CSSProperties = { padding: '4px 12px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: 'pointer' }
const psToggleActiveStyle: React.CSSProperties = { background: '#eef2ff', color: '#4f46e5', borderColor: '#c7d2fe' }
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
