# PostForMe Vendor Confirm — API facts for the adapter (v1.0)

**Status:** Companion to ADR-0006 (PostForMe replaces PostPeer). Records the confirmed
PostForMe API contract the posting adapter (`services/social/postforme_adapter.py`) is
built against. Supersedes the PostPeer vendor-confirm doc for the live provider.

**Method note:** `api.postforme.dev` and `postforme.dev` are egress-blocked in the Claude
Code sandbox (same policy as Apify), so these facts come from (a) the owner running Claude
in Chrome against the live dashboard + the full OpenAPI spec at
`api.postforme.dev/docs/openapi.json` (93,921 bytes, validated), and (b) an **empirical
isolation test** in the dashboard. Where the two agree with the spec they are treated as
confirmed. The `SocialPostResultDto` field names were not in the captured spec fragment, so
the result parse is deliberately defensive.

## 1. Isolation — the load-bearing finding ✅ (empirically verified)

A PostForMe **API key is scoped to a single Project**; we run **one Project per client**.

- Structural: API keys are generated *inside* a Project (`My Team → Projects → [Project] →
  API Keys`), not at Team level.
- Empirical: a key from Project A returned that project's **12** connected accounts; a key
  from a fresh Project B returned `{"data": [], "meta": {"total": 0}}`. A second key in the
  same project saw the same 12 — so isolation is **per-project**, not per-key.
- **No project id is passed in any API call** (checked every endpoint's params in the spec).
  The Bearer key alone selects the project. Auth: *"Provide a valid API key as a Bearer
  token in the Authorization header."*

⇒ The per-client project key IS the client-isolation boundary (ADR-0006). We store it in
`social_client_credentials` (secret) and load it per client via `get_adapter(client_id)`.

## 2. Provisioning — manual (no API) ⚠️

The full endpoint list has **no `/v1/projects`, `/v1/api-keys`, or `/v1/teams`** — projects
and keys are dashboard-only. So per client, an admin creates the Project + key in the
PostForMe dashboard and pastes the key into the client's Social setup (validated live before
storing). PostPeer's auto `social_profile_provision` job does not apply on this path.

## 3. Billing / quota

Billing + the post quota **pool at the Team level** (e.g. Pro = 1,000 posts/month shared
across all projects), not per project. Per-project isolation covers accounts/keys, not
quota. Our own `social_usage` fail-closed meter does per-client spend accounting. Project
type at creation: **Quickstart** (owner choice) — uses PostForMe's system OAuth credentials,
so `redirect_url_override` on the auth-url is ignored (the redirect is the project's
dashboard-configured one); White Label is the branded/own-redirect alternative, not used.

## 4. Auth + base

- Base URL: `https://api.postforme.dev/v1`. Every endpoint: `Authorization: Bearer <key>`
  (bearerFormat JWT). Exception: `POST /v1/social-post-previews` is unauthenticated.
- **No documented structured error body** for non-2xx (just a description string), so the
  adapter's `classify_error` keys mostly off the status code.
- **No dedicated "account connected" webhook** — the event enum is
  `social.post.{created,updated,deleted}` / `social.post.result.created` /
  `social.account.{created,updated}`. We do not depend on webhooks (poll on read).

## 5. Platforms

Enum: `bluesky, facebook, instagram, linkedin, pinterest, threads, tiktok, x, youtube`
(account creation also allows `tiktok_business`). It is **`x`, not `twitter`** — the module's
internal slug is `twitter`, mapped only at the adapter boundary. YouTube posts require a
`title` (via `platform_configurations`).

## 6. Endpoints the adapter uses

