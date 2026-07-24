import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Globe, Radar, Search } from 'lucide-react'
import { api } from '../lib/api'
import type { ClientListItem } from '../lib/types'

// Domain Intelligence landing (the "SEMrush clone", global sidebar entry).
// The tool itself is client-scoped — every endpoint lives under
// /clients/{id}/domain-intel — so this global entry is a client picker that
// jumps into the chosen client's Domain Intelligence workspace.

export function DomainIntelHome() {
  const { data: clients = [], isLoading } = useQuery<ClientListItem[]>({
    queryKey: ['clients'],
    queryFn: () => api.get<ClientListItem[]>('/clients'),
  })

  const [q, setQ] = useState('')
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return clients
    return clients.filter(
      (c) =>
        c.name.toLowerCase().includes(needle) ||
        (c.website_url ?? '').toLowerCase().includes(needle),
    )
  }, [clients, q])

  return (
    <div style={{ padding: 32, maxWidth: 820 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <Radar size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Domain Intelligence</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, margin: '0 0 24px', lineHeight: 1.5 }}>
        Point at any domain — a competitor, a prospect, or a client's own site — and see its
        estimated organic traffic, authority, and keyword gaps. The SEMrush-style
        research view. Pick a client to open its Domain Intelligence workspace.
      </p>

      <div style={{ position: 'relative', marginBottom: 16 }}>
        <Search size={15} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#94a3b8' }} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search clients…"
          style={{
            width: '100%', padding: '10px 12px 10px 34px', borderRadius: 8,
            border: '1px solid #e2e8f0', fontSize: 14, boxSizing: 'border-box',
          }}
        />
      </div>

      {isLoading ? (
        <div style={{ color: '#64748b', fontSize: 14 }}>Loading clients…</div>
      ) : filtered.length === 0 ? (
        <div style={{ ...cardStyle, textAlign: 'center', color: '#64748b', padding: 40 }}>
          {clients.length === 0 ? 'No clients yet.' : 'No clients match your search.'}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {filtered.map((c) => (
            <Link
              key={c.id}
              to={`/clients/${c.id}/domain-intel`}
              style={{ ...cardStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between', textDecoration: 'none' }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: 15, color: '#0f172a', marginBottom: 4 }}>{c.name}</div>
                {c.website_url && (
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#6366f1' }}>
                    <Globe size={12} /> {c.website_url}
                  </div>
                )}
              </div>
              <span style={{ fontSize: 13, fontWeight: 600, color: '#6366f1' }}>Open →</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

const cardStyle: React.CSSProperties = {
  background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 20,
}
