import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client, GbpProfile } from '../lib/types'
import { GbpPicker } from '../components/GbpPicker'
import { ArrowLeft, Radar, Loader2 } from 'lucide-react'
import { ErrorDetails } from '../components/ErrorDetails'

/**
 * Lightweight create/edit form for a PROSPECT — a stripped-down client record
 * for prospecting (running one-off organic / maps / AI-visibility / competitive
 * reports without building a full client profile). Only name is required; a
 * website + business location + linked Google Business Profile are optional and
 * just make the reports richer (the GBP anchors the Maps geo-grid and enables
 * review-based Competitive Intel; the location feeds Maps + Domain Intelligence
 * defaults). Creating a prospect skips all the full-client machinery (brand
 * voice / ICP scans, website scrape, GSC, deliverables) — see the backend.
 */
export function ProspectForm() {
  const { id } = useParams<{ id: string }>()
  const isEdit = Boolean(id)
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [location, setLocation] = useState('')
  const [placeId, setPlaceId] = useState<string | null>(null)
  const [gbp, setGbp] = useState<GbpProfile | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Edit mode: load the prospect and seed the form.
  const { data: existing } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: isEdit,
  })
  useEffect(() => {
    if (!existing) return
    setName(existing.name ?? '')
    setWebsite(existing.website_url ?? '')
    setLocation(existing.business_location ?? '')
    setPlaceId(existing.gbp_place_id ?? null)
    setGbp(existing.gbp ?? null)
  }, [existing])

  function onGbpChange(newPlaceId: string | null, profile: GbpProfile | null) {
    setPlaceId(newPlaceId)
    setGbp(profile)
    // Convenience: fill empty name/website from the selected profile.
    if (profile) {
      if (!name.trim() && profile.business_name) setName(profile.business_name)
      if (!website.trim() && profile.website) setWebsite(profile.website)
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError('name_required')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = {
        name: name.trim(),
        website_url: website.trim(),
        business_location: location.trim() || null,
        gbp_place_id: placeId,
        gbp,
      }
      let saved: Client
      if (isEdit) {
        saved = await api.patch<Client>(`/clients/${id}`, payload)
      } else {
        saved = await api.post<Client>('/clients', {
          ...payload,
          kind: 'prospect',
          // Required by the client model; a prospect has no brand guide / ICP.
          brand_guide_source_type: 'text',
          brand_guide_text: '',
          icp_source_type: 'text',
          icp_text: '',
        })
      }
      navigate(`/clients/${saved.id}`)
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <div style={{ padding: 32, maxWidth: 640 }}>
      <Link to="/" style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 40, height: 40, borderRadius: 10, background: '#eef2ff', color: '#6366f1' }}>
          <Radar size={20} />
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>
          {isEdit ? 'Edit prospect' : 'New prospect'}
        </h1>
      </div>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 24px' }}>
        A lightweight record for prospecting — run one-off Organic, Maps, AI-Visibility
        and Competitive-Intel reports without building a full client profile. Convert it
        to a full client later if they sign. Only a name is required.
      </p>

      <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <Field label="Business name" required>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Acme Plumbing"
            style={inputStyle}
            autoFocus
          />
        </Field>

        <Field label="Website" hint="Optional — powers the organic (Domain Intelligence) report.">
          <input
            value={website}
            onChange={e => setWebsite(e.target.value)}
            placeholder="https://example.com"
            style={inputStyle}
          />
        </Field>

        <Field label="Business location" hint="Optional — a default location for Maps & organic research (e.g. “Tampa, FL”).">
          <input
            value={location}
            onChange={e => setLocation(e.target.value)}
            placeholder="City, State"
            style={inputStyle}
          />
        </Field>

        <Field label="Google Business Profile" hint="Optional — link one to anchor the Maps geo-grid and pull competitor reviews. Auto-fills the name & website if blank.">
          <GbpPicker placeId={placeId} profile={gbp} onChange={onGbpChange} />
        </Field>

        {error && <ErrorDetails message={error} />}

        <div style={{ display: 'flex', gap: 10 }}>
          <button type="submit" disabled={saving} style={primaryBtn}>
            {saving && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
            {isEdit ? 'Save changes' : 'Create prospect'}
          </button>
          <Link to="/" style={secondaryBtn}>Cancel</Link>
        </div>
      </form>
    </div>
  )
}

function Field({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: '#334155' }}>
        {label}{required && <span style={{ color: '#dc2626' }}> *</span>}
      </span>
      {children}
      {hint && <span style={{ fontSize: 12, color: '#94a3b8' }}>{hint}</span>}
    </label>
  )
}

const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const inputStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1', borderRadius: 8, padding: '9px 12px', fontSize: 14, color: '#0f172a',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8,
  padding: '10px 18px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
}
const secondaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center',
  background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 8,
  padding: '10px 18px', fontSize: 14, fontWeight: 600, textDecoration: 'none',
}
