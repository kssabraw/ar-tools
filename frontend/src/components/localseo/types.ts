// Shared types for the Local SEO module (#2) frontend.
// These mirror the platform-api passthrough responses (which in turn mirror the
// private nlp service's Pydantic models).

export interface ContentGap {
  category: string
  missing: string
  score_impact: 'high' | 'medium' | 'low'
  why_important: string
  how_to_add: string
}

export interface LocalSeoPageListItem {
  id: string
  client_id: string
  keyword: string
  location: string
  page_title: string | null
  composite_score: number | null
  composite_status: string | null
  mode: 'generate' | 'reoptimize'
  created_at: string
}

export interface LocalSeoPageDetail extends LocalSeoPageListItem {
  run_analysis: boolean
  content_html: string
  schema_json: string
  content_gaps: ContentGap[]
  token_usage: Record<string, unknown> | null
  cost_breakdown: Record<string, unknown> | null
  updated_at: string
}

export interface EngineScore {
  score: number
  issues?: string[]
  recommendations?: string[]
  icp_detected?: string
}

// Mirrors the nlp `_build_deficiencies` output (engine/engine_key/score/
// issues/recommendations) — note there is no singular `issue`.
export interface Deficiency {
  engine: string
  engine_key: string
  score?: number
  issues?: string[]
  recommendations?: string[]
}

export interface ScoreResult {
  composite_score: number
  composite_status: string
  engine_scores: Record<string, EngineScore>
  deficiencies: Deficiency[]
  token_usage: { cost_usd?: number; input_tokens?: number; output_tokens?: number } & Record<string, unknown>
  serp_analysis?: AnalysisResult | null
}

export interface FindPageResult {
  found: boolean
  page?: { url: string; title: string; h1?: string }
  is_blog_post: boolean
}

export interface RelatedPageItem {
  keyword: string
  group: 'parents' | 'siblings' | 'children'
  status: 'found' | 'missing'
  url?: string | null
  page_title?: string | null
  composite_score?: number | null
  composite_status?: string | null
  deficiencies?: Deficiency[] | null
}

export interface RelatedPagesResult {
  items: RelatedPageItem[]
  token_usage: Record<string, unknown>
}

export interface SocialPostsResult {
  gbp: string[]
  token_usage: Record<string, unknown>
}

export interface AnalysisResult {
  keyword: string
  location: string
  serp_urls: string[]
  related_keywords: {
    title: Array<Record<string, unknown>>
    h1: Array<Record<string, unknown>>
    h2_h3: Array<Record<string, unknown>>
    paragraphs?: Array<Record<string, unknown>>
  }
  top_quadgrams: Array<Record<string, unknown>>
  google_entities: Array<Record<string, unknown>>
  serp_bold_keywords?: Array<Record<string, unknown>>
  zone_targets?: Record<string, unknown>
  competitor_headings?: Array<Record<string, unknown>>
}
