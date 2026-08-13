import { api } from '../../lib/api'
import type { ScoreResult } from '../localseo/types'

// API layer for the run-spawning reoptimization flows (Blog + Service), plus the
// per-run Score/Reoptimize job endpoints used by the blog run detail view. The
// Local SEO + Ecommerce reoptimize flows keep using their own module api.ts
// (job-based reoptimizeBulk + jobsStatus) — the adapters call those directly.

// One item that failed to start (missing url/html, frozen client, …). Shape is
// defensively read since the backend's exact skipped payload isn't pinned.
export interface ReoptBulkSkipped {
  keyword?: string | null
  source_url?: string | null
  url?: string | null
  reason?: string | null
  error?: string | null
}

export interface ReoptBulkRun {
  run_id: string
  keyword: string
  source?: string | null
}

export interface ReoptBulkResponse {
  runs: ReoptBulkRun[]
  skipped?: ReoptBulkSkipped[] | null
}

// One item for a run-spawning bulk reoptimize — either a live URL or pasted HTML.
export interface ReoptRunItem {
  keyword: string
  source_url?: string | null
  source_html?: string | null
  location?: string | null
  location_code?: number | null
}

// What a spawned run's poll returns (a subset of the run detail).
export interface RunPoll {
  id: string
  status: string
  error_message?: string | null
  published_doc_url?: string | null
  published_url?: string | null
}

// What the blog per-run score/reopt job poll returns on completion.
export interface BlogScoreJobPoll {
  status: string // pending | running | complete | failed | cancelled
  score?: ScoreResult | null
  page?: unknown
  error?: string | null
}

export const reoptApi = {
  // ── Blog: external URL / pasted content (spawns full suite runs) ──
  blogReoptimizeBulk: (
    clientId: string,
    body: { writer_notes?: string | null; items: ReoptRunItem[] },
  ) => api.post<ReoptBulkResponse>('/blog/reoptimize-bulk', { client_id: clientId, ...body }),

  // ── Service: external URL / pasted content (spawns service/location runs) ──
  serviceReoptimizeBulk: (
    clientId: string,
    body: { page_type: 'service_page' | 'location_page'; items: ReoptRunItem[] },
  ) => api.post<ReoptBulkResponse>('/service-pages/reoptimize-bulk', { client_id: clientId, ...body }),

  // ── Poll a spawned run to completion ──
  getRun: (runId: string) => api.get<RunPoll>(`/runs/${runId}`),

  // ── Blog per-run Score/Reoptimize (job-based, in-place on an existing run) ──
  blogScoreAsync: (runId: string) =>
    api.post<{ job_id: string; status: string }>(`/runs/${runId}/blog-score-async`, {}),

  blogReoptimizeAsync: (runId: string, deficiencies: Array<Record<string, unknown>>) =>
    api.post<{ job_id: string; status: string }>(`/runs/${runId}/blog-reoptimize-async`, { deficiencies }),

  blogScoreJob: (runId: string, jobId: string) =>
    api.get<BlogScoreJobPoll>(`/runs/${runId}/blog-score-jobs/${jobId}`),
}
