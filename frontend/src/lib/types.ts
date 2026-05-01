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
