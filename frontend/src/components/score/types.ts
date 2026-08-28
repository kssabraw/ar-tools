import type { EntityProvider } from '../EntityProviderSelect'
import type { ScoreResult } from '../localseo/types'

// Shared "Score only" panel contract. Each writer tool supplies an adapter that
// knows how to start a run-free score job for one page and poll it to a
// ScoreResult — the panel owns the input form + rendering. Unlike the reoptimize
// flow, nothing is rewritten: this is a check (composite + engines + entity
// usage/gaps), full stop.

export interface ScoreJobPoll {
  status: 'pending' | 'running' | 'complete' | 'failed' | 'cancelled'
  result?: ScoreResult | null
  error?: string | null
}

export interface ScoreTarget {
  keyword: string
  url?: string | null
  html?: string | null
  location?: string | null
  locationCode?: number | null
  pageType?: string
  entityProvider?: EntityProvider
}

export interface ScorePageTypeOption {
  id: string
  label: string
}

export interface ScoreAdapter {
  toolLabel: string
  clientId: string
  // localStorage prefix for the resumable score job (the panel appends a per-run key).
  storageKeyBase: string
  // Ordered engine key → label map for the breakdown (engines absent from a
  // result are skipped, so a national scorer that drops geo engines still renders).
  engineLabels: Record<string, string>
  itemNoun?: string
  requiresKeyword?: boolean
  keywordLabel?: string
  keywordPlaceholder?: string
  supportsLocation?: boolean
  // When true the area field is required to run (Local SEO scores geo-anchored);
  // when only supportsLocation is set, the field is shown but optional (Service).
  requiresLocation?: boolean
  supportsPaste?: boolean
  supportsEntityProvider?: boolean
  ownsPageTypeSwitch?: boolean
  pageTypeOptions?: ScorePageTypeOption[]
  defaultPageType?: string
  introText?: string
  // Enqueue a score for one page; returns the job id.
  start(target: ScoreTarget): Promise<string>
  // Poll a score job; on completion `result` carries the ScoreResult.
  poll(jobId: string): Promise<ScoreJobPoll>
}
