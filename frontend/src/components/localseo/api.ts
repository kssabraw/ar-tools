import { api } from '../../lib/api'
import type {
  AnalysisResult,
  LocalSeoPageDetail,
  LocalSeoPageListItem,
  LocationSuggestion,
  RankabilityResult,
  ScoreHistoryRow,
  SiloPlanJob,
  SiloPlanResult,
} from './types'

// All Local SEO calls go through platform-api, which proxies to the private
// nlp service and owns persistence. The frontend never reaches nlp directly.

// The long-running actions (generate / reoptimize / score / precheck / analyze /
// find-page / related-pages / social-posts) enqueue a background async job and
// return a { job_id, status } handle; poll `jobsStatus` for the terminal state +
// result. Running server-side means they finish — and the result is retrievable
// via a reconnecting poll — even if the user navigates away.
export const localSeoApi = {
  // Background generation — enqueue a job and poll, so the UI can navigate away
  // (even to other clients) while the page generates server-side. The page lands
  // in the client's pages when done.
  generateAsync: (
    clientId: string,
    body: {
      keyword: string
      location: string
      location_code?: number | null
      force_refresh?: boolean
      page_template_url?: string | null
    },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/generate-async`, body),

  getGenerateJob: (clientId: string, jobId: string) =>
    api.get<{ status: string; page_id?: string | null; error?: string | null }>(
      `/clients/${clientId}/local-seo/generate/${jobId}`,
    ),

  // Bulk background generation — enqueue one job per keyword; poll jobsStatus.
  generateBulk: (
    clientId: string,
    body: {
      keywords: string[]
      location: string
      location_code?: number | null
      force_refresh?: boolean
      page_template_url?: string | null
    },
  ) => api.post<{ job_ids: string[] }>(`/clients/${clientId}/local-seo/generate-bulk`, body),

  // Bulk background reoptimization — enqueue one job per page URL; poll jobsStatus.
  reoptimizeBulk: (
    clientId: string,
    body: {
      targets: Array<{ page_url: string; keyword?: string; location?: string; location_code?: number | null }>
      score_threshold?: number | null
      publish_to_doc?: boolean
    },
  ) => api.post<{ jobs: Array<{ job_id: string; page_url: string }> }>(
    `/clients/${clientId}/local-seo/reoptimize-bulk`, body,
  ),

  // Batch-poll background jobs (generate / reoptimize). `result` is the job's
  // result dict — {page_id} for generate, a ReoptimizeUrlResult for reoptimize.
  jobsStatus: (clientId: string, jobIds: string[]) =>
    api.post<Array<{ job_id: string; status: string; result?: Record<string, unknown> | null; error?: string | null }>>(
      `/clients/${clientId}/local-seo/jobs/status`, { job_ids: jobIds },
    ),

  // Pre-write existing-page detection (in-tool + live site + GSC/DataForSEO
  // ranking). The New Page flow runs this first and, when it returns matches,
  // offers reoptimize-vs-write-new before generating. Enqueued as a background
  // job (the live scan + SERP lookup take tens of seconds) so the UI can navigate
  // away and reconnect; the PrecheckResult comes back via `jobsStatus().result`.
  precheck: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/precheck`, body),

  // Phase 3 — save (or clear) the client's default page-template URL.
  setPageTemplateDefault: (clientId: string, page_template_url: string | null) =>
    api.put<{ local_seo_page_template_url: string | null }>(
      `/clients/${clientId}/local-seo/page-template-default`,
      { page_template_url },
    ),

  // Area-field typeahead — DataForSEO location suggestions scoped to the client's country.
  searchLocations: (clientId: string, query: string, country?: string) =>
    api.get<LocationSuggestion[]>(
      `/clients/${clientId}/local-seo/locations?query=${encodeURIComponent(query)}` +
        (country ? `&country=${encodeURIComponent(country)}` : ''),
    ),

  // Background job — poll jobsStatus for the AnalysisResult in `result`.
  analyze: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null; force_refresh?: boolean },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/analyze`, body),

  // Map-pack rankability report — a single point-in-time, non-streaming check
  // (no LLM). The business identity is sourced server-side from the client's GBP;
  // the caller only supplies the keyword/area (+ sab_city for a service-area biz).
  checkRankability: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null; sab_city?: string | null },
  ) => api.post<RankabilityResult>(`/clients/${clientId}/local-seo/rankability`, body),

  // Background job — poll jobsStatus for the FindPageResult in `result`.
  findPage: (clientId: string, body: { keyword: string; location: string }) =>
    api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/find-page`, body),

  // Background job — poll jobsStatus for the ScoreResult in `result`. Runs minutes
  // when it analyzes competitors first, so it survives navigating away.
  score: (
    clientId: string,
    body: {
      keyword: string
      location: string
      page_url?: string | null
      page_content?: string | null
      serp_analysis?: AnalysisResult | null
    },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/score`, body),

  // Background job — poll jobsStatus for the RelatedPagesResult in `result`.
  relatedPages: (clientId: string, body: { keyword: string; location: string }) =>
    api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/related-pages`, body),

  // Plan Silo (Fanout-powered): enqueue the keyword-research pipeline, then poll.
  // It runs for minutes and bills DataForSEO/LLM, so it's an async job rather
  // than a blocking stream.
  startSiloPlan: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null },
  ) => api.post<SiloPlanJob>(`/clients/${clientId}/local-seo/silo-plan`, body),

  getSiloPlan: (clientId: string, jobId: string) =>
    api.get<SiloPlanResult>(`/clients/${clientId}/local-seo/silo-plan/${jobId}`),

  // Score→reoptimize as a background job: enqueue the rewrite, then poll
  // jobsStatus (result.page_id) — the UI can leave while it runs.
  reoptimizeAsync: (
    clientId: string,
    body: {
      keyword: string
      location: string
      existing_page_html?: string | null
      existing_page_url?: string | null
      deficiencies: Array<Record<string, unknown>>
      serp_analysis?: AnalysisResult | null
    },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/reoptimize-async`, body),

  // Background job — poll jobsStatus for the SocialPostsResult in `result`.
  socialPosts: (
    clientId: string,
    body: { keyword: string; location: string; page_content: string; serp_analysis?: AnalysisResult | null },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/local-seo/social-posts`, body),

  listPages: (clientId: string) =>
    api.get<LocalSeoPageListItem[]>(`/clients/${clientId}/local-seo/pages`),

  // Soft-deleted pages — the Drafts tab.
  listDrafts: (clientId: string) =>
    api.get<LocalSeoPageListItem[]>(`/clients/${clientId}/local-seo/drafts`),

  getPage: (pageId: string) =>
    api.get<LocalSeoPageDetail>(`/local-seo/pages/${pageId}`),

  // Per-run score history for a client (newest first) — each row carries the full
  // 8-engine verdict. Optionally scoped to a single page.
  scoreHistory: (clientId: string, opts: { pageId?: string; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.pageId) params.set('page_id', opts.pageId)
    if (opts.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return api.get<ScoreHistoryRow[]>(
      `/clients/${clientId}/local-seo/score-history${qs ? `?${qs}` : ''}`,
    )
  },

  // Soft-delete: move a page to Drafts (recoverable).
  deletePage: (pageId: string) =>
    api.delete<void>(`/local-seo/pages/${pageId}`),

  // Restore a drafted page back to Saved Pages.
  restorePage: (pageId: string) =>
    api.post<{ restored: boolean }>(`/local-seo/pages/${pageId}/restore`, {}),

  // Permanently delete a page (from Drafts). Irreversible.
  purgePage: (pageId: string) =>
    api.delete<void>(`/local-seo/pages/${pageId}/permanent`),

  // Permanently delete ALL of a client's drafts (empty the bin).
  purgeDrafts: (clientId: string) =>
    api.delete<{ purged: number }>(`/clients/${clientId}/local-seo/drafts`),

  // Publish a saved page to a Google Doc (default) or straight to the client's
  // WordPress site (destination='wordpress').
  publishPage: (
    pageId: string,
    opts: { destination?: 'google_docs' | 'wordpress'; status?: 'draft' | 'publish' } = {},
  ) =>
    api.post<{
      success: boolean
      destination?: string
      doc_id?: string | null
      doc_url?: string | null
      url?: string | null
      edit_url?: string | null
      status?: string
    }>(`/local-seo/pages/${pageId}/publish`, opts),

  // Attach (or clear) a page's featured/hero image (public wordpress_images URL).
  setFeaturedImage: (pageId: string, url: string | null) =>
    api.put<{ featured_image_url: string | null }>(
      `/local-seo/pages/${pageId}/featured-image`,
      { url },
    ),
}
