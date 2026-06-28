export type RunStatus =
  | 'queued'
  | 'brief_running'
  | 'sie_running'
  | 'research_running'
  | 'writer_running'
  | 'sources_cited_running'
  | 'service_brief_running'
  | 'service_writer_running'
  | 'complete'
  | 'failed'
  | 'cancelled'

export interface TeamUser {
  id: string
  email: string
  full_name: string | null
  role: 'admin' | 'team_member'
  created_at: string
}

export interface ClientListItem {
  id: string
  name: string
  website_url: string
  website_analysis_status: 'pending' | 'complete' | 'failed'
  archived: boolean
  created_at: string
  logo_url: string | null
}

export interface GbpReview {
  reviewer: string
  rating: number | null
  text: string
  date: string
}
export interface GbpProfile {
  business_name: string | null
  description: string | null
  address: string | null
  phone: string | null
  website: string | null
  logo: string | null
  photo: string | null
  gbp_category: string | null
  gbp_categories: string[]
  gbp_rating: number | null
  gbp_review_count: number | null
  latitude: number | null
  longitude: number | null
  hours: Record<string, unknown> | null
  google_maps_uri: string | null
  reviews: GbpReview[]
  // Service-area places Google lists for a service-area business (best-effort).
  service_area_places?: string[]
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
  drive_folders: Record<string, string> | null
  github_repo: string | null
  github_branch: string | null
  github_content_path: string | null
  // WordPress direct-publish target. app_password is never returned — only the
  // boolean flag indicates whether one is stored.
  wordpress_site_url: string | null
  wordpress_username: string | null
  wordpress_app_password_set: boolean
  gsc_property: string | null
  business_location: string | null
  gbp_place_id: string | null
  gbp: GbpProfile | null
  brand_voice: BrandVoice | null
  detected_icp: DetectedIcp | null
  differentiators: Differentiator[] | null
  local_seo_page_template_url: string | null
  page_structures: Record<string, PageStructureEntry> | null
  // Manual extra cities to plan location pages for (silo planner target-city source).
  target_cities: string[] | null
  updated_at: string
}

export type PageStructureType = 'local_landing' | 'service' | 'location' | 'blog_post' | 'product' | 'solution'

export interface PageStructureEntry {
  url: string
  status: 'pending' | 'complete' | 'failed'
  error: string | null
  analysis: Record<string, unknown> | null
  analyzed_at: string | null
}

// Organic Rank Tracker (Module #4) — GSC property connection (M1).
export interface GscProperty {
  id: string
  client_id: string
  site_url: string
  property_type: 'url_prefix' | 'domain'
  access_status: 'ok' | 'no_access' | 'pending'
  last_verified_at: string | null
  created_at: string
  updated_at: string
}

export interface VerifyAccessResponse {
  property_id: string
  access_status: 'ok' | 'no_access' | 'pending'
  detail: string | null
  last_verified_at: string | null
}

export interface SyncRun {
  id: string
  property_id: string
  job_type: string
  run_at: string
  start_date: string | null
  end_date: string | null
  rows: number
  status: 'ok' | 'failed'
  error: string | null
}

export interface IngestResponse {
  property_id: string
  status: 'ok' | 'failed'
  rows: number
  error: string | null
}

export type KeywordStatus =
  | 'climbing' | 'stable' | 'volatile' | 'dropping' | 'deindex_risk' | 'no_data'

export interface KeywordSummary {
  id: string
  keyword: string
  source: string
  primary_source: 'gsc' | 'dataforseo' | 'none'
  canonical_url: string | null
  canonical_url_locked: boolean
  status: KeywordStatus
  status_updated_at: string | null
  avg_7: number | null
  avg_30: number | null
  avg_60: number | null
  avg_90: number | null
  clicks_30d: number
  impressions_30d: number
  ctr_30d: number
  today_rank: number | null
  cpc: number | null
  search_volume: number | null
  competition: string | null
  est_monthly_value: number | null
  index_status: 'indexed' | 'not_indexed' | 'unknown' | null
  index_checked_at: string | null
  page_count: number
  sparkline: (number | null)[]
  direction: 'up' | 'down' | 'flat' | null
}

