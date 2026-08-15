import { FileText, GitBranch, Globe, Link2 } from 'lucide-react'
import { localSeoApi } from '../localseo/api'
import { ecommerceApi } from '../ecommerce/api'
import type { EcommercePageType, ReoptimizeUrlResult } from '../ecommerce/types'
import { reoptApi, type ReoptBulkResponse } from './api'
import type { ReoptAdapter, ReoptHandle, ReoptResult } from './types'

// The four tool adapters that drive the shared ReoptimizePanel. Local SEO +
// Ecommerce keep their existing job-based reoptimizeBulk + jobsStatus flow (a
// ReoptimizeUrlResult per job). Blog + Service external reopt spawns full suite
// runs (one per item) which are polled via /runs/{id}. Blog + Service "existing
// suite run" score/reopt (job endpoints) live in their run-detail views, not here.

// ── Job-based result mapping (Local SEO / Ecommerce) ──
type JobStatus = { job_id: string; status: string; result?: Record<string, unknown> | null; error?: string | null }

function jobResult(id: string, label: string, st: JobStatus | undefined): ReoptResult {
  if (!st) return { id, label, status: 'queued' }
  if (st.status === 'complete' && st.result) {
    const r = st.result as unknown as ReoptimizeUrlResult
    if (r.status === 'skipped') {
      return { id, label, status: 'skipped', reason: r.reason, prevScore: r.score }
    }
    return {
      id, label, status: 'done',
      prevScore: r.prev_score, newScore: r.new_score,
      docUrl: r.published?.doc_url ?? null,
      publishError: r.publish_error ?? null,
    }
  }
  if (st.status === 'failed') return { id, label, status: 'failed', reason: st.error ?? 'Reoptimization failed' }
  if (st.status === 'running') return { id, label, status: 'working' }
  return { id, label, status: 'queued' }
}

// ── Run-based result mapping (Blog / Service) ──
const RUN_TERMINAL = new Set(['complete', 'failed', 'cancelled'])

async function runPoll(handles: ReoptHandle[]): Promise<ReoptResult[]> {
  return Promise.all(handles.map(async h => {
    if (h.kind !== 'run') return { id: h.id, label: h.label, status: 'queued' as const }
    try {
      const run = await reoptApi.getRun(h.runId)
      if (run.status === 'complete') {
        return { id: h.id, label: h.label, status: 'done', runId: h.runId, docUrl: run.published_doc_url ?? null }
      }
      if (RUN_TERMINAL.has(run.status)) {
        return { id: h.id, label: h.label, status: 'failed', reason: run.error_message ?? 'The run did not complete.', runId: h.runId }
      }
      return { id: h.id, label: h.label, status: 'working', runId: h.runId }
    } catch {
      // Transient poll failure — keep the row in-flight rather than failing it.
      return { id: h.id, label: h.label, status: 'working', runId: h.runId }
    }
  }))
}

// Turn a run-spawning bulk response into handles: one `run` handle per started
// run + one terminal `skipped` handle per item the backend refused to start.
function runHandles(res: ReoptBulkResponse): ReoptHandle[] {
  const runs: ReoptHandle[] = (res.runs ?? []).map(r => ({
    kind: 'run' as const, id: r.run_id, runId: r.run_id, label: r.keyword || r.run_id,
  }))
  const skipped: ReoptHandle[] = (res.skipped ?? []).map((s, i) => ({
    kind: 'skipped' as const,
    id: `skip:${i}:${s.keyword ?? s.source_url ?? s.url ?? i}`,
    label: s.keyword ?? s.source_url ?? s.url ?? 'Skipped item',
    reason: s.reason ?? s.error ?? 'Skipped — already strong, or missing a URL / content.',
  }))
  return [...runs, ...skipped]
}

