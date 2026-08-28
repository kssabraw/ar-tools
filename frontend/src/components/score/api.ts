import { api } from '../../lib/api'
import type { ScoreResult } from '../localseo/types'

// API layer for the run-free Blog + Service "Score an existing page" jobs. Local
// SEO + Ecommerce score through their own module apis (localSeoApi.score /
// ecommerceApi.score), so those adapters don't use this file.

export interface ScoreExistingJob {
  job_id: string
  status: string
}

export interface ScoreExistingStatus {
  status: string
  result?: ScoreResult | null
  error?: string | null
}

export const scoreApi = {
  blogScoreExisting: (
    clientId: string,
    body: { keyword: string; page_url?: string | null; page_content?: string | null; entity_provider?: string | null },
  ) => api.post<ScoreExistingJob>(`/clients/${clientId}/blog/score-existing`, body),

  serviceScoreExisting: (
    clientId: string,
    body: {
      keyword: string
      page_type: 'service_page' | 'location_page'
      page_url?: string | null
      page_content?: string | null
      location?: string | null
      location_code?: number | null
      entity_provider?: string | null
    },
  ) => api.post<ScoreExistingJob>(`/clients/${clientId}/service-pages/score-existing`, body),

  getJob: (clientId: string, jobId: string) =>
    api.get<ScoreExistingStatus>(`/clients/${clientId}/score-existing/${jobId}`),
}
