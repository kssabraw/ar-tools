import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, MapPin, ArrowRight, Loader, Plus, X, RotateCw } from 'lucide-react'
import { api } from '../lib/api'
import { LocationAutocomplete } from '../components/localseo/LocationAutocomplete'
import { useBulkPublish, type PublishItem } from '../components/publish/useBulkPublish'
import { BulkPublishBar } from '../components/publish/BulkPublishBar'
import { usePagedPublish, PublishTabs, Pager, PublishBadges } from '../components/publish/PublishFilter'
import type { Client, RunListResponse, RunStatus } from '../lib/types'

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']
const runPublished = (r: { published_doc_url?: string | null; published_url?: string | null }) =>
  Boolean(r.published_doc_url || r.published_url)

function statusColor(status: RunStatus): string {
  if (status === 'complete') return '#16a34a'
  if (status === 'failed') return '#dc2626'
  if (status === 'cancelled') return '#94a3b8'
  return '#6366f1'
}

/** Pull a clean list of service names from the client's website analysis. The
 * scraper stores `services` as a list of strings; tolerate object entries too. */
function extractScannedServices(wa: Record<string, unknown> | null | undefined): string[] {
  const raw = (wa as { services?: unknown } | null | undefined)?.services
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of raw) {
    let name = ''
    if (typeof item === 'string') name = item.trim()
    else if (item && typeof item === 'object' && 'name' in item) name = String((item as { name: unknown }).name).trim()
    const key = name.toLowerCase()
    if (name && !seen.has(key)) { seen.add(key); out.push(name) }
  }
  return out
}

