import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Bell, BellOff, ChevronDown, ChevronRight, ExternalLink, FileText,
  Link2, RefreshCw, Search, TrendingUp, Zap,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'

// Backlink explorer — an any-domain Site Explorer over the DataForSEO Backlinks
// API family. The DEFAULT lookup is domain-wide and page-aware (summary +
// per-page UR/RD breakdown + history — 3 cheap calls, cached 24h). The
// referring-domains list and anchors are LAZY tab loads: auto-fetched on first
// open, with the paid call made fully explicit in the UI. The individual-link
// list stays on demand (one-per-domain by default) to bound cost.

interface Overview {
  referring_domains: number | null
  backlinks: number | null
  dofollow: number | null
  nofollow: number | null
  broken_backlinks: number | null
  referring_ips: number | null
  referring_subnets: number | null
  domain_rating: number | null
  pages_count: number | null
}
interface PageRow {
  url: string; page_rating: number | null; referring_domains: number | null
  backlinks: number | null; first_seen: string | null
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
  overview: Overview; pages: PageRow[]; history: HistoryPoint[]
}
interface LazyRdResponse { target: string; cached: boolean; captured_at: string | null; referring_domains: ReferringDomain[] }
interface LazyAnchorsResponse { target: string; cached: boolean; captured_at: string | null; anchors: Anchor[] }
interface BacklinkLink {
  url_from: string | null; domain_from: string | null; url_to: string | null; anchor: string | null
  dofollow: boolean | null; domain_rating: number | null; page_rating: number | null
  first_seen: string | null; is_new: boolean; is_lost: boolean; is_broken: boolean
}
interface LinksResponse { total_count: number | null; links: BacklinkLink[]; limit: number; offset: number; filter: string }
interface TrackedTarget {
  id: string; target: string; label: string | null
  latest: { referring_domains: number | null; domain_rating: number | null; new_domains: number | null; lost_domains: number | null; pages_count: number | null; captured_at: string | null } | null
}

const LINK_FILTERS = ['all', 'dofollow', 'nofollow', 'new', 'lost', 'broken'] as const
type LinkFilter = (typeof LINK_FILTERS)[number]
type Tab = 'overview' | 'pages' | 'rd' | 'anchors' | 'links'

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString()
}
function shortDate(s: string | null): string {
  if (!s) return '—'
  return s.slice(0, 10)
}
function pathOf(url: string): string {
  try {
    const u = new URL(url.includes('//') ? url : `https://${url}`)
    const p = u.pathname + (u.search || '')
    return p === '/' ? '/ (homepage)' : p
  } catch {
    return url
  }
}

