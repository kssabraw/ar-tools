import { api } from '../../lib/api'
import type {
  AnalysisResult,
  FindPageResult,
  LocalSeoPageDetail,
  LocalSeoPageListItem,
  LocationSuggestion,
  RankabilityResult,
  RelatedPagesResult,
  ScoreResult,
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
      run_analysis: boolean
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

  // Publish a saved page to a Google Doc in the client's Drive folder.
  publishPage: (pageId: string) =>
    api.post<{ success: boolean; doc_id: string | null; doc_url: string | null }>(
      `/local-seo/pages/${pageId}/publish`,
      {},
    ),
}
