export interface Client {
  id: string
  name: string
  website_url: string
  industry: string | null
  tone_of_voice: string | null
  target_audience: string | null
  created_at: string
}

export interface Run {
  id: string
  client_id: string
  keyword: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  article_markdown: string | null
  created_at: string
  completed_at: string | null
  clients?: { name: string }
}

export interface RunDetail extends Run {
  brief_output: Record<string, unknown> | null
  sie_output: Record<string, unknown> | null
  research_output: Record<string, unknown> | null
  writer_output: Record<string, unknown> | null
  sources_output: Record<string, unknown> | null
  error_message: string | null
}

export interface Profile {
  id: string
  email: string
  role: 'admin' | 'editor' | 'viewer'
  full_name: string | null
}
