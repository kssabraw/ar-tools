import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Circle, ExternalLink, GitBranch, Loader2, Play } from 'lucide-react'
import { ACCENT, Chip, btn, card, denyReason } from './shared'
import type { Deploy, Website } from './shared'
import { api } from '../../lib/api'

// The provisioning step machine, in the order the job runs them. Showing the
// steps rather than a spinner is what makes a failure actionable: PRD §6.3 asks
// for "steps 1..N-1 green, step N red", and a Resume that re-runs from N rather
// than a Start over that would mint a second repo.
const STEPS: { key: string; label: string; detail: string }[] = [
  { key: 'generate', label: 'Repository', detail: 'Create the site repo from the house template' },
  { key: 'secrets', label: 'Deploy secrets', detail: 'Write the Cloudflare credentials into the repo' },
  { key: 'configure', label: 'Site config', detail: 'Commit site.config.json and the worker name' },
  { key: 'deploy', label: 'First deploy', detail: 'Record the build the config commit triggered' },
]

interface Props {
  website: Website
  deploys: Deploy[]
  pageCount: number
  publishedCount: number
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

export function OverviewTab({ website, deploys, pageCount, publishedCount, perms }: Props) {
  const qc = useQueryClient()
  const done = new Set(website.provision_state?.done ?? [])
  const provisioned = Boolean(website.github_repo)
  const deny = denyReason('staff', perms)

  const provision = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/provision`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['website', website.id] }),
  })

  const currentStep = STEPS.find((s) => !done.has(s.key))
  const lastDeploy = deploys[0]

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <strong style={{ fontSize: 15, color: '#0f172a' }}>{website.name}</strong>
            <Chip status={website.status} />
          </div>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            {website.site_type.replace(/_/g, ' ')}
          </span>
        </div>

        <dl style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '8px 16px', margin: 0, fontSize: 13 }}>
          <dt style={{ color: '#64748b' }}>Staging</dt>
          <dd style={{ margin: 0 }}>
            {website.staging_url ? (
              <a href={website.staging_url} target="_blank" rel="noreferrer"
                 style={{ color: ACCENT, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {website.staging_url} <ExternalLink size={12} />
              </a>
            ) : <span style={{ color: '#94a3b8' }}>not provisioned yet</span>}
          </dd>

          <dt style={{ color: '#64748b' }}>Domain</dt>
          <dd style={{ margin: 0 }}>
            {website.custom_domain
              ? <>{website.custom_domain} <Chip status={website.domain_status === 'active' ? 'success' : 'queued'} /></>
              : <span style={{ color: '#94a3b8' }}>none attached — the site answers on its staging URL</span>}
          </dd>

          <dt style={{ color: '#64748b' }}>Repository</dt>
          <dd style={{ margin: 0 }}>
            {website.github_repo ? (
              <a href={`https://github.com/${website.github_repo}`} target="_blank" rel="noreferrer"
                 style={{ color: ACCENT, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <GitBranch size={12} /> {website.github_repo}
              </a>
            ) : <span style={{ color: '#94a3b8' }}>not created yet</span>}
          </dd>

          <dt style={{ color: '#64748b' }}>Pages</dt>
          <dd style={{ margin: 0 }}>{publishedCount} published of {pageCount} planned</dd>

          <dt style={{ color: '#64748b' }}>Last deploy</dt>
          <dd style={{ margin: 0 }}>
            {lastDeploy
              ? <><Chip status={lastDeploy.status} /> <span style={{ color: '#64748b', marginLeft: 6 }}>
                  {new Date(lastDeploy.created_at).toLocaleString()}
                </span></>
              : <span style={{ color: '#94a3b8' }}>none yet</span>}
          </dd>
        </dl>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <strong style={{ fontSize: 14, color: '#0f172a' }}>Provisioning</strong>
          {website.status !== 'provisioning' && (
            <button
              onClick={() => provision.mutate()}
              disabled={Boolean(deny) || provision.isPending}
              title={deny ?? undefined}
              style={{ ...btn(deny ? '#e2e8f0' : ACCENT, deny ? '#94a3b8' : '#fff'), cursor: deny ? 'not-allowed' : 'pointer' }}
            >
              {provision.isPending ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
              {website.status === 'error' ? 'Resume' : provisioned ? 'Re-run' : 'Provision'}
            </button>
          )}
        </div>
        <p style={{ fontSize: 12, color: '#64748b', margin: '0 0 12px' }}>
          Each step is re-runnable and completed steps are skipped, so a failure is resumed
          rather than restarted — running it again never mints a second repo.
        </p>

        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 8 }}>
          {STEPS.map((step) => {
            const isDone = done.has(step.key)
            const isFailed = website.status === 'error' && currentStep?.key === step.key
            return (
              <li key={step.key} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13 }}>
                {isDone
                  ? <CheckCircle2 size={16} color="#15803d" style={{ flexShrink: 0, marginTop: 1 }} />
                  : isFailed
                    ? <AlertTriangle size={16} color="#b91c1c" style={{ flexShrink: 0, marginTop: 1 }} />
                    : <Circle size={16} color="#cbd5e1" style={{ flexShrink: 0, marginTop: 1 }} />}
                <div>
                  <div style={{ color: isFailed ? '#b91c1c' : '#0f172a', fontWeight: 600 }}>{step.label}</div>
                  <div style={{ color: '#64748b', fontSize: 12 }}>{step.detail}</div>
                </div>
              </li>
            )
          })}
        </ol>

        {website.error && (
          <div style={{ marginTop: 12, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
            Failed at <strong>{currentStep?.label ?? 'an unknown step'}</strong>: <code>{website.error}</code>
          </div>
        )}
        {provision.error && (
          <div style={{ marginTop: 12, padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
            {(provision.error as Error).message}
          </div>
        )}
      </div>
    </div>
  )
}
