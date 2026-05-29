import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import {
  PenLine, MapPin, Search, TrendingUp, Map, Activity, CalendarClock,
  ArrowLeft, ArrowRight, Globe,
} from 'lucide-react'

interface ModuleTile {
  label: string
  description: string
  icon: React.ReactNode
  to?: (clientId: string) => string
  status: 'active' | 'planned'
}

const modules: ModuleTile[] = [
  {
    label: 'Blog Writer',
    description: 'Generate SEO + AEO-optimized blog content through the five-module pipeline.',
    icon: <PenLine size={22} />,
    to: (id) => `/runs?client=${id}`,
    status: 'active',
  },
  {
    label: 'Local SEO Content',
    description: 'Location-specific service pages and local content.',
    icon: <MapPin size={22} />,
    status: 'planned',
  },
  {
    label: 'Keyword Research',
    description: 'Discover and cluster keyword opportunities, enriched with Search Console data.',
    icon: <Search size={22} />,
    status: 'planned',
  },
  {
    label: 'Organic Rank Tracker',
    description: 'Daily organic positions for tracked keywords, with clicks & impressions.',
    icon: <TrendingUp size={22} />,
    status: 'planned',
  },
  {
    label: 'Maps Ranker',
    description: 'Local-pack and maps rankings across a geo-grid per client location.',
    icon: <Map size={22} />,
    status: 'planned',
  },
  {
    label: 'Ranking-Drop Agent',
    description: 'Detects ranking drops and recommends fixes from your SOPs.',
    icon: <Activity size={22} />,
    status: 'planned',
  },
  {
    label: 'Content Scheduler',
    description: 'Plan and auto-publish monthly blog and local SEO content per client.',
    icon: <CalendarClock size={22} />,
    status: 'planned',
  },
]

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>()

  const { data: client, isLoading } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20 }}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28 }}>
        {client?.logo_url ? (
          <img src={client.logo_url} alt="" style={{ width: 52, height: 52, borderRadius: 12, objectFit: 'contain', background: '#f8fafc', border: '1px solid #e2e8f0' }} />
        ) : (
          <div style={{ width: 52, height: 52, borderRadius: 12, background: '#eef2ff' }} />
        )}
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>
            {isLoading ? 'Loading…' : client?.name ?? 'Client'}
          </h1>
          {client?.website_url && (
            <a href={client.website_url} target="_blank" rel="noreferrer"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#6366f1', textDecoration: 'none' }}>
              <Globe size={12} /> {client.website_url}
            </a>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {modules.map(m => {
          const inner = (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 44, height: 44, borderRadius: 10,
                  background: m.status === 'active' ? '#eef2ff' : '#f1f5f9',
                  color: m.status === 'active' ? '#6366f1' : '#94a3b8',
                }}>
                  {m.icon}
                </div>
                {m.status === 'planned' ? (
                  <span style={badgeStyle}>Coming soon</span>
                ) : (
                  <ArrowRight size={18} color="#6366f1" />
                )}
              </div>
              <div style={{ marginTop: 14, fontWeight: 600, fontSize: 15, color: m.status === 'active' ? '#0f172a' : '#64748b' }}>
                {m.label}
              </div>
              <div style={{ marginTop: 4, fontSize: 13, color: '#94a3b8', lineHeight: 1.5 }}>
                {m.description}
              </div>
            </>
          )

          return m.status === 'active' && m.to && id ? (
            <Link key={m.label} to={m.to(id)} style={{ ...tileStyle, cursor: 'pointer' }}>
              {inner}
            </Link>
          ) : (
            <div key={m.label} style={{ ...tileStyle, opacity: 0.7, cursor: 'default' }} aria-disabled>
              {inner}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const tileStyle: React.CSSProperties = {
  display: 'block',
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 20,
  textDecoration: 'none',
}
const badgeStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#64748b',
  background: '#f1f5f9', borderRadius: 999, padding: '3px 10px',
}
