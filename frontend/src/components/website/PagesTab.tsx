import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, GitCommit, Loader2, RotateCcw, Sparkles, Upload, X } from 'lucide-react'
import { ACCENT, Chip, btn, card, denyReason, useBatch } from './shared'
import type { Website, WebsitePage } from './shared'
import { api } from '../../lib/api'

// The Pages tab. Two things it must not do:
//
//  * imply that everything is generable — a page type with no engine says so on
//    its row rather than sitting at draft with no explanation; and
//  * hide why a page is held. A gate reason is the whole point of holding at
//    draft instead of dropping the page, so it renders next to the row.

// Reasons a page can be held, in the words the backend uses, translated once.
const GATE_COPY: Record<string, string> = {
  facts_consistency_failed: 'Claims a fact that is not in the business facts. Not overridable at any role.',
  voice_violation: 'Unresolved critical brand-voice finding.',
  writer_run_degraded: 'Written with zero brand context — never auto-published.',
  news_post_missing_review_date: 'A news post needs a review/sunset date.',
  seo_composite_missing: 'No SEO score — scoring failed or never ran.',
  body_not_generated: 'Nothing written yet. Generate it first.',
  content_no_brand_context: 'This client has no brand voice on file.',
}

function gateHint(error: string | null): string | null {
  if (!error) return null
  const key = error.split(':')[0]
  if (GATE_COPY[key]) return GATE_COPY[key]
  if (key === 'seo_composite_below_threshold') return `SEO composite below 75 (${error.split(':')[1]}). Reoptimize, or publish with an override.`
  if (key === 'engine_unavailable') return `No writer in the suite covers ${error.split(':')[1]} pages yet.`
  if (key === 'engine_not_built') return `The ${error.split(':')[1]} generator is specified but not built yet.`
  if (key === 'template_rendered') return 'Rendered by the template from published data — nothing to write.'
  return error
}

