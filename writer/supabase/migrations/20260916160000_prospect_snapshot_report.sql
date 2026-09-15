-- Prospect Snapshot: a combined one-off prospecting report (organic / maps /
-- AI-visibility / competitive-intel) rendered through the same client_reports
-- pipeline. Widen the report_type CHECK to allow the new type.

alter table public.client_reports
  drop constraint if exists client_reports_report_type_check;

alter table public.client_reports
  add constraint client_reports_report_type_check
  check (report_type = any (array[
    'monthly'::text,
    'weekly'::text,
    'ai_visibility'::text,
    'maps'::text,
    'prospect_snapshot'::text
  ]));
