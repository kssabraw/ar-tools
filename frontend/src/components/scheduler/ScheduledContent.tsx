import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ExternalLink, GitBranch, Loader2, Pause, Play, X } from 'lucide-react'
import { card, outlineBtn } from '../localseo/shared'
import {
  CONTENT_TYPE_LABEL,
  schedulerApi,
  type ContentType,
  type ItemStatus,
  type ScheduledContentItem,
} from './api'

const ITEM_STATUS: Record<ItemStatus, { label: string; color: string; bg: string }> = {
  scheduled: { label: 'Scheduled', color: '#475569', bg: '#f1f5f9' },
  queued: { label: 'Queued', color: '#1d4ed8', bg: '#eff6ff' },
  running: { label: 'Writing', color: '#4338ca', bg: '#eef2ff' },
  complete: { label: 'Generated', color: '#166534', bg: '#f0fdf4' },
  failed: { label: 'Failed', color: '#b91c1c', bg: '#fef2f2' },
  cancelled: { label: 'Cancelled', color: '#64748b', bg: '#f8fafc' },
}

function fmtWhen(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
    ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

/** The expanded per-item list for one suite batch: what's scheduled, generated,
 *  and (for auto-publish batches) live — the "what's scheduled to publish" view. */
function BatchItems({ clientId, batchId }: { clientId: string; batchId: string }) {
  const q = useQuery({
    queryKey: ['content-batch-detail', clientId, batchId],
    queryFn: () => schedulerApi.batchDetail(clientId, batchId),
    refetchInterval: 20000,
  })
  if (q.isLoading) {
    return <div style={{ fontSize: 13, color: '#64748b', padding: '8px 2px' }}>
      <Loader2 size={13} className="spin" /> Loading items…
    </div>
  }
  const items = q.data?.items ?? []
  if (!items.length) return <div style={{ fontSize: 13, color: '#94a3b8', padding: '8px 2px' }}>No items.</div>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 8 }}>
      {items.map(it => {
        const s = ITEM_STATUS[it.status] ?? ITEM_STATUS.scheduled
        return (
          <div key={it.id} style={{
            display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 96px 92px 96px',
            alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6,
            background: '#fff', border: '1px solid #f1f5f9', fontSize: 13,
          }}>
            <span style={{ color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={it.keyword}>{it.keyword}</span>
            <span style={{ color: '#64748b', fontSize: 12 }}>{fmtWhen(it.scheduled_at)}</span>
            <span style={{
              justifySelf: 'start', fontSize: 11, fontWeight: 700, padding: '2px 8px',
              borderRadius: 999, color: s.color, background: s.bg,
            }}>{s.label}</span>
            {it.published_url ? (
              <a href={it.published_url} target="_blank" rel="noreferrer"
                style={{ fontSize: 12, color: '#166534', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                Live <ExternalLink size={11} />
              </a>
            ) : it.status === 'complete' ? (
              <span style={{ fontSize: 12, color: '#b45309' }}>Draft</span>
            ) : it.status === 'failed' ? (
              <span style={{ fontSize: 12, color: '#b91c1c' }} title={it.error ?? undefined}>—</span>
            ) : (
              <span style={{ fontSize: 12, color: '#cbd5e1' }}>—</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

const MODE_LABEL: Record<string, string> = {
  now: 'Immediate', all_at_once: 'All at once', drip: 'Drip', weekly: 'Weekly',
  monthly_date: 'Monthly', monthly_weekday: 'Monthly', fixed: 'On a date',
}

const STATUS_COLOR: Record<string, string> = {
  active: '#2563eb', paused: '#b45309', complete: '#16a34a',
  cancelled: '#64748b', failed: '#dc2626',
}

function typeLabel(t: string): string {
  return CONTENT_TYPE_LABEL[t as ContentType] ?? t.replace(/_/g, ' ')
}

function progressLine(p: ScheduledContentItem['progress']): string {
  const pending = p.scheduled + p.queued
  const parts = [`${p.complete}/${p.total} done`]
  if (p.running) parts.push(`${p.running} writing`)
  if (pending) parts.push(`${pending} pending`)
  if (p.failed) parts.push(`${p.failed} failed`)
  if (p.cancelled) parts.push(`${p.cancelled} cancelled`)
  return parts.join(' · ')
}

function Bar({ p }: { p: ScheduledContentItem['progress'] }) {
  const total = Math.max(1, p.total)
  const seg = (n: number, color: string) =>
    n > 0 ? <div style={{ flex: n, background: color }} /> : null
  return (
    <div style={{ display: 'flex', height: 6, borderRadius: 4, overflow: 'hidden', background: '#f1f5f9' }}>
      {seg(p.complete, '#16a34a')}
      {seg(p.running, '#6366f1')}
      {seg(p.failed, '#dc2626')}
      {seg(p.cancelled, '#cbd5e1')}
      {seg(total - p.complete - p.running - p.failed - p.cancelled, '#e2e8f0')}
    </div>
  )
}

export function ScheduledContent({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) => setExpanded(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })
  const feedQ = useQuery({
    queryKey: ['scheduled-content', clientId],
    queryFn: () => schedulerApi.scheduledContent(clientId),
    refetchInterval: 15000,
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['scheduled-content', clientId] })

  const act = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: invalidate,
    onError: (e: Error) => alert(e.message),
  })

  const items = feedQ.data?.items ?? []

  if (feedQ.isLoading) {
    return <div style={{ ...card, color: '#64748b', fontSize: 14 }}><Loader2 size={15} className="spin" /> Loading…</div>
  }
  if (!items.length) {
    return (
      <div style={{ ...card, color: '#64748b', fontSize: 14 }}>
        Nothing scheduled yet. Create or schedule pages above and they'll appear here — including
        content scheduled from the Topic Fan-out tool.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {items.map(it => {
        const isSuite = it.source === 'content_scheduler'
        const active = it.status === 'active'
        const paused = it.status === 'paused'
        const key = `${it.source}:${it.id}`
        const isOpen = expanded.has(key)
        return (
          <div key={key} style={{ ...card, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {isSuite && (
                  <button onClick={() => toggle(key)} title={isOpen ? 'Hide items' : 'Show scheduled items'}
                    style={{ border: 'none', background: 'none', cursor: 'pointer', padding: 0, display: 'flex', color: '#64748b' }}>
                    {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  </button>
                )}
                <strong style={{ fontSize: 14, color: '#0f172a' }}>{typeLabel(it.content_type)}</strong>
                {it.label && <span style={{ fontSize: 13, color: '#64748b' }}>· {it.label}</span>}
                <span style={{ fontSize: 12, color: '#64748b' }}>· {MODE_LABEL[it.mode ?? ''] ?? it.mode}</span>
                <span style={{
                  fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.4,
                  color: STATUS_COLOR[it.status ?? ''] ?? '#64748b',
                }}>{it.status}</span>
                <span style={{
                  fontSize: 11, padding: '1px 7px', borderRadius: 999,
                  background: isSuite ? '#eef2ff' : '#f0fdf4',
                  color: isSuite ? '#4338ca' : '#166534',
                }}>{isSuite ? 'Content Scheduler' : 'Fan-out'}</span>
                {it.github_publish && (
                  <span title="Finished posts auto-publish to the client's GitHub repo (with images)"
                    style={{
                      fontSize: 11, padding: '1px 7px', borderRadius: 999, background: '#0f172a', color: '#fff',
                      display: 'inline-flex', alignItems: 'center', gap: 3,
                    }}>
                    <GitBranch size={11} /> Auto-publish
                  </span>
                )}
              </div>
              {isSuite && (active || paused) && (
                <div style={{ display: 'flex', gap: 6 }}>
                  {active && (
                    <button style={{ ...outlineBtn, padding: '6px 10px' }} disabled={act.isPending}
                      onClick={() => act.mutate(() => schedulerApi.pauseBatch(clientId, it.id))}>
                      <Pause size={13} /> Pause
                    </button>
                  )}
                  {paused && (
                    <button style={{ ...outlineBtn, padding: '6px 10px' }} disabled={act.isPending}
                      onClick={() => act.mutate(() => schedulerApi.resumeBatch(clientId, it.id))}>
                      <Play size={13} /> Resume
                    </button>
                  )}
                  <button style={{ ...outlineBtn, padding: '6px 10px', color: '#b91c1c' }} disabled={act.isPending}
                    onClick={() => { if (confirm('Cancel all pending pages in this batch?')) act.mutate(() => schedulerApi.cancelBatch(clientId, it.id)) }}>
                    <X size={13} /> Cancel
                  </button>
                </div>
              )}
            </div>
            <Bar p={it.progress} />
            <div style={{ fontSize: 12, color: '#64748b' }}>{progressLine(it.progress)}</div>
            {isSuite && isOpen && <BatchItems clientId={clientId} batchId={it.id} />}
          </div>
        )
      })}
    </div>
  )
}