export interface KeywordPageRow {
  page: string
  clicks: number
  impressions: number
  avg_position: number | null
  is_canonical: boolean
}

export interface KeywordPagesResponse {
  keyword: string
  canonical_url: string | null
  pages: KeywordPageRow[]
}

export interface StrikingKeyword {
  query: string
  avg_position: number
  clicks: number
  impressions: number
}

export interface StrikingDistanceResponse {
  gsc_connected: boolean
  keywords: StrikingKeyword[]
}

export interface TrendPoint {
  date: string
  gsc_position: number | null
  tracked_rank: number | null
  clicks: number
  impressions: number
  ctr: number
}

export interface KeywordTrendline {
  id: string
  keyword: string
  status: KeywordStatus
  canonical_url: string | null
  points: TrendPoint[]
}

export interface HeroPoint {
  date: string
  avg_position: number | null
  clicks: number
  impressions: number
}

export interface RankLocation {
  location: string | null
  location_code: number | null
  source?: 'auto' | 'manual' | null
}

export type FetchMode = 'off' | 'weekly' | 'monthly' | 'interval'

export interface FetchSchedule {
  mode: FetchMode
  day_of_week: number | null
  day_of_month: number | null
  interval_days: number | null
  last_fetched_at: string | null
}

export type ReportMode = 'as_needed' | 'weekly' | 'monthly' | 'interval'

export interface ReportSchedule {
  mode: ReportMode
  day_of_week: number | null
  day_of_month: number | null
  interval_days: number | null
  deliver_google_doc: boolean
  last_generated_at: string | null
}

export interface ReportListItem {
  id: string
  title: string
  created_at: string
  doc_url: string | null
}

export interface ReportSnapshot {
  generated_at: string
  client: { name: string | null; logo_url: string | null }
  location: string | null
  gsc_connected: boolean
  overview: RankOverview
  keywords: KeywordSummary[]
}

export interface GeneratedReport {
  id: string
  title: string
  created_at: string
  snapshot: ReportSnapshot
}

export interface PageRow {
  page: string
  clicks: number
  impressions: number
  keywords: number
  avg_position: number | null
}

export interface PagesResponse {
  gsc_connected: boolean
  pages: PageRow[]
}

export interface RankOverview {
  keyword_count: number
  gsc_connected: boolean
  status_counts: Record<string, number>
  clicks_30d: number
  impressions_30d: number
  avg_position_30d: number | null
  at_risk: number
  hero: HeroPoint[]
  unread_alert_count: number
}

export type RankAlertType = 'weekly_drop' | 'page_one_exit' | 'thirty_day_drop' | 'deindexed'

export interface RankAlert {
  id: string
  keyword_id: string
  keyword: string
  alert_type: RankAlertType
  source: string | null
  from_position: number | null
  to_position: number | null
  delta: number | null
  message: string
  status: 'unread' | 'read' | 'dismissed'
  triggered_on: string | null
  resolved_at: string | null
  created_at: string
}

export interface RankAlertsResponse {
  alerts: RankAlert[]
  unread_count: number
}

// ── ICP + differentiators (converged client-level assets, Option A) ──────────

export interface IcpSegment {
  label?: string
  confidence?: number
  primary?: boolean
  demographics?: { description?: string; situation?: string }
  psychographics?: {
    trigger?: string
    fears?: string[]
    motivations?: string[]
    buying_behavior?: string
  }
  messaging?: { tone?: string; hooks?: string[]; trust_signals?: string[] }
}

export interface DetectedIcp {
  source: 'user' | 'app' | null
  raw_text: string | null
  segments: IcpSegment[] | null
  reasoning: string | null
  generated_at: string | null
  edited_at: string | null
}

export interface Differentiator {
  claim?: string
  mechanism?: string
  type?: string
}

export interface IcpResponse {
  detected_icp: DetectedIcp | null
  differentiators: Differentiator[] | null
  pages_crawled?: number | null
  analysis_status?: string | null
}

// ── Brand Voice (converged client-level asset, Option A) ─────────────────────

