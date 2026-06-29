import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, Trash2, UploadCloud, Plus } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, Sop } from '../lib/types'

// SOP / Playbook store. Two modes from one component:
//  - agency-wide  (route /playbook, no :id)      → GET/POST /sops
//  - per-client   (route /clients/:id/sops)      → GET/POST /clients/:id/sops
// Loaded SOPs ground the Action Plan's per-task recommendations in the agency's
// own methodology + voice.
const CATEGORIES: Sop['category'][] = ['general', 'reoptimization', 'link_building', 'local', 'content', 'theory']

export function Sops() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const isClient = Boolean(id)
  const listPath = isClient ? `/clients/${id}/sops` : '/sops'
  const createPath = listPath
  const fileRef = useRef<HTMLInputElement>(null)

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [category, setCategory] = useState<Sop['category']>('general')
  const [source, setSource] = useState<'paste' | 'upload'>('paste')
  const [error, setError] = useState<string | null>(null)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: isClient,
  })

  const { data: sops = [], isLoading } = useQuery<Sop[]>({
    queryKey: ['sops', id ?? 'agency'],
    queryFn: () => api.get<Sop[]>(listPath),
  })

  const create = useMutation({
    mutationFn: () => api.post<Sop>(createPath, { title, content, category, source }),
    onSuccess: () => {
      setTitle(''); setContent(''); setCategory('general'); setSource('paste'); setError(null)
      queryClient.invalidateQueries({ queryKey: ['sops', id ?? 'agency'] })
    },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Failed to save'),
  })

  const toggle = useMutation({
    mutationFn: (s: Sop) => api.patch<Sop>(`/sops/${s.id}`, { enabled: !s.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sops', id ?? 'agency'] }),
  })

  const remove = useMutation({
    mutationFn: (sopId: string) => api.delete(`/sops/${sopId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['sops', id ?? 'agency'] }),
  })

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('field', 'sop')
      const res = await api.upload<{ parsed_text: string; original_filename: string }>('/files/upload', form)
      setContent(res.parsed_text || '')
      if (!title) setTitle(res.original_filename?.replace(/\.[^.]+$/, '') || 'Uploaded SOP')
      setSource('upload')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not parse the file')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // Per-client view: own SOPs vs the inherited agency-wide ones (read-only here).
  const own = isClient ? sops.filter((s) => s.client_id) : sops
  const inherited = isClient ? sops.filter((s) => !s.client_id) : []

  return (
    <div style={{ padding: 32, maxWidth: 860 }}>
      <Link to={isClient ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {isClient ? (client?.name ?? 'Client') : 'Home'}
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        <BookOpen size={20} /> {isClient ? 'Client SOPs' : 'Agency Playbook & Theories'}
      </h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '6px 0 20px' }}>
        {isClient
          ? `SOPs specific to ${client?.name ?? 'this client'}, layered on top of the agency-wide playbook. These ground this client's Action Plan recommendations.`
          : 'Your standard operating procedures and strategic theories. These apply to every client and ground the Action Plan recommendations across the suite.'}
      </p>

      {/* Add form */}
      <div style={card}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input
            style={{ ...input, flex: 1, minWidth: 220 }}
            placeholder="Title (e.g. 'Ranking-drop recovery SOP')"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select style={input} value={category} onChange={(e) => setCategory(e.target.value as Sop['category'])}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
        <textarea
          style={{ ...input, width: '100%', minHeight: 140, resize: 'vertical', fontFamily: 'inherit' }}
          placeholder="Paste the SOP / theory text here, or upload a document to extract it…"
          value={content}
          onChange={(e) => { setContent(e.target.value); setSource('paste') }}
        />
        {error && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button style={primaryBtn} disabled={create.isPending || !title.trim() || !content.trim()} onClick={() => create.mutate()}>
            <Plus size={14} /> {create.isPending ? 'Saving…' : 'Add SOP'}
          </button>
          <button style={ghostBtn} onClick={() => fileRef.current?.click()}>
            <UploadCloud size={14} /> Upload a document (PDF/DOCX/MD/TXT)
          </button>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.doc,.md,.txt" style={{ display: 'none' }} onChange={onFile} />
          {source === 'upload' && <span style={{ fontSize: 12, color: '#16a34a' }}>Extracted from upload — review &amp; add.</span>}
        </div>
      </div>

      {/* Lists */}
      {isLoading ? (
        <div style={empty}>Loading…</div>
      ) : (
        <>
          <SopList title={isClient ? 'This client’s SOPs' : 'Playbook entries'} sops={own}
                   onToggle={(s) => toggle.mutate(s)} onRemove={(sid) => remove.mutate(sid)} />
          {isClient && inherited.length > 0 && (
            <SopList title="Inherited from the agency playbook" sops={inherited} readOnly />
          )}
        </>
      )}
    </div>
  )
}

function SopList({ title, sops, onToggle, onRemove, readOnly }: {
  title: string; sops: Sop[]; readOnly?: boolean
  onToggle?: (s: Sop) => void; onRemove?: (id: string) => void
}) {
  return (
    <div style={{ marginTop: 22 }}>
      <h2 style={{ fontSize: 13, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.03em', margin: '0 0 8px' }}>
        {title} <span style={{ color: '#cbd5e1' }}>({sops.length})</span>
      </h2>
      {sops.length === 0 ? (
        <div style={empty}>None yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sops.map((s) => (
            <div key={s.id} style={{ ...row, opacity: s.enabled ? 1 : 0.55 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>{s.title}</span>
                  <span style={catPill}>{s.category.replace('_', ' ')}</span>
                  {!s.enabled && <span style={{ ...catPill, color: '#b45309', background: '#fffbeb' }}>disabled</span>}
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 4, whiteSpace: 'pre-wrap', maxHeight: 80, overflow: 'hidden' }}>
                  {s.content.slice(0, 280)}{s.content.length > 280 ? '…' : ''}
                </div>
              </div>
              {!readOnly && (
                <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignSelf: 'center' }}>
                  <button style={ghostBtn} onClick={() => onToggle?.(s)}>{s.enabled ? 'Disable' : 'Enable'}</button>
                  <button style={{ ...ghostBtn, color: '#dc2626' }} onClick={() => onRemove?.(s.id)}>
                    <Trash2 size={13} />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, background: '#fff',
}
const row: React.CSSProperties = {
  display: 'flex', gap: 12, padding: '12px 14px',
  border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff',
}
const input: React.CSSProperties = {
  fontSize: 13, color: '#0f172a', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600,
  color: '#334155', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 12px', cursor: 'pointer',
}
const catPill: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px',
  color: '#4338ca', background: '#eef2ff', textTransform: 'uppercase', letterSpacing: '0.03em',
}
const empty: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 18, background: '#f8fafc',
  fontSize: 13, color: '#64748b', textAlign: 'center',
}
