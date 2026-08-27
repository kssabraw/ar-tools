import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Sparkles, Trash2, Save, Download } from 'lucide-react'
import { ACCENT, btn, card, denyReason, input, POST_FORMATS } from './shared'
import type { ContentPlan, ContentPlanPillar, ContentPlanPost, Website } from './shared'
import { api } from '../../lib/api'

// The blog content plan (reference §5.3). Site-owned: the Website Builder keeps
// the pillars → posts inventory in `config.content_plan`, editable here and
// durable across a re-research. Two seed sources fill it in one click — the
// client's latest topic-strategist plan, or a finished Topic Fanout session —
// after which it is the site's own data. Shown for every site type: an
// informational site's whole inventory, a local site's /blog/.

interface Props {
  website: Website
  perms: { isStaff: boolean; isAdmin: boolean; frozen: boolean }
}

const EVERGREEN = new Set(['informational_cluster', 'listicle', 'comparison', 'local_geo'])
const PILLAR_MIN = 5

export function ContentPlanEditor({ website, perms }: Props) {
  const qc = useQueryClient()
  const stored = (website.config as { content_plan?: ContentPlan }).content_plan
  const [pillars, setPillars] = useState<ContentPlanPillar[]>(stored?.pillars ?? [])
  const [sessionId, setSessionId] = useState('')

  // Re-seed from the stored plan when a seed/save lands underneath us.
  useEffect(() => {
    setPillars(stored?.pillars ?? [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(stored?.pillars)])

  const deny = denyReason('staff', perms)
  const hasStored = Boolean(stored?.pillars?.length)
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['website', website.id] })
    void qc.invalidateQueries({ queryKey: ['website-plan', website.id] })
  }

  const save = useMutation({
    mutationFn: () => api.put(`/websites/${website.id}/content-plan`, { content_plan: { pillars } }),
    onSuccess: invalidate,
  })
  const seedStrategist = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/content-plan/seed`, { replace: hasStored }),
    onSuccess: invalidate,
  })
  const seedFanout = useMutation({
    mutationFn: () => api.post(`/websites/${website.id}/content-plan/seed-fanout`,
      { session_id: sessionId.trim(), replace: hasStored }),
    onSuccess: invalidate,
  })

  const confirmReplace = () =>
    !hasStored || window.confirm('This replaces the current content plan. Continue?')

  const totalPosts = pillars.reduce((n, p) => n + p.posts.length, 0)
  const hubs = pillars.filter((p) => p.posts.filter((x) => EVERGREEN.has(x.format || 'informational_cluster')).length >= PILLAR_MIN).length
  const dirty = JSON.stringify(pillars) !== JSON.stringify(stored?.pillars ?? [])

  const updatePillar = (i: number, patch: Partial<ContentPlanPillar>) =>
    setPillars(pillars.map((p, j) => (i === j ? { ...p, ...patch } : p)))
  const updatePost = (pi: number, si: number, patch: Partial<ContentPlanPost>) =>
    updatePillar(pi, { posts: pillars[pi].posts.map((s, j) => (j === si ? { ...s, ...patch } : s)) })

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
        <div>
          <strong style={{ fontSize: 14, color: '#0f172a' }}>Blog content plan</strong>
          <p style={{ fontSize: 12, color: '#64748b', margin: '4px 0 0', maxWidth: 640 }}>
            Topic silos (pillars) and the posts under each. Every post gets a format before
            generation; a silo with {PILLAR_MIN}+ evergreen posts also earns a top-level hub
            page. Seed it from a research plan, then edit — after seeding it's the site's own
            data. On a local site this fills the <code>/blog/</code> alongside your service pages.
          </p>
        </div>
        <span style={{ fontSize: 12, color: '#64748b', whiteSpace: 'nowrap' }}>
          {pillars.length} silo{pillars.length === 1 ? '' : 's'} · {totalPosts} post{totalPosts === 1 ? '' : 's'} · {hubs} hub{hubs === 1 ? '' : 's'}
        </span>
      </div>

      {/* Seed bar */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '12px 0 4px' }}>
        <button
          onClick={() => { if (confirmReplace()) seedStrategist.mutate() }}
          disabled={Boolean(deny) || seedStrategist.isPending}
          title={deny ?? 'Import the client’s latest Topic-Strategist plan.'}
          style={btn(deny ? '#e2e8f0' : '#fff', deny ? '#94a3b8' : ACCENT)}
        >
          {seedStrategist.isPending ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
          {hasStored ? 'Re-seed from strategist' : 'Seed from strategist'}
        </button>
        <span style={{ fontSize: 12, color: '#cbd5e1' }}>or</span>
        <input
          style={{ ...input, width: 280 }}
          placeholder="Fanout session id"
          value={sessionId}
          disabled={Boolean(deny)}
          onChange={(e) => setSessionId(e.target.value)}
        />
        <button
          onClick={() => { if (confirmReplace()) seedFanout.mutate() }}
          disabled={Boolean(deny) || seedFanout.isPending || !sessionId.trim()}
          title={deny ?? (!sessionId.trim() ? 'Paste the Fanout session id (from its workspace URL).' : 'Import a finished Fanout session’s silos & clusters (always regenerates fresh).')}
          style={btn(deny || !sessionId.trim() ? '#e2e8f0' : '#fff', deny || !sessionId.trim() ? '#94a3b8' : ACCENT)}
        >
          {seedFanout.isPending ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
          Seed from Fanout
        </button>
      </div>
      {seedStrategist.error && <SeedError message={(seedStrategist.error as Error).message} />}
      {seedFanout.error && <SeedError message={(seedFanout.error as Error).message} />}

      {/* Editor */}
      <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
        {pillars.map((pillar, pi) => (
          <div key={pi} style={{ border: '1px solid #e2e8f0', borderRadius: 8, padding: 12, background: '#f8fafc' }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <input style={{ ...input, fontWeight: 600 }} placeholder="Silo / pillar title (e.g. Roof Maintenance)"
                     value={pillar.title} disabled={Boolean(deny)}
                     onChange={(e) => updatePillar(pi, { title: e.target.value })} />
              <button onClick={() => setPillars(pillars.filter((_, j) => j !== pi))} disabled={Boolean(deny)}
                      style={{ ...btn('#fff', '#b91c1c'), padding: '6px 8px' }} title="Remove silo">
                <Trash2 size={13} />
              </button>
            </div>

            <div style={{ display: 'grid', gap: 5 }}>
              {pillar.posts.map((post, si) => (
                <div key={si} style={{ display: 'grid', gridTemplateColumns: '2fr 1.2fr 1.4fr auto', gap: 6, alignItems: 'center' }}>
                  <input style={input} placeholder="Post title" value={post.title} disabled={Boolean(deny)}
                         onChange={(e) => updatePost(pi, si, { title: e.target.value })} />
                  <select style={input} value={post.format || 'informational_cluster'} disabled={Boolean(deny)}
                          onChange={(e) => updatePost(pi, si, { format: e.target.value })}>
                    {POST_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                  <input style={input} placeholder="Target keyword (optional)" value={post.keyword ?? ''} disabled={Boolean(deny)}
                         onChange={(e) => updatePost(pi, si, { keyword: e.target.value })} />
                  <button onClick={() => updatePillar(pi, { posts: pillar.posts.filter((_, j) => j !== si) })}
                          disabled={Boolean(deny)} style={{ ...btn('#fff', '#b91c1c'), padding: '6px 8px' }} title="Remove post">
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              <button onClick={() => updatePillar(pi, { posts: [...pillar.posts, { title: '', format: 'informational_cluster' }] })}
                      disabled={Boolean(deny)} style={{ ...btn('#fff', ACCENT), justifySelf: 'start', padding: '5px 10px' }}>
                <Plus size={12} /> Add post
              </button>
            </div>
          </div>
        ))}
        <button onClick={() => setPillars([...pillars, { title: '', posts: [] }])} disabled={Boolean(deny)}
                style={{ ...btn('#fff', ACCENT), justifySelf: 'start' }}>
          <Plus size={13} /> Add silo
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14 }}>
        <button
          onClick={() => save.mutate()}
          disabled={Boolean(deny) || save.isPending || !dirty}
          title={deny ?? (!dirty ? 'No changes to save.' : 'Save the plan and rebuild the reviewable page list.')}
          style={btn(deny || !dirty ? '#e2e8f0' : '#15803d', deny || !dirty ? '#94a3b8' : '#fff')}
        >
          {save.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
          Save content plan
        </button>
        {save.isSuccess && !dirty && <span style={{ fontSize: 12, color: '#15803d' }}>Saved — plan rebuilt below.</span>}
      </div>
      {save.error && <SeedError message={(save.error as Error).message} />}
    </div>
  )
}

function SeedError({ message }: { message: string }) {
  return (
    <div style={{ padding: 10, borderRadius: 8, background: '#fef2f2', color: '#b91c1c', fontSize: 12, marginTop: 8 }}>
      {friendlySeedError(message)}
    </div>
  )
}

// The backend's stable codes → a sentence a VA can act on.
function friendlySeedError(message: string): string {
  const m = message.toLowerCase()
  if (m.includes('no_strategist_plan')) return 'No topic-strategist plan on file for this client yet — run Topic Research (with the strategist) first, or build the plan by hand.'
  if (m.includes('fanout_session_not_found')) return 'No Fanout session with that id.'
  if (m.includes('fanout_session_other_client')) return 'That Fanout session belongs to a different client.'
  if (m.includes('fanout_session_empty')) return 'That Fanout session has no clusters to import.'
  if (m.includes('content_plan_exists')) return 'A content plan already exists — this replaces it.'
  return message
}
