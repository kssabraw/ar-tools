import { api } from '../../lib/api'
import type {
  AnalysisResult,
  FindPageResult,
  LocalSeoPageDetail,
  LocalSeoPageListItem,
  LocationSuggestion,
  RankabilityResult,
  RelatedPagesResult,
  ReoptimizeUrlResult,
  ScoreResult,
  SiloPlanJob,
  SiloPlanResult,
  SocialPostsResult,
} from './types'

// All Local SEO calls go through platform-api, which proxies to the private
// nlp service and owns persistence. The frontend never reaches nlp directly.

// The action endpoints are heartbeat-SSE streams (see lib/api `stream`) so a
// multi-minute generate/score/reoptimize isn't dropped by a proxy idle timeout.
// They still resolve to the same typed payload as a plain POST would.
export const localSeoApi = {
  generate: (
    clientId: string,
    body: {
      keyword: string
      location: string
      location_code?: number | null
      force_refresh?: boolean
      page_template_url?: string | null
    },
    signal?: AbortSignal,
  ) => api.stream<LocalSeoPageDetail>(`/clients/${clientId}/local-seo/generate`, body, signal),

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

  analyze: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null; force_refresh?: boolean },
  ) => api.stream<AnalysisResult>(`/clients/${clientId}/local-seo/analyze`, body),

  // Map-pack rankability report — a single point-in-time, non-streaming check
  // (no LLM). The business identity is sourced server-side from the client's GBP;
  // the caller only supplies the keyword/area (+ sab_city for a service-area biz).
  checkRankability: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null; sab_city?: string | null },
  ) => api.post<RankabilityResult>(`/clients/${clientId}/local-seo/rankability`, body),

  findPage: (clientId: string, body: { keyword: string; location: string }) =>
    api.stream<FindPageResult>(`/clients/${clientId}/local-seo/find-page`, body),

  score: (
    clientId: string,
    body: {
      keyword: string
      location: string
      page_url?: string | null
      page_content?: string | null
      serp_analysis?: AnalysisResult | null
    },
  ) => api.stream<ScoreResult>(`/clients/${clientId}/local-seo/score`, body),

  relatedPages: (clientId: string, body: { keyword: string; location: string }) =>
    api.stream<RelatedPagesResult>(`/clients/${clientId}/local-seo/related-pages`, body),

  // Plan Silo (Fanout-powered): enqueue the keyword-research pipeline, then poll.
  // It runs for minutes and bills DataForSEO/LLM, so it's an async job rather
  // than a blocking stream.
  startSiloPlan: (
    clientId: string,
    body: { keyword: string; location: string; location_code?: number | null },
  ) => api.post<SiloPlanJob>(`/clients/${clientId}/local-seo/silo-plan`, body),

  getSiloPlan: (clientId: string, jobId: string) =>
    api.get<SiloPlanResult>(`/clients/${clientId}/local-seo/silo-plan/${jobId}`),

  reoptimize: (
    clientId: string,
    body: {
      keyword: string
      location: string
      existing_page_html?: string | null
      existing_page_url?: string | null
      deficiencies: Array<Record<string, unknown>>
      serp_analysis?: AnalysisResult | null
    },
  ) => api.stream<LocalSeoPageDetail>(`/clients/${clientId}/local-seo/reoptimize`, body),

  // Reoptimization tab — score a live page by URL and rewrite it only if it
  // scores below `score_threshold` (strong pages are skipped with a note). The
  // single + bulk flows both loop one URL per call so progress + failures stay
  // isolated per page (same pattern as bulk page creation).
  reoptimizeUrl: (
    clientId: string,
    body: {
      page_url: string
      keyword: string
      location: string
      location_code?: number | null
      score_threshold?: number
      publish_to_doc?: boolean
    },
    signal?: AbortSignal,
  ) => api.stream<ReoptimizeUrlResult>(`/clients/${clientId}/local-seo/reoptimize-url`, body, signal),

  socialPosts: (
    clientId: string,
    body: { keyword: string; location: string; page_content: string; serp_analysis?: AnalysisResult | null },
  ) => api.stream<SocialPostsResult>(`/clients/${clientId}/local-seo/social-posts`, body),

  listPages: (clientId: string) =>
    api.get<LocalSeoPageListItem[]>(`/clients/${clientId}/local-seo/pages`),

  getPage: (pageId: string) =>
    api.get<LocalSeoPageDetail>(`/local-seo/pages/${pageId}`),

  deletePage: (pageId: string) =>
    api.delete<void>(`/local-seo/pages/${pageId}`),

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
