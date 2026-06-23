import { supabase } from "./supabaseClient";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface Me {
  user_id: string;
  email: string | null;
  display_name: string | null;
  role: "owner" | "va";
}

export interface Project {
  id: string;
  name: string;
  is_scratch: boolean;
  created_at: string;
}

export type RelationshipType =
  | "property_or_mechanism"
  | "use_case"
  | "effect_or_outcome"
  | "practical_commercial"
  | "research_or_trial"
  | "broader_class"
  | "peer_entity";

export interface Silo {
  id: string;
  session_id: string;
  name: string;
  rationale: string | null;
  relationship_type: RelationshipType;
  supporting_evidence: string | null;
  source: "llm_proposed" | "user_added" | "llm_proposed_then_user_edited";
  is_broader_class: boolean;
  is_gated_for_competitor_mining: boolean;
  created_at: string;
}

export interface SiloDiscovery {
  session_id: string;
  status: string;
  seed_keyword: string | null;
  detected_audience: string | null;
  needs_disambiguation: boolean;
  interpretations: string[];
  degraded_notes: string[];
  silos: Silo[];
  site_base_url?: string | null;
  publish_config?: {
    github?: { repo?: string; branch?: string; content_path?: string };
    drive?: { folder_id?: string };
  };
  publish_available?: { github?: boolean; drive?: boolean };
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) throw new Error("Not authenticated");

  const resp = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const getMe = () => request<Me>("/me");
export const getProjects = () => request<Project[]>("/projects");

// Session Browser (PRD §9.4): sessions under a project, newest first, for
// resume. cluster_count is the planned-article count; status drives where a
// resumed session lands (results views vs. still-in-flight).
export interface SessionListItem {
  id: string;
  seed_keyword: string;
  status: string;
  coverage_mode: string;
  cluster_count: number;
  archived: boolean;
  created_at: string;
  completed_at: string | null;
}

export const listSessions = (projectId: string, includeArchived = false) =>
  request<SessionListItem[]>(
    `/projects/${projectId}/sessions${includeArchived ? "?include_archived=true" : ""}`,
  );

// Supported English-market countries (E1, 2026-06-17). The code is the
// DataForSEO location_code (2000 + ISO-3166 numeric); language stays "en". Must
// mirror the backend allow-list (storage/silo.SUPPORTED_LOCATION_CODES) + the DB
// check constraint. Default = US.
export const SUPPORTED_COUNTRIES = [
  { label: "United States", code: 2840 },
  { label: "United Kingdom", code: 2826 },
  { label: "Canada", code: 2124 },
  { label: "Australia", code: 2036 },
  { label: "New Zealand", code: 2554 },
] as const;
export const DEFAULT_LOCATION_CODE = 2840;

export interface CreateSessionBody {
  seed_keyword: string;
  project_id?: string;
  audience_hint?: string;
  disambiguation_hint?: string;
  topic_count?: number;
  coverage_mode?: "standard" | "comprehensive";
  // Per-country locale (E1). DataForSEO location_code for the session's market.
  // Omit -> backend defaults to US (2840).
  location_code?: number;
  // §7.8 metrics enrichment toggle. Omit -> backend uses workspace default
  // (currently true). Setting false skips the DataForSEO keyword_overview pass
  // -> Volume / CPC / KD stay null.
  enrich_with_metrics?: boolean;
}

export const createSession = (body: CreateSessionBody) =>
  request<SiloDiscovery>("/sessions", { method: "POST", body: JSON.stringify(body) });

export const getSession = (id: string) => request<SiloDiscovery>(`/sessions/${id}`);

export const disambiguateSession = (id: string, choice: string) =>
  request<SiloDiscovery>(`/sessions/${id}/disambiguate`, {
    method: "POST",
    body: JSON.stringify({ choice }),
  });

export const overrideAudience = (id: string, detected_audience: string) =>
  request<SiloDiscovery>(`/sessions/${id}/audience`, {
    method: "PATCH",
    body: JSON.stringify({ detected_audience }),
  });

