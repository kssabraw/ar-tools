import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft, ExternalLink, Link2, RefreshCw, Search, TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Backlink explorer — an any-domain Site Explorer over the DataForSEO Backlinks
// API family. Overview / referring domains / anchors / history are cached per
// target (24h TTL) server-side; the individual-link list is fetched on demand
// (one-per-domain by default) to bound cost.

interface Overview {
  referring_domains: number | null
  backlinks: number | null
  dofollow: number | null
  nofollow: number | null
  broken_backlinks: number | null
  referring_ips: number | null
  referring_subnets: number | null
  domain_rating: number | null
}
interface ReferringDomain {
  domain: string; domain_rating: number | null; backlinks: number | null
  dofollow: number | null; first_seen: string | null; last_seen: string | null
  is_new: boolean; is_lost: boolean
}
interface Anchor { anchor: string | null; backlinks: number | null; referring_domains: number | null; dofollow: number | null }
interface HistoryPoint { date: string; referring_domains: number | null; backlinks: number | null }
interface LookupResponse {
  target: string; target_type: string; cached: boolean; captured_at: string | null
  overview: Overview; referring_domains: ReferringDomain[]; anchors: Anchor[]; history: HistoryPoint[]
}
interface BacklinkLink {
  url_from: string | null; domain_from: string | null; url_to: string | null; anchor: string | null
  dofollow: boolean | null; domain_rating: number | null; page_rating: number | null
  first_seen: string | null; is_new: boolean; is_lost: boolean; is_broken: boolean
}
interface LinksResponse { total_count: number | null; links: BacklinkLink[]; limit: number; offset: number; filter: string }

const LINK_FILTERS = ['all', 'dofollow', 'nofollow', 'new', 'lost', 'broken'] as const
type LinkFilter = (typeof LINK_FILTERS)[number]

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString()
}
function shortDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 10)
}

export function Backlinks() {
  const { id } = useParams<{ id: string }>()
  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [tab, setTab] = useState<'overview' | 'links'>('overview')

  // Prefill + auto-analyze the client's own domain when opened from a workspace.
  useEffect(() => {
    if (client?.website_url && !query) {
      setQuery(client.website_url)
      setSubmitted(client.website_url)
    }
  }, [client?.website_url]) // eslint-disable-line react-hooks/exhaustive-deps

  const lookup = useMutation({
    mutationFn: (vars: { target: string; force: boolean }) =>
      api.post<LookupResponse>('/backlinks/lookup', {
        target: vars.target, client_id: id ?? null, force: vars.force,
      }),
  })

  function analyze(force = false) {
    const t = query.trim()
    if (!t) return
    setSubmitted(t)
    setTab('overview')
    lookup.mutate({ target: t, force })
  }

  const data = lookup.data
  const ov = data?.overview

  return (
    <div style={{ padding: 32, maxWidth: 1040 }}>
      {id && (
        <Link to={`/clients/${id}`} style={backLink}>
          <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
        </Link>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 4px' }}>
        <Link2 size={22} color="#4f46e5" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Backlink Explorer</h1>
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 18px' }}>
        Look up the backlink profile of any domain, subdomain, or URL. Overview, referring domains,
        anchors and history are cached for 24h; the full link list is fetched on demand.
      </p>

      {/* Search bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={15} style={{ position: 'absolute', left: 11, top: 10, color: '#94a3b8' }} />
          <input
            style={{ ...input, paddingLeft: 32 }}
            placeholder="example.com  ·  blog.example.com  ·  example.com/page"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') analyze(false) }}
          />
        </div>
        <button style={primaryBtn} disabled={lookup.isPending || !query.trim()} onClick={() => analyze(false)}>
          <Search size={14} /> Analyze
        </button>
        {data && (
          <button style={ghostBtn} disabled={lookup.isPending} onClick={() => analyze(true)} title="Force a fresh pull (ignores the 24h cache)">
            <RefreshCw size={14} style={lookup.isPending ? { animation: 'spin 1s linear infinite' } : undefined} /> Refresh
          </button>
        )}
      </div>

      {lookup.isPending && <div style={emptyBox}>Pulling backlink data for {submitted}…</div>}
      {lookup.isError && (
        <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>
          {(lookup.error as Error).message === 'dataforseo_not_configured'
            ? 'DataForSEO credentials are not configured on the platform.'
            : `Could not fetch backlinks for ${submitted}.`}
        </div>
      )}

      {data && ov && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{data.target}</span>
            <span style={typeChip}>{data.target_type}</span>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              {data.cached ? 'cached' : 'fresh'} · {shortDate(data.captured_at)}
            </span>
          </div>

          {/* Overview stat strip */}
          <div style={statGrid}>
            <Stat label="Domain Rating" value={ov.domain_rating != null ? ov.domain_rating.toFixed(1) : '—'} accent />
            <Stat label="Referring domains" value={fmt(ov.referring_domains)} />
            <Stat label="Backlinks" value={fmt(ov.backlinks)} />
            <Stat label="Dofollow" value={dofollowPct(ov)} />
            <Stat label="Broken" value={fmt(ov.broken_backlinks)} />
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', margin: '22px 0 16px' }}>
            <TabBtn active={tab === 'overview'} onClick={() => setTab('overview')}>Overview</TabBtn>
            <TabBtn active={tab === 'links'} onClick={() => setTab('links')}>Backlinks</TabBtn>
          </div>

          {tab === 'overview' && <OverviewTab data={data} />}
          {tab === 'links' && <LinksTab target={data.target} />}
        </>
      )}
    </div>
  )
}