| Adapter method | PostForMe call |
|---|---|
| `check_auth` | `GET /social-accounts?limit=1` (no health endpoint; 200 = key good) |
| `create_profile` | **n/a** — raises `postforme_manual_provision` (projects are dashboard-created) |
| `connect_url` | `POST /social-accounts/auth-url {platform, external_id?, permissions:["posts"], redirect_url_override?}` → `{url, platform}` |
| `list_integrations` | `GET /social-accounts` (offset/limit) → `{data:[SocialAccountDto], meta:{total}}`; the per-client key scopes it |
| `post` | `POST /social-posts {caption, social_accounts:[id], media:[{url}], platform_configurations?, external_id?}` → `SocialPostDto {id, status}`, then bounded-poll `GET /social-post-results?post_id=<id>` |

Full paths (13): `POST /media/create-upload-url`; `GET,POST /social-posts`;
`GET,PUT,DELETE /social-posts/{id}`; `GET /social-post-results`; `GET /social-post-results/{id}`;
`GET,POST /social-accounts`; `GET,PATCH,DELETE /social-accounts/{id}`;
`POST /social-accounts/auth-url`; `POST /social-accounts/{id}/disconnect`;
`POST /social-post-previews`; `GET,POST /webhooks` + `GET,PATCH,DELETE /webhooks/{id}`;
`GET /social-account-feeds/{id}` (feeds are cursor/`has_more` paginated; the rest offset/limit).

### Key schemas

- **CreateSocialPostDto:** `{caption (req), scheduled_at? (null/omitted = publish now),
  platform_configurations?, account_configurations?, media?:[SocialPostMediaDto],
  social_accounts (req): string[], external_id?, isDraft? (default false)}`. There is **no
  separate publish-now flag** — we always omit `scheduled_at` (we schedule from our own
  due-sweep). `external_id` is our own post reference (the spec's description of it is a
  copy-paste bug — it is not "an array of account ids").
- **SocialPostMediaDto:** `{url (req), thumbnail_url?, thumbnail_timestamp_ms?, tags?,
  skip_processing?}`. **URL-only** — the API infers image vs video from the content; there
  is no `type` field and no uploaded-media-id reference (the `create-upload-url` flow returns
  a `media_url` you put in this same `url`, only needed when you don't already have a public
  URL — we hand it R2 public URLs directly).
- **SocialAccountDto:** `{id (spc_…), platform, username?, user_id, external_id?, status ∈
  {connected, disconnected}, …}`. **No separate reconnect flag** — `disconnected` ⇒
  reconnect required. `access_token`/`refresh_token` come back verbatim on every read (a
  reason the list is never surfaced raw to the frontend).
- **SocialPostDto** (create/get response): `{id, external_id?, caption, status ∈ {draft,
  scheduled, processing, processed}, scheduled_at?, media?, social_accounts:[SocialAccountDto],
  created_at, updated_at}`. Per-platform result/URL is **not** here.
- **SocialPostResult** (via `/social-post-results?post_id=`): per (post, account) row with
  `success`, `error`/`details`, and `platform_data.{id,url}`. This is how a **partial
  per-platform failure** surfaces (one row per account, each independently success/failure).

## 7. Async posting (Decision 2 = A)

`POST /social-posts` is async. `post()` creates the post, then bounded-polls
`/social-post-results?post_id=<id>` (`social_postforme_result_poll_attempts` ×
`social_postforme_result_poll_interval_secs`, ~30s) for this account's row. If it arrives →
map `success`/`platform_data.url` to the `PostResult`. If not (still processing) → return
"accepted" (`ok` reflects acceptance, `post_url` empty, `provider_post_id` = the post id).
Follow-up option (B), not built: consume the `social.post.result.created` webhook or a
reconcile job to fill the URL + final status for slow platforms.

## 8. Config + activation

Config (`config.py`): `postforme_base_url`, `social_postforme_cost_per_post_usd`,
`social_postforme_result_poll_attempts`, `social_postforme_result_poll_interval_secs`. No
global key (keys are per client). Activate on PLATFORM with
`SOCIAL_POSTING_PROVIDER=postforme` (the code default stays `postpeer`, inert without a key).
