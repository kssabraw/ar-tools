-- SED Local Search Intelligence Platform
-- Physical Supabase/Postgres Schema Contract v0.1
-- Generated 2026-09-09
--
-- PURPOSE
--   Translate the approved conceptual architecture into a physical PostgreSQL schema
--   while preserving immutable raw evidence, separate/versioned entity resolution,
--   shared cross-surface entities/signals, temporal enrichment, attributable costs,
--   and reproducible derived research data.
--
-- IMPORTANT
--   This migration does NOT define product-facing RLS/auth policies.
--   Keep research schemas private from anon/authenticated roles until a separate
--   application security contract is approved.

begin;

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;
create extension if not exists vector;

create schema if not exists manifest;
create schema if not exists ops;
create schema if not exists core;
create schema if not exists maps;
create schema if not exists organic;
create schema if not exists aio;
create schema if not exists chatgpt;
create schema if not exists enrichment;
create schema if not exists research;
create schema if not exists client;

-- ============================================================================
-- ENUMS / CONTROLLED STATES
-- ============================================================================

create type manifest.version_status as enum ('draft','frozen','retired');
create type manifest.treatment_kind as enum ('query','prompt');
create type manifest.coordinate_eligibility as enum (
  'pending',
  'eligible_land',
  'structural_water_exclusion',
  'manual_review',
  'configuration_failure'
);

create type ops.wave_kind as enum ('full_panel','sentinel','pilot','validation','ad_hoc');
create type ops.wave_status as enum ('planned','running','complete','partial','failed','quarantined','cancelled');
create type ops.job_status as enum (
  'planned',
  'blocked_structural',
  'queued',
  'submitted',
  'succeeded',
  'retryable_failure',
  'terminal_failure',
  'quarantined',
  'skipped'
);
create type ops.attempt_event_type as enum (
  'submitted',
  'provider_acknowledged',
  'poll',
  'response_received',
  'retryable_failure',
  'terminal_failure',
  'succeeded',
  'cancelled'
);
create type ops.payload_kind as enum (
  'request',
  'task_post_response',
  'task_get_response',
  'rendered_response',
  'screenshot',
  'other'
);
create type ops.observation_state as enum (
  'returned',
  'terminal_error',
  'provider_failure',
  'parser_failure',
  'refusal',
  'clarification_requested',
  'generic_guidance_only',
  'no_local_recommendations',
  'other'
);

create type core.resolution_state as enum (
  'resolved',
  'probable_match',
  'ambiguous',
  'unresolved',
  'likely_nonexistent',
  'insufficient_information'
);
create type core.assertion_action as enum ('assert','retract');

create type enrichment.freshness_state as enum ('fresh','stale','unknown','not_applicable');
create type enrichment.request_status as enum ('planned','skipped_fresh','queued','running','succeeded','failed','quarantined');

create type research.build_status as enum ('planned','running','complete','failed','quarantined','superseded');
create type research.finding_status as enum ('draft','active','superseded','retired');

create type client.recommendation_state as enum (
  'TEST',
  'MONITOR',
  'LEAVE_ALONE',
  'insufficient_evidence',
  'ineligible'
);

-- ============================================================================
-- SHARED PROVIDER / COMPONENT VERSION REGISTRIES
-- ============================================================================

create table ops.provider (
  provider_id uuid primary key default gen_random_uuid(),
  provider_code text not null unique,
  provider_name text not null,
  provider_kind text not null,
  homepage_url text,
  created_at timestamptz not null default now()
);

create table ops.provider_price_version (
  provider_price_version_id uuid primary key default gen_random_uuid(),
  provider_id uuid not null references ops.provider(provider_id),
  price_code text not null,
  endpoint_or_product text,
  billing_unit text not null,
  unit_amount_microusd bigint not null check (unit_amount_microusd >= 0),
  currency char(3) not null default 'USD',
  effective_from timestamptz not null,
  effective_to timestamptz,
  source_url text,
  source_observed_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (provider_id, price_code, effective_from)
);

create table ops.component_version (
  component_version_id uuid primary key default gen_random_uuid(),
  component_kind text not null check (component_kind in (
    'collector','parser','resolver','classifier','embedder','llm','sql','analysis_code','job_generator','other'
  )),
  component_name text not null,
  version_code text not null,
  git_sha text,
  config_sha256 char(64),
  artifact_uri text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (component_kind, component_name, version_code)
);

-- ============================================================================
-- MANIFEST: VERSIONED ANSWER TO "WHAT EXACTLY DO WE RUN?"
-- ============================================================================

create table manifest.methodology_version (
  methodology_version_id uuid primary key default gen_random_uuid(),
  methodology_code text not null unique,
  status manifest.version_status not null default 'draft',
  effective_from timestamptz,
  effective_to timestamptz,
  parent_methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  manifest_sha256 char(64),
  manifest_artifact_uri text,
  governing_handoff_drive_id text,
  governing_parent_prd_drive_id text,
  notes text,
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  check ((status <> 'frozen') or frozen_at is not null)
);

create table manifest.surface (
  surface_id uuid primary key default gen_random_uuid(),
  surface_code text not null unique,
  surface_name text not null,
  is_primary_observation_surface boolean not null default true,
  created_at timestamptz not null default now()
);

create table manifest.industry (
  industry_id uuid primary key default gen_random_uuid(),
  industry_code text not null unique,
  industry_name text not null,
  canonical_service_term text not null,
  vertical_group text,
  created_at timestamptz not null default now()
);

create table manifest.market (
  market_id uuid primary key default gen_random_uuid(),
  market_code text not null unique,
  city text not null,
  state_region text not null,
  country_code char(2) not null default 'US',
  census_place_geoid text,
  center_lat numeric(10,7),
  center_lon numeric(10,7),
  center_source text,
  center_method_version text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (center_lat is null or center_lat between -90 and 90),
  check (center_lon is null or center_lon between -180 and 180)
);

create table manifest.methodology_industry (
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  industry_id uuid not null references manifest.industry(industry_id),
  ordinal smallint not null,
  registry_status text not null default 'approved',
  approval_basis text,
  primary key (methodology_version_id, industry_id),
  unique (methodology_version_id, ordinal)
);

create table manifest.methodology_market (
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  market_id uuid not null references manifest.market(market_id),
  ordinal smallint not null,
  registry_status text not null default 'approved',
  approval_basis text,
  primary key (methodology_version_id, market_id),
  unique (methodology_version_id, ordinal)
);

create table manifest.geometry_version (
  geometry_version_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  geometry_code text not null,
  geometry_name text not null,
  surface_group text not null,
  coordinate_crs text not null default 'EPSG:4326',
  coordinate_precision smallint not null default 7 check (coordinate_precision between 0 and 9),
  generation_method text not null,
  water_mask_version text,
  status manifest.version_status not null default 'draft',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, geometry_code)
);

create table manifest.geometry_point (
  geometry_point_id uuid primary key default gen_random_uuid(),
  geometry_version_id uuid not null references manifest.geometry_version(geometry_version_id),
  point_code text not null,
  point_label text not null,
  bearing_deg numeric(6,2),
  distance_miles numeric(8,3) not null default 0 check (distance_miles >= 0),
  full_geometry_member boolean not null default true,
  nested_candidate_member boolean not null default false,
  incremental_member boolean not null default false,
  ordinal smallint not null,
  metadata jsonb not null default '{}'::jsonb,
  unique (geometry_version_id, point_code),
  unique (geometry_version_id, ordinal),
  check (
    (distance_miles = 0 and bearing_deg is null)
    or
    (distance_miles > 0 and bearing_deg between 0 and 360)
  )
);

create table manifest.market_coordinate (
  coordinate_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  market_id uuid not null references manifest.market(market_id),
  geometry_point_id uuid not null references manifest.geometry_point(geometry_point_id),
  latitude numeric(10,7) not null check (latitude between -90 and 90),
  longitude numeric(10,7) not null check (longitude between -180 and 180),
  eligibility manifest.coordinate_eligibility not null default 'pending',
  structural_exclusion_reason text,
  water_feature_name text,
  water_feature_mtfcc text,
  water_feature_id text,
  water_mask_source text,
  water_mask_version text,
  eligibility_decided_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, market_id, geometry_point_id),
  check (
    (eligibility in ('structural_water_exclusion','configuration_failure') and structural_exclusion_reason is not null)
    or eligibility not in ('structural_water_exclusion','configuration_failure')
  )
);