export const finalizeSilos = (id: string) =>
  request<{ finalized: boolean; topic_count: number }>(`/sessions/${id}/finalize`, {
    method: "POST",
  });

export interface AddTopicBody {
  name: string;
  rationale?: string;
  relationship_type?: RelationshipType;
  is_broader_class?: boolean;
}

export const addTopic = (sessionId: string, body: AddTopicBody) =>
  request<Silo>(`/sessions/${sessionId}/topics`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface EditTopicBody {
  name?: string;
  rationale?: string;
  relationship_type?: RelationshipType;
}

export const editTopic = (topicId: string, body: EditTopicBody) =>
  request<Silo>(`/topics/${topicId}`, { method: "PATCH", body: JSON.stringify(body) });

export const deleteTopic = (topicId: string) =>
  request<void>(`/topics/${topicId}`, { method: "DELETE" });

export interface PipelineTopicCount {
  topic_id: string;
  name: string;
  active: number;
  total: number;
  grouping_count: number;
}

export interface PipelineCounts {
  active: number;
  filtered_relevance: number;
  filtered_junk: number;
  // Optional: older sessions / older backend payloads predate the
  // pre-embedding language filter, so this field may be absent.
  filtered_language?: number;
}

// The long pipeline steps run in the background and return this immediately;
// the UI then polls getSummary for status (running -> terminal).
export interface AsyncAck {
  status: string;
  session_id: string;
  relevance_threshold?: number;
}

export interface SummaryPlanTopic {
  topic_id: string;
  name: string;
  articles: number;
  gaps: number;
}

// Approval state on the summary payload (PRD §11.3). The VA's waiting screen
// reads `note` (set on a reject) and `estimated_cost_usd`; `decided_at` is set
// once the Owner acts.
export interface SummaryApproval {
  required: boolean;
  estimated_cost_usd: number | null;
  note: string | null;
  decided_at: string | null;
}

// Live cost attribution on the summary payload (PRD §8.4 / §16.4). The cost
// banner reads actual vs estimated; the background job flushes actual_cost_usd
// every ~10s, so it climbs while the run is in progress.
export interface SummaryCost {
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  breakdown: Record<string, number>;
}

export interface PipelineSummary {
  status: string;
  last_error: string | null;
  approval: SummaryApproval;
  cost: SummaryCost;
  expansion: {
    counts: PipelineCounts;
    topics: PipelineTopicCount[];
  };
  plan: {
    clusters: number;
    gaps: number;
    dropped: number;
    collisions: number;
    topics: SummaryPlanTopic[];
  } | null;
  architecture: { generated_at: string; is_user_edited: boolean } | null;
}

export interface Keyword {
  id: string;
  topic_id: string;
  cluster_id: string | null;
  keyword: string;
  sources: string[];
  status: string;
  is_primary_for_cluster: boolean;
  relevance_score: number | null;
  // §7.8 metrics (null when enrich_with_metrics was off / data unavailable).
  volume: number | null;
  cpc_usd: number | null;
  keyword_difficulty: number | null;
  competition_index: number | null;
  created_at: string;
  // Within-cluster display-time dedup. Populated only by the cluster-keywords
  // endpoint (Cluster View); null on the Table View's `/keywords` shape. When
  // set, this row is a near-duplicate of the row with id == dedupe_canonical_id
  // (which lives in the same cluster) and should be hidden by default.
  dedupe_canonical_id?: string | null;
}

// One planned article (the orchestrator's output). Mirrors fanout.clusters
// minus the centroid embedding. M7 read shapes; editing lands in M7b.
export interface Cluster {
  id: string;
  topic_id: string;
  name: string;
  primary_keyword_id: string | null;
  intent: string | null;
  suggested_h2s: string[] | null;
  peer_article_links: string[] | null;
  source_statistical_grouping_id: string | null;
  orchestrator_notes: string | null;
  is_user_edited: boolean;
  is_gap_placeholder: boolean;
  created_at: string;
}

export interface CoverageGap {
  id: string;
  topic_id: string;
  suggested_title: string;
  target_keyword: string | null;
  rationale: string | null;
  status: "pending" | "accepted" | "dismissed";
  accepted_cluster_id: string | null;
}

export const getClusters = (id: string) =>
  request<{ clusters: Cluster[]; coverage_gaps: CoverageGap[] }>(
    `/sessions/${id}/clusters`,
  );

// ---- M7b editing (PRD §9.1 / §9.2 / §9.4) --------------------------------
export interface ClusterEdit {
  name?: string;
  intent?: string;
  // H2 outlines are owned by the writer module — no longer editable via PATCH.
}

export const editCluster = (clusterId: string, body: ClusterEdit) =>
  request<Cluster>(`/clusters/${clusterId}`, { method: "PATCH", body: JSON.stringify(body) });

export const promotePrimary = (clusterId: string, keyword_id: string) =>
  request<Cluster>(`/clusters/${clusterId}/promote-primary`, {
    method: "POST",
    body: JSON.stringify({ keyword_id }),
  });

export const deleteCluster = (clusterId: string) =>
  request<void>(`/clusters/${clusterId}`, { method: "DELETE" });

export const mergeClusters = (survivor_id: string, merged_ids: string[], name?: string) =>
  request<Cluster>(`/clusters/merge`, {
    method: "POST",
    body: JSON.stringify({ survivor_id, merged_ids, name }),
  });

export const splitCluster = (
  clusterId: string,
  keyword_ids: string[],
  name: string,
  primary_keyword_id?: string,
) =>
  request<Cluster>(`/clusters/${clusterId}/split`, {
    method: "POST",
    body: JSON.stringify({ keyword_ids, name, primary_keyword_id }),
  });

export const bulkKeywordStatus = (
  sessionId: string,
  keyword_ids: string[],
  status: "active" | "excluded" | "covered",
) =>
  request<{ updated: number }>(`/sessions/${sessionId}/keywords/status`, {
    method: "POST",
    body: JSON.stringify({ keyword_ids, status }),
  });

export const bulkKeywordMove = (
  sessionId: string,
  keyword_ids: string[],
  cluster_id: string | null,
) =>
  request<{ updated: number }>(`/sessions/${sessionId}/keywords/move`, {
    method: "POST",
    body: JSON.stringify({ keyword_ids, cluster_id }),
  });

export const acceptGap = (gapId: string) =>
  request<Cluster>(`/coverage-gaps/${gapId}/accept`, { method: "POST" });

export const dismissGap = (gapId: string) =>
  request<void>(`/coverage-gaps/${gapId}/dismiss`, { method: "POST" });

export interface SessionPatch {
  project_id?: string;
  archived?: boolean;
}

export const patchSession = (sessionId: string, body: SessionPatch) =>
  request<{ session_id: string; moved: boolean; archived: boolean | null }>(
    `/sessions/${sessionId}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );

export const deleteSession = (sessionId: string) =>
  request<void>(`/sessions/${sessionId}`, { method: "DELETE" });

export const setDeepMine = (id: string, topic_ids: string[]) =>
  request<{ gated_topic_ids: string[]; topics: Silo[] }>(`/sessions/${id}/deep-mine`, {
    method: "POST",
    body: JSON.stringify({ topic_ids }),
  });

export const expandSession = (id: string) =>
  request<AsyncAck>(`/sessions/${id}/expand`, { method: "POST" });

export const planArticles = (id: string) =>
  request<AsyncAck>(`/sessions/${id}/plan-articles`, { method: "POST" });

// Cancel an in-progress pipeline run. 200 once the worker is signalled (it will
// exit at its next external-call checkpoint); 409 if no run is currently in
// progress. Both roles, RLS-scoped to a visible session.
export const cancelRun = (id: string) =>
  request<{ status: string; session_id: string }>(`/sessions/${id}/cancel`, {
    method: "POST",
  });

export const getSummary = (id: string) =>
  request<PipelineSummary>(`/sessions/${id}/summary`);

// Owner debug view (PRD §15.3 #8): raw clustering + orchestrator logs + cost.
// Owner-only on the backend (require_owner) — a VA gets 403.
export interface ArchitectureLinkHealth {
  orphan_articles: number;
  orphan_pillars: number;
  dangling_links: number;
}

export interface SessionDebug {
  status: string | null;
  seed_keyword: string | null;
  estimated_cost_usd: number | null;
  actual_cost_usd: number | null;
  cost_breakdown: Record<string, number>;
  statistical_clustering_log: unknown;
  orchestrator_log: unknown;
  // §15.2 #3 no-orphan / no-dangling audit; null until architecture is generated.
  architecture_link_health: ArchitectureLinkHealth | null;
}

export const getSessionDebug = (id: string) =>
  request<SessionDebug>(`/sessions/${id}/debug`);

export interface RegateBody {
  relevance_threshold?: number;
  clustering_edge_threshold?: number;
  clustering_resolution?: number;
}

export const regate = (id: string, body: RegateBody = {}) =>
  request<AsyncAck>(`/sessions/${id}/regate`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface ClusterPreviewConfig {
  edge_threshold: number;
  resolution: number;
  groupings: number;
  median_size: number;
  singletons: number;
  size_buckets: Record<string, number>;
}

export interface ClusterPreview {
  relevance_threshold: number;
  active_keywords: number;
  configs: ClusterPreviewConfig[];
}

export interface FanoutBody {
  confirm_cost?: boolean;
  relevance_threshold?: number;
  clustering_edge_threshold?: number;
  clustering_resolution?: number;
}

export interface FanoutEstimate {
  sub_anchors_total: number;
  sub_anchors_per_silo: Record<string, number>;
  cost_multiplier_range: [number, number];
  note: string;
}

export interface FanoutAck {
  status: string; // "estimate" (not started) | "running"
  session_id: string;
  estimate: FanoutEstimate;
}

// Recursive Fanout (PRD §7.7). Without confirm_cost it returns the cost
// estimate + sub-anchor plan and does NOT spend; resend with confirm_cost: true.
export const fanout = (id: string, body: FanoutBody = {}) =>
  request<FanoutAck>(`/sessions/${id}/fanout`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const clusterPreview = (
  id: string,
  body: { relevance_threshold?: number; configs?: [number, number][] } = {},
) =>
  request<ClusterPreview>(`/sessions/${id}/cluster-preview`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getKeywords = (id: string, topicId: string, limit = 200, status = "active") =>
  request<Keyword[]>(
    `/sessions/${id}/keywords?topic_id=${encodeURIComponent(topicId)}` +
      `&status=${encodeURIComponent(status)}&limit=${limit}`,
  );

// The Table/Cluster views need every *surviving* keyword (active + the user
// states excluded/covered), not just one topic's. The endpoint caps each page
// at 500, so we page through with offset until a short page comes back. Hard
// stop at 20 pages (10k) so a runaway never spins forever.
const SURVIVING_STATUSES = "active,excluded,covered";

// Cluster View only: surviving keywords already assigned to a cluster, each
// row carrying a `dedupe_canonical_id` set when the row is a near-duplicate
// of another keyword in the same cluster (so the card can render one variant
// per intent instead of every phrasing). Backend handles surface-form + cosine
// dedup; the frontend filters non-canonicals out of the card.
export const getClusterKeywords = (id: string): Promise<Keyword[]> =>
  request<Keyword[]>(`/sessions/${id}/cluster-keywords`);

export async function getAllSurvivingKeywords(id: string): Promise<Keyword[]> {
  const pageSize = 500;
  const all: Keyword[] = [];
  for (let offset = 0; offset < pageSize * 20; offset += pageSize) {
    const page = await request<Keyword[]>(
      `/sessions/${id}/keywords?statuses=${encodeURIComponent(SURVIVING_STATUSES)}` +
        `&limit=${pageSize}&offset=${offset}`,
    );
    all.push(...page);
    if (page.length < pageSize) break;
  }
  return all;
}

// M6 site architecture (PRD §7.11). One pillar per article-bearing silo + the
// internal linking matrix. The full two-panel Architecture View is M7.
export interface ArchitecturePillar {
  topic_id: string;
  silo_name: string;
  title: string;
  target_keyword: string;
  summary: string;
  h2_outline: string[];
  supporting_article_ids: string[];
  lateral_pillar_links: string[];
  degraded: boolean;
}

export interface ArchitectureSupportingArticle {
  article_id: string;
  name: string;
  intent: string;
  parent_pillar_topic_id: string;
  lateral_article_links: string[];
}

export interface ArchitectureJson {
  seed_keyword: string;
  detected_audience: string;
  pillars: ArchitecturePillar[];
  supporting_articles: ArchitectureSupportingArticle[];
  skipped_silos: string[];
  // §15.2 #3 audit (present on architectures generated 2026-06-09+).
  link_health?: ArchitectureLinkHealth;
}

export interface SiteArchitecture {
  session_id: string;
  architecture_json: ArchitectureJson;
  generated_at: string;
  is_user_edited: boolean;
}

// Kicks off generation in the background; poll getSummary until
// summary.architecture is non-null, then call getArchitecture.
export const generateArchitecture = (id: string) =>
  request<AsyncAck>(`/sessions/${id}/architecture`, { method: "POST" });

export const getArchitecture = (id: string) =>
  request<SiteArchitecture>(`/sessions/${id}/architecture`);

// ---- M9 cost estimate + approval workflow (PRD §8.4 / §11.3) -------------
export interface CostEstimate {
  session_id: string;
  estimated_cost_usd: number;
  breakdown: Record<string, number>;
  recursive_multiplier: number | null;
  silo_count: number;
  deep_mine_count: number;
  coverage_mode: string;
  recursive_fanout: boolean;
  va_soft_cap_usd: number;
  requires_approval: boolean;
  approval_triggers: string[];
}

// Authoritative server-side estimate (PRD §8.1). `gatedCount` previews the
// wizard's not-yet-persisted deep-mine selection so the cost updates live.
export const getCostEstimate = (id: string, gatedCount?: number) =>
  request<CostEstimate>(
    `/sessions/${id}/cost-estimate` +
      (gatedCount != null ? `?gated_count=${gatedCount}` : ""),
  );

export interface WorkspaceSettings {
  va_soft_cap_usd: number;
  owner_cost_confirm_threshold_usd: number;
  default_relevance_threshold: number;
}

export const getWorkspaceSettings = () =>
  request<WorkspaceSettings>("/workspace-settings");

// Park a run at the approval gate (does not start the pipeline). The deep-mine
// selection must already be persisted via setDeepMine (same as run-now).
export const submitForApproval = (id: string) =>
  request<CostEstimate & { status: string }>(`/sessions/${id}/submit-for-approval`, {
    method: "POST",
  });

export const cancelApproval = (id: string) =>
  request<{ status: string; session_id: string }>(`/sessions/${id}/cancel-approval`, {
    method: "POST",
  });

// Owner approval queue (PRD §11.3 step 4).
export interface ApprovalQueueItem {
  session_id: string;
  va_display_name: string | null;
  project_name: string | null;
  seed_keyword: string;
  coverage_mode: string;
  recursive_fanout: boolean;
  topic_count: number | null;
  deep_mine_count: number;
  estimated_cost_usd: number | null;
  submitted_at: string;
}

export const listApprovals = () => request<ApprovalQueueItem[]>("/approvals");

export const approveSession = (id: string, note?: string) =>
  request<{ status: string; session_id: string }>(`/sessions/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export const rejectSession = (id: string, note?: string) =>
  request<{ status: string; session_id: string }>(`/sessions/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

// ---- M10 CSV export (PRD §12) --------------------------------------------
export type CsvExportFormat = "flat" | "topic_grouped" | "architecture" | "linking";

export interface CsvExportResult {
  export_id: string;
  session_id: string;
  format: CsvExportFormat;
  storage_path?: string;
  generated_at: string;
  download_url: string;
}

export interface CsvExportListItem {
  id: string;
  session_id: string;
  user_id: string;
  format: CsvExportFormat;
  storage_path: string;
  generated_at: string;
}

// Generate a CSV snapshot live from current Postgres state, store it, and return
// a short-lived signed download URL. Export is available to both roles (§11.2).
export const createExport = (sessionId: string, format: CsvExportFormat) =>
  request<CsvExportResult>(
    `/sessions/${sessionId}/export?format=${encodeURIComponent(format)}`,
    { method: "POST" },
  );

// Past snapshots for a session, newest first (the Exports tab, §12).
export const listExports = (sessionId: string) =>
  request<CsvExportListItem[]>(`/sessions/${sessionId}/exports`);

// Re-issue a fresh signed URL for a past snapshot (the old one may have expired).
export const downloadExport = (exportId: string) =>
  request<CsvExportResult>(`/exports/${exportId}/download`);

// §9.1 bulk action — stream a flat CSV of just the selected keyword ids.
// Transient (no Storage snapshot, no Exports-tab row); the browser saves the
// blob directly. The `request<T>` JSON helper above doesn't fit (this returns a
// CSV body, not JSON), so this calls fetch + supabase auth itself, then yields
// the blob plus the filename parsed off Content-Disposition.
export async function exportSelected(
  sessionId: string,
  keywordIds: string[],
): Promise<{ blob: Blob; filename: string }> {
  const { supabase } = await import("./supabaseClient");
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const token = session?.access_token;
  if (!token) throw new Error("Not authenticated");
  const resp = await fetch(
    `${import.meta.env.VITE_API_BASE_URL ?? ""}/sessions/${sessionId}/export-selected`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ keyword_ids: keywordIds }),
    },
  );
  if (!resp.ok) {
    let detail = `Export failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const blob = await resp.blob();
  // Pull the server-suggested filename so the download matches the snapshot ts
  // the backend stamped — keeps multiple exports apart in the Downloads folder.
  const cd = resp.headers.get("Content-Disposition") ?? "";
  const m = cd.match(/filename="([^"]+)"/);
  const filename = m?.[1] ?? `fanout-selected-${Date.now()}.csv`;
  return { blob, filename };
}

// Trigger a save dialog for an in-memory blob (no server round-trip). Used by
// the Table View bulk export — the blob comes from exportSelected().
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Defer revoke so Firefox/Chrome finish the download handoff first.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ----- M12 SIE Term & Entity analysis (owner-only) --------------------------
export interface SieZoneRange { min: number; target: number; max: number }
export interface SieRequiredTerm {
  term: string;
  recommendation_score: number;
  is_entity: boolean;
  entity_category: string | null;
}
export interface SieUsageRec {
  term: string;
  h2: SieZoneRange;
  h3: SieZoneRange;
  paragraphs: SieZoneRange;
}
export interface SieEntity {
  term: string;
  entity_category: string | null;
  example_context: string | null;
  ner_variants: string[];
  recommendation_score: number;
}
export interface SiePage {
  url: string;
  rank: number | null;
  included: boolean;
  reason: string | null;
}
export interface SieReport {
  schema_version: string;
  keyword: string;
  word_count: { min: number; target: number; max: number };
  target_keyword: { term: string; minimum_usage: { h2: number; h3: number; paragraphs: number } };
  terms: { required: SieRequiredTerm[]; avoid: string[] };
  usage_recommendations: SieUsageRec[];
  entities: SieEntity[];
  warnings: string[];
  pages: SiePage[];
}
export interface TermAnalysisResponse {
  status: "complete" | "running";
  keyword: string;
  report?: SieReport;
}

export const startTermAnalysis = (
  sessionId: string,
  clusterId: string,
  body?: { force_refresh?: boolean; outlier_mode?: "safe" | "aggressive" },
) =>
  request<TermAnalysisResponse>(
    `/sessions/${sessionId}/clusters/${clusterId}/term-analysis`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );

export const getTermAnalysis = (sessionId: string, clusterId: string) =>
  request<TermAnalysisResponse>(
    `/sessions/${sessionId}/clusters/${clusterId}/term-analysis`,
  );

// ----- M13 Brief Generator (answer-engine-first) — owner-only validation surface ----
export interface BriefHeading {
  text: string;
  type?: string;
  level: string; // H1 | H2 | H3
  order: number;
  parent_h2_text?: string | null;
  source?: string | null;
  exempt?: boolean;
  parent_relevance?: number | null;
  format_directive?: Record<string, unknown> | null;
}
export interface BriefFaq {
  question: string;
  answer?: string | null;
}
export interface BriefReport {
  schema_version: string;
  keyword: string;
  h1: string;
  title: string;
  scope_statement?: string | null;
  intent_type?: string | null;
  intent_confidence?: number | null;
  intent_review_required?: boolean;
  format_directives?: Record<string, unknown>;
  heading_structure: BriefHeading[];
  faqs: BriefFaq[];
  discarded_headings?: unknown[];
  metadata?: Record<string, unknown>;
}
export interface BriefResponse {
  status: "complete" | "running";
  keyword: string;
  brief?: BriefReport;
}

export const startBrief = (
  sessionId: string,
  clusterId: string,
  body?: { force_refresh?: boolean },
) =>
  request<BriefResponse>(`/sessions/${sessionId}/clusters/${clusterId}/brief`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });

