import type { ReactNode } from 'react'

// ── Shared reoptimization types ─────────────────────────────────────────────
//
// One shared Reoptimize component (ReoptimizePanel) drives all four content
// tools (Local SEO / Ecommerce / Service pages / Blog). Each tool supplies a
// ReoptAdapter that wires the panel's generic start/poll to that tool's real
// endpoints — some are job-based (Local SEO / Ecommerce reoptimizeBulk +
// jobsStatus → a ReoptimizeUrlResult per job), others spawn full suite runs
// (Blog / Service reoptimize-bulk → one run per item, polled via /runs/{id}).
// The adapter hides that difference behind the ReoptHandle union.

// The three input modes the panel offers (the adapter opts into each).
export type ReoptInputMode = 'url' | 'paste' | 'existing'

// One reoptimization target, ready to dispatch. A target is either a live URL
// (`url`), pasted rich content (`html`), or an existing item picked from a list
// (carries `url`). `keyword` is the target term; `location`/`locationCode` apply
// only to location-scoped tools (Local SEO); `pageType` lets a discovered item
// carry its own product/collection classification.
export interface ReoptItem {
  keyword: string
  url?: string | null
  html?: string | null
  location?: string | null
  locationCode?: number | null
  pageType?: string | null
  // Original textarea line / display label (for invalid-line warnings + rows).
  raw?: string
  label?: string
}

// A dispatched unit of work the panel polls to completion. `job` — a background
// async_jobs row (Local SEO / Ecommerce; poll the tool's jobs/status endpoint).
// `run` — a spawned suite run (Blog / Service; poll /runs/{id}). `skipped` — a
// unit the backend refused to start (surfaced immediately as terminal, never
// polled). `id` is the stable key the panel uses for persistence + row matching.
export type ReoptHandle =
  | { kind: 'job'; id: string; jobId: string; label: string }
  | { kind: 'run'; id: string; runId: string; label: string }
  | { kind: 'skipped'; id: string; label: string; reason: string }

// Per-unit outcome the panel renders. `done` = reoptimized; `skipped` = strong
// enough to skip (with a reason); `queued`/`working` are in-flight; `detached` =
// left to finish in the background; `failed` carries a reason.
export type ReoptResultStatus =
  | 'queued'
  | 'working'
  | 'done'
  | 'skipped'
  | 'failed'
  | 'detached'

export interface ReoptResult {
  // Matches the originating handle's id.
  id: string
  label: string
  status: ReoptResultStatus
  // Job / score results (before → after composite):
  prevScore?: number | null
  newScore?: number | null
  // Skipped / failed reason:
  reason?: string | null
  // Publish outcome (job-based tools that publish to a Google Doc):
  docUrl?: string | null
  publishError?: string | null
  // Run-based results link back to the spawned run.
  runId?: string | null
}

// Options gathered from the panel's shared controls, passed to `start`.
export interface ReoptStartOpts {
  // Destination id chosen from `adapter.destinations` (e.g. 'app' | 'doc').
  destination?: string
  // Publish each reoptimized page to a Google Doc (checkbox variant).
  publishToDoc?: boolean
  // Free-text writer guidance applied to every item.
  notes?: string | null
  // The active page type (product/collection or service_page/location_page).
  pageType?: string
  // Entity-extraction engine for the nlp SERP analysis ("textrazor"|"google").
  // Only set by adapters that opt in via `supportsEntityProvider`.
  entityProvider?: string | null
}

// A radio-style destination choice (Local SEO's "where should pages go?").
export interface ReoptDestination {
  id: string
  title: string
  subtitle: string
  icon?: ReactNode
  // Rendered but non-selectable (e.g. "GitHub — coming soon").
  disabled?: boolean
}

// One page surfaced by a "pick an existing item" list (the `existing` mode).
export interface ReoptExistingItem {
  id: string
  label: string
  url?: string | null
  keyword?: string | null
}

// One page surfaced by a "discover from site" scan (Ecommerce).
export interface ReoptDiscoverItem {
  url: string
  label: string
  pageType?: string
}

// The tool-specific contract the shared panel is driven by. Capability flags
// (supports*) decide which controls render; the async fns wire the panel's
// generic lifecycle to the tool's real endpoints.
export interface ReoptAdapter {
  // Identity / copy.
  toolLabel: string
  // Unique per tool+client(+pageType) — the useResumableBatch persistence key.
  storageKey: string
  // Needed by LocationAutocomplete (location-scoped tools).
  clientId: string
  introText?: string
  scoreThreshold?: number
  // Noun for one target in the UI copy ('page' default; 'article' for blog).
  itemNoun?: string

  // ── Input-mode capabilities ──
  supportsUrl: boolean
  supportsPaste: boolean
  supportsExisting: boolean
  supportsDiscover?: boolean
  // Local SEO's single-URL vs multiple-URLs sub-toggle within URL mode.
  urlSingleToggle?: boolean

  // ── Shared keyword field ──
  requiresKeyword?: boolean
  keywordLabel?: string
  keywordPlaceholder?: string
  keywordOptionalHint?: string

  // ── Location (Local SEO) ──
  supportsLocation?: boolean

  // ── Page type ──
  // When true the panel renders its own product/collection or
  // service_page/location_page switch (Service). Ecommerce instead has its
  // switch in the parent page and passes `pageType` down as a prop.
  ownsPageTypeSwitch?: boolean
  pageTypeOptions?: Array<{ id: string; label: string }>
  defaultPageType?: string

  // ── Notes ──
  supportsNotes?: boolean
  notesLabel?: string
  notesPlaceholder?: string

  // ── Entity engine ──
  // When true the panel renders the TextRazor/Google NLP selector and threads the
  // choice into `start`'s opts.entityProvider. Only Local SEO + Ecommerce set it.
  supportsEntityProvider?: boolean

  // ── Destination ──
  destinations?: ReoptDestination[]
  supportsPublishToDoc?: boolean
  publishToDocLabel?: string

  // ── Completion linkback ──
  onOpenSaved?: () => void
  savedLinkLabel?: string
  // Base path for a run-kind "View run" link (e.g. '/runs').
  runLinkBase?: string
  // What a finished run-kind result did (shown in the summary line).
  runVerb?: string

  // ── Lifecycle ──
  start(items: ReoptItem[], opts: ReoptStartOpts): Promise<ReoptHandle[]>
  poll(handles: ReoptHandle[]): Promise<ReoptResult[]>
  cancel?(handles: ReoptHandle[]): Promise<void>
  discover?(pageType?: string): Promise<{ items: ReoptDiscoverItem[]; note?: string | null }>
  listExisting?(): Promise<ReoptExistingItem[]>
}
