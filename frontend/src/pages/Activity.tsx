import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Loader2, RefreshCw, CheckCircle2, ExternalLink } from 'lucide-react'

// One in-flight content job the current user started (mirrors the platform-api
// `/activity` payload).
export interface ActivityItem {
  id: string
  source: 'job' | 'run'
  family: string
  kind_label: string
  mode: 'generate' | 'reoptimize'
  client_id: string
  client_name: string
  label: string
  status: string
  created_at: string | null
  href: string | null
}

export interface ActivityGroup {
  client_id: string
  client_name: string
  count: number
  families: Record<string, number>
}

export interface ActivityResponse {
  count: number
  items: ActivityItem[]
  groups: ActivityGroup[]
}

// Poll interval for the live view. The sidebar badge polls on its own (slower);
// this page refreshes faster while it's open so progress feels live.
export const ACTIVITY_POLL_MS = 8000

function statusChip(status: string) {
  const running = status === 'running'
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        background: running ? '#dbeafe' : '#f1f5f9',
        color: running ? '#1e40af' : '#475569',
        borderRadius: 999, padding: '2px 10px', fontSize: 12, fontWeight: 600,
      }}
    >
      {running ? <Loader2 size={12} className="spin" /> : null}
      {running ? 'Writing' : 'Queued'}
    </span>
  )
}

export function Activity() {
  const { data, isLoading, isFetching, refetch } = useQuery<ActivityResponse>({
    queryKey: ['activity'],
    queryFn: () => api.get<ActivityResponse>('/activity'),
    refetchInterval: ACTIVITY_POLL_MS,
  })

  const items = data?.items ?? []

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Activity</h1>
        <button
          onClick={() => refetch()}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8,
            padding: '6px 12px', fontSize: 13, color: '#475569', cursor: 'pointer',
          }}
        >
          <RefreshCw size={14} className={isFetching ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <p style={{ color: '#64748b', fontSize: 14, marginTop: 0, marginBottom: 24 }}>
        Content you started that&rsquo;s still generating — across every client. These keep
        running on the server even if you close the page; finished pages land in each
        tool&rsquo;s Saved list, and you&rsquo;ll get a notification when a batch completes.
      </p>

      {isLoading ? (
        <div style={{ color: '#94a3b8', fontSize: 14 }}>Loading&hellip;</div>
      ) : items.length === 0 ? (
        <div
          style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
            padding: '48px 24px', background: '#fff', border: '1px solid #e2e8f0',
            borderRadius: 12, color: '#475569',
          }}
        >
          <CheckCircle2 size={28} color="#16a34a" />
          <div style={{ fontWeight: 600 }}>Nothing generating right now</div>
          <div style={{ fontSize: 13, color: '#94a3b8', textAlign: 'center' }}>
            When you generate or reoptimize pages, blog posts, or location/service pages,
            they&rsquo;ll appear here while they run.
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {(data?.groups ?? []).map((g) => (
            <div key={g.client_id || 'none'} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
              <div
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '12px 16px', borderBottom: '1px solid #f1f5f9', background: '#f8fafc',
                }}
              >
                <div style={{ fontWeight: 600, color: '#0f172a', fontSize: 14 }}>{g.client_name}</div>
                <div style={{ fontSize: 12, color: '#64748b' }}>
                  {g.count} {g.count === 1 ? 'item' : 'items'} &middot;{' '}
                  {Object.entries(g.families).map(([f, n]) => `${n} ${f}`).join(' · ')}
                </div>
              </div>
              <div>
                {items.filter((it) => it.client_id === g.client_id).map((it) => (
                  <div
                    key={it.id}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      gap: 12, padding: '10px 16px', borderBottom: '1px solid #f8fafc',
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14, color: '#0f172a', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {it.label}
                      </div>
                      <div style={{ fontSize: 12, color: '#94a3b8' }}>
                        {it.kind_label}{it.mode === 'reoptimize' ? ' · reoptimize' : ''}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
                      {statusChip(it.status)}
                      {it.href ? (
                        <Link to={it.href} style={{ display: 'inline-flex', color: '#6366f1' }} title="Open tool">
                          <ExternalLink size={15} />
                        </Link>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