create table manifest.treatment (
  treatment_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  industry_id uuid not null references manifest.industry(industry_id),
  treatment_set_code text not null,
  treatment_code text not null,
  treatment_kind manifest.treatment_kind not null,
  family text,
  core_query_class text,
  exact_template text not null,
  sequence smallint not null,
  city_slot_required boolean not null default false,
  is_locked boolean not null default false,
  approval_basis text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, industry_id, treatment_set_code, treatment_code),
  unique (methodology_version_id, industry_id, treatment_set_code, sequence)
);

create table manifest.surface_treatment (
  surface_treatment_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  treatment_id uuid not null references manifest.treatment(treatment_id),
  sequence smallint not null,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  unique (methodology_version_id, surface_id, treatment_id),
  unique (methodology_version_id, surface_id, sequence)
);

create table manifest.provider_profile (
  provider_profile_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  provider_id uuid not null references ops.provider(provider_id),
  profile_code text not null,
  method text not null,
  post_endpoint text,
  get_endpoint text,
  language_code text,
  device text,
  operating_system text,
  location_mode text,
  location_template text,
  result_depth integer,
  priority smallint,
  max_tasks_per_post integer,
  settings jsonb not null default '{}'::jsonb,
  settings_sha256 char(64),
  created_at timestamptz not null default now(),
  unique (methodology_version_id, profile_code)
);

create table manifest.surface_config (
  surface_config_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  provider_profile_id uuid not null references manifest.provider_profile(provider_profile_id),
  geometry_version_id uuid references manifest.geometry_version(geometry_version_id),
  full_panel_cadence text not null,
  sentinel_cadence text not null,
  replicates smallint not null default 1 check (replicates >= 1),
  result_depth integer,
  raw_response_required boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  unique (methodology_version_id, surface_id)
);

create table manifest.panel_subset (
  panel_subset_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  subset_code text not null,
  subset_kind text not null,
  fixed_membership boolean not null default true,
  description text,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, subset_code)
);

create table manifest.panel_subset_industry (
  panel_subset_id uuid not null references manifest.panel_subset(panel_subset_id) on delete cascade,
  industry_id uuid not null references manifest.industry(industry_id),
  ordinal smallint,
  primary key (panel_subset_id, industry_id)
);

create table manifest.panel_subset_market (
  panel_subset_id uuid not null references manifest.panel_subset(panel_subset_id) on delete cascade,
  market_id uuid not null references manifest.market(market_id),
  ordinal smallint,
  primary key (panel_subset_id, market_id)
);

-- ============================================================================
-- CORE CANONICAL ENTITY GRAPH
-- ============================================================================

create table core.entity_type (
  entity_type_code text primary key,
  description text not null
);

