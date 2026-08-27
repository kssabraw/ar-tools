import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'

// Shared types and the batch-job hook for the Website Builder.
//
// "Publish" here means committing a page file into the site's GitHub repo — the
// repo builds and deploys itself. Nothing in this module puts anything on the
// internet directly, and the copy throughout says so.

export const ACCENT = '#0ea5e9'

export type SiteType = 'local_business' | 'informational' | 'lead_gen'
export type SiteStatus = 'draft' | 'provisioning' | 'live' | 'error'
export type DomainStatus = 'none' | 'pending_ns' | 'active'
export type PageStatus = 'draft' | 'queued' | 'published' | 'failed'
export type DeployStatus = 'queued' | 'building' | 'success' | 'failed' | 'unknown' | 'superseded'

export interface Website {
  id: string
  client_id: string
  name: string
  slug: string
  site_type: SiteType
  theme_id: string | null
  status: SiteStatus
  github_repo: string | null
  cf_project: string | null
  staging_url: string | null
  custom_domain: string | null
  domain_status: DomainStatus
  monetization: string[]
  config: Record<string, unknown>
  provision_state: { done?: string[] }
  error: string | null
  unpublished_at: string | null
  created_at: string
}

export interface WebsitePage {
  id: string
  website_id: string
  route: string
  title: string
  page_type: string | null
  trigger: string | null
  tier: number
  content_source: string
  source_id: string | null
  repo_path: string | null
  commit_sha: string | null
  status: PageStatus
  error: string | null
  published_at: string | null
  plan: { engine?: string | null; keyword?: string | null; location?: string | null }
}

export interface Deploy {
  id: string
  commit_sha: string | null
  trigger: string
  status: DeployStatus
  actions_run_id: string | null
  url: string | null
  error: string | null
  meta: { pages?: string[]; overrides?: { page_id: string; gate: string; forced_by: string }[] }
  polled_at: string | null
  created_at: string
}

export interface PlanIssue {
  kind: string
  blocking: boolean
  detail: string
  acknowledgeable: boolean
}

export interface PlanResponse {
  pages: WebsitePage[]
  plan: {
    pages: { path: string; page_type: string; title: string; trigger: string; tier: number; is_core: boolean; is_core_conditional: boolean }[]
    issues: PlanIssue[]
    matrix_count: number
    links_per_index: Record<string, number>
    blocked: boolean
  }
  approved: boolean
  approval: { approved_at?: string; approved_by?: string; acknowledged?: string[] }
  conflicts: PlanIssue[]
}

export interface ServiceRow {
  name: string
  slug?: string
  teaser?: string
  order?: number
  include_in_matrix?: boolean
  parent_slug?: string | null
  // Equipment brands this service is offered for. Their presence opts a
  // top-level service into brand × service pages (/{service}/{brand}/).
  brands?: string[]
}

export interface CityRow {
  name: string
  slug?: string
  neighborhoods?: { name: string }[]
}

// --- content plan (the blog) --------------------------------------------
// Blog posts are cross-family: an informational site's whole inventory and a
// local site's /blog/ both come from this. Planned per cluster (pillar), each
// post with a target format before generation.

export interface ContentPlanPost {
  title: string
  slug?: string
  format?: string
  keyword?: string
  buyer_problem?: string
  target_keywords?: string[]
}

export interface ContentPlanPillar {
  title: string
  slug?: string
  posts: ContentPlanPost[]
}

export interface ContentPlan {
  pillars: ContentPlanPillar[]
}

// The five formats the template renders. `format` is a plan-time decision: it
// changes the geo rule, the schema, and whether the post counts toward the
// >=5-evergreen pillar trigger (news is non-evergreen, excluded).
export const POST_FORMATS: { value: string; label: string }[] = [
  { value: 'informational_cluster', label: 'Cluster post (evergreen)' },
  { value: 'listicle', label: 'Listicle / roundup' },
  { value: 'comparison', label: 'Comparison / “vs”' },
  { value: 'local_geo', label: 'Local geo (local sites)' },
  { value: 'news', label: 'News (non-evergreen)' },
]

// --- release (drip-publish) schedule ------------------------------------

export type ReleaseMode = 'daily' | 'weekly' | 'monthly'

export interface ReleaseSchedule {
  id: string
  website_id: string
  enabled: boolean
  mode: ReleaseMode
  weekday: number | null
  day_of_month: number | null
  immediate_count: number
  per_release_count: number
  status: 'active' | 'complete' | 'paused'
  next_run_at: string | null
  last_run_at: string | null
}

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// --- shared styles -------------------------------------------------------

export const btn = (bg: string, fg = '#fff'): React.CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px', borderRadius: 8,
  border: bg === '#fff' ? '1px solid #e2e8f0' : 'none', background: bg, color: fg,
  fontSize: 13, fontWeight: 600, cursor: 'pointer',
})

