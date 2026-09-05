# Social media assets are stored in Cloudflare R2, behind a MediaStore interface

**Status:** accepted (2026-09-05)

The Social Media module publishes to platforms through PostPeer, which **fetches
media by public URL** — so every image and video the module produces or accepts
must live at a public HTTPS URL. With the owner's expected mix of **~50% short
videos and ~50% ~3-minute clips** (largest files ~200–300 MB), the dominant
storage cost is **egress**, not bytes at rest: each asset is fetched by PostPeer
and then again by the destination platform (and re-fetched during YouTube/IG
async processing). We store all of the social module's media — user-uploaded
images and videos, and AI-generated social images — in **Cloudflare R2**.

## Considered options

- **Supabase Storage** (the suite's existing store). Chosen for the P0 image
  path and kept as the fallback. Rejected as the primary for video: Supabase
  bills egress, and at 50/50 video volume repeated multi-hundred-MB fetches make
  that the deciding cost; its per-file/global upload limits also need raising.
- **AWS S3.** Rejected: a brand-new vendor (account, IAM, creds) the suite does
  not have, and it charges egress.
- **Cloudflare R2 (chosen).** **Zero egress fees** — the decisive factor for
  video fetched multiple times; **Cloudflare is already provisioned** in the
  suite (Website Builder Workers; `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`),
  so it is not a net-new vendor relationship; and it speaks the **S3 API**, so a
  standard `boto3` client and presigned uploads work.

## Consequences

- **New dependency:** `boto3` (S3 client), imported lazily in
  `services/social/media_store.py` only.
- **New credentials on PLATFORM:** `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`. R2 access keys are
  distinct from the Cloudflare API token and are minted in the R2 dashboard.
- **Swappable, like the posting adapter (ADR-0001):** a `MediaStore` interface
  (`put_bytes` for server-produced bytes such as AI images; `presigned_put_url`
  for direct browser upload of big video; `public_url`) with an `R2Store` impl
  and a `SupabaseStore` fallback. When R2 creds are absent the module degrades to
  Supabase (images only — video may exceed Supabase limits), so nothing breaks
  before provisioning.
- **Big files upload direct, not through the API:** the presigned-PUT path keeps
  200–300 MB videos out of the platform-api process and off Railway's request
  limits (the earlier read-into-memory proxy was fine only for small images).
- **Public-URL exposure:** media sits at a public URL under `R2_PUBLIC_BASE_URL`
  (a custom domain is preferred over `r2.dev` for production; presigned GET was
  rejected for video because a platform may re-fetch after the URL would expire).
  Acceptable because the media is being published publicly anyway; a later
  lifecycle/cleanup job can prune old objects.
- **Scope:** the SOCIAL module only. GBP post images, article illustrations,
  website heroes, and client logos stay on Supabase, unchanged — migrating them
  is a separate decision.