create table core.entity (
  entity_id uuid primary key default gen_random_uuid(),
  entity_type_code text not null references core.entity_type(entity_type_code),
  operational_label text,
  lifecycle_state text not null default 'active' check (lifecycle_state in ('active','retired','merged','unknown')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table core.organization (
  entity_id uuid primary key references core.entity(entity_id),
  organization_kind text,
  metadata jsonb not null default '{}'::jsonb
);

create table core.brand (
  entity_id uuid primary key references core.entity(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.business_location (
  entity_id uuid primary key references core.entity(entity_id),
  preferred_analysis_grain boolean not null default true,
  metadata jsonb not null default '{}'::jsonb
);

create table core.google_business_profile (
  entity_id uuid primary key references core.entity(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.web_domain (
  entity_id uuid primary key references core.entity(entity_id),
  normalized_domain text not null unique,
  registered_domain text,
  metadata jsonb not null default '{}'::jsonb
);

create table core.web_url (
  entity_id uuid primary key references core.entity(entity_id),
  normalized_url text not null unique,
  domain_entity_id uuid references core.web_domain(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.profile_entity (
  entity_id uuid primary key references core.entity(entity_id),
  profile_kind text not null,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.source_asset (
  entity_id uuid primary key references core.entity(entity_id),
  source_kind text not null,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.relationship_type (
  relationship_type_code text primary key,
  description text not null
);

-- ============================================================================
-- OPS: WAVES, JOBS, RAW BLOBS, ATTEMPTS, OBSERVATIONS, COSTS
-- ============================================================================

create table ops.collection_wave (
  wave_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  panel_subset_id uuid references manifest.panel_subset(panel_subset_id),
  wave_code text not null unique,
  wave_kind ops.wave_kind not null,
  scheduled_for timestamptz not null,
  collection_window_start timestamptz,
  collection_window_end timestamptz,
  parent_wave_id uuid references ops.collection_wave(wave_id),
  notes text,
  created_at timestamptz not null default now()
);

create table ops.wave_event (
  wave_event_id uuid primary key default gen_random_uuid(),
  wave_id uuid not null references ops.collection_wave(wave_id),
  status ops.wave_status not null,
  event_at timestamptz not null default now(),
  actor text,
  details jsonb not null default '{}'::jsonb
);

create table ops.collection_job (
  job_id uuid primary key default gen_random_uuid(),
  job_key char(64) not null unique,
  wave_id uuid not null references ops.collection_wave(wave_id),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  industry_id uuid not null references manifest.industry(industry_id),
  market_id uuid not null references manifest.market(market_id),
  surface_treatment_id uuid not null references manifest.surface_treatment(surface_treatment_id),
  coordinate_id uuid references manifest.market_coordinate(coordinate_id),
  provider_profile_id uuid not null references manifest.provider_profile(provider_profile_id),
  replicate_no smallint not null default 1 check (replicate_no >= 1 and replicate_no <= 99),
  rendered_input_text text not null,
  rendered_request jsonb not null,
  rendered_request_sha256 char(64) not null,
  planned_eligibility manifest.coordinate_eligibility,
  generated_by_component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now()
);

create table ops.job_event (
  job_event_id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ops.collection_job(job_id),
  status ops.job_status not null,
  event_at timestamptz not null default now(),
  attempt_no integer,
  actor text,
  reason_code text,
  details jsonb not null default '{}'::jsonb
);

create table ops.raw_blob (
  blob_id uuid primary key default gen_random_uuid(),
  sha256 char(64) not null unique,
  storage_bucket text not null,
  storage_path text not null,
  byte_size bigint not null check (byte_size >= 0),
  mime_type text not null,
  content_encoding text,
  created_at timestamptz not null default now(),
  unique (storage_bucket, storage_path)
);

create table ops.provider_payload (
  payload_id uuid primary key default gen_random_uuid(),
  provider_id uuid not null references ops.provider(provider_id),
  blob_id uuid not null references ops.raw_blob(blob_id),
  payload_kind ops.payload_kind not null,
  provider_task_id text,
  captured_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table ops.collection_attempt (
  attempt_id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ops.collection_job(job_id),
  attempt_no integer not null check (attempt_no >= 1),
  provider_id uuid not null references ops.provider(provider_id),
  provider_task_id text,
  request_payload_id uuid references ops.provider_payload(payload_id),
  submitted_at timestamptz not null,
  collector_component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (job_id, attempt_no),
  unique (attempt_id, job_id)
);

create table ops.collection_attempt_event (
  attempt_event_id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references ops.collection_attempt(attempt_id),
  event_type ops.attempt_event_type not null,
  event_at timestamptz not null default now(),
  response_payload_id uuid references ops.provider_payload(payload_id),
  provider_status_code text,
  error_code text,
  details jsonb not null default '{}'::jsonb
);

create table ops.observation (
  observation_id uuid primary key default gen_random_uuid(),
  job_id uuid not null unique references ops.collection_job(job_id),
  accepted_attempt_id uuid references ops.collection_attempt(attempt_id),
  observation_state ops.observation_state not null,
  observed_at timestamptz not null,
  received_at timestamptz,
  raw_payload_id uuid references ops.provider_payload(payload_id),
  parser_version_id uuid references ops.component_version(component_version_id),
  normalized_output_sha256 char(64),
  parser_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint observation_attempt_same_job_fk
    foreign key (accepted_attempt_id, job_id)
    references ops.collection_attempt(attempt_id, job_id)
);

create table ops.cost_event (
  cost_event_id uuid primary key default gen_random_uuid(),
  provider_id uuid references ops.provider(provider_id),
  provider_price_version_id uuid references ops.provider_price_version(provider_price_version_id),
  wave_id uuid references ops.collection_wave(wave_id),
  job_id uuid references ops.collection_job(job_id),
  attempt_id uuid references ops.collection_attempt(attempt_id),
  economic_unit_entity_id uuid references core.entity(entity_id),
  purpose text not null,
  billing_unit text,
  billed_units numeric(20,6),
  amount_microusd bigint not null check (amount_microusd >= 0),
  currency char(3) not null default 'USD',
  provider_reference text,
  occurred_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table ops.cost_allocation (
  cost_allocation_id uuid primary key default gen_random_uuid(),
  cost_event_id uuid not null references ops.cost_event(cost_event_id),
  job_id uuid references ops.collection_job(job_id),
  entity_id uuid references core.entity(entity_id),
  allocation_microusd bigint not null check (allocation_microusd >= 0),
  allocation_basis text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (job_id is not null or entity_id is not null)
);

create table ops.qa_contract_version (
  qa_contract_version_id uuid primary key default gen_random_uuid(),
  contract_code text not null,
  version_code text not null,
  status manifest.version_status not null default 'draft',
  effective_from timestamptz,
  effective_to timestamptz,
  artifact_uri text,
  artifact_sha256 char(64),
  notes text,
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  unique (contract_code, version_code),
  check ((status <> 'frozen') or frozen_at is not null)
);

create table ops.qa_rule (
  qa_rule_id uuid primary key default gen_random_uuid(),
  qa_contract_version_id uuid not null references ops.qa_contract_version(qa_contract_version_id),
  rule_code text not null,
  scope text not null,
  severity text not null check (severity in ('info','warning','error','critical')),
  description text not null,
  rule_config jsonb not null,
  created_at timestamptz not null default now(),
  unique (qa_contract_version_id, rule_code)
);

create table ops.qa_event (
  qa_event_id uuid primary key default gen_random_uuid(),
  qa_rule_id uuid references ops.qa_rule(qa_rule_id),
  wave_id uuid references ops.collection_wave(wave_id),
  job_id uuid references ops.collection_job(job_id),
  observation_id uuid references ops.observation(observation_id),
  severity text not null check (severity in ('info','warning','error','critical')),
  qa_code text not null,
  expected_value jsonb,
  observed_value jsonb,
  disposition text,
  created_at timestamptz not null default now()
);

create table ops.wave_evaluation (
  wave_evaluation_id uuid primary key default gen_random_uuid(),
  wave_id uuid not null references ops.collection_wave(wave_id),
  qa_contract_version_id uuid not null references ops.qa_contract_version(qa_contract_version_id),
  status ops.wave_status not null,
  expected_jobs integer not null check (expected_jobs >= 0),
  executable_jobs integer not null check (executable_jobs >= 0),
  returned_observations integer not null check (returned_observations >= 0),
  structurally_excluded_jobs integer not null check (structurally_excluded_jobs >= 0),
  failed_jobs integer not null check (failed_jobs >= 0),
  quarantined_jobs integer not null check (quarantined_jobs >= 0),
  metrics jsonb not null default '{}'::jsonb,
  evaluated_at timestamptz not null default now(),
  evaluator_component_version_id uuid references ops.component_version(component_version_id),
  unique (wave_id, evaluated_at)
);

-- ============================================================================
-- CORE OBSERVED OBJECTS + VERSIONED ENTITY RESOLUTION
-- ============================================================================

create table core.observed_object (
  observed_object_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references ops.observation(observation_id),
  surface_id uuid not null references manifest.surface(surface_id),
  object_kind text not null,
  local_sequence integer not null check (local_sequence >= 1),
  raw_name text,
  raw_url text,
  raw_domain text,
  raw_phone text,
  raw_address text,
  raw_text_span text,
  raw_external_ids jsonb not null default '{}'::jsonb,
  raw_attributes jsonb not null default '{}'::jsonb,
  parser_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (observation_id, object_kind, local_sequence)
);

create table core.entity_graph_release (
  entity_graph_release_id uuid primary key default gen_random_uuid(),
  release_code text not null unique,
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  parent_release_id uuid references core.entity_graph_release(entity_graph_release_id),
  status manifest.version_status not null default 'draft',
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  notes text,
  check ((status <> 'frozen') or frozen_at is not null)
);

create table core.resolution_run (
  resolution_run_id uuid primary key default gen_random_uuid(),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  resolver_version_id uuid not null references ops.component_version(component_version_id),
  resolver_stage text not null,
  input_sha256 char(64),
  run_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create table core.resolution_candidate (
  resolution_candidate_id uuid primary key default gen_random_uuid(),
  resolution_run_id uuid not null references core.resolution_run(resolution_run_id),
  candidate_entity_id uuid not null references core.entity(entity_id),
  candidate_rank integer,
  match_score numeric(12,6),
  score_semantics text not null default 'uncalibrated',
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (resolution_run_id, candidate_entity_id)
);

create table core.resolution_assertion (
  resolution_assertion_id uuid primary key default gen_random_uuid(),
  resolution_run_id uuid not null references core.resolution_run(resolution_run_id),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  resolved_entity_id uuid references core.entity(entity_id),
  resolution_state core.resolution_state not null,
  confidence_value numeric(8,6),
  confidence_semantics text,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.resolution_assertion(resolution_assertion_id),
  analyst_override boolean not null default false,
  analyst_note text,
  created_at timestamptz not null default now(),
  check (
    (resolution_state in ('resolved','probable_match') and resolved_entity_id is not null)
    or
    (resolution_state not in ('resolved','probable_match') and resolved_entity_id is null)
  ),
  check (confidence_value is null or confidence_value between 0 and 1)
);

create table core.entity_relationship_assertion (
  relationship_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  from_entity_id uuid not null references core.entity(entity_id),
  relationship_type_code text not null references core.relationship_type(relationship_type_code),
  to_entity_id uuid not null references core.entity(entity_id),
  action core.assertion_action not null default 'assert',
  effective_from timestamptz,
  effective_to timestamptz,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  source_observed_object_id uuid references core.observed_object(observed_object_id),
  resolver_version_id uuid references ops.component_version(component_version_id),
  supersedes_assertion_id uuid references core.entity_relationship_assertion(relationship_assertion_id),
  created_at timestamptz not null default now(),
  check (from_entity_id <> to_entity_id)
);

create table core.external_identifier (
  external_identifier_id uuid primary key default gen_random_uuid(),
  namespace text not null,
  identifier_type text not null,
  identifier_value text not null,
  normalized_value text,
  created_at timestamptz not null default now(),
  unique (namespace, identifier_type, identifier_value)
);

create table core.external_identifier_assertion (
  external_identifier_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  external_identifier_id uuid not null references core.external_identifier(external_identifier_id),
  entity_id uuid not null references core.entity(entity_id),
  resolution_state core.resolution_state not null,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.external_identifier_assertion(external_identifier_assertion_id),
  created_at timestamptz not null default now(),
  check (resolution_state in ('resolved','probable_match'))
);

create table core.entity_alias_assertion (
  entity_alias_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  entity_id uuid not null references core.entity(entity_id),
  alias_type text not null,
  alias_text text not null,
  normalized_alias text not null,
  source_observed_object_id uuid references core.observed_object(observed_object_id),
  supporting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.entity_alias_assertion(entity_alias_assertion_id),
  created_at timestamptz not null default now()
);

-- ============================================================================
-- MAPS SURFACE
-- ============================================================================

create table maps.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  returned_result_count integer check (returned_result_count is null or returned_result_count >= 0),
  provider_depth integer,
  search_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table maps.result (
  maps_result_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references maps.observation(observation_id),
  result_sequence integer not null check (result_sequence >= 1),
  rank_absolute integer,
  rank_group integer,
  provider_item_type text,
  title_raw text,
  category_raw text,
  rating numeric(4,2),
  review_count integer,
  address_raw text,
  phone_raw text,
  latitude numeric(10,7),
  longitude numeric(10,7),
  url_raw text,
  observed_object_id uuid references core.observed_object(observed_object_id),
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, result_sequence),
  check (rank_absolute is null or rank_absolute >= 1),
  check (review_count is null or review_count >= 0),
  check (latitude is null or latitude between -90 and 90),
  check (longitude is null or longitude between -180 and 180)
);

-- ============================================================================
-- ORGANIC SURFACE
-- ============================================================================

create table organic.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  returned_result_count integer check (returned_result_count is null or returned_result_count >= 0),
  provider_depth integer,
  serp_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table organic.result (
  organic_result_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references organic.observation(observation_id),
  result_sequence integer not null check (result_sequence >= 1),
  rank_absolute integer,
  page_number integer,
  position_on_page integer,
  result_type text,
  title_raw text,
  snippet_raw text,
  url_raw text,
  domain_raw text,
  observed_object_id uuid references core.observed_object(observed_object_id),
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, result_sequence),
  check (rank_absolute is null or rank_absolute >= 1),
  check (page_number is null or page_number >= 1),
  check (position_on_page is null or position_on_page >= 1)
);

-- ============================================================================
-- AIO / AI MODE SURFACE
-- ============================================================================

create table aio.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  aio_triggered boolean,
  response_text_raw text,
  response_markdown_raw text,
  provider_model text,
  response_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table aio.presentation_unit (
  presentation_unit_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  unit_sequence integer not null check (unit_sequence >= 1),
  unit_type text not null,
  presentation_zone text,
  heading_raw text,
  text_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, unit_sequence)
);

create table aio.business_appearance (
  business_appearance_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  appearance_sequence integer not null check (appearance_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  appearance_type text,
  local_business_card boolean,
  embedded_gbp boolean,
  selected boolean,
  raw_label text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, appearance_sequence)
);

create table aio.source_occurrence (
  source_occurrence_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  source_sequence integer not null check (source_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  source_url_raw text,
  source_title_raw text,
  publisher_raw text,
  retrieval_position integer,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, source_sequence)
);

create table aio.citation (
  citation_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  source_occurrence_id uuid not null references aio.source_occurrence(source_occurrence_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  citation_sequence integer not null check (citation_sequence >= 1),
  marker_raw text,
  cited_span_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, citation_sequence)
);

create table aio.destination (
  destination_id uuid primary key default gen_random_uuid(),
  business_appearance_id uuid not null references aio.business_appearance(business_appearance_id),
  destination_sequence integer not null check (destination_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  destination_url_raw text not null,
  destination_type text,
  direct_business_link boolean,
  third_party_business_link boolean,
  created_at timestamptz not null default now(),
  unique (business_appearance_id, destination_sequence)
);

create table aio.evidence_link (
  aio_evidence_link_id uuid primary key default gen_random_uuid(),
  citation_id uuid not null references aio.citation(citation_id),
  business_appearance_id uuid references aio.business_appearance(business_appearance_id),
  relationship_type text not null check (relationship_type in (
    'supports_business','supports_claim','supports_comparison','supports_list','general_background','unclear'
  )),
  claim_text_raw text,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- CHATGPT SURFACE
-- ============================================================================

create table chatgpt.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  response_outcome text not null check (response_outcome in (
    'answered_local','clarification_requested','generic_guidance_only',
    'no_local_recommendations','refusal','error','other'
  )),
  response_text_raw text,
  response_markdown_raw text,
  product_name text,
  model_name text,
  search_available boolean,
  search_invoked boolean,
  search_invocation_status text,
  observable_tool_metadata jsonb not null default '{}'::jsonb,
  account_context_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table chatgpt.product_event (
  product_event_id uuid primary key default gen_random_uuid(),
  event_code text not null unique,
  event_at timestamptz not null,
  product_name text not null default 'ChatGPT',
  event_type text not null,
  description text not null,
  source_url text,
  observed_evidence jsonb not null default '{}'::jsonb,
  comparability_impact text,
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  created_at timestamptz not null default now()
);

create table chatgpt.fanout_query (
  fanout_query_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  sequence integer not null check (sequence >= 1),
  origin text not null check (origin in ('observed','derived_inferred')),
  query_text text not null,
  stage text,
  provider_raw text,
  query_timestamp timestamptz,
  location_context jsonb not null default '{}'::jsonb,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, sequence, origin)
);

create table chatgpt.retrieved_source (
  retrieved_source_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  fanout_query_id uuid references chatgpt.fanout_query(fanout_query_id),
  source_sequence integer not null check (source_sequence >= 1),
  retrieval_position integer,
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  source_url_raw text,
  source_title_raw text,
  publisher_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, source_sequence)
);

create table chatgpt.citation (
  citation_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  retrieved_source_id uuid not null references chatgpt.retrieved_source(retrieved_source_id),
  citation_sequence integer not null check (citation_sequence >= 1),
  marker_raw text,
  cited_span_raw text,
  created_at timestamptz not null default now(),
  unique (observation_id, citation_sequence)
);

create table chatgpt.entity_mention (
  entity_mention_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  mention_sequence integer not null check (mention_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  raw_span text not null,
  mention_position integer,
  polarity text check (polarity in ('positive','neutral','cautionary','negative')),
  mention_linked boolean,
  supporting_citation_present boolean,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, mention_sequence)
);

create table chatgpt.recommendation (
  recommendation_id uuid primary key default gen_random_uuid(),
  entity_mention_id uuid not null unique references chatgpt.entity_mention(entity_mention_id),
  recommended boolean not null,
  recommendation_strength smallint not null check (recommendation_strength between 0 and 4),
  recommendation_position integer,
  shortlist_member boolean not null default false,
  top_choice boolean not null default false,
  explicit_ranking boolean not null default false,
  explicit_rank integer,
  created_at timestamptz not null default now(),
  check (
    (recommended = false and recommendation_strength = 0)
    or
    (recommended = true and recommendation_strength between 1 and 4)
  ),
  check (recommendation_position is null or recommendation_position >= 1),
  check (explicit_rank is null or explicit_rank >= 1),
  check (recommended = true or (shortlist_member = false and top_choice = false))
);

create table chatgpt.rationale (
  rationale_id uuid primary key default gen_random_uuid(),
  recommendation_id uuid not null references chatgpt.recommendation(recommendation_id),
  rationale_sequence integer not null check (rationale_sequence >= 1),
  category text not null check (category in (
    'review_reputation','service_match','availability','location','price_value',
    'experience_longevity','specialization','credentials','brand_reputation',
    'third_party_recognition','other','unclear'
  )),
  raw_text text,
  raw_span text,
  classifier_version_id uuid references ops.component_version(component_version_id),
  confidence numeric(8,6),
  created_at timestamptz not null default now(),
  unique (recommendation_id, rationale_sequence),
  check (confidence is null or confidence between 0 and 1)
);

create table chatgpt.destination (
  destination_id uuid primary key default gen_random_uuid(),
  entity_mention_id uuid not null references chatgpt.entity_mention(entity_mention_id),
  destination_sequence integer not null check (destination_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  destination_url_raw text not null,
  destination_type text not null check (destination_type in (
    'business_homepage','business_service_page','business_location_page','business_other_page',
    'google_maps','google_business_profile','directory_profile','review_platform',
    'publisher_editorial','social_profile','booking_contact','other'
  )),
  direct_business_link boolean,
  third_party_business_link boolean,
  created_at timestamptz not null default now(),
  unique (entity_mention_id, destination_sequence)
);

create table chatgpt.evidence_link (
  chatgpt_evidence_link_id uuid primary key default gen_random_uuid(),
  citation_id uuid not null references chatgpt.citation(citation_id),
  entity_mention_id uuid references chatgpt.entity_mention(entity_mention_id),
  recommendation_id uuid references chatgpt.recommendation(recommendation_id),
  relationship_type text not null check (relationship_type in (
    'supports_business','supports_claim','supports_comparison','supports_list','general_background','unclear'
  )),
  claim_text_raw text,
  created_at timestamptz not null default now(),
  check (entity_mention_id is not null or recommendation_id is not null)
);

-- ============================================================================
-- ENRICHMENT: SHARED, TEMPORAL, DEDUPLICATED SIGNAL HISTORY
-- ============================================================================

create table enrichment.signal_type (
  signal_type_code text primary key,
  economic_unit_type text not null,
  description text not null,
  universal_or_selective text not null check (universal_or_selective in ('universal','selective','analysis_contract')),
  metadata jsonb not null default '{}'::jsonb
);

create table enrichment.freshness_policy (
  freshness_policy_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  policy_code text not null,
  ttl interval,
  refresh_mode text not null,
  effective_from timestamptz,
  effective_to timestamptz,
  policy jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (signal_type_code, policy_code)
);

create table enrichment.enrichment_request (
  enrichment_request_id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references core.entity(entity_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  wave_id uuid references ops.collection_wave(wave_id),
  trigger_job_id uuid references ops.collection_job(job_id),
  trigger_observation_id uuid references ops.observation(observation_id),
  trigger_reason text not null,
  economic_unit_key text not null,
  freshness_policy_id uuid references enrichment.freshness_policy(freshness_policy_id),
  freshness_decision enrichment.freshness_state not null default 'unknown',
  status enrichment.request_status not null default 'planned',
  dedup_reused_snapshot_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  requested_at timestamptz not null default now()
);

create table enrichment.enrichment_run (
  enrichment_run_id uuid primary key default gen_random_uuid(),
  enrichment_request_id uuid not null references enrichment.enrichment_request(enrichment_request_id),
  provider_id uuid references ops.provider(provider_id),
  component_version_id uuid references ops.component_version(component_version_id),
  request_payload_id uuid references ops.provider_payload(payload_id),
  response_payload_id uuid references ops.provider_payload(payload_id),
  cost_event_id uuid references ops.cost_event(cost_event_id),
  status enrichment.request_status not null,
  started_at timestamptz,
  finished_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table enrichment.signal_snapshot (
  signal_snapshot_id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references core.entity(entity_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  enrichment_run_id uuid references enrichment.enrichment_run(enrichment_run_id),
  provider_id uuid references ops.provider(provider_id),
  source_payload_id uuid references ops.provider_payload(payload_id),
  freshness_policy_id uuid references enrichment.freshness_policy(freshness_policy_id),
  observed_at timestamptz not null,
  effective_at timestamptz,
  last_verified_at timestamptz,
  freshness_state enrichment.freshness_state not null,
  value_sha256 char(64),
  value_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table enrichment.enrichment_request
  add constraint enrichment_request_reused_snapshot_fk
  foreign key (dedup_reused_snapshot_id)
  references enrichment.signal_snapshot(signal_snapshot_id);

create table enrichment.business_identity_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  display_name text,
  physical_location_known boolean,
  serves_research_market boolean,
  service_area_business boolean,
  phone text,
  address_text text,
  founding_year integer,
  business_type text,
  license_identifiers jsonb not null default '{}'::jsonb
);

create table enrichment.gbp_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  primary_category text,
  additional_categories text[],
  rating numeric(4,2),
  review_count integer,
  website_url_entity_id uuid references core.web_url(entity_id),
  phone text,
  address_text text,
  services jsonb not null default '[]'::jsonb,
  attributes jsonb not null default '{}'::jsonb,
  posts_summary jsonb not null default '{}'::jsonb,
  photos_summary jsonb not null default '{}'::jsonb,
  check (review_count is null or review_count >= 0)
);

create table enrichment.review_state_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  rating numeric(4,2),
  review_count integer,
  newest_review_at timestamptz,
  oldest_review_at timestamptz,
  provider_summary jsonb not null default '{}'::jsonb,
  check (review_count is null or review_count >= 0)
);

create table enrichment.review (
  review_id uuid primary key default gen_random_uuid(),
  business_entity_id uuid not null references core.entity(entity_id),
  provider_id uuid references ops.provider(provider_id),
  provider_review_id text,
  content_sha256 char(64) not null,
  rating numeric(4,2),
  reviewer_identifier text,
  published_at timestamptz,
  first_seen_at timestamptz not null,
  body_raw text,
  source_payload_id uuid references ops.provider_payload(payload_id),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table enrichment.website_site_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  domain_entity_id uuid not null references core.web_domain(entity_id),
  sitemap_sha256 char(64),
  sitemap_state jsonb not null default '{}'::jsonb,
  last_modified_header text,
  etag text,
  metadata jsonb not null default '{}'::jsonb
);

create table enrichment.website_page_version (
  page_version_id uuid primary key default gen_random_uuid(),
  url_entity_id uuid not null references core.web_url(entity_id),
  domain_entity_id uuid references core.web_domain(entity_id),
  observed_at timestamptz not null,
  raw_blob_id uuid references ops.raw_blob(blob_id),
  content_sha256 char(64),
  rendered_text_sha256 char(64),
  structured_data_sha256 char(64),
  http_status integer,
  etag text,
  last_modified_header text,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  parser_version_id uuid references ops.component_version(component_version_id),
  extraction_jsonb jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null,
  last_checked_at timestamptz not null,
  last_changed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (url_entity_id, observed_at)
);

create table enrichment.link_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  target_entity_id uuid not null references core.entity(entity_id),
  domain_rating numeric(10,4),
  url_rating numeric(10,4),
  referring_domains bigint,
  backlinks bigint,
  dofollow_backlinks bigint,
  metrics jsonb not null default '{}'::jsonb,
  check (referring_domains is null or referring_domains >= 0),
  check (backlinks is null or backlinks >= 0),
  check (dofollow_backlinks is null or dofollow_backlinks >= 0)
);

create table enrichment.brand_demand_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  brand_entity_id uuid references core.entity(entity_id),
  query_set jsonb not null default '[]'::jsonb,
  volume_metrics jsonb not null default '{}'::jsonb
);

create table enrichment.social_profile_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  profile_entity_id uuid not null references core.profile_entity(entity_id),
  platform text not null,
  profile_url_entity_id uuid references core.web_url(entity_id),
  activity_metrics jsonb not null default '{}'::jsonb,
  profile_metadata jsonb not null default '{}'::jsonb
);

create table enrichment.source_content_version (
  source_content_version_id uuid primary key default gen_random_uuid(),
  source_entity_id uuid not null references core.entity(entity_id),
  url_entity_id uuid references core.web_url(entity_id),
  observed_at timestamptz not null,
  raw_blob_id uuid references ops.raw_blob(blob_id),
  content_sha256 char(64) not null,
  rendered_text_sha256 char(64),
  parser_version_id uuid references ops.component_version(component_version_id),
  extraction_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (source_entity_id, observed_at)
);

create table enrichment.embedding (
  embedding_id uuid primary key default gen_random_uuid(),
  entity_id uuid references core.entity(entity_id),
  observed_object_id uuid references core.observed_object(observed_object_id),
  content_sha256 char(64) not null,
  embedding_model_version_id uuid not null references ops.component_version(component_version_id),
  embedding_dimension integer not null check (embedding_dimension > 0),
  embedding vector not null,
  source_content_uri text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (entity_id is not null or observed_object_id is not null),
  unique (entity_id, observed_object_id, content_sha256, embedding_model_version_id)
);

-- ============================================================================
-- RESEARCH: ANALYSIS CONTRACTS, REPRODUCIBLE DERIVED DATA, FINDINGS
-- ============================================================================

create table research.analysis_specification (
  analysis_specification_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  spec_code text not null,
  spec_version text not null,
  title text not null,
  population_definition jsonb not null,
  estimand text not null,
  exposure_definition jsonb not null,
  confounder_plan jsonb not null default '{}'::jsonb,
  mediator_collider_plan jsonb not null default '{}'::jsonb,
  timing_lag_plan jsonb not null default '{}'::jsonb,
  missingness_plan jsonb not null default '{}'::jsonb,
  repeated_measures_plan jsonb not null default '{}'::jsonb,
  multiple_testing_plan jsonb not null default '{}'::jsonb,
  validation_holdout_plan jsonb not null default '{}'::jsonb,
  practical_effect_plan jsonb not null default '{}'::jsonb,
  code_provenance jsonb not null default '{}'::jsonb,
  status text not null default 'draft',
  created_at timestamptz not null default now(),
  unique (methodology_version_id, spec_code, spec_version)
);

alter table enrichment.enrichment_request
  add column analysis_specification_id uuid references research.analysis_specification(analysis_specification_id);

create table research.dataset_build (
  dataset_build_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  entity_graph_release_id uuid references core.entity_graph_release(entity_graph_release_id),
  analysis_specification_id uuid references research.analysis_specification(analysis_specification_id),
  dataset_code text not null,
  build_version text not null,
  source_observation_cutoff timestamptz not null,
  sql_component_version_id uuid references ops.component_version(component_version_id),
  resolver_component_version_id uuid references ops.component_version(component_version_id),
  parser_bundle jsonb not null default '{}'::jsonb,
  input_manifest_uri text not null,
  input_manifest_sha256 char(64) not null,
  output_artifact_uri text,
  output_sha256 char(64),
  exclusion_manifest_uri text,
  exclusion_manifest_sha256 char(64),
  row_count bigint,
  build_metrics jsonb not null default '{}'::jsonb,
  build_config jsonb not null default '{}'::jsonb,
  status research.build_status not null default 'planned',
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (methodology_version_id, dataset_code, build_version)
);

create table research.feature_definition (
  feature_definition_id uuid primary key default gen_random_uuid(),
  feature_code text not null,
  feature_version text not null,
  description text not null,
  subject_grain text not null,
  value_type text not null check (value_type in ('numeric','boolean','text','jsonb','timestamp')),
  derivation_spec jsonb not null,
  component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (feature_code, feature_version)
);

create table research.feature_build (
  feature_build_id uuid primary key default gen_random_uuid(),
  dataset_build_id uuid not null references research.dataset_build(dataset_build_id),
  feature_definition_id uuid not null references research.feature_definition(feature_definition_id),
  status research.build_status not null,
  build_config jsonb not null default '{}'::jsonb,
  built_at timestamptz not null default now(),
  output_artifact_uri text,
  output_sha256 char(64),
  unique (dataset_build_id, feature_definition_id)
);

create table research.feature_value (
  feature_value_id uuid primary key default gen_random_uuid(),
  feature_build_id uuid not null references research.feature_build(feature_build_id),
  entity_id uuid references core.entity(entity_id),
  observation_id uuid references ops.observation(observation_id),
  wave_id uuid references ops.collection_wave(wave_id),
  numeric_value numeric,
  boolean_value boolean,
  text_value text,
  jsonb_value jsonb,
  timestamp_value timestamptz,
  created_at timestamptz not null default now(),
  check (
    entity_id is not null or observation_id is not null or wave_id is not null
  ),
  check (
    num_nonnulls(numeric_value, boolean_value, text_value, jsonb_value, timestamp_value) = 1
  )
);

create table research.cohort (
  cohort_id uuid primary key default gen_random_uuid(),
  analysis_specification_id uuid not null references research.analysis_specification(analysis_specification_id),
  cohort_code text not null,
  cohort_version text not null,
  role text,
  definition jsonb not null,
  created_at timestamptz not null default now(),
  unique (analysis_specification_id, cohort_code, cohort_version)
);

create table research.cohort_member (
  cohort_member_id uuid primary key default gen_random_uuid(),
  cohort_id uuid not null references research.cohort(cohort_id),
  entity_id uuid not null references core.entity(entity_id),
  wave_id uuid references ops.collection_wave(wave_id),
  effective_from timestamptz,
  effective_to timestamptz,
  inclusion_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table research.model_version (
  model_version_id uuid primary key default gen_random_uuid(),
  model_code text not null,
  version_code text not null,
  model_kind text not null,
  artifact_uri text,
  artifact_sha256 char(64),
  git_sha text,
  parameters jsonb not null default '{}'::jsonb,
  training_dataset_build_id uuid references research.dataset_build(dataset_build_id),
  created_at timestamptz not null default now(),
  unique (model_code, version_code)
);

create table research.analysis_run (
  analysis_run_id uuid primary key default gen_random_uuid(),
  analysis_specification_id uuid not null references research.analysis_specification(analysis_specification_id),
  dataset_build_id uuid not null references research.dataset_build(dataset_build_id),
  model_version_id uuid references research.model_version(model_version_id),
  analysis_component_version_id uuid references ops.component_version(component_version_id),
  run_code text not null,
  run_parameters jsonb not null default '{}'::jsonb,
  result_artifact_uri text,
  result_sha256 char(64),
  status research.build_status not null,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (analysis_specification_id, run_code)
);

create table research.hypothesis (
  hypothesis_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  hypothesis_code text not null,
  statement text not null,
  preregistered_at timestamptz,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, hypothesis_code)
);

create table research.finding (
  finding_id uuid primary key default gen_random_uuid(),
  hypothesis_id uuid references research.hypothesis(hypothesis_id),
  analysis_run_id uuid not null references research.analysis_run(analysis_run_id),
  finding_code text not null,
  statement text not null,
  evidence_label text,
  population_of_inference text not null,
  association_or_causal text not null check (association_or_causal in ('descriptive','associational','predictive','causal')),
  practical_effect_summary text,
  uncertainty_summary text,
  status research.finding_status not null default 'draft',
  supersedes_finding_id uuid references research.finding(finding_id),
  created_at timestamptz not null default now(),
  unique (analysis_run_id, finding_code)
);

create table research.finding_evidence (
  finding_evidence_id uuid primary key default gen_random_uuid(),
  finding_id uuid not null references research.finding(finding_id),
  evidence_kind text not null,
  evidence_ref_uri text,
  evidence_sha256 char(64),
  observation_id uuid references ops.observation(observation_id),
  dataset_build_id uuid references research.dataset_build(dataset_build_id),
  analysis_run_id uuid references research.analysis_run(analysis_run_id),
  notes text,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- CLIENT MODE: REFERENCES SHARED RESEARCH TRUTH; DOES NOT DUPLICATE IT
-- ============================================================================

create table client.case_record (
  client_case_id uuid primary key default gen_random_uuid(),
  client_entity_id uuid not null references core.entity(entity_id),
  industry_id uuid references manifest.industry(industry_id),
  market_id uuid references manifest.market(market_id),
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  metadata jsonb not null default '{}'::jsonb
);

create table client.assessment (
  assessment_id uuid primary key default gen_random_uuid(),
  client_case_id uuid not null references client.case_record(client_case_id),
  finding_id uuid references research.finding(finding_id),
  recommendation_state client.recommendation_state not null,
  client_observation jsonb not null default '{}'::jsonb,
  competitive_gap jsonb not null default '{}'::jsonb,
  rationale text,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- INDEXES
-- ============================================================================

create index provider_price_effective_idx
  on ops.provider_price_version(provider_id, endpoint_or_product, effective_from desc);

create index methodology_industry_lookup_idx
  on manifest.methodology_industry(methodology_version_id, ordinal);

create index methodology_market_lookup_idx
  on manifest.methodology_market(methodology_version_id, ordinal);

create index market_coordinate_exec_idx
  on manifest.market_coordinate(methodology_version_id, market_id, eligibility);

create index treatment_lookup_idx
  on manifest.treatment(methodology_version_id, industry_id, treatment_kind, sequence);

create index surface_treatment_lookup_idx
  on manifest.surface_treatment(methodology_version_id, surface_id, active);

create index collection_wave_method_time_idx
  on ops.collection_wave(methodology_version_id, scheduled_for);

create index wave_event_latest_idx
  on ops.wave_event(wave_id, event_at desc);

create index collection_job_wave_surface_idx
  on ops.collection_job(wave_id, surface_id);

create index collection_job_market_industry_idx
  on ops.collection_job(market_id, industry_id, surface_id);

create index collection_job_treatment_coordinate_idx
  on ops.collection_job(surface_treatment_id, coordinate_id);

create index job_event_latest_idx
  on ops.job_event(job_id, event_at desc);

create index provider_payload_task_idx
  on ops.provider_payload(provider_id, provider_task_id);

create index attempt_job_idx
  on ops.collection_attempt(job_id, attempt_no);

create index attempt_event_latest_idx
  on ops.collection_attempt_event(attempt_id, event_at desc);

create index observation_observed_at_brin
  on ops.observation using brin(observed_at);

create index cost_event_wave_provider_idx
  on ops.cost_event(wave_id, provider_id, occurred_at);

create index cost_event_entity_idx
  on ops.cost_event(economic_unit_entity_id, occurred_at);

create index qa_rule_contract_idx
  on ops.qa_rule(qa_contract_version_id, severity, rule_code);

create index qa_event_wave_code_idx
  on ops.qa_event(wave_id, qa_code, severity);

create index observed_object_observation_idx
  on core.observed_object(observation_id, object_kind);

create index observed_object_name_trgm_idx
  on core.observed_object using gin (raw_name gin_trgm_ops);

create index resolution_run_object_idx
  on core.resolution_run(observed_object_id, run_at desc);

create index resolution_candidate_run_rank_idx
  on core.resolution_candidate(resolution_run_id, candidate_rank);

create index resolution_assertion_object_idx
  on core.resolution_assertion(resolution_run_id, created_at desc);

create index resolution_assertion_entity_idx
  on core.resolution_assertion(resolved_entity_id, created_at desc)
  where resolved_entity_id is not null;

create index entity_alias_trgm_idx
  on core.entity_alias_assertion using gin (normalized_alias gin_trgm_ops);

create index entity_relationship_from_idx
  on core.entity_relationship_assertion(from_entity_id, relationship_type_code, created_at desc);

create index entity_relationship_to_idx
  on core.entity_relationship_assertion(to_entity_id, relationship_type_code, created_at desc);

create index maps_result_observation_rank_idx
  on maps.result(observation_id, rank_absolute);

create index maps_result_object_idx
  on maps.result(observed_object_id);

create index organic_result_observation_rank_idx
  on organic.result(observation_id, rank_absolute);

create index organic_result_object_idx
  on organic.result(observed_object_id);

create index aio_business_obs_idx
  on aio.business_appearance(observation_id, appearance_sequence);

create index aio_source_obs_idx
  on aio.source_occurrence(observation_id, source_sequence);

create index aio_citation_source_idx
  on aio.citation(source_occurrence_id);

create index chatgpt_product_event_time_idx
  on chatgpt.product_event(event_at desc);

create index chatgpt_fanout_observed_idx
  on chatgpt.fanout_query(observation_id, sequence)
  where origin = 'observed';

create index chatgpt_source_fanout_idx
  on chatgpt.retrieved_source(fanout_query_id, retrieval_position);

create index chatgpt_mention_obs_idx
  on chatgpt.entity_mention(observation_id, mention_sequence);

create index chatgpt_destination_mention_idx
  on chatgpt.destination(entity_mention_id, destination_sequence);

create index enrichment_request_economic_unit_idx
  on enrichment.enrichment_request(signal_type_code, economic_unit_key, requested_at desc);

create index signal_snapshot_entity_signal_time_idx
  on enrichment.signal_snapshot(entity_id, signal_type_code, observed_at desc);

create index signal_snapshot_observed_at_brin
  on enrichment.signal_snapshot using brin(observed_at);

create index review_business_time_idx
  on enrichment.review(business_entity_id, published_at desc);

create unique index review_provider_id_unique_idx
  on enrichment.review(provider_id, provider_review_id)
  where provider_review_id is not null;

create unique index review_hash_fallback_unique_idx
  on enrichment.review(business_entity_id, content_sha256, coalesce(published_at, first_seen_at));

create index page_version_url_time_idx
  on enrichment.website_page_version(url_entity_id, observed_at desc);

create index source_content_entity_time_idx
  on enrichment.source_content_version(source_entity_id, observed_at desc);

create index source_content_hash_idx
  on enrichment.source_content_version(source_entity_id, content_sha256);

create index embedding_entity_model_idx
  on enrichment.embedding(entity_id, embedding_model_version_id)
  where entity_id is not null;

create index embedding_object_model_idx
  on enrichment.embedding(observed_object_id, embedding_model_version_id)
  where observed_object_id is not null;

create index dataset_build_method_time_idx
  on research.dataset_build(methodology_version_id, source_observation_cutoff desc);

create index feature_value_entity_idx
  on research.feature_value(entity_id, feature_build_id)
  where entity_id is not null;

create index feature_value_observation_idx
  on research.feature_value(observation_id, feature_build_id)
  where observation_id is not null;

create index cohort_member_entity_idx
  on research.cohort_member(entity_id, cohort_id);

create index finding_status_idx
  on research.finding(status, evidence_label);

-- ============================================================================
-- REBUILDABLE "LATEST" VIEWS — CONVENIENCE, NEVER SOURCE OF RAW TRUTH
-- ============================================================================

create view ops.current_wave_state as
select distinct on (we.wave_id)
  we.wave_id,
  we.status,
  we.event_at,
  we.actor,
  we.details
from ops.wave_event we
order by we.wave_id, we.event_at desc, we.wave_event_id desc;

create view ops.current_job_state as
select distinct on (je.job_id)
  je.job_id,
  je.status,
  je.event_at,
  je.attempt_no,
  je.actor,
  je.reason_code,
  je.details
from ops.job_event je
order by je.job_id, je.event_at desc, je.job_event_id desc;

create view core.latest_resolution as
select distinct on (rr.observed_object_id)
  rr.observed_object_id,
  ra.resolution_assertion_id,
  ra.entity_graph_release_id,
  ra.resolved_entity_id,
  ra.resolution_state,
  ra.confidence_value,
  ra.confidence_semantics,
  ra.created_at
from core.resolution_assertion ra
join core.resolution_run rr on rr.resolution_run_id = ra.resolution_run_id
order by rr.observed_object_id, ra.created_at desc, ra.resolution_assertion_id desc;

create view enrichment.latest_signal_snapshot as
select distinct on (ss.entity_id, ss.signal_type_code)
  ss.*
from enrichment.signal_snapshot ss
order by ss.entity_id, ss.signal_type_code, ss.observed_at desc, ss.signal_snapshot_id desc;

-- ============================================================================
-- IMMUTABILITY PROTECTIONS
-- ============================================================================

create or replace function ops.reject_update_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception 'table %.% is append-only; insert a new version/assertion/event instead',
    tg_table_schema, tg_table_name;
end;
$$;

-- Raw/blob/provider evidence
create trigger raw_blob_append_only
before update or delete on ops.raw_blob
for each row execute function ops.reject_update_delete();

create trigger provider_price_append_only
before update or delete on ops.provider_price_version
for each row execute function ops.reject_update_delete();

create trigger provider_payload_append_only
before update or delete on ops.provider_payload
for each row execute function ops.reject_update_delete();

create trigger collection_job_append_only
before update or delete on ops.collection_job
for each row execute function ops.reject_update_delete();

create trigger observation_append_only
before update or delete on ops.observation
for each row execute function ops.reject_update_delete();

-- Normalized raw surface evidence
create trigger observed_object_append_only
before update or delete on core.observed_object
for each row execute function ops.reject_update_delete();

create trigger maps_observation_append_only
before update or delete on maps.observation
for each row execute function ops.reject_update_delete();

create trigger maps_result_append_only
before update or delete on maps.result
for each row execute function ops.reject_update_delete();

create trigger organic_observation_append_only
before update or delete on organic.observation
for each row execute function ops.reject_update_delete();

create trigger organic_result_append_only
before update or delete on organic.result
for each row execute function ops.reject_update_delete();

create trigger aio_observation_append_only
before update or delete on aio.observation
for each row execute function ops.reject_update_delete();

create trigger aio_presentation_append_only
before update or delete on aio.presentation_unit
for each row execute function ops.reject_update_delete();

create trigger aio_business_append_only
before update or delete on aio.business_appearance
for each row execute function ops.reject_update_delete();

create trigger aio_source_append_only
before update or delete on aio.source_occurrence
for each row execute function ops.reject_update_delete();

create trigger aio_citation_append_only
before update or delete on aio.citation
for each row execute function ops.reject_update_delete();

create trigger aio_destination_append_only
before update or delete on aio.destination
for each row execute function ops.reject_update_delete();

create trigger aio_evidence_append_only
before update or delete on aio.evidence_link
for each row execute function ops.reject_update_delete();

create trigger chatgpt_observation_append_only
before update or delete on chatgpt.observation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_fanout_append_only
before update or delete on chatgpt.fanout_query
for each row execute function ops.reject_update_delete();

create trigger chatgpt_source_append_only
before update or delete on chatgpt.retrieved_source
for each row execute function ops.reject_update_delete();

create trigger chatgpt_citation_append_only
before update or delete on chatgpt.citation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_mention_append_only
before update or delete on chatgpt.entity_mention
for each row execute function ops.reject_update_delete();

create trigger chatgpt_recommendation_append_only
before update or delete on chatgpt.recommendation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_rationale_append_only
before update or delete on chatgpt.rationale
for each row execute function ops.reject_update_delete();

create trigger chatgpt_destination_append_only
before update or delete on chatgpt.destination
for each row execute function ops.reject_update_delete();

create trigger chatgpt_evidence_append_only
before update or delete on chatgpt.evidence_link
for each row execute function ops.reject_update_delete();

-- Resolution history
create trigger resolution_run_append_only
before update or delete on core.resolution_run
for each row execute function ops.reject_update_delete();

create trigger resolution_candidate_append_only
before update or delete on core.resolution_candidate
for each row execute function ops.reject_update_delete();

create trigger resolution_assertion_append_only
before update or delete on core.resolution_assertion
for each row execute function ops.reject_update_delete();

create trigger relationship_assertion_append_only
before update or delete on core.entity_relationship_assertion
for each row execute function ops.reject_update_delete();

create trigger external_identifier_assertion_append_only
before update or delete on core.external_identifier_assertion
for each row execute function ops.reject_update_delete();

create trigger entity_alias_assertion_append_only
before update or delete on core.entity_alias_assertion
for each row execute function ops.reject_update_delete();

-- Temporal enrichment evidence
create trigger signal_snapshot_append_only
before update or delete on enrichment.signal_snapshot
for each row execute function ops.reject_update_delete();

create trigger review_append_only
before update or delete on enrichment.review
for each row execute function ops.reject_update_delete();

create trigger page_version_append_only
before update or delete on enrichment.website_page_version
for each row execute function ops.reject_update_delete();

create trigger source_content_append_only
before update or delete on enrichment.source_content_version
for each row execute function ops.reject_update_delete();

create trigger embedding_append_only
before update or delete on enrichment.embedding
for each row execute function ops.reject_update_delete();

create trigger cost_event_append_only
before update or delete on ops.cost_event
for each row execute function ops.reject_update_delete();

create trigger cost_allocation_append_only
before update or delete on ops.cost_allocation
for each row execute function ops.reject_update_delete();

-- ============================================================================
-- SEED CONTROLLED LOOKUPS
-- ============================================================================

insert into manifest.surface(surface_code, surface_name, is_primary_observation_surface) values
  ('maps','Google Maps / Local Pack',true),
  ('organic','Google Organic',true),
  ('aio','Google AIO / AI Mode',true),
  ('chatgpt','ChatGPT Local Search',true),
  ('google_top50','Google Top-50 Brand/Service/Location Evidence',false)
on conflict (surface_code) do nothing;

insert into core.entity_type(entity_type_code, description) values
  ('organization','Operating/legal organization'),
  ('brand','Brand, trade name, or DBA'),
  ('business_location','Specific local location or service operation'),
  ('google_business_profile','Google Business Profile / Google Place asset'),
  ('domain','Canonical web domain'),
  ('url','Canonical URL/page asset'),
  ('directory_profile','Directory profile asset'),
  ('review_profile','Review-platform profile asset'),
  ('social_profile','Official or observed social profile asset'),
  ('booking_destination','Booking/contact destination asset'),
  ('publisher_source','Publisher/editorial source entity'),
  ('source_asset','Generic evidence/source asset'),
  ('other','Other canonical entity type')
on conflict (entity_type_code) do nothing;

insert into core.relationship_type(relationship_type_code, description) values
  ('operated_by','Business location/service operation is operated by an organization'),
  ('brand_of','Brand relationship'),
  ('franchisee_of','Franchisee relationship'),
  ('member_of','Membership/brand-network relationship'),
  ('gbp_for','GBP represents a business location/service operation'),
  ('domain_for','Domain represents an entity'),
  ('url_for','URL/page represents or belongs to an entity'),
  ('profile_for','External profile represents an entity'),
  ('source_supports','Source asset supports/relates to an entity'),
  ('merged_into','Later canonical merge relationship'),
  ('same_as','Asserted equivalent entity relationship')
on conflict (relationship_type_code) do nothing;

insert into enrichment.signal_type(signal_type_code, economic_unit_type, description, universal_or_selective) values
  ('business_identity','business/location','Slow-changing business identity facts','universal'),
  ('gbp_state','GBP','GBP categories, rating, review count, services, attributes, website destination and profile state','universal'),
  ('review_state','business/location','Cheap current review count/rating/recency state','universal'),
  ('review_body','review','Append-only individual review text/history','selective'),
  ('website_site','domain','Site/sitemap/change-detection state','universal'),
  ('website_page','URL/content hash','Versioned page content and parsed state','universal'),
  ('backlinks','domain/URL','Approved link/referring-domain/authority history','universal'),
  ('brand_demand','brand/business','Approved brand-demand/search-volume history','universal'),
  ('social_profile','social profile','Direct social profile/activity evidence where selectively authorized','selective'),
  ('source_content','source URL/content hash','AIO/ChatGPT/source evidence content snapshot','selective'),
  ('top50_evidence','business/query','Brand + service + location Top-50 Google evidence layer','universal')
on conflict (signal_type_code) do nothing;

-- ============================================================================
-- COMMENTS ON CRITICAL SEMANTICS
-- ============================================================================

comment on table ops.provider_price_version is
'Versioned provider pricing evidence used for cost drift and budget checks. Price changes create new rows rather than overwriting history.';

comment on table ops.qa_contract_version is
'Frozen/versioned operational QA and wave-acceptance contract. Threshold changes create a new version and are never retrofitted after seeing outcomes.';

comment on table ops.qa_rule is
'Machine-readable QA rule bound to a versioned QA contract. qa_event rows should reference the rule that fired.';

comment on table ops.collection_job is
'One deterministic planned scientific collection unit. job_key is a SHA-256 idempotency key over methodology/wave/surface/industry/market/treatment/coordinate/replicate. Rows are append-only.';

comment on table ops.observation is
'One terminal scientific observation per planned job. Technical attempts are separate. Failed/refusal/clarification/no-recommendation outcomes remain observations rather than being silently replaced.';

comment on table ops.raw_blob is
'Content-addressed immutable raw bytes. Store complete provider payloads in a private Supabase Storage bucket; this table stores hash/path/size metadata.';

comment on table core.observed_object is
'Normalized extraction of an observed business/source/URL/profile/etc. It is NOT canonical identity. Raw returned values remain immutable.';

comment on table core.resolution_assertion is
'Append-only versioned identity adjudication. Later resolution may supersede an earlier assertion without rewriting the original observation or observed object.';

comment on view core.latest_resolution is
'Convenience view of latest resolution assertions. It is rebuildable and MUST NOT replace historical resolution-version provenance in analyses.';

comment on table enrichment.signal_snapshot is
'Temporal shared signal history. Cached reuse must reference prior snapshots; it must never be represented as a newly observed fresh snapshot.';

comment on table enrichment.embedding is
'Content-hash and model-version keyed shared embeddings. Stored once and reused across surfaces when scientifically equivalent; no ANN index is created until a fixed model/dimension and measured query need justify it.';

comment on table chatgpt.product_event is
'Versioned registry of observed/known ChatGPT product changes that may create structural breaks or comparability concerns.';

comment on table research.dataset_build is
'Reproducible derived dataset build with methodology version, entity-graph release, analysis specification, source cutoff, code/config provenance and artifact hashes.';

comment on table research.finding is
'Research finding registry. Predictive/associational findings are not causal unless association_or_causal = causal under a qualifying design.';

commit;