// ── Local SEO ────────────────────────────────────────────────────────────────
export function localSeoAdapter(clientId: string, clientName: string | undefined, onOpenSaved: () => void): ReoptAdapter {
  const SCORE_THRESHOLD = 75
  return {
    toolLabel: 'Local SEO',
    storageKey: `reopt:localseo:${clientId}`,
    clientId,
    scoreThreshold: SCORE_THRESHOLD,
    supportsUrl: true,
    supportsPaste: false,
    supportsExisting: false,
    supportsEntityProvider: true,
    urlSingleToggle: true,
    requiresKeyword: true,
    keywordLabel: 'Service',
    keywordPlaceholder: 'e.g. emergency plumber',
    supportsLocation: true,
    onOpenSaved,
    savedLinkLabel: 'view in Saved Pages',
    destinations: [
      { id: 'app', title: 'Save in the app', subtitle: "Stored as a reoptimized page in this client's workspace (always saved).", icon: <Link2 size={15} /> },
      { id: 'doc', title: 'Save in the app + publish to Google Doc', subtitle: `A Google Doc is created in ${clientName ?? 'the client'}'s Drive folder for each rewritten page.`, icon: <FileText size={15} /> },
      { id: 'github', title: 'Commit to a GitHub repo', subtitle: 'Coming soon.', icon: <GitBranch size={15} />, disabled: true },
      { id: 'wordpress', title: 'Publish to WordPress', subtitle: 'Coming soon.', icon: <Globe size={15} />, disabled: true },
    ],
    async start(items, opts) {
      const res = await localSeoApi.reoptimizeBulk(clientId, {
        targets: items.map(t => ({
          page_url: t.url ?? '',
          keyword: t.keyword,
          location: t.location ?? undefined,
          location_code: t.locationCode ?? null,
        })),
        score_threshold: SCORE_THRESHOLD,
        publish_to_doc: opts.destination === 'doc',
        entity_provider: opts.entityProvider ?? null,
      })
      return (res.jobs ?? []).map(j => ({
        kind: 'job' as const, id: j.job_id, jobId: j.job_id, label: j.page_url.replace(/^https?:\/\//, ''),
      }))
    },
    async poll(handles) {
      const jobIds = handles.map(h => (h.kind === 'job' ? h.jobId : '')).filter(Boolean)
      if (!jobIds.length) return []
      const statuses = await localSeoApi.jobsStatus(clientId, jobIds)
      const byId = new Map(statuses.map(s => [s.job_id, s]))
      return handles.map(h => jobResult(h.id, h.label, h.kind === 'job' ? byId.get(h.jobId) : undefined))
    },
  }
}

// ── Ecommerce ────────────────────────────────────────────────────────────────
export function ecommerceAdapter(clientId: string, clientName: string | undefined, onOpenSaved: () => void): ReoptAdapter {
  const SCORE_THRESHOLD = 75
  return {
    toolLabel: 'Ecommerce',
    storageKey: `reopt:ecommerce:${clientId}`,
    clientId,
    scoreThreshold: SCORE_THRESHOLD,
    supportsUrl: true,
    supportsPaste: false,
    supportsExisting: false,
    supportsDiscover: true,
    supportsEntityProvider: true,
    requiresKeyword: false,
    keywordLabel: 'Target keyword',
    keywordPlaceholder: 'e.g. wireless noise-cancelling headphones',
    keywordOptionalHint: '(optional — default for every page)',
    supportsNotes: true,
    notesLabel: 'Notes',
    notesPlaceholder: 'e.g. emphasize fast shipping; write for clinics not individuals',
    supportsPublishToDoc: true,
    publishToDocLabel: `Publish each reoptimized page to a Google Doc in ${clientName ?? 'the client'}'s Drive folder`,
    onOpenSaved,
    savedLinkLabel: 'view in Saved Pages',
    async discover(pageType) {
      const res = await ecommerceApi.discover(clientId, pageType as EcommercePageType | undefined)
      return {
        items: (res.items ?? []).map(it => ({ url: it.url, label: it.url.replace(/^https?:\/\//, ''), pageType: it.page_type })),
        note: res.note ?? null,
      }
    },
    async start(items, opts) {
      const res = await ecommerceApi.reoptimizeBulk(clientId, {
        targets: items.map(t => ({
          page_url: t.url ?? '',
          keyword: t.keyword || null,
          page_type: (t.pageType ?? opts.pageType ?? 'product') as EcommercePageType,
        })),
        score_threshold: SCORE_THRESHOLD,
        publish_to_doc: Boolean(opts.publishToDoc),
        notes: opts.notes ?? null,
        entity_provider: opts.entityProvider ?? null,
      })
      return (res.jobs ?? []).map(j => ({
        kind: 'job' as const, id: j.job_id, jobId: j.job_id, label: j.page_url.replace(/^https?:\/\//, ''),
      }))
    },
    async poll(handles) {
      const jobIds = handles.map(h => (h.kind === 'job' ? h.jobId : '')).filter(Boolean)
      if (!jobIds.length) return []
      const statuses = await ecommerceApi.jobsStatus(clientId, jobIds)
      const byId = new Map(statuses.map(s => [s.job_id, s]))
      return handles.map(h => jobResult(h.id, h.label, h.kind === 'job' ? byId.get(h.jobId) : undefined))
    },
    async cancel() {
      await ecommerceApi.cancelJobs(clientId)
    },
  }
}

// ── Service / Location pages (spawns runs) ───────────────────────────────────
export function serviceAdapter(clientId: string): ReoptAdapter {
  return {
    toolLabel: 'Service pages',
    storageKey: `reopt:service:${clientId}`,
    clientId,
    supportsUrl: true,
    supportsPaste: true,
    supportsExisting: false,
    requiresKeyword: true,
    keywordLabel: 'Keyword',
    keywordPlaceholder: 'e.g. emergency plumber',
    ownsPageTypeSwitch: true,
    pageTypeOptions: [
      { id: 'service_page', label: 'Service page' },
      { id: 'location_page', label: 'Location page' },
    ],
    defaultPageType: 'service_page',
    runLinkBase: '/runs',
    runVerb: 'reoptimizing (see the run list)',
    introText: 'Point at a live service or location page — paste its URL(s) or its content. Each is scored and rewritten to fix its deficiencies as a new run you can review, score and publish.',
    async start(items, opts) {
      const res = await reoptApi.serviceReoptimizeBulk(clientId, {
        page_type: (opts.pageType === 'location_page' ? 'location_page' : 'service_page'),
        items: items.map(t => ({
          keyword: t.keyword,
          source_url: t.url ?? null,
          source_html: t.html ?? null,
          location: t.location ?? null,
          location_code: t.locationCode ?? null,
        })),
      })
      return runHandles(res)
    },
    poll: runPoll,
  }
}

// ── Blog (spawns runs) ───────────────────────────────────────────────────────
export function blogAdapter(clientId: string): ReoptAdapter {
  return {
    toolLabel: 'Blog',
    storageKey: `reopt:blog:${clientId}`,
    clientId,
    itemNoun: 'article',
    supportsUrl: true,
    supportsPaste: true,
    supportsExisting: false,
    requiresKeyword: true,
    keywordLabel: 'Keyword',
    keywordPlaceholder: 'e.g. best hvac systems 2026',
    supportsNotes: true,
    notesLabel: 'Notes for the writer',
    notesPlaceholder: 'e.g. lead with the cost angle; keep the intro under 60 words',
    runLinkBase: '/runs',
    runVerb: 'reoptimizing (see the run list)',
    introText: 'Reoptimize an existing article from its live URL or by pasting its content. Each becomes a full suite run — brief, research, writer — you can review and publish. To re-score & rewrite an article already in this suite, open its run and use Score / Reoptimize there.',
    async start(items, opts) {
      const res = await reoptApi.blogReoptimizeBulk(clientId, {
        writer_notes: opts.notes ?? null,
        items: items.map(t => ({
          keyword: t.keyword,
          source_url: t.url ?? null,
          source_html: t.html ?? null,
        })),
      })
      return runHandles(res)
    },
    poll: runPoll,
  }
}

// ── Mass Posts (Fan-out) — reoptimize existing Fan-out articles ──────────────
// Job-based, client-scoped, "pick existing" only: a Fan-out article is
// reoptimized via its mirrored suite run (score → rewrite-to-threshold) and the
// improved article is reflected back into the Fan-out Articles library. Only
// client-linked articles are listed.
type FanoutJobStatus = { job_id: string; status: string; result?: { prev_score?: number | null; new_score?: number | null } | null; error?: string | null }

function fanoutJobResult(id: string, label: string, st: FanoutJobStatus | undefined): ReoptResult {
  if (!st) return { id, label, status: 'queued' }
  if (st.status === 'complete') {
    return { id, label, status: 'done', prevScore: st.result?.prev_score ?? null, newScore: st.result?.new_score ?? null }
  }
  if (st.status === 'failed') return { id, label, status: 'failed', reason: st.error ?? 'Reoptimization failed' }
  if (st.status === 'running') return { id, label, status: 'working' }
  return { id, label, status: 'queued' }
}

export function fanoutAdapter(clientId: string): ReoptAdapter {
  return {
    toolLabel: 'Mass Posts (Fan-out)',
    storageKey: `reopt:fanout:${clientId}`,
    clientId,
    itemNoun: 'article',
    supportsUrl: false,
    supportsPaste: false,
    supportsExisting: true,
    requiresKeyword: false,
    introText:
      'Reoptimize blog articles created by the Mass Posts (Fan-out) tool for this client. Each is re-scored against the blog/AEO rubric, rewritten to fix its weaknesses, then updated in place in the Fan-out Articles library. Only client-linked articles appear here.',
    async listExisting() {
      const res = await reoptApi.fanoutList(clientId)
      return (res.articles ?? []).map(a => ({
        id: a.cluster_id,
        label: a.composite_score != null ? `${a.name} · score ${Math.round(a.composite_score)}` : a.name,
      }))
    },
    async start(items) {
      const labelByCluster = new Map(items.map(t => [t.existingId ?? '', t.label ?? t.existingId ?? '']))
      const clusterIds = items.map(t => t.existingId).filter((x): x is string => Boolean(x))
      const res = await reoptApi.fanoutReoptimizeBulk(clientId, clusterIds)
      const jobs: ReoptHandle[] = (res.jobs ?? []).map(j => ({
        kind: 'job' as const, id: j.job_id, jobId: j.job_id, label: labelByCluster.get(j.cluster_id) || j.cluster_id,
      }))
      const skipped: ReoptHandle[] = (res.skipped ?? []).map((s, i) => ({
        kind: 'skipped' as const, id: `skip:${i}:${s.cluster_id}`,
        label: labelByCluster.get(s.cluster_id) || s.cluster_id,
        reason: s.reason ?? 'Skipped — not client-linked or no article.',
      }))
      return [...jobs, ...skipped]
    },
    async poll(handles) {
      const jobIds = handles.map(h => (h.kind === 'job' ? h.jobId : '')).filter(Boolean)
      if (!jobIds.length) return []
      const res = await reoptApi.fanoutJobsStatus(clientId, jobIds)
      const byId = new Map(res.jobs.map(s => [s.job_id, s]))
      return handles.map(h => fanoutJobResult(h.id, h.label, h.kind === 'job' ? byId.get(h.jobId) : undefined))
    },
  }
}
