import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, ExternalLink, Globe, Link2, MapPin, Plus, RefreshCw, Star, Swords, Trash2, TrendingUp,
} from 'lucide-react'
import { api } from '../lib/api'
import type { Client, CompetitorProfilesResponse } from '../lib/types'

// Competitive intelligence — the unified per-client competitor registry.
// Rows are auto-discovered weekly (maps leaderboard, recurring organic
// top-10 domains, AI-visibility list) + manual adds; each is profiled
// across every module from already-captured data.

export function Competitors() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })
  const { data, isLoading } = useQuery<CompetitorProfilesResponse>({
    queryKey: ['competitors', id],
    queryFn: () => api.get<CompetitorProfilesResponse>(`/clients/${id}/competitors`),
    enabled: Boolean(id),
  })

  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [syncJob, setSyncJob] = useState<string | null>(null)

  const addCompetitor = useMutation({
    mutationFn: () =>
      api.post(`/clients/${id}/competitors`, { name: name.trim(), domain: domain.trim() || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['competitors', id] })
      setName(''); setDomain(''); setShowForm(false)
    },
  })
  const removeCompetitor = useMutation({
    mutationFn: (compId: string) => api.delete(`/clients/${id}/competitors/${compId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['competitors', id] }),
  })
  const syncNow = useMutation({
    mutationFn: () => api.post<{ job_id: string }>(`/clients/${id}/competitors/sync`, {}),
    onSuccess: (r) => setSyncJob(r.job_id),
  })

  const { data: syncStatus } = useQuery<{ status: string }>({
    queryKey: ['competitor-sync', id, syncJob],
    queryFn: () => api.get(`/clients/${id}/competitors/sync/${syncJob}`),
    enabled: Boolean(syncJob),
    refetchInterval: (q) =>
      ['complete', 'failed'].includes(q.state.data?.status ?? '') ? false : 2500,
  })
  useEffect(() => {
    if (syncStatus?.status === 'complete' || syncStatus?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['competitors', id] })
      if (syncStatus.status === 'complete') setSyncJob(null)
    }
  }, [syncStatus?.status, queryClient, id])

  const me = data?.client
  const profiles = data?.competitors ?? []
  const syncing = Boolean(syncJob) && syncStatus?.status !== 'failed'

  return (
    <div style={{ padding: 32, maxWidth: 980 }}>
      <Link to={id ? `/clients/${id}` : '/'} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '0 0 4px' }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Competitive Intel</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={ghostBtn} disabled={syncing} onClick={() => syncNow.mutate()}>
            <RefreshCw size={14} style={syncing ? { animation: 'spin 1s linear infinite' } : undefined} />
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
          <button style={primaryBtn} onClick={() => setShowForm((s) => !s)}>
            <Plus size={14} /> Add competitor
          </button>
        </div>
      </div>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Who you're up against, unified across every tracker — auto-discovered weekly from the
        maps leaderboard, recurring organic top-10 domains &amp; AI-visibility list, profiled
        from data the suite already captures. New pages they publish are watched too.
      </p>

      {showForm && (
        <section style={card}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8, alignItems: 'end' }}>
            <div>
              <label style={fieldLabel}>Name</label>
              <input style={input} placeholder="e.g. Bob's Roofing" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label style={fieldLabel}>Website (optional — enables content watch &amp; backlink joins)</label>
              <input style={input} placeholder="bobsroofing.com" value={domain} onChange={(e) => setDomain(e.target.value)} />
            </div>
            <button style={primaryBtn} disabled={!name.trim() || addCompetitor.isPending} onClick={() => addCompetitor.mutate()}>
              {addCompetitor.isPending ? 'Adding…' : 'Add'}
            </button>
          </div>
          {addCompetitor.isError && (
            <p style={{ color: '#dc2626', fontSize: 12, margin: '8px 0 0' }}>
              {(addCompetitor.error as Error).message === 'competitor_exists'
                ? 'That competitor is already registered.'
                : `Couldn't add: ${(addCompetitor.error as Error).message}`}
            </p>
          )}
        </section>
      )}

      {isLoading ? (
        <div style={emptyBox}>Loading…</div>
      ) : !profiles.length ? (
        <div style={emptyBox}>
          No competitors registered yet. Hit <strong>Sync now</strong> to auto-discover them from
          this client's maps scans, SERP snapshots &amp; AI-visibility list — or add one manually.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {profiles.map((p) => (
            <section key={p.id} style={card}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <Swords size={15} style={{ color: '#64748b' }} />
                    <span style={{ fontSize: 14.5, fontWeight: 600, color: '#0f172a' }}>{p.name}</span>
                    {p.domain && (
                      <a href={`https://${p.domain}`} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#4f46e5', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        {p.domain} <ExternalLink size={11} />
                      </a>
                    )}
                    {(p.sources ?? []).map((s) => (
                      <span key={s} style={sourceChip}>{s.replace('_', ' ')}</span>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 10 }}>
                    {p.organic && (
                      <Stat icon={<TrendingUp size={13} />} label="Organic top-10"
                        value={`${p.organic.top10_keyword_count} kw${p.organic.best_position ? ` · best #${p.organic.best_position}` : ''}`} />
                    )}
                    {p.local_pack && (
                      <Stat icon={<MapPin size={13} />} label="Local pack"
                        value={`${p.local_pack.top3_pins ?? 0} top-3 pins${p.local_pack.avg_rank ? ` · avg ${p.local_pack.avg_rank}` : ''}`} />
                    )}
                    {p.gbp && (
                      <Stat icon={<Star size={13} />} label="GBP"
                        value={`${p.gbp.rating ?? '—'}★ · ${p.gbp.review_count ?? '—'} reviews`} />
                    )}
                    {p.backlinks && (
                      <Stat icon={<Link2 size={13} />} label="Authority"
                        value={`DR ${p.backlinks.domain_rating ?? '—'} · ${p.backlinks.referring_domains ?? '—'} RD`}
                        highlight={compare(p.backlinks.referring_domains, me?.referring_domains)} />
                    )}
                    {p.review_velocity_30d != null && (
                      <Stat icon={<Star size={13} />} label="Review velocity"
                        value={`${p.review_velocity_30d}/mo${me?.review_velocity_30d != null ? ` (you: ${me.review_velocity_30d})` : ''}`} />
                    )}
                    {p.new_pages_30d > 0 && (
                      <Stat icon={<Globe size={13} />} label="New pages (30d)" value={String(p.new_pages_30d)} highlight />
                    )}
                  </div>
                  {p.recent_pages?.length > 0 && (
                    <details style={{ marginTop: 8 }}>
                      <summary style={{ fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
                        Recently published pages
                      </summary>
                      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                        {p.recent_pages.map((pg) => (
                          <li key={pg.url} style={{ fontSize: 12, color: '#475569', marginBottom: 2 }}>
                            <a href={pg.url} target="_blank" rel="noreferrer" style={{ color: '#4f46e5', wordBreak: 'break-all' }}>{pg.url}</a>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
                <button
                  style={iconBtn}
                  title="Remove from tracking"
                  onClick={() => { if (window.confirm(`Stop tracking “${p.name}”?`)) removeCompetitor.mutate(p.id) }}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </section>
          ))}
        </div>
      )}

      {me && (me.domain_rating != null || me.referring_domains != null) && (
        <p style={{ fontSize: 12, color: '#94a3b8', marginTop: 14 }}>
          Your profile: DR {me.domain_rating ?? '—'} · {me.referring_domains ?? '—'} referring domains
          {me.gbp_review_count != null && <> · {me.gbp_review_count} GBP reviews</>}.
          Competitor RD/DR are tool-visibility reads (true RD ≈ ×10).
        </p>
      )}
    </div>
  )
}

function Stat({ icon, label, value, highlight }: { icon: React.ReactNode; label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: 0.3 }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: highlight ? '#b45309' : '#0f172a', marginTop: 2 }}>{value}</div>
    </div>
  )
}

function compare(theirs: number | null | undefined, ours: number | null | undefined): boolean {
  return theirs != null && ours != null && theirs > ours * 1.5
}

const backLink: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b',
  textDecoration: 'none', marginBottom: 14,
}
const card: React.CSSProperties = { border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, background: '#fff', marginBottom: 4 }
const fieldLabel: React.CSSProperties = { display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4 }
const input: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '7px 10px', fontSize: 13,
  border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#0f172a',
}
const primaryBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#fff', background: '#4f46e5', border: 'none', borderRadius: 8, cursor: 'pointer',
}
const ghostBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', fontSize: 13,
  fontWeight: 600, color: '#475569', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, cursor: 'pointer',
}
const iconBtn: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', padding: 6,
  color: '#94a3b8', background: 'transparent', border: 'none', cursor: 'pointer',
}
const sourceChip: React.CSSProperties = {
  fontSize: 10.5, fontWeight: 700, color: '#64748b', background: '#f1f5f9',
  padding: '2px 7px', borderRadius: 999, textTransform: 'uppercase', letterSpacing: 0.3,
}
const emptyBox: React.CSSProperties = {
  border: '1px dashed #cbd5e1', borderRadius: 10, padding: 24, fontSize: 13, color: '#94a3b8', textAlign: 'center',
}