interface Props {
  website: Website
  pages: WebsitePage[]
  approved: boolean
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

export function PagesTab({ website, pages, approved, perms }: Props) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [force, setForce] = useState(false)

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['website', website.id] })
    void qc.invalidateQueries({ queryKey: ['website-plan', website.id] })
  }
  const batch = useBatch(`website-batch-${website.id}`, website.id, refresh)

  // VAs generate and retry — that is their work, and both are idempotent. What
  // they may not do is publish: publish here means the public internet, not a
  // reviewable Doc (PRD §2). So generation's only bar is the freeze.
  const generateDeny = perms.frozen
    ? 'This client is frozen — content output is paused until the freeze lifts.'
    : null
  const publishDeny = denyReason('staff', perms)

  // Both writing engines: nlp (service/location/matrix, with SERP + scoring) and
  // core_pages (home/about/contact, a light single call). 'template' and null
  // are not generable — the template renders one and nothing writes the other.
  const generable = useMemo(
    () => pages.filter((p) => (p.plan?.engine === 'nlp' || p.plan?.engine === 'core_pages') && selected.has(p.id)),
    [pages, selected],
  )
  const publishable = useMemo(
    () => pages.filter((p) => selected.has(p.id) && p.plan?.engine !== null),
    [pages, selected],
  )

  const generate = useMutation({
    mutationFn: () => api.post<{ job_ids: string[] }>(`/websites/${website.id}/generate`, {
      page_ids: generable.map((p) => p.id),
    }),
    onSuccess: (res) => { batch.start(res.job_ids, 'generate'); setSelected(new Set()) },
  })

  const publish = useMutation({
    mutationFn: () => api.post<{ job_ids: string[] }>(`/websites/${website.id}/publish`, {
      page_ids: publishable.map((p) => p.id), force,
    }),
    onSuccess: (res) => { batch.start(res.job_ids, 'publish'); setSelected(new Set()); setForce(false) },
  })

  const retry = useMutation({
    mutationFn: (pageId: string) => api.post(`/websites/${website.id}/pages/${pageId}/retry`, {}),
    onSuccess: refresh,
  })

  const toggle = (id: string) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  if (!approved) {
    return (
      <div style={{ ...card, color: '#64748b', fontSize: 13 }}>
        The plan needs approving before anything is generated or published. Approve it on the
        Plan tab — a local business site gets a human review before its first publish.
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {batch.batch && (
        <div style={{ ...card, borderColor: '#bae6fd', background: '#f0f9ff', display: 'flex', alignItems: 'center', gap: 10 }}>
          <Loader2 size={15} className="spin" color={ACCENT} />
          <div style={{ flex: 1, fontSize: 13, color: '#0369a1' }}>
            <strong>{batch.batch.kind === 'generate' ? 'Generating' : 'Publishing'}</strong>{' '}
            {batch.finished} of {batch.total}
            {batch.failed > 0 && <span style={{ color: '#b91c1c' }}> · {batch.failed} failed</span>}
            <div style={{ fontSize: 11, color: '#64748b' }}>
              Safe to leave — this runs server-side and picks back up when you return.
            </div>
          </div>
          <button onClick={batch.clear} style={{ ...btn('#fff', '#64748b'), padding: '6px 8px' }} title="Stop watching">
            <X size={13} />
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          onClick={() => generate.mutate()}
          disabled={generable.length === 0 || Boolean(generateDeny) || generate.isPending}
          title={generateDeny ?? (generable.length === 0 ? 'Select pages an engine can write.' : `Writes ${generable.length} page(s). Service/location pages cost a SERP analysis each; home/about/contact are a single cheap call.`)}
          style={{ ...btn(generable.length === 0 || generateDeny ? '#e2e8f0' : ACCENT, generable.length === 0 || generateDeny ? '#94a3b8' : '#fff') }}
        >
          {generate.isPending ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
          Generate {generable.length > 0 ? `(${generable.length})` : ''}
        </button>

        <button
          onClick={() => publish.mutate()}
          disabled={publishable.length === 0 || Boolean(publishDeny) || publish.isPending}
          title={publishDeny ?? (publishable.length === 0 ? 'Select pages to commit.' : 'Commits each page into the site repo, which triggers a deploy.')}
          style={{ ...btn(publishable.length === 0 || publishDeny ? '#e2e8f0' : '#15803d', publishable.length === 0 || publishDeny ? '#94a3b8' : '#fff') }}
        >
          {publish.isPending ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
          Publish {publishable.length > 0 ? `(${publishable.length})` : ''}
        </button>

        {!publishDeny && (
          <label style={{ fontSize: 12, color: '#64748b', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                 title="Forces past an overridable gate only. A facts-consistency failure is not overridable at any role, and the override is recorded on the deploy.">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            Publish anyway
          </label>
        )}
        {publishDeny && (
          <span style={{ fontSize: 12, color: '#94a3b8' }}>{publishDeny}</span>
        )}
      </div>

      {(generate.error || publish.error) && (
        <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12 }}>
          {((generate.error ?? publish.error) as Error).message}
        </div>
      )}

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: 'left', color: '#64748b' }}>
              <th style={{ ...th, width: 28 }}>
                <input type="checkbox"
                       checked={selected.size > 0 && selected.size === pages.length}
                       onChange={(e) => setSelected(e.target.checked ? new Set(pages.map((p) => p.id)) : new Set())} />
              </th>
              <th style={th}>Path</th><th style={th}>Type</th><th style={th}>Status</th>
              <th style={th}>Engine</th><th style={th}>Notes</th><th style={th} />
            </tr>
          </thead>
          <tbody>
            {pages.map((page) => {
              const hint = gateHint(page.error)
              const engine = page.plan?.engine
              return (
                <tr key={page.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={td}>
                    <input type="checkbox" checked={selected.has(page.id)} onChange={() => toggle(page.id)} />
                  </td>
                  <td style={{ ...td, fontFamily: 'ui-monospace, monospace' }}>
                    {page.route}
                    {page.commit_sha && (
                      <div style={{ color: '#94a3b8', fontSize: 11, display: 'flex', alignItems: 'center', gap: 3 }}>
                        <GitCommit size={10} /> {page.commit_sha.slice(0, 7)}
                      </div>
                    )}
                  </td>
                  <td style={td}>{page.page_type}</td>
                  <td style={td}><Chip status={page.status} /></td>
                  <td style={{ ...td, color: engine ? '#475569' : '#b45309' }}>
                    {engine ?? 'none'}
                  </td>
                  <td style={{ ...td, color: page.status === 'failed' ? '#b91c1c' : '#64748b', maxWidth: 320 }}>
                    {hint && (
                      <span style={{ display: 'inline-flex', gap: 4, alignItems: 'flex-start' }}>
                        <AlertTriangle size={11} style={{ marginTop: 2, flexShrink: 0 }} /> {hint}
                      </span>
                    )}
                  </td>
                  <td style={td}>
                    {page.status === 'failed' && (
                      <button onClick={() => retry.mutate(page.id)} disabled={perms.frozen}
                              title={perms.frozen ? 'This client is frozen.' : 'Retry — idempotent, so this never creates a second commit.'}
                              style={{ ...btn('#fff', ACCENT), padding: '5px 8px' }}>
                        <RotateCcw size={12} /> Retry
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {pages.length === 0 && (
          <div style={{ color: '#64748b', fontSize: 13, padding: 8 }}>
            No pages yet — build the plan on the Plan tab.
          </div>
        )}
      </div>
    </div>
  )
}

const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600 }
const td: React.CSSProperties = { padding: '6px 8px', verticalAlign: 'top' }
