-- Migration: 20260701120000_syndication_publish_target.sql
-- Purpose: Content Syndication switched from auto-publish to a manual
--          select-and-publish model. `publish_target` is the single per-client
--          setting for where a selected page publishes: a Google Doc, a Google
--          Sheet, or both.

alter table syndication_config
  add column if not exists publish_target text not null default 'both'
    check (publish_target in ('doc', 'sheet', 'both'));
