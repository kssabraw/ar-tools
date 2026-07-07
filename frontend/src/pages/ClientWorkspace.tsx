import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import {
  PenLine, MapPin, Search, TrendingUp, Map, Activity, CalendarClock,
  ArrowLeft, ArrowRight, Globe, Building2, Sparkles, Users, FileSearch, FileText, Eye, ListChecks, FileBarChart, UploadCloud,
  ClipboardList, BookOpen, Share2, Target, Swords,
} from 'lucide-react'
import { ClientNotifications } from '../components/ClientNotifications'
import { FreezeBanner } from '../components/FreezeBanner'
import { StrategistReview } from '../components/StrategistReview'

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>()

  const { data: client, isLoading } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  // Surface how many Local SEO pages this client already has (otherwise saved
  // pages are only reachable via the New-Page flow's "Saved" tab — easy to miss).
  const { data: localSeoPages } = useQuery<Array<{ id: string }>>({
    queryKey: ['local-seo-pages', id],
    queryFn: () => api.get<Array<{ id: string }>>(`/clients/${id}/local-seo/pages`),
    enabled: Boolean(id),
  })
  const savedLocalSeoCount = localSeoPages?.length ?? 0

  // Count of service pages generated for this client (service_page runs).
  const { data: servicePageRuns } = useQuery<{ total: number }>({
    queryKey: ['service-page-runs', id],
    queryFn: () => api.get<{ total: number }>(`/runs?client_id=${id}&content_type=service_page&page_size=1`),
    enabled: Boolean(id),
  })
  const savedServicePageCount = servicePageRuns?.total ?? 0

  // Count of location pages generated for this client (location_page runs).
  const { data: locationPageRuns } = useQuery<{ total: number }>({
    queryKey: ['location-page-runs', id],
    queryFn: () => api.get<{ total: number }>(`/runs?client_id=${id}&content_type=location_page&page_size=1`),
    enabled: Boolean(id),
  })
  const savedLocationPageCount = locationPageRuns?.total ?? 0

  // Count of syndication items already published (public Doc + Sheet) for this
  // client, surfaced on the Content Syndication card.
  const { data: syndicationData } = useQuery<{ counts: { published: number } }>({
    queryKey: ['syndication-counts', id],
    queryFn: () => api.get<{ counts: { published: number } }>(`/clients/${id}/syndication/items?limit=1`),
    enabled: Boolean(id),
  })
  const syndicationPublishedCount = syndicationData?.counts?.published ?? 0

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

      {id && <FreezeBanner clientId={id} />}
      {/* SerMaStr — strategist review as its own section, directly under the
          Freeze Protocol banner and above Client setup. Renders nothing when
          the strategist is off and no review exists (so quiet clients stay
          clean). */}
      {id && <StrategistReview clientId={id} />}
      {id && <ClientNotifications clientId={id} />}

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
        <ActionCard
          icon={<Sparkles size={22} />}
          label="Brand Voice"
          description={brandVoiceCopy(client)}
          to={id ? `/clients/${id}/brand-voice` : undefined}
          cta={brandVoiceHasContent(client) ? 'Edit' : 'Set up'}
          highlight={!brandVoiceHasContent(client)}
        />
        <ActionCard
          icon={<Users size={22} />}
          label="ICP & Differentiators"
          description={icpCopy(client)}
          to={id ? `/clients/${id}/icp` : undefined}
          cta={icpHasContent(client) ? 'Edit' : 'Set up'}
          highlight={!icpHasContent(client)}
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
          description={
            savedLocalSeoCount > 0
              ? `Location-specific service pages. ${savedLocalSeoCount} saved page${savedLocalSeoCount === 1 ? '' : 's'} for this client.`
              : 'Location-specific service pages and local content.'
          }
          to={id ? `/clients/${id}/local-seo` : undefined}
          cta="Create"
          footer={
            savedLocalSeoCount > 0 && id ? (
              <Link to={`/clients/${id}/local-seo?tab=saved`} style={footerLinkStyle}>
                View {savedLocalSeoCount} saved page{savedLocalSeoCount === 1 ? '' : 's'} <ArrowRight size={13} />
              </Link>
            ) : undefined
          }
        />
        <ActionCard
          icon={<FileText size={22} />}
          label="Create Service Pages"
          description={
            savedServicePageCount > 0
              ? `Conversion-focused service / landing pages. ${savedServicePageCount} generated for this client.`
              : 'Conversion-focused service / landing pages, brief + writer in one run.'
          }
          to={id ? `/clients/${id}/service-pages` : undefined}
          cta="Create"
          footer={
            savedServicePageCount > 0 && id ? (
              <Link to={`/clients/${id}/service-pages`} style={footerLinkStyle}>
                View {savedServicePageCount} page{savedServicePageCount === 1 ? '' : 's'} <ArrowRight size={13} />
              </Link>
            ) : undefined
          }
        />
        <ActionCard
          icon={<MapPin size={22} />}
          label="Create Location Pages"
          description={
            savedLocationPageCount > 0
              ? `Multi-service pages targeting one location. ${savedLocationPageCount} generated for this client.`
              : 'Location landing pages covering every major service in one area — brief + writer in one run.'
          }
          to={id ? `/clients/${id}/location-pages` : undefined}
          cta="Create"
          footer={
            savedLocationPageCount > 0 && id ? (
              <Link to={`/clients/${id}/location-pages`} style={footerLinkStyle}>
                View {savedLocationPageCount} page{savedLocationPageCount === 1 ? '' : 's'} <ArrowRight size={13} />
              </Link>
            ) : undefined
          }
        />
        <ActionCard
          icon={<CalendarClock size={22} />}
          label="Create Mass Posts"
          description="Plan and mass-generate this client's blog posts & Local SEO pages on a monthly schedule — opens the Topic Fan-out keyword-research, planning & scheduling tool."
          href={id ? `/fanout/?client_id=${id}&client_name=${encodeURIComponent(client?.name ?? '')}` : '/fanout/'}
          cta="Open"
        />
        <ActionCard
          icon={<FileSearch size={22} />}
          label="Plan a Content Silo"
          description="Research the parent, sibling & neighbourhood pages a topic needs — and see which already exist on this client’s site."
          to={id ? `/clients/${id}/local-seo?tab=plan` : undefined}
          cta="Plan"
        />
        <ActionCard
          icon={<UploadCloud size={22} />}
          label="Publish to Google Docs"
          description="Select already-generated articles & Local SEO pages and publish them to this client's Drive folder in one batch."
          to={id ? `/clients/${id}/content` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<Share2 size={22} />}
          label="Content Syndication"
          description={
            syndicationPublishedCount > 0
              ? `Auto-rewrites this client's new blog posts, pages & products into public Google Docs + Sheets that link back. ${syndicationPublishedCount} published.`
              : "Auto-rewrites this client's new blog posts, pages & products into unique, search-discoverable Google Docs + Sheets that link back to the site."
          }
          to={id ? `/clients/${id}/syndication` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<BookOpen size={22} />}
          label="Citations"
          description="Liveness tracking for ordered citations — paste the URLs from vendor deliverables; a weekly sweep flags listings that stop resolving."
          to={id ? `/clients/${id}/citations` : undefined}
          cta="Open"
        />
      </Section>

      {/* ── Rank Trackers ───────────────────────────────────────────── */}
      <Section
        title="Rank Trackers"
        subtitle="Track organic and local-pack positions over time."
      >
        <ActionCard
          icon={<TrendingUp size={22} />}
          label="Organic Rank Tracker"
          description="Connect Search Console to track organic positions, clicks & impressions. Keyword tracking comes online once a property is verified."
          to={id ? `/clients/${id}/rankings` : undefined}
          cta="Connect"
        />
        <ActionCard
          icon={<Map size={22} />}
          label="Maps Ranker"
          description="Local-pack and Maps rankings across a geo-grid around this client's business."
          to={id ? `/clients/${id}/maps` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<FileSearch size={22} />}
          label="GSC Research"
          description="Mine Search Console for opportunities — keyword cannibalization, quick wins (pos 6–10) & hidden wins (pos 11–30), enriched with CPC & volume."
          to={id ? `/clients/${id}/gsc-research` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<Eye size={22} />}
          label="AI Visibility"
          description="Track whether this brand shows up in AI assistant answers — ChatGPT, Claude, Gemini, Perplexity & Google AI Overviews — across your keywords, over time."
          to={id ? `/clients/${id}/ai-visibility` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<Target size={22} />}
          label="Campaign Goals"
          description="What success means for this client — rank, traffic, AI-visibility & local-pack targets with live on-track / behind status. SerMaStr judges every review and answer against these."
          to={id ? `/clients/${id}/goals` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<TrendingUp size={22} />}
          label="Forecast"
          description="Where the campaign is heading at the current trend — projected positions, est. traffic & value in 90 days, the quick-win upside in clicks & dollars, and goal trajectories."
          to={id ? `/clients/${id}/forecast` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<Swords size={22} />}
          label="Competitive Intel"
          description="Who you're up against, unified across every tracker — local-pack pins, GBP reviews, authority, organic overlap & the new pages they publish. Auto-discovered weekly."
          to={id ? `/clients/${id}/competitors` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<ListChecks size={22} />}
          label="Action Plan"
          description="A prioritized reoptimization to-do list built from this client's rank signals — drops to fix, winnable quick wins & Search Console opportunities, each linked to the tool that does it."
          to={id ? `/clients/${id}/action-plan` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<ClipboardList size={22} />}
          label="Monthly Task Plan"
          description="The Recipe Engine: budget + diagnosis → a costed, assigned month of work — baseline stack, Diagnose-and-Fund, capacity-capped content, every line with an owner."
          to={id ? `/clients/${id}/task-plan` : undefined}
          cta="Open"
        />
        <ActionCard
          icon={<BookOpen size={22} />}
          label="SOPs & Playbook"
          description="This client's SOPs plus the agency-wide playbook & theories. Loaded SOPs ground the Action Plan's recommendations in your own methodology and voice."
          to={id ? `/clients/${id}/sops` : undefined}
          cta="Open"
        />
      </Section>

      {/* ── Project Management ──────────────────────────────────────── */}
      <Section
        title="Project Management"
        subtitle="Plan and dispatch this client's delivery work."
      >
        <ActionCard
          icon={<ClipboardList size={22} />}
          label="Asana Tasks"
          description="Define the tasks this client gets each month — name, assignee & category. The monthly job creates them in Asana under a new section, automatically or on demand."
          to={id ? `/clients/${id}/asana-tasks` : undefined}
          cta="Open"
        />
      </Section>

      {/* ── Reporting ────────────────────────────────────────────────── */}
      <Section
        title="Reporting"
        subtitle="Generate client-facing performance reports."
      >
        <ActionCard
          icon={<FileBarChart size={22} />}
          label="Client Reports"
          description="Generate a PDF performance report — organic rankings, local-pack geo-grids & Google Business Profile. (Analytics, Asana & a campaign-health summary land in later phases.)"
          to={id ? `/clients/${id}/reports` : undefined}
          cta="Open"
        />
      </Section>

      {/* ── More tools (de-emphasized roadmap) ──────────────────────── */}
      <Section title="More tools" subtitle="Additional modules on the roadmap.">
        {moreTools.map(t => {
          // Carry the current client into the Fanout app so it shows only this
          // client's runs (client-scoped runs) and tags new runs to it.
          const href = t.href && id
            ? `${t.href}?client_id=${id}&client_name=${encodeURIComponent(client?.name ?? '')}`
            : t.href
          return (
            <ActionCard
              key={t.label}
              icon={t.icon}
              label={t.label}
              description={t.description}
              href={href}
              cta={href ? 'Open' : undefined}
              badge="Coming soon"
              compact
            />
          )
        })}
      </Section>
    </div>
  )
}

