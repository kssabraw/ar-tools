import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, CalendarDays, List } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { backLink } from '../components/localseo/shared'
import { ScheduleBatch } from '../components/scheduler/ScheduleBatch'
import { ScheduledContent } from '../components/scheduler/ScheduledContent'
import { ContentCalendar } from '../components/scheduler/ContentCalendar'

// The suite Content Scheduler: paste/upload a keyword list, choose a page type
// (blog / service / location / local SEO / ecommerce), then create every page now
// or drip/weekly/monthly-schedule them. The "Scheduled Content" list below shows
// everything queued for this client, including content scheduled from the Topic
// Fan-out tool.

export function ContentScheduler() {
  const { id } = useParams<{ id: string }>()
  const [view, setView] = useState<'list' | 'calendar'>('list')
  const { data: client } = useQuery<Client>({
    queryKey: ['client', id],
    queryFn: () => api.get<Client>(`/clients/${id}`),
    enabled: Boolean(id),
  })

  if (!id) return null

  return (
    <div style={{ padding: 32, maxWidth: 900 }}>
      <Link to={`/clients/${id}`} style={backLink}>
        <ArrowLeft size={14} /> Back to {client?.name ?? 'Client'}
      </Link>

      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
        Content Scheduler
      </h1>
      <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 20px' }}>
        Bulk-create or schedule pages from a keyword list — blog posts, service pages, location
        pages, Local SEO pages or ecommerce products. Upload a CSV (with headers) or paste one
        per line. Create now, or drip them out on a schedule.
      </p>

      <ScheduleBatch clientId={id} githubReady={Boolean(client?.github_repo)} />

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '28px 0 12px', gap: 12 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: 0 }}>
          Scheduled content
        </h2>
        <div style={{ display: 'inline-flex', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
          {([['list', 'List', <List size={14} key="l" />], ['calendar', 'Calendar', <CalendarDays size={14} key="c" />]] as const).map(([v, label, icon]) => (
            <button
              key={v}
              onClick={() => setView(v)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px',
                border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600,
                background: view === v ? '#eef2ff' : '#fff',
                color: view === v ? '#4338ca' : '#64748b',
              }}
            >
              {icon} {label}
            </button>
          ))}
        </div>
      </div>
      {view === 'list'
        ? <ScheduledContent clientId={id} />
        : <ContentCalendar scope="client" clientId={id} />}
    </div>
  )
}