export const getBrief = (sessionId: string, clusterId: string) =>
  request<BriefResponse>(`/sessions/${sessionId}/clusters/${clusterId}/brief`);

// ----- M14 Content Writer (article generation) — owner-only -----------------
export interface ArticleOutput {
  keyword: string;
  intent_type: string;
  title: string;
  article_markdown: string;
  article_html: string;
  key_takeaways: string[];
  metadata: Record<string, unknown>;
}
export interface ArticleResponse {
  status: "complete" | "running";
  keyword: string;
  article?: ArticleOutput;
}

export const startArticle = (
  sessionId: string,
  clusterId: string,
  body?: { force_refresh?: boolean },
) =>
  request<ArticleResponse>(
    `/sessions/${sessionId}/clusters/${clusterId}/generate-article`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );

export const getArticle = (sessionId: string, clusterId: string) =>
  request<ArticleResponse>(`/sessions/${sessionId}/clusters/${clusterId}/article`);

export interface ArticleListItem {
  cluster_id: string;
  name: string;
  total_word_count: number | null;
  cost_usd: number | null;
  generated_at: string | null;
  scheduled: boolean;
}
export const listArticles = (sessionId: string) =>
  request<{ articles: ArticleListItem[]; count: number }>(`/sessions/${sessionId}/articles`);