function brandVoiceHasContent(client?: Client): boolean {
  const bv = client?.brand_voice
  return Boolean(bv && (bv.raw_text || bv.current_voice || bv.recommended_voice))
}

function brandVoiceCopy(client?: Client): string {
  const bv = client?.brand_voice
  if (!brandVoiceHasContent(client)) {
    return 'Set the tone, personality, and wording — used by both the Blog Writer and Local SEO. Add your own or let the app draft one.'
  }
  return (bv?.source === 'user' || Boolean(bv?.raw_text))
    ? 'Set by you — your voice supersedes the app-generated one across both tools.'
    : 'AI-generated — review, edit, or replace it with your own.'
}

function icpHasContent(client?: Client): boolean {
  const icp = client?.detected_icp
  return Boolean((icp && (icp.raw_text || icp.segments?.length)) || client?.differentiators?.length)
}

function icpCopy(client?: Client): string {
  const icp = client?.detected_icp
  if (!icpHasContent(client)) {
    return 'Define who this client serves and what sets them apart — fed into both the Blog Writer and Local SEO. Add your own or let the app detect it.'
  }
  return (icp?.source === 'user' || Boolean(icp?.raw_text))
    ? 'Set by you — your profile supersedes the app-detected one across both tools.'
    : 'AI-detected — review, edit, or replace it with your own.'
}