export interface VoiceProfile {
  personality?: string[]
  tone?: string
  writing_style?: {
    sentence_length?: string
    person?: string
    jargon_level?: string
    formality?: string
  }
  vocabulary?: { use?: string[]; avoid?: string[] }
  messaging_themes?: string[]
  sample_phrases?: string[]
  content_generation_instructions?: string
}

export interface BrandVoice {
  source: 'user' | 'app' | null
  raw_text: string | null
  current_voice: VoiceProfile | null
  recommended_voice: VoiceProfile | null
  recommended_accepted: boolean | null
  writer_execution_guide: Record<string, unknown> | null
  generated_at: string | null
  edited_at: string | null
}

export interface BrandVoiceResponse {
  brand_voice: BrandVoice | null
  pages_sampled?: number | null
}

export interface ModuleOutput {
  status: 'running' | 'complete' | 'failed'
  output_payload: Record<string, unknown> | null
  cost_usd: number | null
  duration_ms: number | null
  module_version: string | null
}

export type RunContentType = 'blog_post' | 'service_page' | 'location_page'

export interface Run {
  id: string
  client_id: string
  client_name: string
  keyword: string
  title: string | null
  content_type: RunContentType
  status: RunStatus
  sie_cache_hit: boolean | null
  total_cost_usd: number | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

// Service Page Writer output (module_outputs.service_writer.output_payload)
export interface ServiceWriterOutput {
  title: string
  meta_description: string
  sections: Array<Record<string, unknown>>
  renderings: { markdown: string; html: string; wordpress: string }
  schema_jsonld: string
  metadata: Record<string, unknown>
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
  content_type: RunContentType
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
    // Present on service_page runs instead of the blog modules above.
    service_brief?: ModuleOutput | null
    service_writer?: ModuleOutput | null
    // Latest score (nlp-api national mode) for a service_page run.
    service_score?: ModuleOutput | null
  }
  // Manually-attached featured/hero image (public wordpress_images URL).
  featured_image_url?: string | null
}

