-- Migration: 20260711160000_task_attachments_bucket.sql
-- Purpose: Native task manager Phase 2 (collaboration) — the private storage
--          bucket for task attachments (PRD §6.10). Files are keyed
--          "<task_id>/<uuid>-<safe name>"; reads go through signed URLs, so
--          the bucket stays private (unlike client-logos / wordpress_images).
--          20 MB per file.

insert into storage.buckets (id, name, public, file_size_limit)
values ('task-attachments', 'task-attachments', false, 20971520)
on conflict (id) do nothing;
