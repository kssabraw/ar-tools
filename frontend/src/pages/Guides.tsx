import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, BookOpen, Rocket, ListChecks, FileText, Building2, Sparkles, TrendingUp,
  MapPin, Eye, FileSearch, FileBarChart, ClipboardList, Settings, LifeBuoy, ArrowRight,
  Plus, Pencil, Trash2,
} from 'lucide-react'
import { Markdown } from '../components/Markdown'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import type { Guide, GuideCategory } from '../lib/types'

// In-app Guides portal — DB-backed and admin-editable. Index (/guides) lists
// guides grouped by category; detail (/guides/:slug) renders one guide's Markdown.
// Admins get inline create/edit/delete. Content is seeded server-side from
// defaults and lives in the `guides` table thereafter.

const ICON_KEYS = [
  'Rocket', 'BookOpen', 'ListChecks', 'FileText', 'Building2', 'Sparkles',
  'TrendingUp', 'MapPin', 'Eye', 'FileSearch', 'FileBarChart', 'ClipboardList', 'Settings',
] as const

const ICONS: Record<string, React.ReactNode> = {
  Rocket: <Rocket size={20} />, BookOpen: <BookOpen size={20} />, ListChecks: <ListChecks size={20} />,
  FileText: <FileText size={20} />, Building2: <Building2 size={20} />, Sparkles: <Sparkles size={20} />,
  TrendingUp: <TrendingUp size={20} />, MapPin: <MapPin size={20} />, Eye: <Eye size={20} />,
  FileSearch: <FileSearch size={20} />, FileBarChart: <FileBarChart size={20} />,
  ClipboardList: <ClipboardList size={20} />, Settings: <Settings size={20} />,
}

const CATEGORIES: GuideCategory[] = ['Start here', 'Content', 'Tracking', 'Reporting', 'Setup']

function icon(key: string): React.ReactNode {
  return ICONS[key] ?? <BookOpen size={20} />
}

