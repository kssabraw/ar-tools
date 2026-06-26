import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileText, ArrowRight, Loader, Sparkles, Check, RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import type { Client, RunListResponse, RunStatus } from '../lib/types'

const TERMINAL: RunStatus[] = ['complete', 'failed', 'cancelled']

type PlanStatus = 'pending' | 'running' | 'complete' | 'failed'
interface PlanItem { keyword: string; group: string; status: 'found' | 'missing' | 'reoptimize'; url: string | null; rank: number | null }
interface PlanResult { status: PlanStatus; items: PlanItem[]; degraded_notes: string[]; error: string | null }

function statusColor(status: RunStatus): string {
  if (status === 'complete') return '#16a34a'
  if (status === 'failed') return '#dc2626'
  if (status === 'cancelled') return '#94a3b8'
  return '#6366f1'
}

export function ServicePages() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [text, setText] = useState('')

  // Service-page planner state.
  const [jobId, setJobId] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [createdNote, setCreatedNote] = useState<string | null>(null)

  const BULK_MAX = 20
  // One service per line; trimmed, de-duped (case-insensitive), capped.
  const services = (() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const line of text.split('\n')) {
      const s = line.trim()
      const key = s.toLowerCase()
      if (s && !seen.has(key)) { seen.add(key); out.push(s) }
    }
    return out
  })()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  const { data: runs } = useQuery<RunListResponse>({
    queryKey: ['service-page-runs', id],
    queryFn: () => api.get<RunListResponse>(`/runs?client_id=${id}&content_type=service_page&page_size=100`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const list = query.state.data?.data ?? []
      return list.some((r) => !TERMINAL.includes(r.status)) ? 5000 : false
    },
  })

  const createRuns = useMutation({
    mutationFn: (keywords: string[]) =>
      api.post<{ created: number }>('/runs/bulk', {
        client_id: id,
        content_type: 'service_page',
        keywords,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['service-page-runs', id] })
      setText('')
    },
  })

  // ── Planner: enqueue → poll → render found/missing → bulk-create ──
  const startPlan = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${id}/service-page-plan`, {}),
    onSuccess: (res) => { setJobId(res.job_id); setSelected(new Set()); setCreatedNote(null) },
  })

  const { data: plan } = useQuery<PlanResult>({
    queryKey: ['service-page-plan', id, jobId],
    queryFn: () => api.get<PlanResult>(`/clients/${id}/service-page-plan/${jobId}`),
    enabled: Boolean(id && jobId),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      return s === 'pending' || s === 'running' ? 3000 : false
    },
  })

  const planRunning = startPlan.isPending || plan?.status === 'pending' || plan?.status === 'running'
  const silos = useMemo(() => {
    const groups = new Map<string, PlanItem[]>()
    for (const it of plan?.items ?? []) {
      if (!groups.has(it.group)) groups.set(it.group, [])
      groups.get(it.group)!.push(it)
    }
    return [...groups.entries()]
  }, [plan])
  const missing = useMemo(() => (plan?.items ?? []).filter((i) => i.status === 'missing'), [plan])
  const reoptimizeItems = useMemo(() => (plan?.items ?? []).filter((i) => i.status === 'reoptimize'), [plan])
  const foundCount = (plan?.items.length ?? 0) - missing.length - reoptimizeItems.length
  const [reoptStarted, setReoptStarted] = useState<Set<string>>(new Set())

  function toggle(keyword: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(keyword)) next.delete(keyword); else next.add(keyword)
      return next
    })
  }
  function selectAllMissing() {
    setSelected(new Set(missing.slice(0, BULK_MAX).map((i) => i.keyword)))
  }

  const createSelected = useMutation({
    mutationFn: (keywords: string[]) =>
      api.post<{ created: number }>('/runs/bulk', { client_id: id, content_type: 'service_page', keywords }),
    onSuccess: (res, keywords) => {
      qc.invalidateQueries({ queryKey: ['service-page-runs', id] })
      // Deselect only what was just created — anything beyond the 20-cap stays
      // checked for a follow-up batch rather than being silently dropped.
      setSelected((prev) => new Set([...prev].filter((k) => !keywords.includes(k))))
      setCreatedNote(`Started ${res.created} page${res.created === 1 ? '' : 's'} — see Generated pages below.`)
      // Mark just-created items found locally so they don't read as missing.
      qc.setQueryData<PlanResult>(['service-page-plan', id, jobId], (prev) =>
        prev ? { ...prev, items: prev.items.map((i) => (keywords.includes(i.keyword) ? { ...i, status: 'found' } : i)) } : prev,
      )
    },
  })
  // Reoptimize a page already published on the live site that isn't ranking top 5.
  // Spawns a service_page run (scrape + score the live page → deficiency-guided
  // regenerate); it shows up under "Generated pages" below.
  const reoptimizeExisting = useMutation({
    mutationFn: (item: PlanItem) =>
      api.post<{ run_id: string }>('/service-pages/reoptimize-existing', {
        client_id: id,
        keyword: item.keyword,
        source_url: item.url,
      }),
    onMutate: (item) => setReoptStarted((prev) => new Set(prev).add(item.keyword)),
    onSuccess: (_res, item) => {
      qc.invalidateQueries({ queryKey: ['service-page-runs', id] })
      setCreatedNote(`Reoptimizing “${item.keyword}” — see Generated pages below.`)
    },
    onError: (_err, item) =>
      setReoptStarted((prev) => { const n = new Set(prev); n.delete(item.keyword); return n }),
  })

  const selectedList = [...selected]

  const canSubmit = services.length > 0 && services.length <= BULK_MAX && !createRuns.isPending
  function submit() {
    if (canSubmit) createRuns.mutate(services)
  }

  const list = runs?.data ?? []

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLinkStyle}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '16px 0 4px' }}>
        <FileText size={22} color="#6366f1" />
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Service Pages</h1>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 0 }}>
        Conversion-focused service / landing pages. Enter the head commercial query — the brief and
        writer run in one pass, and you get Markdown, HTML, and WordPress-ready output. Add one
        service per line to bulk-create several at once.
      </p>

      {/* Planner */}
      <div style={plannerCardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <Sparkles size={16} color="#6366f1" />
              <span style={{ fontWeight: 600, color: '#0f172a', fontSize: 14 }}>Plan service pages</span>
            </div>
            <div style={{ color: '#64748b', fontSize: 13, marginTop: 2 }}>
              Discover the full set of service pages this business should have — grouped by silo, with the
              ones you already have marked. Seeded from the client’s business category.
            </div>
          </div>
          <button
            type="button"
            onClick={() => startPlan.mutate()}
            disabled={planRunning}
            style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1', opacity: planRunning ? 0.6 : 1, whiteSpace: 'nowrap' }}
          >
            {planRunning ? <><Loader size={14} /> Analyzing…</> : 'Suggest pages'}
          </button>
        </div>

        {startPlan.isError && (
          <div style={{ color: '#dc2626', fontSize: 13, marginTop: 10 }}>
            Could not start the plan. {(startPlan.error as Error)?.message}
          </div>
        )}
        {plan?.status === 'failed' && (
          <div style={{ color: '#dc2626', fontSize: 13, marginTop: 10 }}>Plan failed. {plan.error}</div>
        )}

        {plan?.status === 'complete' && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 13, color: '#334155', marginBottom: 8 }}>
              {plan.items.length} candidate{plan.items.length === 1 ? '' : 's'} across {silos.length} silo
              {silos.length === 1 ? '' : 's'} · <span style={{ color: '#16a34a' }}>{foundCount} exist</span> ·{' '}
              <span style={{ color: '#b45309' }}>{missing.length} missing</span>
              {reoptimizeItems.length > 0 && (
                <> · <span style={{ color: '#2563eb' }}>{reoptimizeItems.length} to reoptimize</span></>
              )}
            </div>
            {plan.degraded_notes.map((n, i) => (
              <div key={i} style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>{n}</div>
            ))}

            {plan.items.length === 0 ? (
              <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 0' }}>
                No candidates could be derived. Make sure the client has a GBP category or a scanned website.
              </div>
            ) : (
              <>
                {missing.length > 0 && (
                  <button type="button" onClick={selectAllMissing} style={{ ...linkBtnStyle, marginBottom: 8 }}>
                    Select all missing{missing.length > BULK_MAX ? ` (first ${BULK_MAX})` : ''}
                  </button>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {silos.map(([group, items]) => (
                    <div key={group}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: 0.3, marginBottom: 6 }}>{group}</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {items.map((it) => {
                          const isMissing = it.status === 'missing'
                          const isReopt = it.status === 'reoptimize'
                          const checked = selected.has(it.keyword)
                          const Row = (isMissing ? 'label' : 'div') as 'label' | 'div'
                          const started = reoptStarted.has(it.keyword)
                          return (
                            <Row key={it.keyword} style={{ ...planRowStyle, cursor: isMissing ? 'pointer' : 'default', opacity: isMissing || isReopt ? 1 : 0.7 }}>
                              {isMissing ? (
                                <input type="checkbox" checked={checked} onChange={() => toggle(it.keyword)} style={{ accentColor: '#6366f1' }} />
                              ) : isReopt ? (
                                <RefreshCw size={14} color="#2563eb" />
                              ) : (
                                <Check size={14} color="#16a34a" />
                              )}
                              <span style={{ flex: 1, fontSize: 13.5, color: '#0f172a' }}>
                                {it.keyword}
                                {isReopt && it.url && (
                                  <a href={it.url} target="_blank" rel="noreferrer" style={{ marginLeft: 8, fontSize: 11.5, color: '#94a3b8', textDecoration: 'none' }}>live page ↗</a>
                                )}
                              </span>
                              {isReopt ? (
                                <>
                                  <span style={{ fontSize: 11.5, color: '#2563eb' }}>
                                    {it.rank != null ? `ranks #${it.rank}` : 'not ranking'}
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => reoptimizeExisting.mutate(it)}
                                    disabled={started}
                                    style={{ ...linkBtnStyle, color: started ? '#94a3b8' : '#2563eb' }}
                                  >
                                    {started ? 'Reoptimizing…' : 'Reoptimize'}
                                  </button>
                                </>
                              ) : (
                                <span style={{ fontSize: 11.5, color: isMissing ? '#b45309' : '#16a34a' }}>{isMissing ? 'missing' : 'exists'}</span>
                              )}
                            </Row>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>

                {selectedList.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14 }}>
                    <button
                      type="button"
                      onClick={() => createSelected.mutate(selectedList.slice(0, BULK_MAX))}
                      disabled={createSelected.isPending}
                      style={{ ...btnStyle, color: '#fff', background: '#16a34a', borderColor: '#16a34a', opacity: createSelected.isPending ? 0.6 : 1 }}
                    >
                      {createSelected.isPending ? 'Creating…' : `Create ${Math.min(selectedList.length, BULK_MAX)} selected`}
                    </button>
                    {selectedList.length > BULK_MAX && (
                      <span style={{ fontSize: 12, color: '#dc2626' }}>Up to {BULK_MAX} at a time.</span>
                    )}
                  </div>
                )}
              </>
            )}
            {createdNote && <div style={{ fontSize: 13, color: '#16a34a', marginTop: 10 }}>{createdNote}</div>}
            {createSelected.isError && (
              <div style={{ color: '#dc2626', fontSize: 13, marginTop: 8 }}>
                Could not start the runs. {(createSelected.error as Error)?.message}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Manual create */}
      <div style={{ display: 'flex', gap: 8, margin: '16px 0 6px', alignItems: 'flex-start' }}>
        <textarea
          className="input"
          placeholder={'e.g. emergency plumber\nwater heater repair\ndrain cleaning'}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); submit() } }}
          rows={4}
          style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1', opacity: canSubmit ? 1 : 0.5 }}
        >
          {createRuns.isPending
            ? 'Starting…'
            : services.length > 1 ? `Generate ${services.length} pages` : 'Generate'}
        </button>
      </div>
      <div style={{ fontSize: 12, color: services.length > BULK_MAX ? '#dc2626' : '#94a3b8', marginBottom: 24 }}>
        {services.length > BULK_MAX
          ? `Up to ${BULK_MAX} at a time — remove ${services.length - BULK_MAX}, or use the Content Scheduler for larger batches.`
          : 'One service per line. ⌘/Ctrl + Enter to generate.'}
      </div>
      {createRuns.isError && (
        <div style={{ color: '#dc2626', fontSize: 13, marginTop: -16, marginBottom: 16 }}>
          Could not start the runs. {(createRuns.error as Error)?.message}
        </div>
      )}

      {/* List */}
      <h2 style={{ fontSize: 15, fontWeight: 600, color: '#334155' }}>Generated pages</h2>
      {list.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: 14, padding: '12px 0' }}>No service pages yet.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {list.map((r) => {
            const running = !TERMINAL.includes(r.status)
            return (
              <Link key={r.id} to={`/runs/${r.id}`} style={rowStyle}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.title || r.keyword}
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>{new Date(r.created_at).toLocaleString()}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: statusColor(r.status) }}>
                    {running && <Loader size={13} />} {r.status.replace(/_/g, ' ')}
                  </span>
                  <ArrowRight size={15} color="#cbd5e1" />
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

const backLinkStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, color: '#6366f1', textDecoration: 'none', fontSize: 13 }
const inputStyle: React.CSSProperties = { flex: 1, fontSize: 14, padding: '9px 12px', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none' }
const btnStyle: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 14, padding: '9px 16px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer', fontWeight: 600 }
const linkBtnStyle: React.CSSProperties = { background: 'none', border: 'none', color: '#6366f1', fontSize: 13, cursor: 'pointer', padding: 0, fontWeight: 600 }
const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', border: '1px solid #e2e8f0', borderRadius: 10, background: '#fff', textDecoration: 'none' }
const plannerCardStyle: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, background: '#fafafe', padding: 16, margin: '8px 0 4px' }
const planRowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 9, padding: '6px 8px', borderRadius: 8 }
