import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { ClientListItem } from '../lib/types'
import { Plus, X, Check, Globe, AlertCircle, Clock, Pencil } from 'lucide-react'

function AnalysisStatus({ status }: { status: ClientListItem['website_analysis_status'] }) {
  if (status === 'complete') return <span style={{ fontSize: 12, color: '#16a34a' }}>✓ Website analyzed</span>
  if (status === 'failed') return <span style={{ fontSize: 12, color: '#dc2626' }}><AlertCircle size={11} style={{ verticalAlign: 'middle' }} /> Analysis failed</span>
  return <span style={{ fontSize: 12, color: '#64748b' }}><Clock size={11} style={{ verticalAlign: 'middle' }} /> Analyzing…</span>
}

export function Clients() {
  const qc = useQueryClient()
  const [deleteId, setDeleteId] = useState<string | null>(null)

  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
    refetchInterval: (query) => {
      const list = query.state.data ?? []
      return list.some(c => c.website_analysis_status === 'pending') ? 8000 : false
    },
  })

  const archiveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/clients/${id}/archive`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clients'] }),
  })

  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Clients</h1>
        <Link to="/clients/new" style={primaryBtn}>
          <Plus size={15} /> Add Client
        </Link>
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : clients.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 48 }}>
          No clients yet.{' '}
          <Link to="/clients/new" style={{ color: '#6366f1', textDecoration: 'none', fontWeight: 500 }}>
            Add your first client
          </Link>{' '}
          to get started.
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
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Link to={`/clients/${c.id}/edit`} style={iconBtn} title="Edit">
                  <Pencil size={14} />
                </Link>
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

const cardStyle: React.CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const primaryBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#6366f1', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, fontSize: 13, cursor: 'pointer', textDecoration: 'none' }
const iconBtn: React.CSSProperties = { display: 'flex', alignItems: 'center', padding: '6px', background: '#fff', color: '#64748b', border: '1px solid #e2e8f0', borderRadius: 6, cursor: 'pointer', textDecoration: 'none' }