export function Guides() {
  const { slug } = useParams<{ slug: string }>()
  const { isAdmin } = useAuth()
  const [editing, setEditing] = useState<Guide | 'new' | null>(null)

  // Admins fetch disabled drafts too (so they can find + re-enable them).
  const { data: guides = [], isLoading } = useQuery<Guide[]>({
    queryKey: ['guides', isAdmin],
    queryFn: () => api.get<Guide[]>(`/guides${isAdmin ? '?include_disabled=true' : ''}`),
  })

  if (editing && isAdmin) {
    return <GuideEditor guide={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
  }
  if (slug) return <GuideDetail slug={slug} guides={guides} isAdmin={isAdmin} onEdit={setEditing} />

  const byCategory = CATEGORIES.map((cat) => ({
    cat, guides: guides.filter((g) => g.category === cat),
  })).filter((group) => group.guides.length > 0)

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <LifeBuoy size={20} /> Guides
          </h1>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '6px 0 24px' }}>
            How to use each module, upload your SOPs, set clients up, and more. New to the suite?
            Start with <strong>Getting started</strong>.
          </p>
        </div>
        {isAdmin && (
          <button style={primaryBtn} onClick={() => setEditing('new')}>
            <Plus size={14} /> New guide
          </button>
        )}
      </div>

      {isLoading ? (
        <div style={empty}>Loading…</div>
      ) : byCategory.length === 0 ? (
        <div style={empty}>No guides yet.{isAdmin && ' Click “New guide” to add one.'}</div>
      ) : (
        byCategory.map(({ cat, guides: list }) => (
          <div key={cat} style={{ marginBottom: 26 }}>
            <h2 style={catHeading}>{cat}</h2>
            <div style={grid}>
              {list.map((g) => (
                <Link key={g.id} to={`/guides/${g.slug}`} style={{ ...cardLink, opacity: g.enabled ? 1 : 0.55 }}>
                  <div style={{ color: '#6366f1', flexShrink: 0 }}>{icon(g.icon)}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>
                      {g.title}{!g.enabled && <span style={draftTag}>draft</span>}
                    </div>
                    <div style={{ fontSize: 12.5, color: '#64748b', marginTop: 3, lineHeight: 1.5 }}>{g.summary}</div>
                  </div>
                  <ArrowRight size={15} style={{ color: '#cbd5e1', flexShrink: 0, alignSelf: 'center' }} />
                </Link>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  )
}

function GuideDetail({ slug, guides, isAdmin, onEdit }: {
  slug: string; guides: Guide[]; isAdmin: boolean; onEdit: (g: Guide) => void
}) {
  const guide = guides.find((g) => g.slug === slug)
  return (
    <div style={{ padding: 32, maxWidth: 820 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Link to="/guides" style={backLink}><ArrowLeft size={14} /> All guides</Link>
        {isAdmin && guide && (
          <button style={ghostBtn} onClick={() => onEdit(guide)}><Pencil size={13} /> Edit</button>
        )}
      </div>
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

function GuideEditor({ guide, onClose }: { guide: Guide | null; onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isNew = guide === null
  const [form, setForm] = useState({
    slug: guide?.slug ?? '',
    title: guide?.title ?? '',
    category: (guide?.category ?? 'Setup') as GuideCategory,
    icon: guide?.icon ?? 'BookOpen',
    summary: guide?.summary ?? '',
    sort_order: guide?.sort_order ?? 0,
    body: guide?.body ?? '',
    enabled: guide?.enabled ?? true,
  })
  const [error, setError] = useState<string | null>(null)
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['guides'] })

  const save = useMutation({
    mutationFn: () =>
      isNew
        ? api.post<Guide>('/guides', form)
        : api.patch<Guide>(`/guides/${guide!.id}`, {
            title: form.title, category: form.category, icon: form.icon,
            summary: form.summary, sort_order: form.sort_order, body: form.body, enabled: form.enabled,
          }),
    onSuccess: () => { invalidate(); onClose() },
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Failed to save'),
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/guides/${guide!.id}`),
    onSuccess: () => { invalidate(); navigate('/guides') },
  })

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div style={{ padding: 32, maxWidth: 820 }}>
      <button style={backLink} onClick={onClose}><ArrowLeft size={14} /> Cancel</button>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: '0 0 16px' }}>
        {isNew ? 'New guide' : `Edit: ${guide!.title}`}
      </h1>

      <div style={card}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <input style={{ ...input, flex: 1, minWidth: 220 }} placeholder="Title"
                 value={form.title} onChange={(e) => set('title', e.target.value)} />
          <input style={{ ...input, width: 180 }} placeholder="slug (url)" disabled={!isNew}
                 value={form.slug} onChange={(e) => set('slug', e.target.value)} />
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
          <select style={input} value={form.category} onChange={(e) => set('category', e.target.value as GuideCategory)}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select style={input} value={form.icon} onChange={(e) => set('icon', e.target.value)}>
            {ICON_KEYS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <input style={{ ...input, width: 110 }} type="number" placeholder="order"
                 value={form.sort_order} onChange={(e) => set('sort_order', Number(e.target.value) || 0)} />
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#334155' }}>
            <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} /> Enabled
          </label>
        </div>
        <input style={{ ...input, width: '100%', marginBottom: 10 }} placeholder="One-line summary (shown on the card)"
               value={form.summary} onChange={(e) => set('summary', e.target.value)} />
        <textarea
          style={{ ...input, width: '100%', minHeight: 320, resize: 'vertical', fontFamily: 'ui-monospace, monospace', fontSize: 12.5 }}
          placeholder="Guide body (Markdown: # headings, **bold**, - bullets, tables, --- rules)"
          value={form.body} onChange={(e) => set('body', e.target.value)}
        />
        {error && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 6 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
          <button style={primaryBtn} disabled={save.isPending || !form.title.trim() || (isNew && !form.slug.trim())}
                  onClick={() => save.mutate()}>
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
          <button style={ghostBtn} onClick={onClose}>Cancel</button>
          {!isNew && (
            <button style={{ ...ghostBtn, color: '#dc2626', marginLeft: 'auto' }}
                    onClick={() => { if (confirm('Delete this guide?')) remove.mutate() }}>
              <Trash2 size={13} /> Delete
            </button>
          )}
        </div>
      </div>

      {/* Live preview */}
      {form.body.trim() && (
        <div style={{ marginTop: 20 }}>
          <h2 style={catHeading}>Preview</h2>
          <div style={article}><Markdown>{form.body}</Markdown></div>
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
  display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1',
  textDecoration: 'none', fontSize: 13, marginBottom: 20, background: 'none', border: 'none', cursor: 'pointer', padding: 0,
}
const article: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff', padding: '8px 24px 24px',
}
const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, background: '#fff',
}
const input: React.CSSProperties = {
  fontSize: 13, color: '#0f172a', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600,
  color: '#fff', background: '#6366f1', border: 'none', borderRadius: 8, padding: '8px 14px', cursor: 'pointer', flexShrink: 0,
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600,
  color: '#334155', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '7px 12px', cursor: 'pointer',
}
const draftTag: React.CSSProperties = {
  marginLeft: 8, fontSize: 10, fontWeight: 700, color: '#b45309', background: '#fffbeb',
  borderRadius: 999, padding: '1px 7px', textTransform: 'uppercase', letterSpacing: '0.03em',
}
const empty: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center',
}