export const downloadAllArticles = (sessionId: string) =>
  request<{ download_url: string; count: number }>(
    `/sessions/${sessionId}/articles/download-all`, { method: "POST" });

export interface PublishConfig {
  github_repo?: string;
  github_branch?: string;
  github_content_path?: string;
  drive_folder_id?: string;
}
export const setPublishConfig = (sessionId: string, cfg: PublishConfig) =>
  request<{ publish_config: Record<string, unknown> }>(
    `/sessions/${sessionId}/publish-config`,
    { method: "PATCH", body: JSON.stringify(cfg) });
export const publishClusterGithub = (sessionId: string, clusterId: string) =>
  request<{ published: boolean; path: string; html_url: string | null }>(
    `/sessions/${sessionId}/clusters/${clusterId}/publish/github`, { method: "POST" });
export const publishAllGithub = (sessionId: string) =>
  request<{ published: boolean; committed: number; commit_sha: string | null }>(
    `/sessions/${sessionId}/publish/github`, { method: "POST" });
export const publishClusterDrive = (sessionId: string, clusterId: string) =>
  request<{ published: boolean; doc_id: string; url: string | null }>(
    `/sessions/${sessionId}/clusters/${clusterId}/publish/drive`, { method: "POST" });

export interface BulkGenerateResponse {
  submitted: string[];
  skipped: string[];
  count: number;
}
export const generateArticles = (sessionId: string, clusterIds: string[]) =>
  request<BulkGenerateResponse>(`/sessions/${sessionId}/generate-articles`, {
    method: "POST",
    body: JSON.stringify({ cluster_ids: clusterIds }),
  });

