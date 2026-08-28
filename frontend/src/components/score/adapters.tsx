import { localSeoApi } from '../localseo/api'
import { ecommerceApi } from '../ecommerce/api'
import type { EcommercePageType } from '../ecommerce/types'
import type { ScoreResult } from '../localseo/types'
import { scoreApi } from './api'
import type { ScoreAdapter, ScoreJobPoll } from './types'

// The four tool adapters that drive the shared ScorePanel. Local SEO + Ecommerce
// reuse their existing run-free score jobs (polled via jobsStatus); Blog +
// Service use the new /score-existing job (polled via scoreApi.getJob). Every
// tool threads the entity engine, so the Google-NLP entity check works uniformly.

const LOCALSEO_ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  gbp_maps: 'GBP / Maps Relevance',
  entity_establishment: 'Entity Establishment',
  icp_alignment: 'ICP Alignment',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  geographic_legitimacy: 'Geographic Legitimacy',
  nearme_intent: 'Hyperlocal / Near-Me',
  serp_signal_coverage: 'SERP Signal Coverage',
  length_fit: 'Length Fit (SERP avg +20%)',
}

const ECOMMERCE_ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  commercial_intent: 'Commercial Intent',
  product_content_depth: 'Product Content Depth',
  entity_establishment: 'Entity Establishment',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  conversion_readiness: 'Conversion Readiness',
  structured_data: 'Structured Data (Schema)',
  serp_signal_coverage: 'SERP Signal Coverage',
}

const BLOG_ENGINE_LABELS: Record<string, string> = {
  organic_ranking: 'Organic Ranking',
  aeo_llm_retrieval: 'AEO / LLM Retrieval',
  content_depth: 'Content Depth',
  entity_topic_coverage: 'Entity & Topic Coverage',
  eeat_citations: 'E-E-A-T & Citations',
  icp_alignment: 'ICP Alignment',
  structural_aeo: 'Structural AEO',
  serp_signal_coverage: 'SERP Signal Coverage',
}

// jobsStatus (Local SEO / Ecommerce) → ScoreJobPoll.
function jobStatusToPoll(st: { status: string; result?: Record<string, unknown> | null; error?: string | null } | undefined): ScoreJobPoll {
  if (!st) return { status: 'running' }
  return {
    status: st.status as ScoreJobPoll['status'],
    result: (st.result as ScoreResult | null) ?? null,
    error: st.error ?? null,
  }
}

// ── Local SEO ────────────────────────────────────────────────────────────────
export function localSeoScoreAdapter(clientId: string): ScoreAdapter {
  return {
    toolLabel: 'Local SEO',
    clientId,
    storageKeyBase: `score:localseo:${clientId}`,
    engineLabels: LOCALSEO_ENGINE_LABELS,
    itemNoun: 'page',
    requiresKeyword: true,
    keywordLabel: 'Service',
    keywordPlaceholder: 'e.g. emergency plumber',
    supportsLocation: true,
    requiresLocation: true,
    supportsEntityProvider: true,
    async start(t) {
      const { job_id } = await localSeoApi.score(clientId, {
        keyword: t.keyword,
        location: t.location ?? '',
        page_url: t.url ?? null,
        page_content: t.html ?? null,
        entity_provider: t.entityProvider ?? null,
      })
      return job_id
    },
    async poll(jobId) {
      const [st] = await localSeoApi.jobsStatus(clientId, [jobId])
      return jobStatusToPoll(st)
    },
  }
}

// ── Ecommerce ────────────────────────────────────────────────────────────────
export function ecommerceScoreAdapter(clientId: string): ScoreAdapter {
  return {
    toolLabel: 'Ecommerce',
    clientId,
    storageKeyBase: `score:ecommerce:${clientId}`,
    engineLabels: ECOMMERCE_ENGINE_LABELS,
    itemNoun: 'product',
    requiresKeyword: true,
    keywordLabel: 'Target keyword',
    keywordPlaceholder: 'e.g. wireless noise-cancelling headphones',
    supportsEntityProvider: true,
    ownsPageTypeSwitch: true,
    pageTypeOptions: [
      { id: 'product', label: 'Product' },
      { id: 'collection', label: 'Collection' },
    ],
    defaultPageType: 'product',
    async start(t) {
      const { job_id } = await ecommerceApi.score(clientId, {
        keyword: t.keyword,
        page_type: (t.pageType ?? 'product') as EcommercePageType,
        page_url: t.url ?? null,
        page_content: t.html ?? null,
        entity_provider: t.entityProvider ?? null,
      })
      return job_id
    },
    async poll(jobId) {
      const [st] = await ecommerceApi.jobsStatus(clientId, [jobId])
      return jobStatusToPoll(st)
    },
  }
}

// ── Service / Location pages ─────────────────────────────────────────────────
export function serviceScoreAdapter(clientId: string): ScoreAdapter {
  return {
    toolLabel: 'Service pages',
    clientId,
    storageKeyBase: `score:service:${clientId}`,
    engineLabels: LOCALSEO_ENGINE_LABELS,
    itemNoun: 'page',
    requiresKeyword: true,
    keywordLabel: 'Keyword',
    keywordPlaceholder: 'e.g. emergency plumber',
    supportsPaste: true,
    supportsLocation: true, // shown; only needed for location pages (scored local)
    supportsEntityProvider: true,
    ownsPageTypeSwitch: true,
    pageTypeOptions: [
      { id: 'service_page', label: 'Service page' },
      { id: 'location_page', label: 'Location page' },
    ],
    defaultPageType: 'service_page',
    introText: 'Point at a live service or location page (or paste its content) and check it against the engines — service pages score national, location pages score against the area. Nothing is rewritten.',
    async start(t) {
      const { job_id } = await scoreApi.serviceScoreExisting(clientId, {
        keyword: t.keyword,
        page_type: t.pageType === 'location_page' ? 'location_page' : 'service_page',
        page_url: t.url ?? null,
        page_content: t.html ?? null,
        location: t.location ?? null,
        location_code: t.locationCode ?? null,
        entity_provider: t.entityProvider ?? null,
      })
      return job_id
    },
    async poll(jobId) {
      const st = await scoreApi.getJob(clientId, jobId)
      return { status: st.status as ScoreJobPoll['status'], result: st.result ?? null, error: st.error ?? null }
    },
  }
}

// ── Blog ─────────────────────────────────────────────────────────────────────
export function blogScoreAdapter(clientId: string): ScoreAdapter {
  return {
    toolLabel: 'Blog',
    clientId,
    storageKeyBase: `score:blog:${clientId}`,
    engineLabels: BLOG_ENGINE_LABELS,
    itemNoun: 'article',
    requiresKeyword: true,
    keywordLabel: 'Keyword',
    keywordPlaceholder: 'e.g. best hvac systems 2026',
    supportsPaste: true,
    supportsEntityProvider: true,
    introText: 'Point at a live article (or paste its content) and check it against the blog/AEO engines — composite score, per-engine breakdown, and entity usage & gaps. Nothing is rewritten.',
    async start(t) {
      const { job_id } = await scoreApi.blogScoreExisting(clientId, {
        keyword: t.keyword,
        page_url: t.url ?? null,
        page_content: t.html ?? null,
        entity_provider: t.entityProvider ?? null,
      })
      return job_id
    },
    async poll(jobId) {
      const st = await scoreApi.getJob(clientId, jobId)
      return { status: st.status as ScoreJobPoll['status'], result: st.result ?? null, error: st.error ?? null }
    },
  }
}
