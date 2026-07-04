import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ArrowRight, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, GitMerge, Sparkles,
  CheckCircle2, MapPin, Users, Star, Link2, FileText, Target, ChevronDown, Globe, Bot,
} from 'lucide-react'
import { api } from '../lib/api'
import { StrategistReview } from '../components/StrategistReview'
import type { Client, ReoptAction, ReoptPlan } from '../lib/types'

// Action Plan — the reoptimization planner's surface. Reads the latest stored
// plan and lets the user rebuild it on demand. Every action deep-links into the
// tool that does the work; nothing is auto-executed (recommend-only).
export function ActionPlan() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: plan, isLoading } = useQuery<ReoptPlan | null>({
    queryKey: ['action-plan', id],
    queryFn: () => api.get<ReoptPlan | null>(`/clients/${id}/action-plan`),
    enabled: Boolean(id),
  })

  const refresh = useMutation({
    mutationFn: () => api.post<ReoptPlan>(`/clients/${id}/action-plan/refresh`, {}),
    onSuccess: (fresh) => {
      queryClient.setQueryData(['action-plan', id], fresh)
    },
  })

  const actions = plan?.items ?? []

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Action Plan</h1>
          {/* Q1: client name + created date up top. */}
          <div style={{ fontSize: 14, color: '#475569', fontWeight: 600, marginTop: 2 }}>
            {client?.name ?? 'Client'}
            {plan && (
              <span style={{ fontWeight: 400, color: '#94a3b8' }}>
                {'  ·  '}Created {new Date(plan.created_at).toLocaleDateString(undefined, {
                  year: 'numeric', month: 'long', day: 'numeric',
                })}
              </span>
            )}
          </div>
          <p style={{ fontSize: 13, color: '#94a3b8', margin: '6px 0 0' }}>
            Prioritized reoptimization recommendations from this client’s rank-tracker signals — organic drops to
            fix, winnable keywords, Search Console opportunities, and local-pack declines from the Maps geo-grid.
            Each routes you into the tool that does it.
          </p>
        </div>
        <button style={refreshBtn} onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw size={14} style={refresh.isPending ? { animation: 'spin 1s linear infinite' } : undefined} />
          {refresh.isPending ? 'Rebuilding…' : 'Rebuild'}
        </button>
      </div>

      {plan && (
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 20 }}>
          {plan.summary} · last built {new Date(plan.created_at).toLocaleString()}
          {plan.trigger !== 'manual' && ` · ${triggerLabel(plan.trigger)}`}
        </div>
      )}

      {/* SerMaStr — strategist review card (renders nothing while the feature
          flag is off and no reviews exist). Strategy sits above the task list. */}
      {id && <StrategistReview clientId={id} />}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : !plan ? (
        <div style={emptyBox}>
          No plan built yet. Click <strong>Rebuild</strong> to generate one from this client’s current signals.
        </div>
      ) : actions.length === 0 ? (
        <div style={{ ...emptyBox, color: '#16a34a', borderColor: '#bbf7d0', background: '#f0fdf4' }}>
          <CheckCircle2 size={18} style={{ verticalAlign: -3, marginRight: 6 }} />
          No actions right now — rankings look healthy.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {actions.map((a, i) => (
            <ActionRow key={`${a.kind}-${a.keyword}-${i}`} action={a} onGo={() => navigate('/' + a.cta_path.replace(/^\//, ''))} />
          ))}
        </div>
      )}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}

function ActionRow({ action, onGo }: { action: ReoptAction; onGo: () => void }) {
  const [open, setOpen] = useState(false)
  const c = sev(action.severity)
  const meta = kindMeta(action.kind)
  const ch = channel(action)
  const tgt = target(action)
  const guide = kindGuide(action.kind)
  return (
    <div style={{ ...row, borderLeft: `3px solid ${c.bar}` }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ color: c.bar, flexShrink: 0, marginTop: 2 }}>{meta.icon}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ ...pill, color: c.fg, background: c.bg }}>{meta.label}</span>
            {/* Q6: channel badge — organic vs local pack vs AI. */}
            <span style={{ ...chip, color: ch.fg, background: ch.bg }}>{ch.icon}{ch.label}</span>
          </div>
          {/* Q2: clearly-labelled keyword / target this action is for. */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.03em', fontWeight: 700 }}>
              {tgt.label}
            </span>
            <span style={{ fontWeight: 600, fontSize: 14, color: '#0f172a' }}>{tgt.value}</span>
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>{action.diagnosis}</div>
          <div style={{ fontSize: 13, color: '#334155', marginTop: 4, lineHeight: 1.5 }}>{action.recommendation}</div>
        </div>
        <button style={goBtn} onClick={onGo}>
          {action.cta_label} <ArrowRight size={13} />
        </button>
      </div>

      {/* Q3: dropdown with why this is recommended + what's needed. */}
      <button style={discloseBtn} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <ChevronDown size={13} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
        {open ? 'Hide details' : 'Why this & what’s needed'}
      </button>
      {open && (
        <div style={detailBox}>
          {/* SOP-grounded detail when a playbook is loaded; static guide otherwise. */}
          {action.detail && (action.detail.why || action.detail.steps?.length) ? (
            <>
              <div style={sopTag}>★ Tailored to your SOPs</div>
              <DetailBlock title="Why this is recommended">
                {action.detail.why || guide.why}
              </DetailBlock>
              <DetailBlock title="What’s needed">
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {(action.detail.steps?.length ? action.detail.steps : guide.needed).map((n, i) => (
                    <li key={i} style={{ marginBottom: 3 }}>{n}</li>
                  ))}
                </ul>
              </DetailBlock>
              {action.detail.sop_refs?.length ? (
                <DetailBlock title="Based on">{action.detail.sop_refs.join(' · ')}</DetailBlock>
              ) : null}
              <DetailBlock title="Signal source">{guide.source}</DetailBlock>
            </>
          ) : (
            <>
              <DetailBlock title="Why this is recommended">{guide.why}</DetailBlock>
              <DetailBlock title="What’s needed">
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                  {guide.needed.map((n, i) => (
                    <li key={i} style={{ marginBottom: 3 }}>{n}</li>
                  ))}
                </ul>
              </DetailBlock>
              <DetailBlock title="Signal source">{guide.source}</DetailBlock>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
        {title}
      </div>
      <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.5, marginTop: 2 }}>{children}</div>
    </div>
  )
}

function kindMeta(kind: string): { label: string; icon: React.ReactNode } {
  switch (kind) {
    case 'rank_drop': return { label: 'Ranking drop', icon: <AlertTriangle size={18} /> }
    case 'quick_win': return { label: 'Quick win', icon: <Sparkles size={18} /> }
    case 'cannibalization': return { label: 'Cannibalization', icon: <GitMerge size={18} /> }
    case 'maps_decline': return { label: 'Local pack decline', icon: <MapPin size={18} /> }
    case 'maps_competitor': return { label: 'Local competitor', icon: <Users size={18} /> }
    case 'maps_weak_area': return { label: 'Weak coverage area', icon: <MapPin size={18} /> }
    case 'gbp_gap': return { label: 'GBP gap', icon: <MapPin size={18} /> }
    case 'review_gap': return { label: 'Reviews', icon: <Star size={18} /> }
    case 'backlink_gap': return { label: 'Backlinks', icon: <Link2 size={18} /> }
    case 'content_gap': return { label: 'Content gap', icon: <FileText size={18} /> }
    case 'local_relevance': return { label: 'Local relevance', icon: <Target size={18} /> }
    case 'maps_solv_drop': return { label: 'Local share loss', icon: <TrendingDown size={18} /> }
    case 'brand_search_decline': return { label: 'Brand search down', icon: <TrendingDown size={18} /> }
    default: return { label: 'Opportunity', icon: <TrendingUp size={18} /> }
  }
}

// Q6: which tracking channel a recommendation comes from. Derived from the
// action's source + kind. (LLM/AI-visibility isn't a planner producer yet, but
// the badge is here so it reads correctly the moment it becomes one.)
function channel(action: ReoptAction): { label: string; fg: string; bg: string; icon: React.ReactNode } {
  if (action.kind === 'brand_search_decline')
    return { label: 'AI / LLM visibility', fg: '#7c3aed', bg: '#f5f3ff', icon: <Bot size={11} style={chIcon} /> }
  if (action.source === 'maps')
    return { label: 'Local pack · Maps geo-grid', fg: '#0369a1', bg: '#f0f9ff', icon: <MapPin size={11} style={chIcon} /> }
  return { label: 'Organic search', fg: '#047857', bg: '#ecfdf5', icon: <Globe size={11} style={chIcon} /> }
}

// Q2: an accurate label for the thing each action targets. Real search keywords
// for the organic/keyword-anchored kinds; place / profile / scope for the rest.
function target(action: ReoptAction): { label: string; value: string } {
  const v = action.keyword || '—'
  switch (action.kind) {
    case 'maps_weak_area': return { label: 'Area', value: v }
    case 'gbp_gap': return { label: 'Profile', value: v }
    case 'review_gap': return { label: 'Profile', value: v }
    case 'backlink_gap': return { label: 'Scope', value: v }
    case 'maps_solv_drop': return { label: 'Scope', value: v }
    case 'brand_search_decline': return { label: 'Scope', value: v }
    default: return { label: 'Keyword', value: v }
  }
}

// Q3: per-kind explanation of *why* the signal fired and *what's needed*, plus
// which signal produced it. Built client-side so existing stored plans get the
// richer detail too (no plan rebuild required).
function kindGuide(kind: string): { why: string; needed: string[]; source: string } {
  switch (kind) {
    case 'rank_drop':
      return {
        why: 'A keyword you track dropped in Google’s organic results by more than the alert threshold. Left alone, lost positions usually keep bleeding clicks.',
        needed: [
          'Capture a fresh SERP snapshot to see what changed (an AI Overview, a stronger competitor, or an intent shift).',
          'If the page is deindexed, run URL Inspection, fix robots/noindex/canonical, and resubmit.',
          'Otherwise reoptimize the ranking page (title, intent match, depth, internal links).',
        ],
        source: 'Organic rank tracker — an open rank-drop alert (GSC + DataForSEO).',
      }
    case 'quick_win':
      return {
        why: 'The Rankability score rates this SERP as winnable for you (Easy/Moderate) and the keyword carries real value, so the effort-to-reward is high.',
        needed: [
          'If you already rank in striking distance (≤20), reoptimize the existing page rather than building new.',
          'If you have no strong page yet, create a purpose-built page for the term.',
        ],
        source: 'Organic rank tracker — Rankability + estimated value (Quick wins).',
      }
    case 'cannibalization':
      return {
        why: 'Search Console shows more than one of your URLs competing for the same query, none of them ranking well — Google can’t decide which page to rank, so authority is split.',
        needed: [
          'Pick the single canonical page that should own the query.',
          '301-redirect or canonical the duplicates into it.',
          'Concentrate internal links on the canonical page.',
        ],
        source: 'GSC Research — query split across multiple URLs.',
      }
    case 'opportunity':
      return {
        why: 'This query already earns impressions but sits on page 2 (positions 11–30). A modest push often moves it to page 1, where almost all clicks are.',
        needed: [
          'Refresh and expand the page — more depth, current information, internal links.',
          'Strengthen on-page relevance to the query’s intent.',
        ],
        source: 'GSC Research — hidden wins (page-2 terms with demand).',
      }
    case 'maps_decline':
      return {
        why: 'Your position in the Google local pack slipped across the geo-grid for this keyword/sector — you’re losing visibility on map searches where you previously showed.',
        needed: [
          'Diagnose where on the grid you slipped in the Maps tracker.',
          'Reinforce local signals: GBP posts/categories, proximity-relevant reviews, and location-page content.',
        ],
        source: 'Maps geo-grid — open local-pack alert.',
      }
    case 'maps_competitor':
      return {
        why: 'A competitor is newly outranking you across the local-pack grid for this keyword — they changed something that’s working.',
        needed: [
          'Review their GBP: primary category, review count and velocity, photos, posts.',
          'Close the specific gaps you find against your own profile.',
        ],
        source: 'Maps geo-grid — competitor surge.',
      }
    case 'maps_weak_area':
      return {
        why: 'A cluster of geo-grid pins near this place rank poorly, meaning you have little local relevance for searches originating there.',
        needed: [
          'Create or strengthen a dedicated location page targeting this area.',
          'Tie GBP service-area and reviews to the area where possible.',
        ],
        source: 'Maps geo-grid — geocoded weak coverage areas (aggregated across your tracked Maps keywords).',
      }
    case 'gbp_gap':
      return {
        why: 'Your Google Business Profile has completeness or competitor-relative gaps. A fuller profile ranks better in the local pack and converts more.',
        needed: [
          'Complete the missing fields flagged in the diagnosis (description, categories, hours, photos, etc.).',
          'If competitor data is available, add the categories competitors use and close the review gap.',
        ],
        source: 'Maps tracker — GBP profile audit (vs captured competitor profiles, when available).',
      }
    case 'review_gap':
      return {
        why: 'Your review velocity trails competitors and/or recent negative reviews have landed — both weaken rating and local-pack strength.',
        needed: [
          'Run a review-generation push with recent customers, especially in weak coverage areas.',
          'Respond to negative reviews to protect the rating.',
        ],
        source: 'Maps tracker — review analytics vs competitors.',
      }
    case 'backlink_gap':
      return {
        why: 'Your domain authority (Domain Rating / referring domains) trails the local-pack competitor median, which caps how high your pages can rank for competitive terms.',
        needed: [
          'Build local citations and directory listings.',
          'Earn supplier, partner, and digital-PR links.',
          'Reclaim unlinked brand mentions.',
        ],
        source: 'Maps strategy — backlink profile vs competitors (run the Maps backlink fetch to populate this).',
      }
    case 'content_gap':
      return {
        why: 'Your page is thinner or missing topics that competitors ranking above you cover, so it under-serves the query’s intent.',
        needed: [
          'Add the missing sections/topics named in the diagnosis.',
          'Increase depth to match the competitor median — keeping it genuinely useful, not padding.',
        ],
        source: 'Maps strategy — content-intelligence comparison vs ranking competitors.',
      }
    case 'local_relevance':
      return {
        why: 'Your GBP, reviews, and pages don’t align with the tracked service/location as tightly as competitors’, weakening local relevance.',
        needed: [
          'Point the GBP at a dedicated service/location page.',
          'Align the primary category to the service.',
          'Encourage reviews that name the service and area.',
        ],
        source: 'Maps strategy — local-relevance scorecard vs competitors.',
      }
    case 'maps_solv_drop':
      return {
        why: 'Your share of the Top-3 local pack fell between scans — competitors are taking local market share across the grid.',
        needed: [
          'Strengthen GBP signals across the board (posts, categories, reviews).',
          'Improve location-page content across the grid.',
          'Review the SoLV trend and competitor gains in the Maps tracker.',
        ],
        source: 'Maps geo-grid — Share-of-Local-Voice drop (scan over scan).',
      }
    case 'brand_search_decline':
      return {
        why: 'Branded search demand is falling — fewer people are searching for you by name, which softens the easiest traffic you have.',
        needed: [
          'Rule out a tracking or seasonality cause first.',
          'Invest in brand-building and reputation: reviews, PR/mentions, branded campaigns.',
        ],
        source: 'Rank tracker — branded GSC impressions trend.',
      }
    default:
      return {
        why: 'An opportunity surfaced from this client’s rank-tracker signals.',
        needed: ['Open the linked tool to act on it.'],
        source: 'Rank tracker signals.',
      }
  }
}

function triggerLabel(trigger: string): string {
  switch (trigger) {
    case 'drop': return 'after a ranking drop'
    case 'maps_drop': return 'after a local-pack drop'
    default: return 'weekly digest'
  }
}

function sev(severity: string): { bar: string; fg: string; bg: string } {
  switch (severity) {
    case 'critical': return { bar: '#dc2626', fg: '#b91c1c', bg: '#fef2f2' }
    case 'warning': return { bar: '#f59e0b', fg: '#b45309', bg: '#fffbeb' }
    default: return { bar: '#6366f1', fg: '#4338ca', bg: '#eef2ff' }
  }
}

const backLinkStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  color: '#6366f1', textDecoration: 'none', fontSize: 13, marginBottom: 20,
}
const row: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 6, padding: '14px 16px',
  border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff',
}
const pill: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px',
  textTransform: 'uppercase', letterSpacing: '0.03em',
}
const chip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4,
  fontSize: 10, fontWeight: 700, borderRadius: 999, padding: '2px 8px',
  textTransform: 'uppercase', letterSpacing: '0.03em',
}
const chIcon: React.CSSProperties = { flexShrink: 0 }
const goBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0,
  fontSize: 12, fontWeight: 600, color: '#6366f1', background: '#eef2ff',
  border: 'none', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', alignSelf: 'center',
}
const discloseBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, alignSelf: 'flex-start',
  fontSize: 12, fontWeight: 600, color: '#6366f1', background: 'transparent',
  border: 'none', padding: '2px 0 0', cursor: 'pointer',
}
const detailBox: React.CSSProperties = {
  marginTop: 4, padding: '12px 14px', borderRadius: 8,
  background: '#f8fafc', border: '1px solid #e2e8f0',
}
const sopTag: React.CSSProperties = {
  display: 'inline-block', marginBottom: 8, fontSize: 10, fontWeight: 700,
  color: '#7c3aed', background: '#f5f3ff', borderRadius: 999, padding: '2px 8px',
  textTransform: 'uppercase', letterSpacing: '0.03em',
}
const refreshBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
  fontSize: 13, fontWeight: 600, color: '#334155', background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 14px', cursor: 'pointer',
}
const emptyBox: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 24, background: '#f8fafc',
  fontSize: 14, color: '#64748b', textAlign: 'center',
}
