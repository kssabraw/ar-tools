import { useState, useEffect } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { ArrowLeft, Check } from 'lucide-react'

interface FormData {
  name: string
  website_url: string
  brand_guide_text: string
  icp_text: string
  google_drive_folder_id: string
}

const empty: FormData = { name: '', website_url: '', brand_guide_text: '', icp_text: '', google_drive_folder_id: '' }

export function ClientForm() {
  const navigate = useNavigate()
  const { id } = useParams<{ id?: string }>()
  const isEdit = Boolean(id)
  const qc = useQueryClient()
  const [form, setForm] = useState<FormData>(empty)
  const [saving, setSaving] = useState(false)

  const { data: existing, isLoading } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: isEdit,
  })

  useEffect(() => {
    if (existing) {
      setForm({
        name: existing.name,
        website_url: existing.website_url,
        brand_guide_text: existing.brand_guide_text ?? '',
        icp_text: existing.icp_text ?? '',
        google_drive_folder_id: existing.google_drive_folder_id ?? '',
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

  function set(field: keyof FormData) {
    return (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm(f => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      if (isEdit) {
        await updateMutation.mutateAsync({
          name: form.name,
          website_url: form.website_url,
          brand_guide_source_type: 'text',
          brand_guide_text: form.brand_guide_text,
          icp_source_type: 'text',
          icp_text: form.icp_text,
          google_drive_folder_id: form.google_drive_folder_id || null,
        })
      } else {
        await createMutation.mutateAsync({
          name: form.name,
          website_url: form.website_url,
          brand_guide_source_type: 'text',
          brand_guide_text: form.brand_guide_text,
          icp_source_type: 'text',
          icp_text: form.icp_text,
          google_drive_folder_id: form.google_drive_folder_id || null,
        })
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
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 32px' }}>
        {isEdit
          ? "Update the client's details. Changes apply to future runs — existing runs keep the snapshot that was taken when they started."
          : "Fill in the client's details. The brand guide and ICP are used by the AI to match the client's voice and audience on every content run."}
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

const sectionStyle: React.CSSProperties = { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 24, marginBottom: 20 }
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#0f172a', margin: '0 0 4px' }
const descStyle: React.CSSProperties = { fontSize: 13, color: '#64748b', margin: '0 0 16px', lineHeight: 1.6 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 6 }
const hintStyle: React.CSSProperties = { fontSize: 12, color: '#94a3b8', margin: '6px 0 0' }
const inputStyle: React.CSSProperties = { padding: '9px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a', fontFamily: 'inherit' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '9px 18px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 14, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '9px 18px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 14, textDecoration: 'none' }
