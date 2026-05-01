import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { Plus, Pencil, Trash2, X, Check } from 'lucide-react'

interface ClientFormData {
  name: string
  website_url: string
  industry: string
  tone_of_voice: string
  target_audience: string
}

const empty: ClientFormData = { name: '', website_url: '', industry: '', tone_of_voice: '', target_audience: '' }

export function Clients() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Client | null>(null)
  const [form, setForm] = useState<ClientFormData>(empty)
  const [saving, setSaving] = useState(false)
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const { data: clients = [], isLoading } = useQuery<Client[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<Client[]>('/clients'),
  })

  const createMutation = useMutation({
    mutationFn: (body: ClientFormData) => api.post('/clients', body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clients'] }); closeForm() },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<ClientFormData> }) =>
      api.patch(`/clients/${id}`, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clients'] }); closeForm() },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/clients/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['clients'] }); setDeleteId(null) },
  })

  function openCreate() { setEditing(null); setForm(empty); setShowForm(true) }
  function openEdit(c: Client) {
    setEditing(c)
    setForm({ name: c.name, website_url: c.website_url, industry: c.industry ?? '', tone_of_voice: c.tone_of_voice ?? '', target_audience: c.target_audience ?? '' })
    setShowForm(true)
  }
  function closeForm() { setShowForm(false); setEditing(null); setForm(empty) }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      if (editing) {
        await updateMutation.mutateAsync({ id: editing.id, body: form })
      } else {
        await createMutation.mutateAsync(form)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Clients</h1>
        <button onClick={openCreate} style={primaryBtn}>
          <Plus size={15} /> Add Client
        </button>
      </div>

      {showForm && (
        <div style={cardStyle}>
          <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 20px', color: '#0f172a' }}>
            {editing ? 'Edit Client' : 'New Client'}
          </h2>
          <form onSubmit={handleSave}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 20px' }}>
              <Field label="Client Name *" value={form.name} onChange={v => setForm(f => ({ ...f, name: v }))} required />
              <Field label="Website URL *" value={form.website_url} onChange={v => setForm(f => ({ ...f, website_url: v }))} type="url" required />
              <Field label="Industry" value={form.industry} onChange={v => setForm(f => ({ ...f, industry: v }))} />
              <Field label="Tone of Voice" value={form.tone_of_voice} onChange={v => setForm(f => ({ ...f, tone_of_voice: v }))} placeholder="e.g. friendly, professional" />
            </div>
            <div style={{ marginTop: 14 }}>
              <label style={labelStyle}>Target Audience</label>
              <textarea
                value={form.target_audience}
                onChange={e => setForm(f => ({ ...f, target_audience: e.target.value }))}
                rows={3}
                placeholder="Describe the target audience…"
                style={{ ...inputStyle, width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
              />
            </div>
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
                <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a' }}>{c.name}</div>
                <a href={c.website_url} target="_blank" rel="noreferrer" style={{ fontSize: 13, color: '#6366f1', textDecoration: 'none' }}>
                  {c.website_url}
                </a>
                {c.industry && <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{c.industry}</div>}
                {c.tone_of_voice && <div style={{ fontSize: 12, color: '#64748b' }}>Tone: {c.tone_of_voice}</div>}
                {c.target_audience && (
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 4, maxWidth: 480 }}>{c.target_audience}</div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => openEdit(c)} style={iconBtn} title="Edit">
                  <Pencil size={14} />
                </button>
                {deleteId === c.id ? (
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: '#dc2626' }}>Delete?</span>
                    <button onClick={() => deleteMutation.mutate(c.id)} style={{ ...iconBtn, color: '#dc2626', borderColor: '#fca5a5' }}>
                      <Check size={14} />
                    </button>
                    <button onClick={() => setDeleteId(null)} style={iconBtn}><X size={14} /></button>
                  </div>
                ) : (
                  <button onClick={() => setDeleteId(c.id)} style={{ ...iconBtn, color: '#dc2626' }} title="Delete">
                    <Trash2 size={14} />
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
