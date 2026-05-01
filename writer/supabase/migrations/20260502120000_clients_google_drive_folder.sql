-- Add Google Drive folder ID to clients for per-client Google Docs publishing
alter table clients add column if not exists google_drive_folder_id text;
