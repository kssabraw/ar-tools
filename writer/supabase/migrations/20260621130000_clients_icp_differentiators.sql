-- Migration: 20260621130000_clients_icp_differentiators.sql
-- Purpose: Suite-wide structured ICP + differentiators as client-level assets,
-- converged (Option A) the same way as brand_voice.
--
--   * detected_icp  — { source, raw_text, segments, reasoning, generated_at,
--                       edited_at }. Canonical store; provenance in `source`
--                       ('user'|'app') governs supersede for BOTH ICP and
--                       differentiators (they're produced by one LLM call).
--   * differentiators — [ { claim, mechanism, type } ].
--
-- Consumers: Local SEO (nlp-api) reads detected_icp.segments + differentiators
-- directly; the Blog Writer reads free text, so detected_icp (+ a folded
-- differentiators block) is rendered into its run snapshot's icp_text.
--
-- Existing hand-written icp_text is preserved by seeding it as a user-authored
-- block (source:'user', raw_text passthrough) so nothing is lost and manual
-- input continues to supersede after convergence.

alter table clients add column if not exists detected_icp   jsonb;
alter table clients add column if not exists differentiators jsonb;

comment on column clients.detected_icp is
  'Structured ICP (converged, Option A). Shape: { source: user|app, raw_text, '
  'segments, reasoning, generated_at, edited_at }. Provenance governs supersede '
  'for both ICP and differentiators. Rendered into the Blog Writer snapshot icp_text.';
comment on column clients.differentiators is
  'Differentiators [ { claim, mechanism, type } ], generated alongside detected_icp.';

-- Seed: preserve any existing free-text ICP as a user-authored block.
update clients
set detected_icp = jsonb_build_object(
      'source',       'user',
      'raw_text',     icp_text,
      'segments',     null,
      'reasoning',    null,
      'generated_at', null,
      'edited_at',    to_char(now() at time zone 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    )
where coalesce(icp_text, '') <> ''
  and detected_icp is null;
