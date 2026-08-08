import { api } from '../../lib/api'

export type ContentType =
  | 'blog_post' | 'service_page' | 'location_page' | 'local_seo_page' | 'ecommerce'
export type ScheduleMode =
  | 'now' | 'all_at_once' | 'drip' | 'weekly' | 'monthly_date' | 'monthly_weekday' | 'fixed'

export const CONTENT_TYPE_LABEL: Record<ContentType, string> = {
  blog_post: 'Blog posts',
  service_page: 'Service pages',
  location_page: 'Location pages',
  local_seo_page: 'Local SEO pages',
  ecommerce: 'Ecommerce',
}

export interface BatchItemInput {
  keyword: string
  location?: string | null
  location_code?: number | null
  services?: string[]
  page_template_url?: string | null
  notes?: string | null
  scheduled_date?: string | null   // 'YYYY-MM-DD' — per-row publish date (overrides cadence)
}

export interface CadenceBody {
  mode: ScheduleMode
  per_day?: number | null
  start_date?: string | null   // 'YYYY-MM-DD'
  time_of_day?: string | null  // 'HH:MM'
  timezone?: string
  weekday?: number | null
  weekdays?: number[] | null
  day_of_month?: number | null
  week_of_month?: number | null
}

export interface EstimateBody extends CadenceBody {
  content_type: ContentType
  items: BatchItemInput[]
}

export interface CreateBody extends EstimateBody {
  auto_publish?: boolean
  // Blog posts only: auto-publish each finished post to the client's GitHub repo
  // (via the image-generation SOP) right after it generates.
  github_publish?: boolean
}

export interface EstimateResponse {
  count: number
  skipped: number
  cost_estimate_usd: number
  content_type: string
  mode: string
  finish_date?: string | null
  requires_approval: boolean
  approval_threshold_usd: number
}

export interface CreateResponse {
  status: 'created' | 'requires_approval'
  created: boolean
  batch_id?: string | null
  count: number
  skipped: number
  enqueued: number
  estimate?: EstimateResponse | null
}

export interface BatchProgress {
  scheduled: number
  queued: number
  running: number
  complete: number
  failed: number
  cancelled: number
  total: number
}

export interface ContentBatch {
  id: string
  client_id: string
  content_type: ContentType
  mode: ScheduleMode
  status: 'active' | 'paused' | 'complete' | 'cancelled'
  total_count: number
  created_at: string
  auto_publish: boolean
  wp_publish: boolean
  wp_status: 'draft' | 'publish'
  github_publish?: boolean
  per_day?: number | null
  start_date?: string | null
  time_of_day?: string | null
  timezone?: string
  progress?: BatchProgress
}

export type ItemStatus =
  | 'scheduled' | 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'

export interface ContentBatchItem {
  id: string
  keyword: string
  location?: string | null
  status: ItemStatus
  scheduled_at?: string | null
  result_kind?: string | null
  result_ref?: string | null
  error?: string | null
  // Attached server-side for run-backed items: the live publish URL (GitHub /
  // WordPress / Doc) and when it went live, or null when generated-but-not-published.
  published_at?: string | null
  published_url?: string | null
}

export interface ContentBatchDetail extends ContentBatch {
  github_publish?: boolean
  items: ContentBatchItem[]
}

export interface ScheduledContentItem {
  source: 'content_scheduler' | 'fanout'
  id: string
  content_type: string
  label?: string | null
  mode?: string | null
  status?: string | null
  created_at?: string | null
  github_publish?: boolean
  progress: BatchProgress
}

// One flattened, concrete-dated scheduled content item — the calendar row shape.
// `scheduled_at` is the day/time this piece of content is set to generate.
export interface CalendarItem {
  source: 'content_scheduler' | 'fanout'
  parent_id: string | null
  item_id: string
  client_id: string | null
  client_name?: string | null
  content_type: string
  mode?: string | null
  label: string
  location?: string | null
  scheduled_at: string | null
  status: ItemStatus
}

export interface CalendarResponse {
  items: CalendarItem[]
  start: string
  end: string
}

export const schedulerApi = {
  estimate: (clientId: string, body: EstimateBody) =>
    api.post<EstimateResponse>(`/clients/${clientId}/content-batches/estimate`, body),
  create: (clientId: string, body: CreateBody) =>
    api.post<CreateResponse>(`/clients/${clientId}/content-batches`, body),
  listBatches: (clientId: string) =>
    api.get<{ batches: ContentBatch[] }>(`/clients/${clientId}/content-batches`),
  batchDetail: (clientId: string, batchId: string) =>
    api.get<ContentBatchDetail>(`/clients/${clientId}/content-batches/${batchId}`),
  scheduledContent: (clientId: string) =>
    api.get<{ items: ScheduledContentItem[] }>(`/clients/${clientId}/scheduled-content`),
  clientCalendar: (clientId: string, start: string, end: string) =>
    api.get<CalendarResponse>(
      `/clients/${clientId}/content-calendar?start=${start}&end=${end}`),
  agencyCalendar: (start: string, end: string) =>
    api.get<CalendarResponse>(`/content-calendar?start=${start}&end=${end}`),
  pauseBatch: (clientId: string, batchId: string) =>
    api.post<{ status: string }>(`/clients/${clientId}/content-batches/${batchId}/pause`, {}),
  resumeBatch: (clientId: string, batchId: string) =>
    api.post<{ status: string }>(`/clients/${clientId}/content-batches/${batchId}/resume`, {}),
  cancelBatch: (clientId: string, batchId: string) =>
    api.post<{ status: string; cancelled_items: number }>(
      `/clients/${clientId}/content-batches/${batchId}/cancel`, {}),
  // Durable per-client draft — handed-off keywords (e.g. from Keyword Research)
  // that seed the batch form and survive a refresh until a batch is created.
  getDraft: (clientId: string) =>
    api.get<SchedulerDraft>(`/clients/${clientId}/content-scheduler-draft`),
  saveDraft: (clientId: string, keywords: string[], contentType?: ContentType) =>
    api.post<SchedulerDraft>(`/clients/${clientId}/content-scheduler-draft`,
      { keywords, content_type: contentType }),
  clearDraft: (clientId: string) =>
    api.delete<{ cleared: boolean }>(`/clients/${clientId}/content-scheduler-draft`),
}

export interface SchedulerDraft {
  terms: string[]
  content_type: ContentType | null
}
