export type RunStatus =
  | 'queued'
  | 'brief_running'
  | 'sie_running'
  | 'research_running'
  | 'writer_running'
  | 'sources_cited_running'
  | 'complete'
  | 'failed'
  | 'cancelled'

export interface ClientListItem {
  id: string
  name: string
  website_url: string
  website_analysis_status: 'pending' | 'complete' | 'failed'
  archived: boolean
  created_at: string
}

export interface Client extends ClientListItem {
  website_analysis: Record<string, unknown> | null
  website_analysis_error: string | null
  brand_guide_source_type: 'text' | 'file'
  brand_guide_text: string
  brand_guide_original_filename: string | null
  icp_source_type: 'text' | 'file'
  icp_text: string
  icp_original_filename: string | null
  google_drive_folder_id: string | null
  updated_at: string
}

export interface ModuleOutput {
  status: 'running' | 'complete' | 'failed'
  output_payload: Record<string, unknown> | null
  cost_usd: number | null
  duration_ms: number | null
  module_version: string | null
}

export interface Run {
  id: string
  client_id: string
  client_name: string
  keyword: string
  title: string | null
  status: RunStatus
  sie_cache_hit: boolean | null
  total_cost_usd: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface RunListResponse {
  data: Run[]
  total: number
  page: number
}

export interface RunDetail {
  id: string
  keyword: string
  title: string | null
  h1: string | null
  client_id: string
  status: RunStatus
  sie_cache_hit: boolean | null
  error_stage: string | null
  error_message: string | null
  total_cost_usd: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  client_context_snapshot: {
    brand_guide_text: string | null
    icp_text: string | null
    website_analysis: Record<string, unknown> | null
    website_analysis_unavailable: boolean
  } | null
  module_outputs: {
    brief: ModuleOutput | null
    sie: ModuleOutput | null
    research: ModuleOutput | null
    writer: ModuleOutput | null
    sources_cited: ModuleOutput | null
  }
}

export interface Profile {
  id: string
  email: string
  role: 'admin' | 'team_member'
  full_name: string | null
}


// ---- Silo Candidates (Platform PRD v1.4 §7.7) ----

export type SiloStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'in_progress'
  | 'published'
  | 'superseded'

export type SiloRoutedFrom = 'non_selected_region' | 'scope_verification'

export type IntentType =
  | 'informational'
  | 'listicle'
  | 'how-to'
  | 'comparison'
  | 'ecom'
  | 'local-seo'
  | 'news'
  | 'informational-commercial'

export interface SiloListItem {
  id: string
  client_id: string
  suggested_keyword: string
  status: SiloStatus
  occurrence_count: number
  cluster_coherence_score: number | null
  search_demand_score: number | null
  viable_as_standalone_article: boolean
  estimated_intent: IntentType | null
  routed_from: SiloRoutedFrom | null
  first_seen_run_id: string
  last_seen_run_id: string
  promoted_to_run_id: string | null
  last_promotion_failed_at: string | null
  created_at: string
  updated_at: string
}

export interface SiloDetail extends SiloListItem {
  source_run_ids: string[]
  viability_reasoning: string | null
  discard_reason_breakdown: Record<string, number>
  source_headings: Array<{
    text: string
    source: string
    title_relevance?: number
    heading_priority?: number
    discard_reason?: string | null
  }>
}

export interface SiloListResponse {
  items: SiloListItem[]
  total: number
  page: number
  page_size: number
}

export interface SiloMetrics {
  client_id: string
  counts_by_status: Partial<Record<SiloStatus, number>>
  average_occurrence_count: number
  high_frequency_threshold: number
  high_frequency_count: number
}

export interface SiloBulkResponse {
  succeeded: string[]
  failed: Array<{ id: string; reason: string }>
  runs_dispatched: string[]
}

export interface SiloPromoteResponse {
  silo_id: string
  run_id: string
  status: SiloStatus
}