const moreTools: { label: string; description: string; icon: React.ReactNode; href?: string }[] = [
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
  /** Full-page navigation (used to open a separately-built suite section, e.g. /fanout). */
  href?: string
  cta?: string
  badge?: string
  compact?: boolean
  highlight?: boolean
  footer?: React.ReactNode
}

function ActionCard({ icon, label, description, to, href, cta, badge, compact, highlight, footer }: ActionCardProps) {
  const active = Boolean(to || href)
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

  if (active) {
    const tileLinkStyle: React.CSSProperties = {
      ...tileStyle,
      cursor: 'pointer',
      ...(highlight ? { borderColor: '#c7d2fe', background: '#f8faff' } : {}),
    }
    // `href` does a real navigation into a separately-built section (the Fanout
    // app under /fanout); `to` is in-app react-router navigation.
    const tile = href ? (
      <a href={href} style={tileLinkStyle}>
        {inner}
      </a>
    ) : (
      <Link to={to!} style={tileLinkStyle}>
        {inner}
      </Link>
    )
    // footer is a separate link rendered as a sibling (can't nest <a> in <a>).
    if (!footer) return tile
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {tile}
        {footer}
      </div>
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
const footerLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 12, fontWeight: 600, color: '#6366f1', textDecoration: 'none', padding: '2px 4px',
}
const badgeStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#64748b',
  background: '#f1f5f9', borderRadius: 999, padding: '3px 10px',
}
