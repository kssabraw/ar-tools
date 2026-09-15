-- Migration: 20260915160000_paa_manifests.sql
-- Purpose: PAA → SEO Neo PHASE 2 — the prep-sheet MANIFEST + link-layer
--   track / cost / QA / hand-off (the "seam"). The methodology's physical
--   hand-off is the prep sheet (reference §3): one artifact carrying the
--   client's identity (NAP / CID / place ID / GBP URL) + EVERY asset URL a
--   campaign produced, routed to a link operator. The one real org gap the
--   source flags is "agree explicitly WHO captures the asset URLs and hands
--   them off." Phase 2 makes the suite that capturer.
--
--   Grain (owner-locked 2026-09-15): ONE manifest per paa_set (per service-in-
--   geo) — matches the methodology's #1 discipline (one service per campaign,
--   never mix) and evolves into Phase 3's per-service Campaign object.
--
--   * paa_manifests        — one per paa_set: status, roll-up summaries
--                            (cost_summary / qa_summary), and the last export's
--                            Google-Sheet refs. The client-identity header
--                            (NAP/CID/place ID/GBP URL) is NOT stored here — it
--                            is read fresh from clients.gbp at build/export time
--                            so it can never go stale.
--   * paa_manifest_assets  — one row per asset (first-class so a QA verdict + a
--                            cost attach per row). Three provenances:
--                              - source='auto' : collected from v1 linkage
--                                (a PAA post's live URL via runs.published_url,
--                                a GBP post's search_url, a syndication copy's
--                                doc/sheet URL). Refreshed on every rebuild.
--                              - source='seed' : the standard authority bundle
--                                (the 7 seam bolts, reference §5.1) as
--                                tracked-only rows, mapped to a Recipe-Engine
--                                cost task_type where one exists, carrying the
--                                methodology's confidence tag. Seeded once;
--                                never clobbered by a rebuild.
--                              - source='manual': operator-added rows
--                                (audio / video / influencer — tracked, NEVER
--                                generated) + any hand edits.
--
--   PERMANENT GUARDRAIL (PRD §9): the suite tracks / costs / QAs / hands off a
--   manifest — it NEVER executes the SEO Neo authority layer (link blasts /
--   RD 100 / GMBB Blast / Omega / PBNs). There is deliberately NO "execute"
--   affordance on an authority row: its status is human-set only
--   (planned → handed_off → done). Nothing in this migration runs anything.
--
--   New async_jobs type `paa_manifest_qa` (below): reviews each content asset's
--   LIVE URL via the QA Agent's bare-URL path (qa_service.review_url) so the
--   content is QA'd BEFORE authority is pointed at it (reference §2: authority
--   on thin content is wasted). Gated on qa_enabled; the deterministic v1
--   per-item checks remain the free fallback.
--
-- Both tables RLS-on with no client-facing policies: access is service-role
-- only, authorization is API-layer client_id filtering (suite single-tenant
-- model), matching every other suite module table.

