# PostForMe replaces PostPeer as the social posting provider

**Status:** accepted (2026-09-17). **Supersedes the provider choice in ADR-0001**
(PostPeer). ADR-0001's core decision — *all publishing goes through our own swappable
`SocialPostingAdapter` interface, no provider is a single point of failure* — **still
holds and is exactly what made this swap a contained change** (one new adapter + the
factory + config, not a refactor). PostPeer remains implemented behind the adapter as a
dormant fallback.

## Context

The agency moved off PostPeer to **PostForMe** (api.postforme.dev). PostForMe is a unified
posting API over the same nine platforms, with managed OAuth (no per-platform app review),
flat pricing (~$10 / 1,000 posts, team-pooled quota), and — decisively — a different
account model that we verified empirically before building.

## The isolation decision (the one that shaped the build)

PostPeer used **one account-wide key** with app-side "profile/Social group" scoping, so
client isolation was *our* responsibility to enforce on every call. PostForMe instead
scopes an **API key to a single Project**, and we run **one Project per client**. We
verified this is a real, provider-enforced boundary: a key from Project A returned that
project's 12 accounts; a key from Project B returned zero — the Bearer key alone selects
the project (there is no project-id parameter anywhere in the API).

**Decision:** store a **per-client PostForMe project API key** and use it as the isolation
boundary. A client's key can only ever see or post to that client's accounts, which is
stronger than app-side scoping. Consequences:

- The key is a **secret**, so it lives in a dedicated RLS/service-role-only table
  (`social_client_credentials`), never on `clients` (which is `select("*")`-ed into
  frontend responses). It is never returned to the UI — only a `{configured}` status is.
  This mirrors how the suite already stores provider secrets (`gbp_oauth_credentials`).
- `get_adapter(client_id)` loads that client's key into the adapter. `list_integrations`
  needs no filtering — the key already scopes it.
- **Provisioning is manual.** PostForMe exposes **no project/key-management API** (verified
  against the full OpenAPI spec — there is no `/v1/projects` or key endpoint), so per
  client an admin creates the Project + key in the PostForMe dashboard and pastes the key
  into the client's Social setup (validated live via `check_auth` before it's stored). This
  retires PostPeer's auto `social_profile_provision` job on the PostForMe path.
- **Quota pools at the Team level**, not per project — so per-client isolation covers
  accounts/keys, not quota. Our own fail-closed per-client budget meter (`social_usage`)
  handles per-client spend accounting; hard per-client quota would need separate PostForMe
  *Teams* and is not done (flag it only if a client ever needs a guaranteed quota).

## Other consequences

- **Posts are async.** PostForMe's `POST /v1/social-posts` returns only a status; the
  per-platform URL + real success come from `GET /v1/social-post-results` afterward. The
  adapter's `post()` bounded-polls that endpoint (~30s) and, if no result lands in the
  window, returns "accepted" (URL fills in later). The documented tradeoff: a post still
  processing past the window is recorded as accepted-without-URL.
- **Flat pricing**, so PostPeer's X-link 5/50-credit surcharge logic is gated to the
  PostPeer provider only; PostForMe posts reserve a flat `social_postforme_cost_per_post_usd`.
- Platform slug: PostForMe uses **`x`**, the module uses **`twitter`** — mapped only at the
  adapter boundary.
- **Activation** is env-driven (the suite pattern): the code default stays
  `social_posting_provider="postpeer"` (inert without a key) so a fresh env ships dark;
  PLATFORM sets `SOCIAL_POSTING_PROVIDER=postforme`. No global provider key exists.

## Alternatives considered

- **Keep PostPeer** — rejected (the agency switched vendors).
- **One team-wide PostForMe key + app-side `external_id` scoping** (the fallback if keys had
  turned out team-scoped) — unnecessary: project-scoped keys give a stronger, simpler
  boundary. `external_id` is still set (to the client id) as a reconciliation reference.
- **Rip out the profile concept entirely** — rejected: keeping `clients.social_profile_id`
  as a connected-marker (set to `'postforme'` when the key is stored) let the publish
  path's existing "is this client connected" gate work unchanged, minimising blast radius.

Authoritative API facts: `docs/modules/social-media-vendor-confirm-postforme-v1_0.md`.