export function LocationPages() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()

  const [location, setLocation] = useState('')
  const [locationCode, setLocationCode] = useState<number | null>(null)
  // The editable services list (one row per service). Prefilled from the site
  // scan once, then fully user-owned (add / edit / remove / rescan-to-replace).
  const [services, setServices] = useState<string[]>([])
  const prefilled = useRef(false)
  const rescanRequested = useRef(false)

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
    // While a rescan is in flight, poll the client so we pick up the refreshed
    // website_analysis the moment the scrape worker finishes.
    refetchInterval: (query) =>
      query.state.data?.website_analysis_status === 'pending' ? 4000 : false,
  })

  const scanned = extractScannedServices(client?.website_analysis)
  const scanPending = client?.website_analysis_status === 'pending'

  // Prefill the editor once from the first scan we see.
  useEffect(() => {
    if (!prefilled.current && client && scanned.length) {
      setServices(scanned)
      prefilled.current = true
    }
  }, [client, scanned])

  // When a rescan we requested completes, replace the list with the fresh scan.
  useEffect(() => {
    if (rescanRequested.current && client && !scanPending) {
      if (scanned.length) setServices(scanned)
      rescanRequested.current = false
    }
  }, [client, scanPending, scanned])

  const { data: runs } = useQuery<RunListResponse>({
    queryKey: ['location-page-runs', id],
    queryFn: () => api.get<RunListResponse>(`/runs?client_id=${id}&content_type=location_page&page_size=200`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const list = query.state.data?.data ?? []
      return list.some((r) => !TERMINAL.includes(r.status)) ? 5000 : false
    },
  })

  const rescan = useMutation({
    mutationFn: () => api.post(`/clients/${id}/reanalyze`, {}),
    onSuccess: () => {
      rescanRequested.current = true
      qc.invalidateQueries({ queryKey: ['client', id] })
    },
  })

  const createRun = useMutation({
    mutationFn: (cleanServices: string[]) =>
      api.post<{ run_id: string }>('/runs', {
        client_id: id,
        // The location is the page's identity (and satisfies the runs keyword
        // constraint); the services drive the per-section architecture.
        keyword: location.trim(),
        content_type: 'location_page',
        location: location.trim(),
        location_code: locationCode,
        services: cleanServices,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['location-page-runs', id] })
      qc.invalidateQueries({ queryKey: ['client', id] })
    },
  })

  const cleanServices = (() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const s of services) {
      const t = s.trim()
      const key = t.toLowerCase()
      if (t && !seen.has(key)) { seen.add(key); out.push(t) }
    }
    return out
  })()

  const canSubmit = location.trim().length > 0 && cleanServices.length > 0 && !createRun.isPending
  function submit() {
    if (canSubmit) createRun.mutate(cleanServices)
  }

  const updateService = (i: number, value: string) =>
    setServices((prev) => prev.map((s, idx) => (idx === i ? value : s)))
  const removeService = (i: number) =>
    setServices((prev) => prev.filter((_, idx) => idx !== i))
  const addService = () => setServices((prev) => [...prev, ''])

  const list = runs?.data ?? []
  const pub = usePagedPublish(list, runPublished)

  // Bulk-publish the completed pages to Google Docs / the client's website / both.
  const bulk = useBulkPublish()
  const publishItems: PublishItem[] = list
    .filter((r) => r.status === 'complete')
    .map((r) => ({ key: `run:${r.id}`, type: 'run', id: r.id, label: r.title || r.keyword }))
  const wpConfigured = Boolean(client?.wordpress_site_url && client?.wordpress_app_password_set)
  const ghConfigured = Boolean(client?.github_repo)

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '16px 0 4px' }}>
        <MapPin size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Location Pages</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 0 }}>
        Location landing pages that cover every major service this client offers in one area — a
        section per service. Pick the target location and edit the services to cover (prefilled from
        the site scan). The brief and writer run in one pass, then the page is scored against the
        local SEO/AEO engines.
      </p>

      {/* Target location */}
      <label style={labelStyle}>Target location</label>
      {id && (
        <LocationAutocomplete
          clientId={id}
          value={location}
          onChange={(loc, code) => { setLocation(loc); setLocationCode(code) }}
          placeholder="e.g. Austin, Texas"
        />
      )}

      {/* Services editor */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '20px 0 6px' }}>
        <label style={{ ...labelStyle, margin: 0 }}>Services to cover</label>
        <button
          type="button"
          onClick={() => rescan.mutate()}
          disabled={rescan.isPending || scanPending}
          style={{ ...btnStyle, padding: '5px 10px', fontSize: 12.5 }}
        >
          <RotateCw size={13} /> {scanPending ? 'Scanning…' : rescan.isPending ? 'Starting…' : 'Rescan site'}
        </button>
      </div>
      {scanPending && (
        <div style={{ fontSize: 12.5, color: '#64748b', marginBottom: 8 }}>
          Rescanning the site — services will refresh automatically when it finishes.
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {services.map((s, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              className="input"
              value={s}
              placeholder="e.g. Emergency Plumbing"
              onChange={(e) => updateService(i, e.target.value)}
              style={inputStyle}
            />
            <button type="button" onClick={() => removeService(i)} title="Remove" style={{ ...btnStyle, padding: '9px 10px' }}>
              <X size={14} />
            </button>
          </div>
        ))}
        <button type="button" onClick={addService} style={{ ...btnStyle, alignSelf: 'flex-start' }}>
          <Plus size={14} /> Add service
        </button>
      </div>
      {services.length === 0 && (
        <div style={{ fontSize: 12.5, color: '#94a3b8', marginTop: 8 }}>
          No services yet — add them manually, or rescan the site to detect them.
        </div>
      )}

      {/* Generate */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '20px 0 6px' }}>
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1', opacity: canSubmit ? 1 : 0.5 }}
        >
          {createRun.isPending ? 'Starting…' : 'Generate location page'}
        </button>
        <span style={{ fontSize: 12.5, color: '#94a3b8' }}>
          {cleanServices.length} service{cleanServices.length === 1 ? '' : 's'} · {location.trim() ? location.trim() : 'no location yet'}
        </span>
      </div>
      {createRun.isError && (
        <div style={{ color: '#dc2626', fontSize: 13, margin: '4px 0 12px' }}>
          Could not start the run. {(createRun.error as Error)?.message}
        </div>
      )}
      {rescan.isError && (
        <div style={{ color: '#dc2626', fontSize: 13, margin: '4px 0 12px' }}>
          Could not start the rescan. {(rescan.error as Error)?.message}
        </div>
      )}

      {/* List */}
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#334155', marginTop: 28 }}>Generated pages</h2>
      {list.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 14, padding: '12px 0' }}>No location pages yet.</div>
      ) : (
        <>
        <BulkPublishBar items={publishItems} bulk={bulk} wordpressConfigured={wpConfigured} githubConfigured={ghConfigured} placement="top" />
        <div style={{ margin: '4px 0 12px' }}>
          <PublishTabs counts={pub.counts} active={pub.filter} onPick={pub.pick} />
        </div>
        {pub.total === 0 ? (
          <div style={{ color: '#94a3b8', fontSize: 14, padding: '12px 0' }}>Nothing in this view.</div>
        ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {pub.pageItems.map((r) => {
            const running = !TERMINAL.includes(r.status)
            const key = `run:${r.id}`
            const result = bulk.results[key]
            return (
              <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {r.status === 'complete' ? (
                  <input
                    type="checkbox"
                    checked={bulk.selected.has(key)}
                    onChange={(e) => bulk.toggle(key, e.target.checked)}
                    disabled={bulk.publishing}
                    style={{ width: 16, height: 16, accentColor: '#6366f1', cursor: 'pointer', flexShrink: 0 }}
                    title="Select for bulk publish"
                  />
                ) : (
                  <span style={{ width: 16, flexShrink: 0 }} />
                )}
                <Link to={`/runs/${r.id}`} style={{ ...rowStyle, flex: 1, minWidth: 0 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {r.title || r.keyword}
                    </div>
                    <div style={{ fontSize: 12, color: '#94a3b8' }}>{new Date(r.created_at).toLocaleString()}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {result?.status === 'failed' && <span style={{ fontSize: 12, color: '#dc2626' }} title={result.error}>Failed</span>}
                    {result?.status === 'publishing' && <Loader size={13} />}
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: statusColor(r.status) }}>
                      {running && <Loader size={13} />} {r.status.replace(/_/g, ' ')}
                    </span>
                    <ArrowRight size={15} color="#cbd5e1" />
                  </div>
                </Link>
                <PublishBadges docUrl={r.published_doc_url} siteUrl={r.published_url} />
              </div>
            )
          })}
        </div>
        )}
        <Pager page={pub.page} pageCount={pub.pageCount} total={pub.total} pageSize={pub.pageSize} onPage={pub.setPage} />
        </>
      )}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 600, color: '#334155', margin: '0 0 6px' }
const inputStyle: React.CSSProperties = { flex: 1, fontSize: 14, padding: '9px 12px', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none' }
const btnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 14, padding: '9px 16px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer', fontWeight: 600 }
const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', textDecoration: 'none' }
