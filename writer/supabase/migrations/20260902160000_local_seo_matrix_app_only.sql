-- Local SEO matrix: add an "App only" publish destination.
--
-- "App only" keeps every generated page in the app (Saved Pages + the matrix
-- grid) and never pushes it to Google Docs / WordPress / GitHub. A cell's
-- terminal state stays `done`; the drip auto-publish and the bulk "publish done
-- cells" both short-circuit on it (services/local_seo_matrix.publishes_externally).

alter table public.local_seo_matrices
  drop constraint if exists local_seo_matrices_publish_destination_check;

alter table public.local_seo_matrices
  add constraint local_seo_matrices_publish_destination_check
  check (publish_destination in ('app_only', 'google_docs', 'wordpress', 'github'));
