import { api } from '../../lib/api'
import type {
  DiscoverResult,
  EcommercePageDetail,
  EcommercePageListItem,
  EcommercePageType,
  ScoreHistoryRow,
} from './types'

// All Ecommerce Writer calls go through platform-api, which proxies to the
// private nlp service and owns persistence. The long-running actions (generate /
// reoptimize / score) enqueue a background async job and return a { job_id }
// handle; poll `jobsStatus` (or the dedicated generate poll) for the terminal
// state + result. Running server-side means they finish — and the result is
// retrievable — even if the user navigates away.
export const ecommerceApi = {
  // Background single-page generation — enqueue a job, poll getGenerateJob.
  generateAsync: (
    clientId: string,
    body: {
      keyword: string
      page_type: EcommercePageType
      source_url?: string | null
      product_input?: string | null
      // Optional per-call override of the client's house PDP template (products
      // only); omit to use the saved default.
      page_template_url?: string | null
      // High-priority per-job writing guidance the writer follows.
      notes?: string | null
    },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/ecommerce/generate-async`, body),

  // House PDP template (products only): the client's reference product page whose
  // structure every new product description mirrors. Set once per client.
  getPageTemplate: (clientId: string) =>
    api.get<{ ecommerce_page_template_url: string | null }>(
      `/clients/${clientId}/ecommerce/page-template-default`,
    ),

  setPageTemplate: (clientId: string, url: string | null) =>
    api.put<{ ecommerce_page_template_url: string | null }>(
      `/clients/${clientId}/ecommerce/page-template-default`,
      { page_template_url: url },
    ),

  getGenerateJob: (clientId: string, jobId: string) =>
    api.get<{ status: string; page_id?: string | null; error?: string | null }>(
      `/clients/${clientId}/ecommerce/generate/${jobId}`,
    ),

  // Bulk background generation — one job per keyword; poll jobsStatus.
  generateBulk: (
    clientId: string,
    body: { keywords: string[]; page_type: EcommercePageType; notes?: string | null },
  ) => api.post<{ job_ids: string[] }>(`/clients/${clientId}/ecommerce/generate-bulk`, body),

  // Bulk background reoptimization — one job per page URL; poll jobsStatus. Each
  // page is scored first; only pages below the threshold are rewritten.
  reoptimizeBulk: (
    clientId: string,
    body: {
      targets: Array<{ page_url: string; keyword?: string | null; page_type: EcommercePageType }>
      score_threshold?: number | null
      publish_to_doc?: boolean
      notes?: string | null
    },
  ) => api.post<{ jobs: Array<{ job_id: string; page_url: string }> }>(
    `/clients/${clientId}/ecommerce/reoptimize-bulk`, body,
  ),

  // Discover live product/collection pages on the client's own site (sitemap →
  // DataForSEO site: fallback). Optionally scoped by page_type.
  discover: (clientId: string, pageType?: EcommercePageType) =>
    api.get<DiscoverResult>(
      `/clients/${clientId}/ecommerce/discover${pageType ? `?page_type=${pageType}` : ''}`,
    ),

  // Score a page (action job) — poll jobsStatus for the ScoreResult in `result`.
  score: (
    clientId: string,
    body: {
      keyword: string
      page_type: EcommercePageType
      page_url?: string | null
      page_content?: string | null
    },
  ) => api.post<{ job_id: string; status: string }>(`/clients/${clientId}/ecommerce/score`, body),

  // Batch-poll background jobs (generate / reoptimize / score). `result` is the
  // job's result dict — {page_id} for generate, a ReoptimizeUrlResult for
  // reoptimize, a ScoreResult for score.
  jobsStatus: (clientId: string, jobIds: string[]) =>
    api.post<Array<{ job_id: string; status: string; result?: Record<string, unknown> | null; error?: string | null }>>(
      `/clients/${clientId}/ecommerce/jobs/status`, { job_ids: jobIds },
    ),

  // Cancel QUEUED (pending) generations/reoptimizations. Pass jobIds to cancel a
  // specific batch, or omit to cancel ALL of the client's pending ecommerce jobs.
  // A job already running is left to finish. Returns { cancelled: N }.
  cancelJobs: (clientId: string, jobIds?: string[]) =>
    api.post<{ cancelled: number }>(
      `/clients/${clientId}/ecommerce/jobs/cancel`,
      { job_ids: jobIds ?? [] },
    ),

  listPages: (clientId: string) =>
    api.get<EcommercePageListItem[]>(`/clients/${clientId}/ecommerce/pages`),

  // Soft-deleted pages — the Drafts tab.
  listDrafts: (clientId: string) =>
    api.get<EcommercePageListItem[]>(`/clients/${clientId}/ecommerce/drafts`),

  getPage: (pageId: string) =>
    api.get<EcommercePageDetail>(`/ecommerce/pages/${pageId}`),

  scoreHistory: (clientId: string, opts: { pageId?: string; limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (opts.pageId) params.set('page_id', opts.pageId)
    if (opts.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return api.get<ScoreHistoryRow[]>(
      `/clients/${clientId}/ecommerce/score-history${qs ? `?${qs}` : ''}`,
    )
  },

  // Soft-delete: move a page to Drafts (recoverable).
  deletePage: (pageId: string) =>
    api.delete<{ deleted: boolean }>(`/ecommerce/pages/${pageId}`),

  // Restore a drafted page back to Saved Pages.
  restorePage: (pageId: string) =>
    api.post<{ restored: boolean }>(`/ecommerce/pages/${pageId}/restore`, {}),

  // Permanently delete a page (from Drafts). Irreversible.
  purgePage: (pageId: string) =>
    api.delete<{ purged: boolean }>(`/ecommerce/pages/${pageId}/permanent`),

  // Permanently delete ALL of a client's drafts (empty the bin).
  purgeDrafts: (clientId: string) =>
    api.delete<{ purged: number }>(`/clients/${clientId}/ecommerce/drafts`),

  // Publish a saved page to a Google Doc (default) or the client's WordPress site.
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
      status?: string
    }>(`/ecommerce/pages/${pageId}/publish`, opts),

  // Attach (or clear) a page's featured/hero image (public wordpress_images URL).
  setFeaturedImage: (pageId: string, url: string | null) =>
    api.put<{ featured_image_url: string | null }>(
      `/ecommerce/pages/${pageId}/featured-image`,
      { url },
    ),
}