export interface SplitUncoveredResponse {
  created: { cluster_id: string; name: string; keywords: string[]; submitted: boolean }[];
  submitted: number;
  uncovered: number;
}
export const splitUncovered = (sessionId: string, clusterId: string) =>
  request<SplitUncoveredResponse>(
    `/sessions/${sessionId}/clusters/${clusterId}/split-uncovered`,
    { method: "POST" },
  );

// ----- M15 content scheduling -----------------------------------------------

export interface ScheduleRequest {
  mode: "all_at_once" | "drip" | "fixed";
  cluster_ids?: string[];          // omit/[] -> whole session
  per_day?: number;                // drip
  start_date?: string;             // YYYY-MM-DD — drip start / fixed target day
  time_of_day?: string;            // HH:MM
  timezone?: string;
  site_base_url?: string;
}
export interface ScheduleEstimate {
  count: number;
  cost_estimate_usd: number;
  mode: string;
  days?: number;
  finish_date?: string;
  already_scheduled: number;
  requires_approval: boolean;
  approval_threshold_usd: number;
}
export interface ContentSchedule {
  id: string;
  session_id: string;
  mode: string;
  per_day: number | null;
  start_date: string | null;
  time_of_day: string;
  timezone: string;
  status: "active" | "paused" | "complete" | "cancelled";
  total_count: number;
  created_at: string;
  progress?: Record<string, number>;
}
export interface ScheduledRun {
  id: string;
  content_schedule_id: string | null;
  cluster_id: string;
  scheduled_at: string;
  status: "queued" | "running" | "complete" | "failed" | "cancelled";
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}
export interface CreateScheduleResponse {
  status: "scheduled" | "requires_approval";
  created: boolean;
  schedule?: ContentSchedule;
  scheduled?: number;
  skipped?: number;
  estimate: ScheduleEstimate;
  approval_threshold_usd?: number;
}

export const scheduleEstimate = (sessionId: string, body: ScheduleRequest) =>
  request<ScheduleEstimate>(`/sessions/${sessionId}/schedule-estimate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const createSchedule = (sessionId: string, body: ScheduleRequest) =>
  request<CreateScheduleResponse>(`/sessions/${sessionId}/schedule`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const listSchedules = (sessionId: string) =>
  request<{ schedules: ContentSchedule[] }>(`/sessions/${sessionId}/schedules`);
export const listScheduleRuns = (sessionId: string) =>
  request<{ runs: ScheduledRun[] }>(`/sessions/${sessionId}/schedule-runs`);
export const pauseSchedule = (sessionId: string, scheduleId: string) =>
  request<{ status: string }>(`/sessions/${sessionId}/schedules/${scheduleId}/pause`, { method: "POST" });
export const resumeSchedule = (sessionId: string, scheduleId: string) =>
  request<{ status: string }>(`/sessions/${sessionId}/schedules/${scheduleId}/resume`, { method: "POST" });
export const cancelSchedule = (sessionId: string, scheduleId: string) =>
  request<{ status: string; cancelled_runs: number }>(
    `/sessions/${sessionId}/schedules/${scheduleId}/cancel`, { method: "POST" });