export const input: React.CSSProperties = {
  width: '100%', padding: 9, borderRadius: 8, border: '1px solid #e2e8f0', fontSize: 13,
  fontFamily: 'inherit', boxSizing: 'border-box',
}

export const label: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 4, display: 'block',
}

export const card: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, background: '#fff',
}

export const STATUS_COLORS: Record<string, { fg: string; bg: string }> = {
  draft: { fg: '#64748b', bg: '#f8fafc' },
  queued: { fg: '#0369a1', bg: '#f0f9ff' },
  building: { fg: '#0369a1', bg: '#f0f9ff' },
  provisioning: { fg: '#0369a1', bg: '#f0f9ff' },
  published: { fg: '#15803d', bg: '#f0fdf4' },
  success: { fg: '#15803d', bg: '#f0fdf4' },
  live: { fg: '#15803d', bg: '#f0fdf4' },
  failed: { fg: '#b91c1c', bg: '#fef2f2' },
  error: { fg: '#b91c1c', bg: '#fef2f2' },
  // Neither red nor green on purpose: a superseded run's content shipped in the
  // run that replaced it, and an unknown one is very likely serving fine.
  superseded: { fg: '#7c3aed', bg: '#faf5ff' },
  unknown: { fg: '#b45309', bg: '#fffbeb' },
}

export function Chip({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? STATUS_COLORS.draft
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 999, fontSize: 11,
      fontWeight: 700, color: c.fg, background: c.bg, textTransform: 'capitalize',
    }}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

// --- batch jobs ----------------------------------------------------------

export interface JobRow {
  id: string
  status: string
  error: string | null
  result: Record<string, unknown> | null
}

export interface Batch {
  jobIds: string[]
  kind: 'generate' | 'publish'
}

const TERMINAL = new Set(['complete', 'failed', 'cancelled'])

/**
 * Track a batch of async jobs, surviving navigation.
 *
 * Generation and publishing run one job per page server-side, so the work
 * finishes whether or not this tab is open. The batch's job ids are persisted
 * so the *UI* survives the same navigation and picks the run back up on return
 * — the suite's "leave & finish in the background" affordance (PRD §6.3).
 */
export function useBatch(storageKey: string, websiteId: string | undefined, onDone: () => void) {
  const [batch, setBatch] = useState<Batch | null>(null)
  const [rows, setRows] = useState<JobRow[]>([])
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  // Resume on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      if (raw) setBatch(JSON.parse(raw) as Batch)
    } catch {
      /* a corrupt entry is not worth failing the page for */
    }
  }, [storageKey])

  const start = useCallback((jobIds: string[], kind: Batch['kind']) => {
    const next = { jobIds, kind }
    localStorage.setItem(storageKey, JSON.stringify(next))
    setBatch(next)
    setRows([])
  }, [storageKey])

  const clear = useCallback(() => {
    localStorage.removeItem(storageKey)
    setBatch(null)
    setRows([])
  }, [storageKey])

  useEffect(() => {
    if (!batch || !websiteId) return
    let cancelled = false

    const tick = async () => {
      try {
        const res = await api.post<{ jobs: JobRow[] }>(
          `/websites/${websiteId}/jobs/status`, { job_ids: batch.jobIds },
        )
        if (cancelled) return
        setRows(res.jobs)
        const finished = res.jobs.length > 0 && res.jobs.every((j) => TERMINAL.has(j.status))
        if (finished) {
          localStorage.removeItem(storageKey)
          doneRef.current()
        }
      } catch {
        /* transient poll failure: try again next tick rather than tearing down */
      }
    }

    void tick()
    const handle = setInterval(tick, 4000)
    return () => { cancelled = true; clearInterval(handle) }
  }, [batch, websiteId, storageKey])

  const finished = rows.filter((r) => TERMINAL.has(r.status)).length
  const failed = rows.filter((r) => r.status === 'failed').length
  const running = Boolean(batch) && (rows.length === 0 || finished < rows.length)

  return { batch, rows, start, clear, running, finished, failed, total: batch?.jobIds.length ?? 0 }
}

/**
 * Why an action is unavailable, or null when it is allowed.
 *
 * Actions above the user's role render disabled **with the reason** rather than
 * hidden (PRD §6.2) — hiding produces support questions instead of
 * understanding, and a VA should be able to see that publish exists and who to
 * ask.
 */
export function denyReason(
  need: 'staff' | 'admin',
  { isStaff, isAdmin, frozen }: { isStaff: boolean; isAdmin: boolean; frozen: boolean },
): string | null {
  if (frozen) return 'This client is frozen — content output is paused until the freeze lifts.'
  if (need === 'admin' && !isAdmin) return 'Admins only.'
  if (need === 'staff' && !isStaff) return 'Staff and admins only.'
  return null
}
