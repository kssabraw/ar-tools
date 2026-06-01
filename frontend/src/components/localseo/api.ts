import { api } from '../../lib/api'
import type {
  AnalysisResult,
  FindPageResult,
  LocalSeoPageDetail,
  LocalSeoPageListItem,
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
  generate: (clientId: string, body: { keyword: string; location: string; run_analysis: boolean }) =>
    api.stream<LocalSeoPageDetail>(`/clients/${clientId}/local-seo/generate`, body),

  analyze: (clientId: string, body: { keyword: string; location: string; location_code?: number | null }) =>
    api.stream<AnalysisResult>(`/clients/${clientId}/local-seo/analyze`, body),

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
}
