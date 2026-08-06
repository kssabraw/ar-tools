import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { ACCENT, Chip, btn, card } from './shared'
import type { Deploy, Website } from './shared'
import { api } from '../../lib/api'

// Deploy history. Two statuses need explaining wherever they appear, because
// neither means what its colour would suggest on its own:
//
//  * superseded — the workflow cancels in-progress runs, so a batch publish
//    cancels everything but the last. That content shipped in the run that
//    replaced it.
//  * unknown — the run could not be found. The site is very likely serving
//    fine; we simply stopped being able to see it, so the answer is a re-check
//    rather than a re-push.
const STATUS_NOTE: Record<string, string> = {
  superseded: 'Cancelled by a later commit — its content shipped in the run that replaced it.',
  unknown: 'The Actions run could not be found. The site is still serving its last good deploy.',
  failed: 'The build or deploy failed. The site is still serving its last good deploy.',
}

interface Props {
  website: Website
  deploys: Deploy[]
}

export function DeploysTab({ website, deploys }: Props) {
  const qc = useQueryClient()
  const recheck = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/deploys/recheck`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['website', website.id] }),
  })

  const unresolved = deploys.filter((d) => ['queued', 'building', 'unknown'].includes(d.status)).length

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <button onClick={() => recheck.mutate()} disabled={recheck.isPending} style={btn('#fff', ACCENT)}>
          {recheck.isPending ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
          Re-check now
        </button>
        <span style={{ fontSize: 12, color: '#64748b' }}>
          {unresolved > 0
            ? `${unresolved} deploy${unresolved === 1 ? '' : 's'} still resolving. GitHub does not call us back, so these are polled.`
            : 'Every recorded deploy has resolved.'}
        </span>
      </div>

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b' }}>
              <th style={th}>When</th><th style={th}>Trigger</th><th style={th}>Commit</th>
              <th style={th}>Status</th><th style={th}>Notes</th><th style={th} />
            </tr>
          </thead>
          <tbody>
            {deploys.map((d) => (
              <tr key={d.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                <td style={td}>{new Date(d.created_at).toLocaleString()}</td>
                <td style={td}>{d.trigger}</td>
                <td style={{ ...td, fontFamily: 'ui-monospace, monospace' }}>
                  {d.commit_sha ? d.commit_sha.slice(0, 7) : '—'}
                </td>
                <td style={td}><Chip status={d.status} /></td>
                <td style={{ ...td, color: '#64748b', maxWidth: 340 }}>
                  {STATUS_NOTE[d.status] ?? ''}
                  {d.meta?.overrides?.length ? (
                    <div style={{ marginTop: 4, color: '#b45309', display: 'flex', gap: 4, alignItems: 'flex-start' }}>
                      <ShieldAlert size={11} style={{ marginTop: 2, flexShrink: 0 }} />
                      <span>
                        Gate overridden: {d.meta.overrides.map((o) => o.gate).join(', ')}
                      </span>
                    </div>
                  ) : null}
                </td>
                <td style={td}>
                  {d.url && (
                    <a href={d.url} target="_blank" rel="noreferrer"
                       style={{ color: ACCENT, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      Actions log <ExternalLink size={11} />
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {deploys.length === 0 && (
          <div style={{ color: '#64748b', fontSize: 13, padding: 8 }}>
            No deploys yet — the first one is recorded when the site is provisioned.
          </div>
        )}
      </div>
    </div>
  )
}

const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600 }
const td: React.CSSProperties = { padding: '6px 8px', verticalAlign: 'top' }
