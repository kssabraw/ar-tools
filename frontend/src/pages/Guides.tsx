import { Link, useParams } from 'react-router-dom'
import {
  ArrowLeft, BookOpen, Rocket, ListChecks, FileText, Building2, Sparkles, TrendingUp,
  MapPin, Eye, FileSearch, FileBarChart, ClipboardList, Settings, LifeBuoy, ArrowRight,
} from 'lucide-react'
import { Markdown } from '../components/Markdown'
import { GUIDES, type Guide, type GuideCategory } from '../lib/guides'

// In-app Guides portal — how to use each module, upload SOPs, set up clients, etc.
// Index (/guides) lists guides grouped by category; detail (/guides/:slug) renders
// one guide's Markdown body. Content lives in lib/guides.ts.

const ICONS: Record<string, React.ReactNode> = {
  Rocket: <Rocket size={20} />,
  BookOpen: <BookOpen size={20} />,
  ListChecks: <ListChecks size={20} />,
  FileText: <FileText size={20} />,
  Building2: <Building2 size={20} />,
  Sparkles: <Sparkles size={20} />,
  TrendingUp: <TrendingUp size={20} />,
  MapPin: <MapPin size={20} />,
  Eye: <Eye size={20} />,
  FileSearch: <FileSearch size={20} />,
  FileBarChart: <FileBarChart size={20} />,
  ClipboardList: <ClipboardList size={20} />,
  Settings: <Settings size={20} />,
}

const CATEGORY_ORDER: GuideCategory[] = ['Start here', 'Content', 'Tracking', 'Reporting', 'Setup']

function icon(key: string): React.ReactNode {
  return ICONS[key] ?? <BookOpen size={20} />
}

export function Guides() {
  const { slug } = useParams<{ slug: string }>()
  if (slug) return <GuideDetail slug={slug} />

  const byCategory = CATEGORY_ORDER.map((cat) => ({
    cat,
    guides: GUIDES.filter((g) => g.category === cat),
  })).filter((group) => group.guides.length > 0)

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        <LifeBuoy size={20} /> Guides
      </h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '6px 0 24px' }}>
        How to use each module, upload your SOPs, set clients up, and more. New to the suite?
        Start with <strong>Getting started</strong>.
      </p>

      {byCategory.map(({ cat, guides }) => (
        <div key={cat} style={{ marginBottom: 26 }}>
          <h2 style={catHeading}>{cat}</h2>
          <div style={grid}>
            {guides.map((g) => (
              <Link key={g.slug} to={`/guides/${g.slug}`} style={cardLink}>
                <div style={{ color: '#6366f1', flexShrink: 0 }}>{icon(g.icon)}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>{g.title}</div>
                  <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 3, lineHeight: 1.5 }}>{g.summary}</div>
                </div>
                <ArrowRight size={15} style={{ color: '#cbd5e1', flexShrink: 0, alignSelf: 'center' }} />
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function GuideDetail({ slug }: { slug: string }) {
  const guide: Guide | undefined = GUIDES.find((g) => g.slug === slug)
  return (
    <div style={{ padding: 32, maxWidth: 820 }}>
      <Link to="/guides" style={backLink}>
        <ArrowLeft size={14} /> All guides
      </Link>
      {!guide ? (
        <div style={empty}>Guide not found. <Link to="/guides" style={{ color: '#6366f1' }}>Back to all guides</Link>.</div>
      ) : (
        <div style={article}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#6366f1', marginBottom: 4 }}>
            {icon(guide.icon)}
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#94a3b8' }}>
              {guide.category}
            </span>
          </div>
          <Markdown>{guide.body}</Markdown>
        </div>
      )}
    </div>
  )
}

const catHeading: React.CSSProperties = {
  fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase',
  letterSpacing: '0.04em', margin: '0 0 10px',
}
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10,
}
const cardLink: React.CSSProperties = {
  display: 'flex', alignItems: 'flex-start', gap: 12, padding: '14px 16px',
  border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', textDecoration: 'none',
}
const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const article: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', padding: '8px 24px 24px',
}
const empty: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center',
}
