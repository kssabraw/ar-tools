// Shared types for the Local SEO module (#2) frontend.
// These mirror the platform-api passthrough responses (which in turn mirror the
// private nlp service's Pydantic models).

export interface LocationSuggestion {
  location_name: string
  location_code: number
  location_type: string
  country_iso_code: string
}

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
  // Set when soft-deleted (moved to Drafts); null = active (Saved Pages).
  deleted_at?: string | null
}

export interface LocalSeoPageDetail extends LocalSeoPageListItem {
  run_analysis: boolean
  content_html: string
  schema_json: string
  content_gaps: ContentGap[]
  token_usage: Record<string, unknown> | null
  cost_breakdown: Record<string, unknown> | null
  published_doc_url: string | null
  published_doc_id: string | null
  published_url: string | null
  published_at: string | null
  featured_image_url: string | null
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

// One existing/ranking page surfaced by the pre-write precheck. Carries
// whichever handles apply: page_id (an already-generated in-tool page — open it),
// url (a live-site or ranking page — score → reoptimize).
export interface ExistingMatch {
  url?: string | null
  page_id?: string | null
  title?: string | null
  is_blog_post: boolean
  rank_position?: number | null
  rank_source?: string | null // 'gsc' | 'dataforseo'
  matched_keyword?: string | null
  signals: string[] // subset of 'in_tool' | 'live_site' | 'ranking'
}

export interface PrecheckResult {
  matches: ExistingMatch[]
  rank_source: string // 'gsc' | 'dataforseo' | 'none'
  checked_variants: string[]
  degraded_notes: string[]
}

export interface RelatedPageItem {
  keyword: string
  // The /related-pages flow uses 'parents'|'siblings'|'children'; the
  // Fanout-powered Plan Silo flow uses free-form silo labels — so this is a
  // string, with the known relationship groups still rendered/ordered first.
  group: string
  // 'found'   — already generated in the tool (url = published doc)
  // 'on_site' — a generic location page for this place already exists on the
  //             client's live site (url = that live page); not offered for create
  // 'missing' — nothing yet; selectable for bulk creation
  status: 'found' | 'missing' | 'on_site'
  url?: string | null
  page_title?: string | null
  composite_score?: number | null
  composite_status?: string | null
  deficiencies?: Deficiency[] | null
  // Same-intent variant keywords this page should also target (decision-fit map).
  supporting_keywords?: string[] | null
}

export interface RelatedPagesResult {
  items: RelatedPageItem[]
  token_usage: Record<string, unknown>
}

// Plan Silo (Fanout-powered) — kicked off async; the client polls for the result.
export interface SiloPlanJob {
  job_id: string
  status: string
}

export interface SiloPlanResult {
  status: 'pending' | 'running' | 'complete' | 'failed'
  items: RelatedPageItem[]
  degraded_notes: string[]
  error?: string | null
}

// One outcome from the Reoptimization tab's per-URL flow (POST .../reoptimize-url).
// A strong page (>= threshold) is 'skipped' with a reason; a weak one is
// 'reoptimized' and saved as a new mode='reoptimize' page (optionally published).
export interface ReoptimizeUrlResult {
  status: 'reoptimized' | 'skipped'
  page_url: string
  keyword: string
  // skipped:
  score?: number | null
  threshold?: number
  reason?: string
  // reoptimized:
  prev_score?: number | null
  new_score?: number | null
  page?: {
    id: string
    page_title: string | null
    composite_score: number | null
    composite_status: string | null
    published_doc_url: string | null
  }
  published?: { doc_url: string | null; doc_id: string | null }
  publish_error?: string
}

export interface SocialPostsResult {
  gbp: string[]
  token_usage: Record<string, unknown>
}

export interface RankabilityCompetitor {
  name: string
  rating?: number
  review_count?: number
  has_keyword_in_name: boolean
}

export interface RankabilityResult {
  score: number
  verdict: string // "strong" | "moderate" | "difficult" | "very_difficult" | "unknown"
  score_breakdown: Record<string, number>
  has_map_pack: boolean
  competitors: RankabilityCompetitor[]
  ranking_categories: Array<{ category: string; count: number }>
  min_reviews_in_pack?: number
  max_reviews_in_pack?: number
  avg_reviews_in_pack?: number
  avg_rating_in_pack?: number
  review_gap?: number
  category_match: string // "exact" | "partial" | "none"
  distance_miles?: number
  distance_ok: boolean
  keyword_in_competitor_names: number
  competitor_name_examples: string[]
  in_maps_results: boolean
  maps_position?: number
  is_sab: boolean
  sab_pack_mismatch: boolean
  physical_competitors_in_pack: number
  message: string
  match_count: number
  total_results: number
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
