-- Integration tests for migration 20260507120000_fanout_sourced_silo_auto_approve.sql.
-- Run against a freshly migrated database: psql -v ON_ERROR_STOP=1 -f this-file.
-- Wrapped in a single transaction with rollback at the end; safe to re-run.

begin;

-- Test fixtures: one client + two run rows, reused across cases.
-- Uses fixed UUIDs to keep assertions readable.
do $$
declare
  v_client_id uuid := '11111111-1111-1111-1111-111111111111';
  v_run_id    uuid := '22222222-2222-2222-2222-222222222222';
begin
  insert into clients (
    id, name, website_url,
    brand_guide_source_type, brand_guide_text,
    icp_source_type, icp_text
  ) values (
    v_client_id, 'Trigger Test Client', 'https://example.com',
    'text', '',
    'text', ''
  ) on conflict (id) do nothing;

  insert into runs (id, client_id, keyword, status)
    values (v_run_id, v_client_id, 'trigger test seed', 'complete')
    on conflict (id) do nothing;
end $$;

-- ------------------------------------------------------------------
-- Case 1: fanout-sourced insert auto-approves.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-1 fanout sourced',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text": "h", "source": "llm_fanout_chatgpt"}]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-1 fanout sourced';
  if v_status is distinct from 'approved' then
    raise exception 'Case 1 failed: expected approved, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 2: non-fanout source stays proposed.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-2 serp only',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text": "h", "source": "serp"}, {"text": "h2", "source": "paa"}]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-2 serp only';
  if v_status is distinct from 'proposed' then
    raise exception 'Case 2 failed: expected proposed, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 3: mixed sources (fanout present alongside SERP) auto-approves.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-3 mixed',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text": "h", "source": "serp"}, {"text": "h2", "source": "llm_fanout_perplexity"}]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-3 mixed';
  if v_status is distinct from 'approved' then
    raise exception 'Case 3 failed: expected approved, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 4: explicit non-proposed status is preserved.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    status,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-4 explicit rejected',
    array_fill(0.0, array[1536])::vector,
    'rejected',
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text": "h", "source": "llm_fanout_claude"}]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-4 explicit rejected';
  if v_status is distinct from 'rejected' then
    raise exception 'Case 4 failed: expected rejected, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 5: null source_headings → status stays proposed (no crash).
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-5 null headings',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    null
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-5 null headings';
  if v_status is distinct from 'proposed' then
    raise exception 'Case 5 failed: expected proposed, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 6: empty source_headings array → status stays proposed.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-6 empty headings',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-6 empty headings';
  if v_status is distinct from 'proposed' then
    raise exception 'Case 6 failed: expected proposed, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 7: lookalike non-fanout sources do NOT auto-approve.
-- Confirms `starts_with` matches the literal prefix exactly (no LIKE
-- wildcard quirks).
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-7 lookalikes',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[
      {"text":"a","source":"llm_response_chatgpt"},
      {"text":"b","source":"llmAfanoutB"},
      {"text":"c","source":"llm_fanouted"}
    ]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-7 lookalikes';
  if v_status is distinct from 'proposed' then
    raise exception 'Case 7 failed: expected proposed, got %', v_status;
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 8: race amplification — duplicate non-rejected (client_id,
-- suggested_keyword) insert is rejected by the unique partial index.
-- ------------------------------------------------------------------
do $$
declare
  v_caught boolean := false;
begin
  begin
    insert into silo_candidates (
      client_id, suggested_keyword, suggested_keyword_embedding,
      first_seen_run_id, last_seen_run_id, source_run_ids,
      source_headings
    ) values (
      '11111111-1111-1111-1111-111111111111',
      'case-1 fanout sourced',  -- already inserted in Case 1
      array_fill(0.0, array[1536])::vector,
      '22222222-2222-2222-2222-222222222222',
      '22222222-2222-2222-2222-222222222222',
      array['22222222-2222-2222-2222-222222222222'::uuid],
      '[{"text":"h","source":"llm_fanout_gemini"}]'::jsonb
    );
  exception when unique_violation then
    v_caught := true;
  end;

  if not v_caught then
    raise exception 'Case 8 failed: expected unique_violation on duplicate keyword';
  end if;
end $$;

-- ------------------------------------------------------------------
-- Case 9: rejected row does NOT block a fresh fanout proposal.
-- A previously-rejected fanout silo with the same keyword should not
-- prevent a new fanout-sourced row from auto-approving.
-- ------------------------------------------------------------------
do $$
declare
  v_status text;
begin
  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    status,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-9 keyword',
    array_fill(0.0, array[1536])::vector,
    'rejected',
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text":"h","source":"llm_fanout_chatgpt"}]'::jsonb
  );

  insert into silo_candidates (
    client_id, suggested_keyword, suggested_keyword_embedding,
    first_seen_run_id, last_seen_run_id, source_run_ids,
    source_headings
  ) values (
    '11111111-1111-1111-1111-111111111111',
    'case-9 keyword',
    array_fill(0.0, array[1536])::vector,
    '22222222-2222-2222-2222-222222222222',
    '22222222-2222-2222-2222-222222222222',
    array['22222222-2222-2222-2222-222222222222'::uuid],
    '[{"text":"h","source":"llm_fanout_chatgpt"}]'::jsonb
  );

  select status into v_status from silo_candidates
    where suggested_keyword = 'case-9 keyword' and status <> 'rejected';
  if v_status is distinct from 'approved' then
    raise exception 'Case 9 failed: expected approved (despite prior rejection), got %', v_status;
  end if;
end $$;

rollback;

-- All tests pass when this file runs without raising.
\echo 'silo fanout auto-approval trigger: all cases passed'
