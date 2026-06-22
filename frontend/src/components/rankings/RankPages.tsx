import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { PagesResponse } from '../../lib/types'
import { card } from '../localseo/shared'

// Pages view: GSC performance pivoted by landing page. Search Console only —
// DataForSEO mode has no per-page data.
export function RankPages({ clientId }: { clientId: string }) {
  const { data, isLoading } = useQuery<PagesResponse>({
    queryKey: ['rank-pages', clientId],
    queryFn: () => api.get<PagesResponse>(`/clients/${clientId}/rank/pages`),
  })

  if (isLoading) return <p style={{ color: '#94a3b8', fontSize: 14 }}>Loading pages…</p>

  if (!data?.gsc_connected) {
    return (
      <div style={{ ...card, color: '#64748b', fontSize: 13, lineHeight: 1.6 }}>
        The Pages view is built from Search Console’s query×page data, so it needs a verified GSC
        property. Connect one under <strong>Settings</strong> to see landing-page performance.
      </div>
    )
  }

  if (data.pages.length === 0) {
    return (
      <div style={{ ...card, color: '#64748b', fontSize: 13 }}>
        No page data yet — the weekly query×page sync populates this. Trigger a sync from Settings, or
        check back after the next run.
      </div>
    )
  }

  return (
    <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
            <th style={thLeft}>Page</th>
            <th style={th}>Keywords</th>
            <th style={th}>Clicks</th>
            <th style={th}>Impr.</th>
            <th style={th}>Avg pos.</th>
          </tr>
        </thead>
        <tbody>
          {data.pages.map(p => (
            <tr key={p.page} style={{ borderBottom: '1px solid #f1f5f9' }}>
              <td style={tdLeft}>
                <a href={p.page} target="_blank" rel="noreferrer"
                  style={{ color: '#6366f1', textDecoration: 'none', maxWidth: 420, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}>
                  {p.page}
                </a>
              </td>
              <td style={td}>{p.keywords.toLocaleString()}</td>
              <td style={td}>{p.clicks.toLocaleString()}</td>
              <td style={td}>{p.impressions.toLocaleString()}</td>
              <td style={td}>{p.avg_position != null ? p.avg_position.toFixed(1) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const th: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', fontSize: 11, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.03em', whiteSpace: 'nowrap' }
const thLeft: React.CSSProperties = { ...th, textAlign: 'left' }
const td: React.CSSProperties = { padding: '10px 12px', textAlign: 'right', whiteSpace: 'nowrap' }
const tdLeft: React.CSSProperties = { ...td, textAlign: 'left' }
