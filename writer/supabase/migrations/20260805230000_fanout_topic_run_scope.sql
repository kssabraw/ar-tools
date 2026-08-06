-- Fanout: per-silo run scope, independent of the deep-mine gate.
--
-- `is_gated_for_competitor_mining` only ever controlled competitor mining (the
-- paid SERP -> ranked-keywords step); expansion, the relevance gate, clustering
-- and article planning always covered every finalized silo. The deep-mine screen
-- read like it scoped the whole run, so a user who picked 3 of 5 silos still got
-- all 5 expanded. This column carries the *run* scope so the two can be chosen
-- independently: a silo can be in the run without being deep-mined.
--
-- Defaults to true so every existing session keeps its current behaviour.

alter table fanout.topics
  add column if not exists is_in_run_scope boolean not null default true;

comment on column fanout.topics.is_in_run_scope is
  'Whether this silo takes part in the keyword run (expansion, relevance gate, '
  'clustering, article planning). Independent of is_gated_for_competitor_mining, '
  'which only adds competitor mining on top. Default true.';