function dofollowPct(ov: Overview): string {
  if (ov.dofollow == null || !ov.backlinks) return fmt(ov.dofollow)
  const pct = Math.round((ov.dofollow / ov.backlinks) * 100)
  return `${fmt(ov.dofollow)} (${pct}%)`
}

function OverviewTab({ data }: { data: LookupResponse }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 20 }}>
      {data.history.length > 1 && (
        <section>
          <SectionTitle icon={<TrendingUp size={14} />}>Referring domains over time</SectionTitle>
          <Sparkline points={data.history} />
        </section>
      )}

      <section>
        <SectionTitle>Referring domains ({data.referring_domains.length})</SectionTitle>
        {data.referring_domains.length === 0 ? (
          <div style={emptyBox}>No referring domains returned.</div>
        ) : (
          <table style={table}>
            <thead>
              <tr>
                <Th>Domain</Th><Th right>DR</Th><Th right>Links</Th><Th right>Dofollow</Th><Th right>First seen</Th>
              </tr>
            </thead>
            <tbody>
              {data.referring_domains.slice(0, 100).map((rd) => (
                <tr key={rd.domain} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>
                    <a href={`https://${rd.domain}`} target="_blank" rel="noreferrer" style={linkCell}>
                      {rd.domain} <ExternalLink size={11} />
                    </a>
                    {rd.is_lost && <span style={{ ...flagChip, color: '#b91c1c', background: '#fef2f2' }}>lost</span>}
                    {rd.is_new && <span style={{ ...flagChip, color: '#047857', background: '#ecfdf5' }}>new</span>}
                  </td>
                  <td style={tdRight}>{rd.domain_rating != null ? rd.domain_rating.toFixed(1) : '—'}</td>
                  <td style={tdRight}>{fmt(rd.backlinks)}</td>
                  <td style={tdRight}>{fmt(rd.dofollow)}</td>
                  <td style={tdRight}>{shortDate(rd.first_seen)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <SectionTitle>Top anchors ({data.anchors.length})</SectionTitle>
        {data.anchors.length === 0 ? (
          <div style={emptyBox}>No anchors returned.</div>
        ) : (
          <table style={table}>
            <thead><tr><Th>Anchor</Th><Th right>Links</Th><Th right>Ref. domains</Th></tr></thead>
            <tbody>
              {data.anchors.slice(0, 50).map((a, i) => (
                <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>{a.anchor || <span style={{ color: '#94a3b8' }}>(empty)</span>}</td>
                  <td style={tdRight}>{fmt(a.backlinks)}</td>
                  <td style={tdRight}>{fmt(a.referring_domains)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

function LinksTab({ target }: { target: string }) {
  const [filter, setFilter] = useState<LinkFilter>('all')
  const [offset, setOffset] = useState(0)
  const limit = 100

  const { data, isLoading, isError } = useQuery<LinksResponse>({
    queryKey: ['backlink-links', target, filter, offset],
    queryFn: () =>
      api.get<LinksResponse>(
        `/backlinks/links?target=${encodeURIComponent(target)}&filter=${filter}&limit=${limit}&offset=${offset}`,
      ),
  })

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {LINK_FILTERS.map((f) => (
          <button
            key={f}
            style={{ ...filterChip, ...(filter === f ? filterChipActive : {}) }}
            onClick={() => { setFilter(f); setOffset(0) }}
          >
            {f}
          </button>
        ))}
        <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto', alignSelf: 'center' }}>
          one link per domain · {data?.total_count != null ? `${fmt(data.total_count)} total` : ''}
        </span>
      </div>

      {isLoading && <div style={emptyBox}>Loading links…</div>}
      {isError && <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>Could not load the link list.</div>}
      {data && data.links.length === 0 && !isLoading && <div style={emptyBox}>No {filter === 'all' ? '' : filter} links.</div>}

      {data && data.links.length > 0 && (
        <>
          <table style={table}>
            <thead>
              <tr>
                <Th>Source page</Th><Th>Anchor</Th><Th right>DR</Th><Th>Target</Th><Th right>Type</Th>
              </tr>
            </thead>
            <tbody>
              {data.links.map((l, i) => (
                <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>
                    <a href={l.url_from ?? '#'} target="_blank" rel="noreferrer" style={linkCell}>
                      {l.domain_from || l.url_from} <ExternalLink size={11} />
                    </a>
                  </td>
                  <td style={{ ...td, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {l.anchor || <span style={{ color: '#94a3b8' }}>—</span>}
                  </td>
                  <td style={tdRight}>{l.domain_rating != null ? l.domain_rating.toFixed(1) : '—'}</td>
                  <td style={{ ...td, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {l.url_to}
                  </td>
                  <td style={tdRight}>
                    <span style={{ ...flagChip, color: l.dofollow ? '#047857' : '#64748b', background: l.dofollow ? '#ecfdf5' : '#f1f5f9' }}>
                      {l.dofollow ? 'dofollow' : 'nofollow'}
                    </span>
                    {l.is_broken && <span style={{ ...flagChip, color: '#b91c1c', background: '#fef2f2' }}>broken</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
            <button style={ghostBtn} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <span style={{ fontSize: 12, color: '#64748b' }}>Rows {offset + 1}–{offset + data.links.length}</span>
            <button style={ghostBtn} disabled={data.links.length < limit} onClick={() => setOffset(offset + limit)}>Next</button>
          </div>
        </>
      )}
    </div>
  )
}

// ---- small presentational bits ----
function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{ ...card, marginBottom: 0, padding: 14 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent ? '#4f46e5' : '#0f172a', marginTop: 4 }}>{value}</div>
    </div>
  )
}
function SectionTitle({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <h2 style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 14, fontWeight: 700, color: '#334155', margin: '0 0 10px' }}>
      {icon}{children}
    </h2>
  )
}
function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer', background: 'transparent',
        border: 'none', borderBottom: active ? '2px solid #4f46e5' : '2px solid transparent',
        color: active ? '#4f46e5' : '#64748b', marginBottom: -1,
      }}
    >{children}</button>
  )
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th style={{ textAlign: right ? 'right' : 'left', fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3, padding: '6px 10px' }}>{children}</th>
}

// A dependency-free referring-domains sparkline.
function Sparkline({ points }: { points: HistoryPoint[] }) {
  const vals = points.map((p) => p.referring_domains ?? 0)
  const w = 640, h = 90, pad = 4
  const max = Math.max(...vals, 1), min = Math.min(...vals, 0)
  const span = max - min || 1
  const path = vals.map((v, i) => {
    const x = pad + (i / Math.max(1, vals.length - 1)) * (w - pad * 2)
    const y = h - pad - ((v - min) / span) * (h - pad * 2)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <div style={{ ...card, padding: 12 }}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
        <path d={path} fill="none" stroke="#4f46e5" strokeWidth={2} />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
        <span>{shortDate(points[0].date)}</span>
        <span>{fmt(max)} peak</span>
        <span>{shortDate(points[points.length - 1].date)}</span>
      </div>
    </div>
  )
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none', marginBottom: 14,
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff', marginBottom: 4 }
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 13,
  border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#0f172a',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#fff', background: '#4f46e5', border: 'none', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#475569', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer', whiteSpace: 'nowrap',
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
const statGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }
const table: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 13, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }
const td: React.CSSProperties = { padding: '8px 10px', color: '#334155' }
const tdRight: React.CSSProperties = { ...td, textAlign: 'right', color: '#475569' }
const linkCell: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 4, color: '#4f46e5', textDecoration: 'none' }
const typeChip: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 700, color: '#4f46e5', background: '#eef2ff',
  padding: '2px 8px', borderRadius: 999, textTransform: 'uppercase', letterSpacing: 0.3,
}
const flagChip: React.CSSProperties = { fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 999, marginLeft: 6 }
const filterChip: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: '#64748b', background: '#f1f5f9', border: '1px solid transparent',
  padding: '5px 12px', borderRadius: 999, cursor: 'pointer', textTransform: 'capitalize',
}
const filterChipActive: React.CSSProperties = { color: '#4f46e5', background: '#eef2ff', border: '1px solid #c7d2fe' }
