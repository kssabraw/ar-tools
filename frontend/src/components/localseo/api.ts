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

export const localSeoApi = {
  generate: (clientId: string, body: { keyword: string; location: string; run_analysis: boolean }) =>
    api.post<LocalSeoPageDetail>(`/clients/${clientId}/local-seo/generate`, body),

  analyze: (clientId: string, body: { keyword: string; location: string; location_code?: number | null }) =>
    api.post<AnalysisResult>(`/clients/${clientId}/local-seo/analyze`, body),

  findPage: (clientId: string, body: { keyword: string; location: string }) =>
    api.post<FindPageResult>(`/clients/${clientId}/local-seo/find-page`, body),

  score: (
    clientId: string,
    body: {
      keyword: string
      location: string
      page_url?: string | null
      page_content?: string | null
      serp_analysis?: AnalysisResult | null
    },
  ) => api.post<ScoreResult>(`/clients/${clientId}/local-seo/score`, body),

  relatedPages: (clientId: string, body: { keyword: string; location: string }) =>
    api.post<RelatedPagesResult>(`/clients/${clientId}/local-seo/related-pages`, body),

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
  ) => api.post<LocalSeoPageDetail>(`/clients/${clientId}/local-seo/reoptimize`, body),

  socialPosts: (
    clientId: string,
    body: { keyword: string; location: string; page_content: string; serp_analysis?: AnalysisResult | null },
  ) => api.post<SocialPostsResult>(`/clients/${clientId}/local-seo/social-posts`, body),

  listPages: (clientId: string) =>
    api.get<LocalSeoPageListItem[]>(`/clients/${clientId}/local-seo/pages`),

  getPage: (pageId: string) =>
    api.get<LocalSeoPageDetail>(`/local-seo/pages/${pageId}`),

  deletePage: (pageId: string) =>
    api.delete<void>(`/local-seo/pages/${pageId}`),
}
