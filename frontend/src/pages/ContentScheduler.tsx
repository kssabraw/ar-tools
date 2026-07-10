import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { api } from '../lib/api'
import type { Client } from '../lib/types'
import { backLink } from '../components/localseo/shared'
import { ScheduleBatch } from '../components/scheduler/ScheduleBatch'
import { ScheduledContent } from '../components/scheduler/ScheduledContent'

// The suite Content Scheduler: paste/upload a keyword list, choose a page type
// (blog / service / location / local SEO), then create every page now or
// drip/weekly/monthly-schedule them. The "Scheduled Content" list below shows
// everything queued for this client, including content scheduled from the Topic
// Fan-out tool.

export function ContentScheduler() {
  const { id } = useParams<{ id: string }>()
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
        pages or Local SEO pages. Create now, or drip them out on a schedule.
      </p>

      <ScheduleBatch clientId={id} />

      <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '28px 0 12px' }}>
        Scheduled content
      </h2>
      <ScheduledContent clientId={id} />
    </div>
  )
}
