-- Migration: 20260622215804_rank_report_delivery.sql
-- Purpose: Organic Rank Tracker (Module #4) — optional Google-Doc delivery for
--          reports. When enabled, generated reports are also published as a
--          Google Doc in the client's Drive folder (reusing the suite's Apps
--          Script publish webhook — the locked delivery destination).

alter table rank_report_config add column if not exists deliver_google_doc boolean not null default false;
alter table rank_reports add column if not exists doc_id text;
alter table rank_reports add column if not exists doc_url text;
alter table rank_reports add column if not exists delivered_at timestamptz;