export interface Profile {
  id: string
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

// --- Maps / local-pack geo-grid ranker (Module #5) ---
export type MapsRadius = 3 | 5 | 7
export interface MapsConfig {
  client_id: string
  google_place_id: string | null
  business_name: string | null
  center_lat: number | null
  center_lng: number | null
  radius_miles: MapsRadius
  shape: 'circle' | 'square'
  resource_category: 'googleMaps' | 'googleLocalFinder'
  serp_device: 'desktop' | 'mobile' | 'both'
  cadence: 'off' | 'weekly'
  weekday: number
  active: boolean
  last_scanned_at: string | null
  configured: boolean
}

export interface MapsKeyword {
  id: string
  keyword: string
  active: boolean
}

export interface MapsCompetitor {
  place_id: string | null
  name: string | null
  rating: number | null
  reviews: number | null
  primary_category: string | null
  website: string | null
  found_pins: number
  top3_pins: number
  top10_pins: number
  avg_rank: number | null
}

export interface MapsCompetitorDirEntry {
  name: string | null
  rating: number | null
  reviews: number | null
  primary_category: string | null
  website: string | null
  lat: number | null
  lng: number | null
}

// Per-pin businesses ranking ABOVE the client. grid[row][col] is a list of
// [place_id, rank] for the pin (rank-ordered, above us only), or null when the
// pin is outside the scan circle. directory holds each business's details once.
export interface MapsCompetitorsAbove {
  directory: Record<string, MapsCompetitorDirEntry>
  grid: Array<Array<Array<[string, number]> | null>>
}

export interface MapsScanResultRow {
  keyword: string
  average_rank: number | null
  found_pins: number
  total_pins: number
  top3_pins: number
  top10_pins: number
  rank_grid: Array<Array<number | null>> | null
  heatmap_image_url: string | null
  dynamic_url: string | null
  competitors: MapsCompetitor[] | null
  competitors_above: MapsCompetitorsAbove | null
  // Local Rank Analysis report (auto-generated when the scan completes).
  report_status: 'pending' | 'complete' | 'failed' | null
  report_md: string | null
  report_weak_directions: string | null
  report_top_competitors: string[] | null
  report_octant_pins: MapsOctantPins | null
  report_weak_locations: MapsWeakLocations | null
  report_analytics: MapsReportAnalytics | null
  report_doc_url: string | null
  report_generated_at: string | null
}

export interface MapsDirectionStat {
  sector: string
  sector_full?: string
  avg_rank: number | null
  coverage_pct_top3: number
}

export interface MapsReportAnalytics {
  overall?: {
    avg_rank: number | null
    coverage_pct_top3: number
    coverage_pct_top10: number
    ranked: number
    not_ranked: number
    cells: number
  }
  performance_horizon?: { ring: number; radius_mi: number; coverage_pct_top3: number } | null
  best_directions?: MapsDirectionStat[]
  weakest_directions?: MapsDirectionStat[]
}

export interface MapsOctantPin {
  sector: string
  octant: string
  ring: number
  radius_m: number
  radius_mi: number
  bearing_deg: number
  lat: number
  lng: number
  strength: string
  // Present once the weak zone has been reverse-geocoded.
  city?: string | null
  admin_area?: string | null
  formatted?: string | null
}

export interface MapsOctantPins {
  ok: boolean
  used_rule?: string | null
  reason: string
  points: MapsOctantPin[]
  debug?: Record<string, unknown>
}

// A nearby city/locality the geo-grid is weak in: the unique place that a cluster
// of opportunity (unranked / poorly-ranked) pins falls in, scored for targeting
// priority, with a representative point.
export type MapsWeakTier = 'critical' | 'weak' | 'watch'

export interface MapsWeakArea {
  city: string | null
  admin_area: string | null
  pins: number
  not_ranked: number
  octants: string[]
  worst_rank: number | null
  avg_rank: number | null
  tier: MapsWeakTier
  priority: number       // 0-100, normalized per keyword (highest = target first)
  score_raw?: number
  lat: number
  lng: number
}

export interface MapsWeakLocations {
  geocoded: boolean
  capped: boolean
  opportunity_floor?: number
  weak_threshold: number
  weak_cell_count: number
  octant_pins: MapsOctantPin[]
  weak_areas: MapsWeakArea[]
}

export interface MapsScanSummary {
  id: string
  scan_uuid: string | null
  status: 'pending' | 'polling' | 'complete' | 'failed' | 'cancelled'
  trigger: 'scheduled' | 'manual'
  radius_miles: number | null
  grid_size: number | null
  search_terms: string[] | null
  requested_at: string | null
  completed_at: string | null
  error: string | null
}

export interface MapsScanDetail extends MapsScanSummary {
  shape: string | null
  distance: number | null
  center_lat: number | null
  center_lng: number | null
  resource_category: string | null
  serp_device: string | null
  results: MapsScanResultRow[]
}

export interface MapsRunResponse {
  client_id: string
  status: string
  error: string | null
}

export interface MapsTrendPoint {
  scan_id: string
  completed_at: string | null
  trigger: 'scheduled' | 'manual'
  total_pins: number
  found_pins: number
  top3_pins: number
  top10_pins: number
  average_rank: number | null
  found_pct: number | null
  top3_pct: number | null
  top10_pct: number | null
}

export interface MapsKeywordTrend {
  keyword: string
  points: MapsTrendPoint[]
}

export interface MapsTrendsResponse {
  keywords: MapsKeywordTrend[]
}

export interface MapsCompetitorTrendPoint {
  scan_id: string
  completed_at: string | null
  beats_pins: number
  total_slots: number
  beats_pct: number | null
  avg_rank_above: number | null
}

export interface MapsCompetitorTrend {
  place_id: string
  name: string | null
  latest_pct: number | null
  delta_pct: number | null   // positive = gaining on us
  points: MapsCompetitorTrendPoint[]
}

export interface MapsCompetitorTrendsResponse {
  scan_count: number
  competitors: MapsCompetitorTrend[]
}

export interface MapsThreat {
  name: string | null
  beats_pct: number | null
  delta_pct: number | null   // positive = gaining on us
}

export interface MapsClientThreats {
  client_id: string
  scan_count: number
  threats: MapsThreat[]
}

export interface MapsThreatsResponse {
  clients: MapsClientThreats[]
}

// Dashboard ranking-health tile: average organic position + average maps rank,
// latest run vs first. Lower rank numbers are better, so direction "up" = the
// latest average is a smaller (better) number than the first.
export interface RankingTrend {
  first_avg: number | null
  latest_avg: number | null
  delta: number | null // first_avg - latest_avg; positive = improved
  direction: 'up' | 'down' | 'flat' | null
  sample_count: number
}

export interface ClientRankingHealth {
  client_id: string
  organic: RankingTrend
  maps: RankingTrend
}

export interface RankingHealthResponse {
  clients: ClientRankingHealth[]
}

// --- Competitive SERP Snapshot (rank tracker §14) -------------------------
export interface SerpSnapshotListItem {
  id: string
  captured_at: string
  status: 'complete' | 'partial' | 'failed'
  query_intent: string | null
  aio_present: boolean
  client_rank: number | null
  result_count: number
}

export interface SerpSnapshotResultRow {
  position: number | null
  url: string | null
  domain: string | null
  title: string | null
  description: string | null
  is_client: boolean
  targeted: boolean | null // page written for the keyword (title/slug coverage)
  referring_domains: number | null
  url_rating: number | null // DataForSEO page rank (0–1000), UR-equivalent
  backlinks: number | null
  backlinks_status: string
}

export interface SerpSnapshotDomainRow {
  domain: string | null
  is_client: boolean
  domain_rating: number | null // DataForSEO domain rank (0–1000), DR-equivalent
  referring_domains: number | null
  backlinks: number | null
  backlinks_status: string
}

export interface SerpAioSource {
  url: string | null
  domain: string | null
  title: string | null
}

export interface SerpSnapshotDetail {
  id: string
  keyword_id: string
  client_id: string
  keyword: string
  captured_at: string
  status: 'complete' | 'partial' | 'failed'
  location_code: number | null
  language_code: string | null
  query_intent: string | null
  intent_probabilities: Record<string, number> | null
  local_intent: boolean
  intent_signals: string[] | null
  aio_present: boolean
  aio_text: string | null
  aio_sources: SerpAioSource[] | null
  serp_features: Record<string, unknown> | null
  targeted_count: number | null
  client_rank: number | null
  client_url: string | null
  error: string | null
  results: SerpSnapshotResultRow[]
  domains: SerpSnapshotDomainRow[]
}

export interface SerpSnapshotCaptureResponse {
  keyword_id: string
  status: string // 'enqueued'
}

// --- SERP Landscape Trends ------------------------------------------------
export interface SerpTimelinePoint {
  snapshot_id: string
  captured_at: string
  status: string
  query_intent: string | null
  local_intent: boolean
  intent_signals: string[]
  aio_present: boolean
  targeted_count: number | null
  client_rank: number | null
  client_rd: number | null
  client_ur: number | null
  client_dr: number | null
  signals_added: string[]
  signals_removed: string[]
  client_rank_delta: number | null
  client_rd_delta: number | null
  client_dr_delta: number | null
}

export interface SerpTimelineResponse {
  keyword_id: string
  keyword: string
  points: SerpTimelinePoint[]
}

export interface SerpTrendSeries {
  signal: string
  counts: number[]
  pct: (number | null)[]
}

export interface SerpChangeItem {
  keyword_id: string
  keyword: string
  captured_at: string
  added: string[]
  removed: string[]
  client_rank_delta: number | null
}

export interface SerpTrendsResponse {
  week_ends: string[]
  keyword_counts: number[]
  series: SerpTrendSeries[]
  changes: SerpChangeItem[]
}

// --- Rankability ----------------------------------------------------------
export interface RankabilityFactor {
  text: string
  direction: 'up' | 'down'
}

export interface RankabilityItem {
  keyword_id: string
  keyword: string
  has_snapshot: boolean
  snapshot_id: string | null
  score: number | null
  band: string | null
  factors: RankabilityFactor[]
  client_rank: number | null
  search_volume: number | null
  cpc: number | null
  est_value: number | null
  priority: number | null
}

export interface RankabilityResponse {
  items: RankabilityItem[]
}
