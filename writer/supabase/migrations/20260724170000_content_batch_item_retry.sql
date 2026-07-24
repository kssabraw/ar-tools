-- Content-batch item transient-failure retry.
--
-- Content-scheduler runs (blog/service/location) drive the orchestrator
-- synchronously and, per the run-level auto-retry hardening, disarm the
-- orchestrator's background retry (disarm_scheduled_retry) on the assumption the
-- driver owns recovery. The fanout scheduler does (fanout/writer/scheduler.py
-- _retry_or_fail), but the content-batch handler did NOT — a transient failure
-- (e.g. a DataForSEO SERP outage) marked the item terminally failed with nothing
-- to re-run it, so scheduled blog posts silently died during an outage.
--
-- retry_attempt lets the content-batch handler re-schedule an item after a
-- transient failure (status back to 'scheduled' with a future scheduled_at,
-- re-released by the shared scheduler's due-check) up to run_transient_retry_max,
-- with the same 5/15/45-min backoff the orchestrator uses. Bookkeeping and
-- auto-publish stay inside the handler on the eventual successful attempt.

alter table content_batch_items
    add column if not exists retry_attempt integer not null default 0;
