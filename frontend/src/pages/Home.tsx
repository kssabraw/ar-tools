import { Link } from 'react-router-dom'
import {
  PenLine, MapPin, Search, TrendingUp, Map, Activity, CalendarClock,
  ArrowRight,
} from 'lucide-react'

interface ModuleTile {
  label: string
  description: string
  icon: React.ReactNode
  to?: string
  status: 'active' | 'planned'
}

const modules: ModuleTile[] = [
  {
    label: 'Blog Writer',
    description: 'Generate SEO + AEO-optimized blog content through the five-module pipeline.',
    icon: <PenLine size={22} />,
    to: '/runs',
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

export function Home() {
  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>AR Tools</h1>
      <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px' }}>
        Internal agency suite. Pick a module to get started.
      </p>

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

          return m.status === 'active' && m.to ? (
            <Link key={m.label} to={m.to} style={{ ...tileStyle, ...activeTile }}>
              {inner}
            </Link>
          ) : (
            <div key={m.label} style={{ ...tileStyle, ...plannedTile }} aria-disabled>
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
const activeTile: React.CSSProperties = { cursor: 'pointer' }
const plannedTile: React.CSSProperties = { opacity: 0.7, cursor: 'default' }
const badgeStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#64748b',
  background: '#f1f5f9', borderRadius: 999, padding: '3px 10px',
}
