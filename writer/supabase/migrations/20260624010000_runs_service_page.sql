-- ============================================================
-- runs: add the service_page content type
-- ============================================================
-- The Service / Landing page content type runs through the existing
-- runs/module_outputs pipeline (so silos + Drive publish come for free)
-- via a distinct two-stage path: service_brief -> service_writer. A
-- content_type discriminator selects the path; service/location columns
-- carry the (keyword-only, optional-location) service-page inputs. Two new
-- status values track the service-page stages. content_type defaults to
-- 'blog_post' so existing rows + the blog pipeline are unaffected.
-- ============================================================

alter table runs add column if not exists content_type text not null default 'blog_post';
alter table runs add column if not exists service text;
alter table runs add column if not exists location text;
alter table runs add column if not exists location_code integer;

alter table runs drop constraint if exists runs_content_type_check;
alter table runs add constraint runs_content_type_check
  check (content_type in ('blog_post', 'service_page'));

-- Extend the status taxonomy with the two service-page stages.
alter table runs drop constraint if exists runs_status_check;
alter table runs add constraint runs_status_check check (status in (
  'queued',
  'brief_running', 'sie_running', 'research_running', 'writer_running',
  'sources_cited_running',
  'service_brief_running', 'service_writer_running',
  'complete', 'failed', 'cancelled'
));
