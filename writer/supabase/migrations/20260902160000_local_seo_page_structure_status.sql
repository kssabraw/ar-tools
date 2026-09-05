-- Local SEO page spec — Phase 4 structure enforcement
-- (docs/modules/local-seo-page-spec-plan-v1_0.md §5.4).
--
-- The page records the deterministic STRUCTURE verdict against its spec the
-- same way it records the length verdict: a sortable status column plus the
-- issue list (required sections, spec order, caps, block composition, FAQ
-- entry range, services sub-section band, and the per-section intent +
-- sentiment audit). Null for pages generated before specs existed.

alter table local_seo_pages
  add column if not exists structure_status text
    check (structure_status in ('ok', 'drift')),
  add column if not exists structure_issues jsonb;

comment on column local_seo_pages.structure_status is
  'Deterministic verdict of the page structure vs its spec (page_spec.structure_verdict): ok / drift. Null for pages generated before specs existed.';
comment on column local_seo_pages.structure_issues is
  'The structure verdict issue list [{key, code, detail, advisory?}] incl. per-section intent/sentiment findings from the nlp audit.';
