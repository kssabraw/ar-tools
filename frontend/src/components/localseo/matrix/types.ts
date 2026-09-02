// Service × location matrix — types mirroring platform-api's
// models/local_seo_matrix.py (docs/modules/local-seo-matrix-plan-v1_0.md §2/§6).

export type MatrixCellStatus =
  | 'missing' | 'found' | 'on_site'
  | 'queued' | 'generating' | 'done' | 'failed'
  | 'publishing' | 'published' | 'publish_failed' | 'publish_blocked'
  | 'skipped'

// Cells a generate run acts on by default; 'found'/'on_site' only when ticked.
export const RUNNABLE: ReadonlySet<MatrixCellStatus> = new Set(['missing', 'failed'])
export const COVERED: ReadonlySet<MatrixCellStatus> = new Set(['found', 'on_site'])
export const IN_FLIGHT: ReadonlySet<MatrixCellStatus> = new Set(['queued', 'generating', 'publishing'])

export interface MatrixCell {
  id: string
  matrix_id: string
  service_label: string
  service_slug: string
  location_name: string
  location_slug: string
  service_order: number
  location_order: number
  keyword: string
  path: string
  status: MatrixCellStatus
  page_id?: string | null
  job_id?: string | null
  url?: string | null
  released_at?: string | null
  link_coverage?: { expected: number; present: string[]; missing: unknown[]; appended?: number } | null
  error?: string | null
  page_title?: string | null
  composite_score?: number | null
  composite_status?: string | null
  published_url?: string | null
  updated_at?: string | null
}

export interface MatrixService { label: string; slug: string }
export interface MatrixLocation {
  name: string
  slug: string
  location_code?: number | null
  canonical?: string | null
  source?: string | null
}

export interface MatrixSummary {
  id: string
  client_id: string
  name: string
  location: string
  location_code?: number | null
  services: MatrixService[]
  locations: MatrixLocation[]
  url_pattern: string
  base_url?: string | null
  page_template_url?: string | null
  entity_provider?: string | null
  publish_destination: 'google_docs' | 'wordpress' | 'github'
  publish_status: 'draft' | 'publish'
  release_enabled: boolean
  release_mode: 'daily' | 'weekly' | 'monthly'
  release_weekday?: number | null
  release_day_of_month?: number | null
  release_per_count: number
  release_status: 'active' | 'complete' | 'paused'
  release_next_run_at?: string | null
  release_last_run_at?: string | null
  coverage: Record<string, number>
  created_at?: string | null
  updated_at?: string | null
}

export interface MatrixDetail extends MatrixSummary {
  cells: MatrixCell[]
  degraded_notes: string[]
}

export interface MatrixGate { kind: string; message: string; blocking: boolean }

export interface MatrixEstimate {
  count: number
  est_cost_usd: number
  est_minutes: number
  gates: MatrixGate[]
  cell_ids: string[]
}

export interface MatrixLocationIn {
  name: string
  location_code?: number | null
  canonical?: string | null
  source?: string | null
}

export interface MatrixCreateBody {
  name: string
  location: string
  location_code?: number | null
  services: string[]
  locations: (MatrixLocationIn | string)[]
  url_pattern?: string | null
  base_url?: string | null
  page_template_url?: string | null
  entity_provider?: string | null
  publish_destination?: 'google_docs' | 'wordpress' | 'github'
  publish_status?: 'draft' | 'publish'
}

export type MatrixUpdateBody = Partial<Omit<MatrixCreateBody, 'location' | 'location_code'>>

export interface MatrixSuggestion {
  label: string
  group?: string | null
  source?: string | null
  lat?: number | null
  lng?: number | null
}

export interface MatrixSuggestResult {
  status: 'pending' | 'running' | 'complete' | 'failed' | string
  axis?: 'services' | 'locations' | null
  suggestions: MatrixSuggestion[]
  degraded_notes: string[]
  error?: string | null
}

export const URL_PATTERN_PRESETS = [
  { value: '/{service}-{location}/', label: '/{service}-{location}/  (flat — WordPress)' },
  { value: '/{location}/{service}/', label: '/{location}/{service}/  (location-first — Website Builder)' },
  { value: '/{service}/{location}/', label: '/{service}/{location}/  (service-first)' },
] as const

// Split a textarea into trimmed, non-empty, case-insensitively deduped lines.
export function splitLines(text: string): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of (text || '').split('\n')) {
    const v = raw.trim()
    if (!v || seen.has(v.toLowerCase())) continue
    seen.add(v.toLowerCase())
    out.push(v)
  }
  return out
}
