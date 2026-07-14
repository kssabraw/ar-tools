// Shared types for the Ecommerce Product & Collection Writer module frontend.
// These mirror the platform-api passthrough responses. This module is national
// (no location/area) — a page targets a keyword + a page_type (product or
// collection), optionally seeded from a live source URL and pasted product facts.

export type EcommercePageType = 'product' | 'collection'

export interface ContentGap {
  category: string
  missing: string
  score_impact: 'high' | 'medium' | 'low'
  why_important: string
  how_to_add: string
}

export interface EcommercePageListItem {
  id: string
  client_id: string
  keyword: string
  page_type: EcommercePageType
  source_url?: string | null
  page_title?: string | null
  composite_score?: number | null
  composite_status?: string | null
  mode: 'generate' | 'reoptimize'
  created_at: string
  // Set when soft-deleted (moved to Drafts); null = active (Saved Pages).
  deleted_at?: string | null
  // Publish state (for the Saved Pages "published" badge).
  published_doc_url?: string | null
  published_url?: string | null
  published_at?: string | null
}

export interface EngineScore {
  score: number
  issues?: string[]
  recommendations?: string[]
}

// Mirrors the nlp `_build_deficiencies` output (engine/engine_key/score/
// issues/recommendations).
export interface Deficiency {
  engine: string
  engine_key: string
  score?: number
  issues?: string[]
  recommendations?: string[]
}

export interface EcommercePageDetail extends EcommercePageListItem {
  product_input?: string | null
  notes?: string | null
  content_html: string
  schema_json: string
  // Either rich objects or plain strings, depending on what the writer emitted.
  content_gaps: Array<ContentGap | string>
  composite_score?: number | null
  composite_status?: string | null
  engine_scores?: Record<string, EngineScore> | null
  token_usage?: Record<string, unknown> | null
  cost_breakdown?: Record<string, unknown> | null
  published_doc_id?: string | null
  featured_image_url?: string | null
  updated_at: string
}

// The 8 ecommerce scoring engines. The `serp_analysis` blob is opaque here —
// the score view only needs the composite + per-engine breakdown + deficiencies.
export interface ScoreResult {
  composite_score: number
  composite_status: string
  engine_scores: Record<string, EngineScore>
  deficiencies: Deficiency[]
  serp_analysis?: Record<string, unknown> | null
}

// One row in the per-run score history.
export interface ScoreHistoryRow {
  id: string
  client_id: string
  page_id: string | null
  keyword: string
  page_type: EcommercePageType | null
  page_url: string | null
  mode: string
  composite_score: number | null
  composite_status: string | null
  engine_scores: Record<string, EngineScore> | null
  deficiencies: Deficiency[] | null
  created_at: string
}

// One page found by the "Discover from site" scan.
export interface DiscoverItem {
  url: string
  page_type: EcommercePageType
}

export interface DiscoverResult {
  items: DiscoverItem[]
  source: string
  count: number
  note?: string | null
}

// One outcome from the Reoptimize tab's per-URL flow (reoptimize-bulk). A strong
// page (>= threshold) is 'skipped' with a reason; a weak one is 'reoptimized' and
// saved as a new mode='reoptimize' page (optionally published to a Google Doc).
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
