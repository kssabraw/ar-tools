// Shared data types for the AI Visibility module (mirror models/brand.py and
// the structured analysis mined at scan time by services/brand_analysis.py).
// Moved out of pages/AiVisibility.tsx so the dashboard components can share them.

export interface Keyword {
  id: string
  keyword: string
  category: string | null
  is_active: boolean
  created_at: string | null
}

export interface ScanStatus {
  status: string
  total: number
  completed: number
  failed: number
  scan_batch_id: string | null
  error: string | null
}

export interface Mention {
  id: string
  keyword_id: string | null
  scan_batch_id: string | null
  engine: string
  status: string
  mention_found: boolean | null
  mention_type: string | null
  sentiment: number | null
  confidence_score: number | null
  citations: string[]
  competitor_results: unknown[] | null
  reasoning: string | null
  snippet: string | null
  invisibility_diagnosis: string | null
  response_analysis: RespAnalysis | null
  failure_reason: string | null
  // False when a Google AI feature (AI Overview / AI Mode) didn't fire for the
  // query — the cell is excluded from the visibility score and shown as absent.
  feature_present: boolean | null
  created_at: string | null
}

export interface RespSource {
  domain: string
  type: string
  is_client: boolean
  is_competitor: boolean
}

export interface NamedBusiness {
  name: string
  attributes: string[]
}

export interface RespAnalysis {
  position?: { rank: number | null; total_businesses: number | null }
  prominence?: string | null
  sources?: {
    client_cited: boolean
    domains: RespSource[]
    by_type: Record<string, number>
    competitor_only_sources: string[]
  }
  discovered_competitors?: NamedBusiness[]
  competitor_attributes?: NamedBusiness[]
  accuracy_flags?: { field: string; stated: string; actual: string }[]
  intent?: { inferred: string | null; locations: string[] }
  aio?: { mention_kind: AioKind }
}

export type AioKind = 'none' | 'citation_only' | 'in_content_link' | 'both'

export const AIO_KIND_LABELS: Record<AioKind, string> = {
  none: 'Not in the AI Overview',
  citation_only: 'Cited in the sources strip only',
  in_content_link: 'Linked inline in the answer',
  both: 'Linked inline + cited as a source',
}

// Google's AI surfaces — the only engines where the in-content-link vs citation
// distinction exists (the others don't expose that structure).
export const AIO_ENGINES = new Set(['google_ai_overview', 'google_ai_mode'])

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  directory: 'Directories', review: 'Review sites', social: 'Social', forum: 'Forums/Q&A',
  search: 'Search/Maps', editorial: 'Editorial/brand sites',
}

// One competitor's re-classification of the same AI answer (stored on the
// client mention's competitor_results JSONB by services/brand_scan.py).
export interface CompResult {
  name: string
  found: boolean | null
  mention_type: string | null
  sentiment: number | null
  confidence: number | null
  snippet: string | null
}

export function compResultFor(m: Mention | undefined, name: string): CompResult | undefined {
  if (!m || !Array.isArray(m.competitor_results)) return undefined
  return (m.competitor_results as CompResult[]).find(c => c?.name === name)
}

// Per-batch rollup from GET /brand/trends (brand_service.compute_trends).
// health_score is computed server-side — the LABS formula's single source —
// so the dashboard gauge and the HTML report can't drift apart.
export interface TrendBatch {
  scan_batch_id: string | null
  created_at: string | null
  total: number
  found: number
  visibility_pct: number
  avg_confidence: number | null
  health_score: number | null
  engines: Record<string, { total: number; found: number; visibility_pct: number }>
  competitors: Record<string, { total: number; found: number; visibility_pct: number; health_score: number | null }>
}

// Format a batch timestamp for chart x-axes ("6/28").
export function batchLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}/${d.getDate()}`
}