-- ---------------------------------------------------------------------------
-- Manifests (one per PAA set)
-- ---------------------------------------------------------------------------
create table if not exists paa_manifests (
  id             uuid primary key default gen_random_uuid(),
  -- One manifest per set (the per-service-in-geo grain). UNIQUE so build is an
  -- upsert, not a duplicate.
  set_id         uuid not null unique references paa_sets (id) on delete cascade,
  client_id      uuid not null references clients (id) on delete cascade,
  status         text not null default 'draft'
                   check (status in ('draft', 'ready', 'handed_off')),
  -- Deterministic roll-ups, recomputed on build / QA / edit (never a source of
  -- truth — the asset rows are). cost_summary = Recipe-Engine cost_of over the
  -- costable rows (honest "not estimated" for off-menu RD 100). qa_summary =
  -- content-asset verdict rollup.
  cost_summary   jsonb,
  qa_summary     jsonb,
  -- Last Google-Sheet export refs (the hand-off artifact). CSV/JSON downloads
  -- are stateless and record nothing here.
  sheet_id       text,
  sheet_url      text,
  last_export_at timestamptz,
  created_by     uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists paa_manifests_client_idx
  on paa_manifests (client_id, created_at desc);

alter table paa_manifests enable row level security;

-- ---------------------------------------------------------------------------
-- Manifest assets (one row per asset — content, authority, or manual media)
-- ---------------------------------------------------------------------------
create table if not exists paa_manifest_assets (
  id            uuid primary key default gen_random_uuid(),
  manifest_id   uuid not null references paa_manifests (id) on delete cascade,
  -- Denormalized for RLS-free client-scoped reads + cascade integrity.
  client_id     uuid not null references clients (id) on delete cascade,
  -- The coarse asset class. Content classes (paa_post / gbp_post / syndication /
  -- image) are what the authority layer amplifies — the QA target. authority =
  -- a tracked link-layer line item (never executed). media = audio/video/
  -- influencer (never generated).
  category      text not null
                   check (category in ('paa_post', 'gbp_post', 'syndication',
                                       'image', 'authority', 'media')),
  -- Provenance: 'auto' (collected from v1 linkage, refreshed on rebuild),
  -- 'seed' (the standard authority bundle, seeded once), 'manual' (operator).
  source        text not null default 'manual'
                   check (source in ('auto', 'seed', 'manual')),
  -- A finer type within the category — e.g. an authority row's seam-bolt key
  -- ('rd_100' / 'gmbb_blast' / 'wiki_cloud_stack' / 'press_release' /
  -- 'neo_bucket'), or a media row's kind ('audio' / 'video' / 'influencer').
  kind          text,
  label         text not null,
  -- The asset URL (a content asset's live URL, or an operator-pasted hand-off
  -- link). Nullable: a not-yet-published PAA post, or a planned authority/media
  -- row, has no URL yet.
  url           text,
  -- Free note / RD-100 anchor text / hand-off instruction.
  note          text,
  -- Lifecycle. Content: 'collected' (has a live URL) | 'pending' (a run exists
  -- but isn't published yet) | 'missing'. Authority/media: 'planned' |
  -- 'handed_off' | 'done'. All human-set for authority/media (no execution).
  status        text not null default 'collected',
  -- The methodology's own confidence tag for a surfaced claim
  -- ([PROVEN]/[THEORY]/[BELIEF]) — carried into the export + UI (PRD §9). e.g.
  -- the RD-100 100:1 ratio is [THEORY]; exact-match/link-high is [BELIEF].
  confidence_tag text,
  -- Costing (reused Recipe-Engine catalog). cost_task_type maps to a
  -- recipe_engine.price_catalog() key when one exists; NULL (e.g. RD 100, off
  -- the default menu) → the row shows "not estimated" rather than a fake $0.
  cost_task_type text,
  cost_quantity  numeric,
  -- Content-asset QA verdict from qa_service.review_url (pass / advisory /
  -- revisions / fail / needs_human / pending), the full review on qa_review, and
  -- when it ran. Only content assets with a live URL are auto-QA'd.
  qa_verdict     text,
  qa_review      jsonb,
  qa_reviewed_at timestamptz,
  -- Soft link back to the originating PAA item (nullable — seed/manual rows have
  -- none). No FK cascade beyond set null so a purged item doesn't drop the row.
  paa_item_id    uuid references paa_items (id) on delete set null,
  position       integer not null default 0,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists paa_manifest_assets_manifest_idx
  on paa_manifest_assets (manifest_id, position);

alter table paa_manifest_assets enable row level security;

-- ---------------------------------------------------------------------------
-- async_jobs: register the paa_manifest_qa job type.
-- Drift-proof + idempotent (mirrors 20260908130000_social_fanout_job): reads
-- the LIVE CHECK definition and appends the type to its ARRAY, so it can't
-- clobber the (repo-wider-than-any-file) current set.
-- ---------------------------------------------------------------------------
do $$
declare
  cur text;
  newdef text;
begin
  select pg_get_constraintdef(oid) into cur
  from pg_constraint
  where conrelid = 'async_jobs'::regclass and conname = 'async_jobs_job_type_check';

  if cur is null then
    raise exception 'async_jobs_job_type_check not found';
  end if;

  if position('''paa_manifest_qa''' in cur) > 0 then
    return;  -- already registered
  end if;

  newdef := regexp_replace(cur, '\]\)\)\)\s*$', ', ''paa_manifest_qa''::text])))');
  execute 'alter table async_jobs drop constraint async_jobs_job_type_check';
  execute 'alter table async_jobs add constraint async_jobs_job_type_check ' || newdef;
end $$;
