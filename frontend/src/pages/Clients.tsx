import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ClientListItem } from '../lib/types'
import { Plus, X, Check, Globe, AlertCircle, Clock } from 'lucide-react'

interface ClientFormData {
  name: string
  website_url: string
  brand_guide_text: string
  icp_text: string
}

const empty: ClientFormData = { name: '', website_url: '', brand_guide_text: '', icp_text: '' }

function AnalysisStatus({ status }: { status: ClientListItem['website_analysis_status'] }) {
  if (status === 'complete') return <span style={{ fontSize: 12, color: '#16a34a' }}>✓ Website analyzed</span>
  if (status === 'failed') return <span style={{ fontSize: 12, color: '#dc2626' }}><AlertCircle size={11} style={{ verticalAlign: 'middle' }} /> Analysis failed</span>
  return <span style={{ fontSize: 12, color: '#64748b' }}><Clock size={11} style={{ verticalAlign: 'middle' }} /> Analyzing…</span>
}

export function Clients() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ClientFormData>(empty)
  const [saving, setSaving] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    refetchInterval: (query) => {
      const list = query.state.data ?? []
      return list.some(c => c.website_analysis_status === 'pending') ? 8000 : false
    },
  })

  const createMutation = useMutation({
    mutationFn: (body: object) => api.post('/clients', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clients'] }); closeForm() },
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/clients/${id}/archive`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clients'] }),
  })

  function closeForm() { setShowForm(false); setForm(empty) }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await createMutation.mutateAsync({
        name: form.name,
        website_url: form.website_url,
        brand_guide_source_type: 'text',
        brand_guide_text: form.brand_guide_text,
        icp_source_type: 'text',
        icp_text: form.icp_text,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Clients</h1>
        <button onClick={() => setShowForm(true)} style={primaryBtn}>
          <Plus size={15} /> Add Client
        </button>
      </div>

      {showForm && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 20px', color: '#0f172a' }}>New Client</h2>
          <form onSubmit={handleSave}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 20px' }}>
              <Field label="Client Name *" value={form.name} onChange={v => setForm(f => ({ ...f, name: v }))} required />
              <Field label="Website URL *" value={form.website_url} onChange={v => setForm(f => ({ ...f, website_url: v }))} type="url" required placeholder="https://example.com" />
            </div>

            <div style={{ marginTop: 14 }}>
              <label style={labelStyle}>Brand Guide</label>
              <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 6px' }}>
                Paste the client's brand guidelines, tone of voice, or any brand positioning text.
              </p>
              <textarea
                value={form.brand_guide_text}
                onChange={e => setForm(f => ({ ...f, brand_guide_text: e.target.value }))}
                rows={5}
                placeholder="e.g. Our brand voice is approachable and expert. We avoid jargon…"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
              />
            </div>

            <div style={{ marginTop: 14 }}>
              <label style={labelStyle}>Ideal Customer Profile (ICP)</label>
              <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 6px' }}>
                Describe the target customer — demographics, pain points, buying triggers.
              </p>
              <textarea
                value={form.icp_text}
                onChange={e => setForm(f => ({ ...f, icp_text: e.target.value }))}
                rows={4}
                placeholder="e.g. Homeowners aged 35-60 in the Sun Belt, concerned about energy costs…"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
              />
            </div>

            {createMutation.error && (
              <div style={{ marginTop: 12, padding: '10px 14px', background: '#fef2f2', borderRadius: 8, color: '#dc2626', fontSize: 13 }}>
                {(createMutation.error as Error).message}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button type="submit" disabled={saving} style={primaryBtn}>
                <Check size={14} /> {saving ? 'Saving…' : 'Save'}
              </button>
              <button type="button" onClick={closeForm} style={ghostBtn}>
                <X size={14} /> Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : clients.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No clients yet. Add your first client to get started.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 14 }}>
          {clients.map(c => (
            <div key={c.id} style={{ ...cardStyle, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 0 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 4 }}>{c.name}</div>
                <a href={c.website_url} target="_blank" rel="noreferrer"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#6366f1', textDecoration: 'none' }}>
                  <Globe size={12} /> {c.website_url}
                </a>
                <div style={{ marginTop: 6 }}>
                  <AnalysisStatus status={c.website_analysis_status} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {deleteId === c.id ? (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: '#dc2626' }}>Archive?</span>
                    <button onClick={() => { archiveMutation.mutate(c.id); setDeleteId(null) }}
                      style={{ ...iconBtn, color: '#dc2626', borderColor: '#fca5a5' }}>
                      <Check size={14} />
                    </button>
                    <button onClick={() => setDeleteId(null)} style={iconBtn}><X size={14} /></button>
                  </div>
                ) : (
                  <button onClick={() => setDeleteId(c.id)} style={{ ...iconBtn, color: '#dc2626' }} title="Archive">
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange, type = 'text', required = false, placeholder = '' }: {
  label: string; value: string; onChange: (v: string) => void; type?: string; required?: boolean; placeholder?: string
}) {
  return (
    <div>
      <label style={labelStyle}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} required={required} placeholder={placeholder}
        style={{ ...inputStyle, width: '100%', boxSizing: 'border-box' }} />
    </div>
  )
}

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 500, color: '#374151', marginBottom: 5 }
const inputStyle: React.CSSProperties = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 8, fontSize: 14, color: '#0f172a' }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer' }
const ghostBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#fff', color: '#374151', border: '1px solid #e2e8f0', borderRadius: 8, fontWeight: 500, fontSize: 13, cursor: 'pointer' }
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer' }
