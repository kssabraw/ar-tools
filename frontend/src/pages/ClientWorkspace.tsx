import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import {
  PenLine, MapPin, Search, TrendingUp, Map, Activity, CalendarClock,
  ArrowLeft, ArrowRight, Globe, Building2,
} from 'lucide-react'

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>()

  const { data: client, isLoading } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  return (
    <div style={{ padding: 32, maxWidth: 1100 }}>
      <Link to="/" style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to Dashboard
      </Link>

      {/* Client header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 32 }}>
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

      {/* ── Client setup ─────────────────────────────────────────────── */}
      <Section
        title="Client setup"
        subtitle="The business context the content & ranking tools draw on."
      >
        <ActionCard
          icon={<Building2 size={22} />}
          label="Business Profile"
          description={
            client?.gbp?.business_name
              ? `Linked: ${client.gbp.business_name}${client.gbp.address ? ` · ${client.gbp.address}` : ''}`
              : 'Attach this client’s Google Business Profile — address, category, rating, and top reviews.'
          }
          to={id ? `/clients/${id}/edit#gbp` : undefined}
          cta={client?.gbp?.business_name ? 'Edit' : 'Set up'}
          highlight={!client?.gbp?.business_name}
        />
      </Section>

      {/* ── Content ──────────────────────────────────────────────────── */}
      <Section
        title="Content"
        subtitle="Generate publication-ready content for this client."
      >
        <ActionCard
          icon={<PenLine size={22} />}
          label="Create Blog Post"
          description="Generate an SEO + AEO-optimized article through the five-module pipeline."
          to={id ? `/runs?client=${id}&new=1` : undefined}
          cta="Create"
        />
        <ActionCard
          icon={<MapPin size={22} />}
          label="Create Local SEO Content"
          description="Location-specific service pages and local content."
          badge="Setup in progress"
        />
      </Section>

      {/* ── Rank Trackers ───────────────────────────────────────────── */}
      <Section
        title="Rank Trackers"
        subtitle="Track organic and local-pack positions over time. Coming in the next phase."
      >
        <ActionCard
          icon={<TrendingUp size={22} />}
          label="Organic Rank Tracker"
          description="Daily organic positions for tracked keywords, with clicks & impressions from Search Console."
          badge="Coming soon"
        />
        <ActionCard
          icon={<Map size={22} />}
          label="Maps Ranker"
          description="Local-pack and maps rankings across a geo-grid for this client's location."
          badge="Coming soon"
        />
      </Section>

      {/* ── More tools (de-emphasized roadmap) ──────────────────────── */}
      <Section title="More tools" subtitle="Additional modules on the roadmap.">
        {moreTools.map(t => (
          <ActionCard
            key={t.label}
            icon={t.icon}
            label={t.label}
            description={t.description}
            badge="Coming soon"
            compact
          />
        ))}
      </Section>
    </div>
  )
}

const moreTools = [
  {
    label: 'Keyword Research',
    description: 'Discover and cluster keyword opportunities, enriched with Search Console data.',
    icon: <Search size={20} />,
  },
  {
    label: 'Ranking-Drop Agent',
    description: 'Detects ranking drops and recommends fixes from your SOPs.',
    icon: <Activity size={20} />,
  },
  {
    label: 'Content Scheduler',
    description: 'Plan and auto-publish monthly blog and local SEO content per client.',
    icon: <CalendarClock size={20} />,
  },
]

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 32 }}>
      <h2 style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', margin: '0 0 2px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {title}
      </h2>
      {subtitle && <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 14px' }}>{subtitle}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
        {children}
      </div>
    </section>
  )
}

interface ActionCardProps {
  icon: React.ReactNode
  label: string
  description: string
  to?: string
  cta?: string
  badge?: string
  compact?: boolean
  highlight?: boolean
}

function ActionCard({ icon, label, description, to, cta, badge, compact, highlight }: ActionCardProps) {
  const active = Boolean(to)
  const inner = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: compact ? 38 : 44, height: compact ? 38 : 44, borderRadius: 10,
          background: active ? '#eef2ff' : '#f1f5f9',
          color: active ? '#6366f1' : '#94a3b8',
        }}>
          {icon}
        </div>
        {active ? (
          <span style={ctaStyle}>{cta ?? 'Open'} <ArrowRight size={14} /></span>
        ) : (
          <span style={badgeStyle}>{badge ?? 'Coming soon'}</span>
        )}
      </div>
      <div style={{ marginTop: 14, fontWeight: 600, fontSize: 15, color: active ? '#0f172a' : '#64748b' }}>
        {label}
      </div>
      <div style={{ marginTop: 4, fontSize: 13, color: '#94a3b8', lineHeight: 1.5 }}>
        {description}
      </div>
    </>
  )

  if (active && to) {
    return (
      <Link
        to={to}
        style={{
          ...tileStyle,
          cursor: 'pointer',
          ...(highlight ? { borderColor: '#c7d2fe', background: '#f8faff' } : {}),
        }}
      >
        {inner}
      </Link>
    )
  }
  return (
    <div style={{ ...tileStyle, opacity: 0.75, cursor: 'default' }} aria-disabled>
      {inner}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const tileStyle: React.CSSProperties = {
  display: 'block',
  background: '#fff',
  border: '1px solid #e2e8f0',
  borderRadius: 12,
  padding: 20,
  textDecoration: 'none',
}
const ctaStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#6366f1',
  background: '#eef2ff', borderRadius: 999, padding: '4px 10px',
}
const badgeStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#64748b',
  background: '#f1f5f9', borderRadius: 999, padding: '3px 10px',
}
