# Pinterest board — first-class field (Scope v1.0)

> Task 1 of the owner-set post-queue work (Pinterest → then P3 Manager). Scoped
> against the live codebase + owner-confirmed provider facts (2026-09-18). Build docs:
> `CLAUDE.md` / `HANDOFF.md` (this folder). Provider decision: ADR-0006 (PostForMe).

## The gap

Pinterest is wired end-to-end (posting / specs / connect / research / image), but a
Pin's **board** is pure opaque passthrough. The seeded spec (migration
`20260905120000`) says `requires_image=true` and the note *"board selection in
platform_metadata"* — but nothing writes, requires, validates, or maps a board. A
board only reaches the provider if a human types raw JSON into the composer's
Advanced-JSON box (`build_post_payload` merges `platform_specific` into
`platform_configurations.pinterest`). **Pinterest requires a board to create a Pin**, so
a boardless Pin fails at publish as a generic `postforme_invalid_request` (422).

## Owner-confirmed decisions (2026-09-18)

1. **Board entry = field-based (paste the id).** The owner verified against PostForMe's
   live OpenAPI spec (Claude-in-Chrome): **there is no board-list endpoint** — all 13
   endpoints are media / social-posts / social-post-results / social-accounts / webhooks
   / social-account-feeds; none list boards. The only place "board" appears is the input
   field **`board_ids`** (a *Pinterest board IDs **array***) in the `POST /v1/social-posts`
   (and `/social-post-previews`) request body, plus the `boards:read,boards:write` OAuth
   scopes PostForMe requests at connect time. So **a provider-driven board dropdown is not
   buildable** on PostForMe; the user pastes the numeric board id. (An undocumented
   internal dashboard endpoint may exist — deliberately **not** depended on for v1; a
   dropdown is a future fast-follow if PostForMe ever exposes boards.)
2. **Block a boardless Pin** (not warn) — a Pin with no board is a guaranteed Pinterest
   rejection, so blocking at compose/publish with an actionable error beats an opaque 422.
3. **Keep the research actor default** `epctex/pinterest-scraper` (env-overridable);
   confirm/replace on the first live P1 research run. **No code change** in this work.

## In scope

- Make **board a first-class field** on the Pinterest posting path: a single board id the
  user provides (paste), stored on the draft, **required + validated**, mapped to
  PostForMe's `board_ids` array **only at the adapter edge**, surfaced in **Compose** and
  on a **Pinterest Draft** (fan-out produces boardless Pinterest drafts → the user sets the
  board in the Drafts tab before publishing).

## Out of scope

- A provider board-list dropdown (PostForMe has no boards endpoint — decision 1).
- Multi-board pins (the `board_ids` array is sent as a single-element `[board_id]`; the
  wire shape already supports multiple, so this is a data-model change only if ever needed).
- The Pinterest research actor swap (decision 3 — deployed-only, no code).
- Any change to the other platforms' paths.

## Data model + flow

Board is stored on the existing **`social_drafts.platform_metadata`** jsonb as our
**internal** key `{"board_id": "<numeric id>"}` — the seeded spec's intended home, and
**no migration** (jsonb column already exists; `social_drafts.status` is free-text so a
new `needs_board` status also costs no migration). Provider shape stays at the edge:

```
Compose "Board ID" field ─┐
Draft "Board ID" field  ──┴─► platform_metadata.board_id  (module-internal, one id)
                                        │
                       validate_post(board_id=…) blocks a boardless Pin (hard rule)
                                        │
              run_publish_job / publish_existing_draft → adapter.post(platform_specific=…)
                                        │
        postforme_adapter edge: pinterest_config maps board_id → board_ids:[id]
                                        │
        platform_configurations.pinterest.board_ids = ["<id>"]   ► POST /v1/social-posts
```

This mirrors the **YouTube-title pattern** (queue #3) exactly — a first-class field folded
into `platform_metadata`, validated by a `validate_post` platform rule — except the
**provider-shape mapping (`board_id` → `board_ids[]`) lives at the adapter edge**, not in
`publish.py`, honoring "provider fields only at the postforme_adapter edge."

### Deployed-only confirms (sandbox is egress-blocked from PostForMe)

- **The `board_ids` placement.** Default: nested under `platform_configurations.pinterest`
  (consistent with YouTube `title` + IG/FB `placement`). The owner read `board_ids` off the
  spec as a request-body input field; the exact nesting (nested vs top-level) is confirmed
  on the **first live Pin**. The field **name** is a one-line config override
  (`social_pinterest_board_field`, default `board_ids`) if it turns out `board_id`; the
  nesting is a one-line adapter change if it turns out top-level. A wrong placement fails
  the post (not silently ignored), so it surfaces immediately on the first live Pin.

## Change set (single PR — additive, nothing else changes)

**Backend**
- `services/social/postforme_adapter.py` — pure `pinterest_config(platform,
  platform_specific)`: for Pinterest, pop internal `board_id` → emit
  `{settings.social_pinterest_board_field: [board_id]}` (array). Wired into
  `build_post_payload` so the provider shape is produced only here.
- `services/social/publish.py` — `validate_post(…, board_id=None)` adds the hard
  `pinterest_board_required` rule; `build_pinterest_config(board_id, platform_specific)`
  folds the internal `board_id` into `platform_metadata`; `create_post(…, board_id=)`
  extracts → validates → stores. (`run_publish_job` unchanged — it already passes
  `platform_metadata` to the adapter, which now maps it.)
- `services/social/fanout.py` — `publish_existing_draft` reads `board_id` from the draft's
  `platform_metadata` and passes it to `validate_post` (a boardless Pinterest draft 422s);
  `draft_status(…, board_required_missing=)` returns **`needs_board`** for a Pinterest draft
  that has media but no board; `update_draft` accepts a `board_id` (folds into
  `platform_metadata`, recomputes `needs_board ↔ ready`); `run_fanout_job` marks a
  Pinterest draft `needs_board`.
- `models/social.py` — `SocialPostCreateRequest.board_id`; `SocialDraftUpdateRequest.board_id`;
  `SocialDraftResponse.board_id` (surfaced from `platform_metadata` for the UI).
- `routers/social.py` — thread `board_id` through `create_social_post` + `update_social_draft`.
- `config.py` — `social_pinterest_board_field` (default `"board_ids"`).

**Frontend** (`SocialCompose.tsx` — keep eslint at 0)
- Compose: `isPinterest` → a **required "Board ID"** field (mirrors the YouTube-title
  block) with help text on finding a board id; added to `hints` when empty; sent as
  `board_id`. Advanced-JSON placeholder no longer suggests a board key.
- `DraftRow`: a **Board ID** field for Pinterest drafts (saved via the existing PATCH,
  now carrying `board_id`); a `needs_board` badge + gate `publishable` on a board being set.
- `errorGuidance.ts`: `pinterest_board_required` (and its `social_spec_violation:` form).

**Tests** — pure: `pinterest_config` mapping (board_id → `board_ids[]`, non-pinterest
untouched, empty board no-op), `validate_post` board rule (block vs pass, non-pinterest
unaffected), `draft_status` `needs_board`, `create_post`/`publish_existing_draft` board
threading. ruff + mypy on changed files; frontend `tsc` + eslint.

## Phasing / effort

One PR (small–medium). No migration. The provider-shape mapping is the only deployed-only
risk, isolated to one adapter helper + one config knob, surfaced on the first live Pin.