export function Backlinks() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [linksScope, setLinksScope] = useState<string | null>(null) // page-scoped links view

  // Tracked targets (client-scoped only) — scheduled re-snapshots + alerts.
  const { data: trackedResp } = useQuery<{ tracked: TrackedTarget[] }>({
    queryKey: ['backlinks-tracked', id],
    queryFn: () => api.get<{ tracked: TrackedTarget[] }>(`/clients/${id}/backlinks/tracked`),
    enabled: Boolean(id),
  })
  const tracked = trackedResp?.tracked ?? []
  const invalidateTracked = () => queryClient.invalidateQueries({ queryKey: ['backlinks-tracked', id] })
  const trackMut = useMutation({
    mutationFn: (target: string) => api.post(`/clients/${id}/backlinks/tracked`, { target }),
    onSuccess: invalidateTracked,
  })
  const untrackMut = useMutation({
    mutationFn: (targetId: string) => api.delete(`/clients/${id}/backlinks/tracked/${targetId}`),
    onSuccess: invalidateTracked,
  })

  const lookup = useMutation({
    mutationFn: (vars: { target: string; force: boolean }) =>
      api.post<LookupResponse>('/backlinks/lookup', {
        target: vars.target, client_id: id ?? null, force: vars.force,
      }),
    onSuccess: () => {
      // New lookup → drop any lazy-tab caches for a clean slate on force.
      queryClient.removeQueries({ queryKey: ['backlink-rd'] })
      queryClient.removeQueries({ queryKey: ['backlink-anchors'] })
    },
  })

  // Prefill + auto-analyze the client's own domain when opened from a workspace.
  useEffect(() => {
    if (client?.website_url && !query) {
      setQuery(client.website_url)
      setSubmitted(client.website_url)
      lookup.mutate({ target: client.website_url, force: false })
    }
  }, [client?.website_url]) // eslint-disable-line react-hooks/exhaustive-deps

  function analyze(target: string, force = false) {
    const t = target.trim()
    if (!t) return
    setSubmitted(t)
    setTab('overview')
    setLinksScope(null)
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
        Look up any domain, subdomain, or URL. The default view is domain-wide — authority, history,
        and which pages hold the links. Referring domains and anchors load on demand.
      </p>

      {/* Tracked domains (client mode) */}
      {id && tracked.length > 0 && (
        <div style={{ marginBottom: 18 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3, marginBottom: 8 }}>
            Tracked domains
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {tracked.map((t) => {
              const nd = t.latest?.new_domains ?? 0
              const ld = t.latest?.lost_domains ?? 0
              return (
                <button key={t.id} style={trackedChip} onClick={() => { setQuery(t.target); analyze(t.target) }}
                  title="Analyze this tracked domain">
                  <span style={{ fontWeight: 600, color: '#334155' }}>{t.label || t.target}</span>
                  {t.latest?.domain_rating != null && <span style={{ color: '#94a3b8' }}>DR {t.latest.domain_rating.toFixed(0)}</span>}
                  {t.latest?.pages_count != null && <span style={{ color: '#94a3b8' }}>{t.latest.pages_count}p</span>}
                  {nd > 0 && <span style={{ color: '#047857' }}>+{nd}</span>}
                  {ld > 0 && <span style={{ color: '#b91c1c' }}>−{ld}</span>}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Search bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <Search size={15} style={{ position: 'absolute', left: 11, top: 10, color: '#94a3b8' }} />
          <input
            style={{ ...input, paddingLeft: 32 }}
            placeholder="example.com  ·  blog.example.com  ·  example.com/page"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') analyze(query) }}
          />
        </div>
        <button style={primaryBtn} disabled={lookup.isPending || !query.trim()} onClick={() => analyze(query)}>
          <Search size={14} /> Analyze
        </button>
        {data && (
          <button style={ghostBtn} disabled={lookup.isPending} onClick={() => analyze(query, true)}
            title="Force a fresh pull — 3 paid API calls (ignores the 24h cache)">
            <RefreshCw size={14} style={lookup.isPending ? { animation: 'spin 1s linear infinite' } : undefined} /> Refresh
          </button>
        )}
      </div>

      {lookup.isPending && <div style={emptyBox}>Pulling backlink data for {submitted}…</div>}
      {lookup.isError && (
        <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>
          {(lookup.error as Error).message === 'dataforseo_not_configured'
            ? 'DataForSEO credentials are not configured on the platform.'
            : (lookup.error as Error).message === 'backlink_budget_exceeded'
              ? 'The daily backlink API budget is used up — cached lookups still work; fresh pulls resume tomorrow.'
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
            {id && (() => {
              const existing = tracked.find((t) => t.target === data.target)
              return existing ? (
                <button style={{ ...ghostBtn, marginLeft: 'auto', padding: '5px 10px' }}
                  disabled={untrackMut.isPending} onClick={() => untrackMut.mutate(existing.id)}
                  title="Stop scheduled re-checks + alerts">
                  <BellOff size={13} /> Tracking
                </button>
              ) : (
                <button style={{ ...primaryBtn, marginLeft: 'auto', padding: '5px 10px' }}
                  disabled={trackMut.isPending} onClick={() => trackMut.mutate(data.target)}
                  title="Re-check weekly and alert on gained/lost referring domains">
                  <Bell size={13} /> Track
                </button>
              )
            })()}
          </div>

          {/* Overview stat strip */}
          <div style={statGrid}>
            <Stat label="Domain Rating" value={ov.domain_rating != null ? ov.domain_rating.toFixed(1) : '—'} accent />
            <Stat label="Referring domains" value={fmt(ov.referring_domains)} />
            <Stat label="Backlinks" value={fmt(ov.backlinks)} />
            <Stat label="Linked pages" value={fmt(ov.pages_count)} />
            <Stat label="Dofollow" value={dofollowPct(ov)} />
            <Stat label="Broken" value={fmt(ov.broken_backlinks)} />
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', margin: '22px 0 16px' }}>
            <TabBtn active={tab === 'overview'} onClick={() => setTab('overview')}>Overview</TabBtn>
            <TabBtn active={tab === 'pages'} onClick={() => setTab('pages')}>Pages{data.pages.length ? ` (${data.pages.length})` : ''}</TabBtn>
            <TabBtn active={tab === 'rd'} onClick={() => setTab('rd')}>Referring domains</TabBtn>
            <TabBtn active={tab === 'anchors'} onClick={() => setTab('anchors')}>Anchors</TabBtn>
            <TabBtn active={tab === 'links'} onClick={() => setTab('links')}>Backlinks</TabBtn>
          </div>

          {tab === 'overview' && <OverviewTab data={data} onViewPages={() => setTab('pages')} />}
          {tab === 'pages' && (
            <PagesTab pages={data.pages} clientId={id ?? null}
              onViewLinks={(url) => { setLinksScope(url); setTab('links') }} />
          )}
          {tab === 'rd' && <RdTab target={data.target} clientId={id ?? null} />}
          {tab === 'anchors' && <AnchorsTab target={data.target} clientId={id ?? null} />}
          {tab === 'links' && (
            <LinksTab target={linksScope ?? data.target} scoped={Boolean(linksScope)}
              onClearScope={() => setLinksScope(null)} />
          )}
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

// ---------------------------------------------------------------------------
// Overview — history + top pages (which pages hold the authority)
// ---------------------------------------------------------------------------
function OverviewTab({ data, onViewPages }: { data: LookupResponse; onViewPages: () => void }) {
  const top = data.pages.slice(0, 10)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 20 }}>
      {data.history.length > 1 && (
        <section>
          <SectionTitle icon={<TrendingUp size={14} />}>Referring domains over time</SectionTitle>
          <Sparkline points={data.history} />
        </section>
      )}
      <section>
        <SectionTitle icon={<FileText size={14} />}>Top pages by referring domains</SectionTitle>
        {top.length === 0 ? (
          <div style={emptyBox}>No per-page data returned.</div>
        ) : (
          <>
            <table style={table}>
              <thead>
                <tr><Th>Page</Th><Th right>UR</Th><Th right>Ref. domains</Th><Th right>Backlinks</Th></tr>
              </thead>
              <tbody>
                {top.map((p) => (
                  <tr key={p.url} style={{ borderTop: '1px solid #f1f5f9' }}>
                    <td style={{ ...td, maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      <a href={p.url} target="_blank" rel="noreferrer" style={linkCell} title={p.url}>
                        {pathOf(p.url)} <ExternalLink size={11} />
                      </a>
                    </td>
                    <td style={tdRight}>{p.page_rating != null ? p.page_rating.toFixed(1) : '—'}</td>
                    <td style={tdRight}>{fmt(p.referring_domains)}</td>
                    <td style={tdRight}>{fmt(p.backlinks)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.pages.length > 10 && (
              <button style={{ ...ghostBtn, marginTop: 10 }} onClick={onViewPages}>
                View all {data.pages.length} pages →
              </button>
            )}
          </>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pages — full per-page table with filter/sort + per-page paid drill-ins
// ---------------------------------------------------------------------------
type PageSortKey = 'referring_domains' | 'page_rating' | 'backlinks'

function PagesTab({ pages, clientId, onViewLinks }: {
  pages: PageRow[]; clientId: string | null; onViewLinks: (url: string) => void
}) {
  const [filter, setFilter] = useState('')
  const [sortKey, setSortKey] = useState<PageSortKey>('referring_domains')
  const [open, setOpen] = useState<string | null>(null)

  const rows = useMemo(() => {
    const f = filter.trim().toLowerCase()
    const filtered = f ? pages.filter((p) => p.url.toLowerCase().includes(f)) : pages
    return [...filtered].sort((a, b) => (b[sortKey] ?? -1) - (a[sortKey] ?? -1))
  }, [pages, filter, sortKey])

  if (pages.length === 0) return <div style={emptyBox}>No per-page data returned for this target.</div>

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input style={{ ...input, maxWidth: 320 }} placeholder="Filter by path…"
          value={filter} onChange={(e) => setFilter(e.target.value)} />
        <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto', alignSelf: 'center' }}>
          {rows.length} of {pages.length} pages · from the cached snapshot (no extra API calls)
        </span>
      </div>
      <table style={table}>
        <thead>
          <tr>
            <Th>Page</Th>
            <SortTh label="UR" active={sortKey === 'page_rating'} onClick={() => setSortKey('page_rating')} />
            <SortTh label="Ref. domains" active={sortKey === 'referring_domains'} onClick={() => setSortKey('referring_domains')} />
            <SortTh label="Backlinks" active={sortKey === 'backlinks'} onClick={() => setSortKey('backlinks')} />
            <Th right>First seen</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <PageRowView key={p.url} page={p} clientId={clientId}
              open={open === p.url} onToggle={() => setOpen(open === p.url ? null : p.url)}
              onViewLinks={() => onViewLinks(p.url)} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PageRowView({ page, clientId, open, onToggle, onViewLinks }: {
  page: PageRow; clientId: string | null; open: boolean; onToggle: () => void; onViewLinks: () => void
}) {
  return (
    <>
      <tr style={{ borderTop: '1px solid #f1f5f9', cursor: 'pointer' }} onClick={onToggle}>
        <td style={{ ...td, maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {open ? <ChevronDown size={13} color="#94a3b8" /> : <ChevronRight size={13} color="#94a3b8" />}
            <span title={page.url}>{pathOf(page.url)}</span>
          </span>
        </td>
        <td style={tdRight}>{page.page_rating != null ? page.page_rating.toFixed(1) : '—'}</td>
        <td style={tdRight}>{fmt(page.referring_domains)}</td>
        <td style={tdRight}>{fmt(page.backlinks)}</td>
        <td style={tdRight}>{shortDate(page.first_seen)}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} style={{ padding: '4px 10px 14px 30px', background: '#f8fafc' }}>
            <PageDrill url={page.url} clientId={clientId} onViewLinks={onViewLinks} />
          </td>
        </tr>
      )}
    </>
  )
}

// Per-page drill-in: the actual referring domains / anchors for ONE page.
// Each fetch is explicit — a button labeled with its cost — never automatic.
function PageDrill({ url, clientId, onViewLinks }: { url: string; clientId: string | null; onViewLinks: () => void }) {
  const [rd, setRd] = useState<ReferringDomain[] | null>(null)
  const [anchors, setAnchors] = useState<Anchor[] | null>(null)
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const cid = clientId ? `&client_id=${clientId}` : ''

  async function fetchRd() {
    setLoading('rd'); setError(null)
    try {
      const r = await api.get<LazyRdResponse>(`/backlinks/referring-domains?target=${encodeURIComponent(url)}${cid}`)
      setRd(r.referring_domains)
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }
  async function fetchAnchors() {
    setLoading('anchors'); setError(null)
    try {
      const r = await api.get<LazyAnchorsResponse>(`/backlinks/anchors?target=${encodeURIComponent(url)}${cid}`)
      setAnchors(r.anchors)
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
        {!rd && (
          <button style={ghostBtn} disabled={loading !== null} onClick={fetchRd}>
            <Zap size={13} color="#d97706" /> {loading === 'rd' ? 'Fetching…' : 'Fetch referring domains — 1 paid call'}
          </button>
        )}
        {!anchors && (
          <button style={ghostBtn} disabled={loading !== null} onClick={fetchAnchors}>
            <Zap size={13} color="#d97706" /> {loading === 'anchors' ? 'Fetching…' : 'Fetch anchors — 1 paid call'}
          </button>
        )}
        <button style={ghostBtn} onClick={onViewLinks}>View individual links →</button>
      </div>
      {error && <div style={{ fontSize: 12, color: '#b91c1c' }}>Fetch failed: {error}</div>}
      {rd && (
        <MiniTable head={['Domain', 'DR', 'Links']}
          rows={rd.slice(0, 15).map((d) => [d.domain, d.domain_rating != null ? d.domain_rating.toFixed(1) : '—', fmt(d.backlinks)])} />
      )}
      {anchors && (
        <MiniTable head={['Anchor', 'Links', 'Ref. domains']}
          rows={anchors.slice(0, 15).map((a) => [a.anchor || '(empty)', fmt(a.backlinks), fmt(a.referring_domains)])} />
      )}
    </div>
  )
}

function MiniTable({ head, rows }: { head: string[]; rows: (string | null)[][] }) {
  if (rows.length === 0) return <div style={{ fontSize: 12, color: '#94a3b8', margin: '6px 0' }}>Nothing returned.</div>
  return (
    <table style={{ ...table, margin: '6px 0', fontSize: 12 }}>
      <thead><tr>{head.map((h, i) => <Th key={h} right={i > 0}>{h}</Th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
            {r.map((c, j) => <td key={j} style={j > 0 ? tdRight : td}>{c}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------
// Lazy tabs — auto-fetch on first open; the paid call is made explicit.
// ---------------------------------------------------------------------------
function LazyNotice({ loading, cached, capturedAt, what, onRefresh, refreshing }: {
  loading: boolean; cached: boolean | undefined; capturedAt: string | null | undefined
  what: string; onRefresh: () => void; refreshing: boolean
}) {
  if (loading) {
    return (
      <div style={{ ...noticeBox, borderColor: '#fcd34d', background: '#fffbeb', color: '#92400e' }}>
        <Zap size={13} /> Fetching {what} live from DataForSEO — 1 paid API call…
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
      <span style={{ fontSize: 12, color: '#94a3b8' }}>
        {cached ? `cached from snapshot · ${shortDate(capturedAt ?? null)}` : 'fetched just now'} · loaded on demand to keep lookups cheap
      </span>
      <button style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12, marginLeft: 'auto' }}
        disabled={refreshing} onClick={onRefresh} title="Fetch a fresh copy — 1 paid API call">
        <Zap size={12} color="#d97706" /> Re-fetch (1 paid call)
      </button>
    </div>
  )
}

function RdTab({ target, clientId }: { target: string; clientId: string | null }) {
  const [force, setForce] = useState(false)
  const cid = clientId ? `&client_id=${clientId}` : ''
  const { data, isLoading, isError, isFetching } = useQuery<LazyRdResponse>({
    queryKey: ['backlink-rd', target, force],
    queryFn: () => api.get<LazyRdResponse>(
      `/backlinks/referring-domains?target=${encodeURIComponent(target)}${cid}${force ? '&force=true' : ''}`),
    staleTime: Infinity,
  })
  const rows = data?.referring_domains ?? []
  return (
    <div>
      <LazyNotice loading={isLoading} cached={data?.cached} capturedAt={data?.captured_at}
        what="referring domains" onRefresh={() => setForce(true)} refreshing={isFetching} />
      {isError && <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>Could not load referring domains.</div>}
      {!isLoading && !isError && rows.length === 0 && <div style={emptyBox}>No referring domains returned.</div>}
      {rows.length > 0 && (
        <table style={table}>
          <thead>
            <tr><Th>Domain</Th><Th right>DR</Th><Th right>Links</Th><Th right>Dofollow</Th><Th right>First seen</Th></tr>
          </thead>
          <tbody>
            {rows.map((rd) => (
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
    </div>
  )
}

function AnchorsTab({ target, clientId }: { target: string; clientId: string | null }) {
  const [force, setForce] = useState(false)
  const cid = clientId ? `&client_id=${clientId}` : ''
  const { data, isLoading, isError, isFetching } = useQuery<LazyAnchorsResponse>({
    queryKey: ['backlink-anchors', target, force],
    queryFn: () => api.get<LazyAnchorsResponse>(
      `/backlinks/anchors?target=${encodeURIComponent(target)}${cid}${force ? '&force=true' : ''}`),
    staleTime: Infinity,
  })
  const rows = data?.anchors ?? []
  return (
    <div>
      <LazyNotice loading={isLoading} cached={data?.cached} capturedAt={data?.captured_at}
        what="anchors" onRefresh={() => setForce(true)} refreshing={isFetching} />
      {isError && <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>Could not load anchors.</div>}
      {!isLoading && !isError && rows.length === 0 && <div style={emptyBox}>No anchors returned.</div>}
      {rows.length > 0 && (
        <table style={table}>
          <thead><tr><Th>Anchor</Th><Th right>Links</Th><Th right>Ref. domains</Th></tr></thead>
          <tbody>
            {rows.slice(0, 100).map((a, i) => (
              <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                <td style={td}>{a.anchor || <span style={{ color: '#94a3b8' }}>(empty)</span>}</td>
                <td style={tdRight}>{fmt(a.backlinks)}</td>
                <td style={tdRight}>{fmt(a.referring_domains)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Links — on-demand individual-link list (optionally scoped to one page)
// ---------------------------------------------------------------------------
function LinksTab({ target, scoped, onClearScope }: { target: string; scoped: boolean; onClearScope: () => void }) {
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
      {scoped && (
        <div style={{ ...noticeBox, borderColor: '#c7d2fe', background: '#eef2ff', color: '#3730a3' }}>
          Scoped to <strong style={{ margin: '0 4px' }}>{pathOf(target)}</strong>
          <button style={{ ...ghostBtn, padding: '2px 8px', fontSize: 12, marginLeft: 'auto' }} onClick={onClearScope}>
            ✕ whole domain
          </button>
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {LINK_FILTERS.map((f) => (
          <button key={f} style={{ ...filterChip, ...(filter === f ? filterChipActive : {}) }}
            onClick={() => { setFilter(f); setOffset(0) }}>
            {f}
          </button>
        ))}
        <span style={{ fontSize: 12, color: '#94a3b8', marginLeft: 'auto', alignSelf: 'center' }}>
          one link per domain · fetched live (paid) · {data?.total_count != null ? `${fmt(data.total_count)} total` : ''}
        </span>
      </div>

      {isLoading && <div style={emptyBox}>Loading links…</div>}
      {isError && <div style={{ ...emptyBox, borderColor: '#fecaca', color: '#b91c1c' }}>Could not load the link list.</div>}
      {data && data.links.length === 0 && !isLoading && <div style={emptyBox}>No {filter === 'all' ? '' : filter} links.</div>}

      {data && data.links.length > 0 && (
        <>
          <table style={table}>
            <thead>
              <tr><Th>Source page</Th><Th>Anchor</Th><Th right>DR</Th><Th>Target</Th><Th right>Type</Th></tr>
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
    <button onClick={onClick}
      style={{
        padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer', background: 'transparent',
        border: 'none', borderBottom: active ? '2px solid #4f46e5' : '2px solid transparent',
        color: active ? '#4f46e5' : '#64748b', marginBottom: -1, whiteSpace: 'nowrap',
      }}
    >{children}</button>
  )
}
function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th style={{ textAlign: right ? 'right' : 'left', fontSize: 11, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3, padding: '6px 10px' }}>{children}</th>
}
function SortTh({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <th onClick={onClick}
      style={{ textAlign: 'right', fontSize: 11, fontWeight: 700, cursor: 'pointer', userSelect: 'none',
               color: active ? '#4f46e5' : '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3, padding: '6px 10px' }}>
      {label}{active ? ' ↓' : ''}
    </th>
  )
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
const noticeBox: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, border: '1px solid #e2e8f0', borderRadius: 10,
  padding: '10px 14px', fontSize: 13, marginBottom: 12,
}
const statGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }
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
const trackedChip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, background: '#fff',
  border: '1px solid #e2e8f0', borderRadius: 999, padding: '5px 12px', cursor: 'pointer',
}
