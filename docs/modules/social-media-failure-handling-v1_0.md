# Social Media Module — Failure & Edge-Path Spec v1.0

**Status:** Companion to `social-media-module-prd-v1_0.md`. Resolves adversarial-review
item **A4** — the PRD specifies the happy path; this specifies the failure, partial,
and empty-state paths the P0/P2/P3 build must implement. Reuses the GBP-Posts
publish-lifecycle guards as the template.

## 1. Connection health (the model the PRD lacked)

`social_accounts.status` is a small state machine, not a boolean:

| status | meaning | how entered | effect |
|---|---|---|---|
| `connected` | provider reports a live token | successful connect / a passing health check | normal publishing |
| `needs_reauth` | provider reports the token expired/insufficient scope | health check or a publish attempt returns an auth error | publishing to this account **holds** (not fails); notify |
| `revoked` | the client removed our access at the platform | provider reports the connection gone | same as `needs_reauth` + surface a reconnect CTA |
| `error` | transient provider/adapter error | health check exception | retry-with-backoff; only escalate after N consecutive |

- **Health check:** a periodic `adapter.status(account)` sweep on the shared scheduler
  (daily is enough), plus an **inline check inside the publish job** immediately before
  posting (the authoritative moment).
- **Transitions notify once** (`notifications.emit`, deduped) — a client dropping to
  `needs_reauth`/`revoked` is an actionable event, not silent.
- **DORA seam:** an account `connected` but with **no successful publish in N days**, or
  any account stuck `needs_reauth`/`revoked` with **queued Posts behind it**, is a
  reconciliation flag (the PRD's "idle connected accounts" made concrete).

## 2. Token revoked/expired between approval and scheduled publish

The sharp case from the review. The publish job (freeze-gated, idempotent — GBP-Posts
template) does, in order:

1. **Freeze check** (existing) → held if frozen.
2. **Account health check** → if the account is not `connected`, the Post moves to
   **`blocked_account`** (a non-terminal hold), a `social_post_blocked` notification
   fires, and **that platform's Cadence is paused** so the autonomous loop stops
   queuing into a dead account. The job does **not** mark the Post `failed` (nothing is
   wrong with the content).
3. **Publish** via the adapter. A provider auth error at this step flips the account to
   `needs_reauth` and routes the Post to `blocked_account` (same as step 2).
4. **On reconnect** (account returns to `connected`): a sweep re-enqueues `blocked_account`
   Posts whose `scheduled_at` hasn't passed by more than a grace window, and drops
   (to `expired`, with a notification) those now stale — never silently back-posts a
   week-old "today only" offer.

## 3. Source edited / unpublished after a Draft is approved

A Draft repurposes a **Source** (a blog run, a page, a URL). If that Source changes
after the Draft is approved but before its Post publishes, the Post may point at claims
that no longer exist.

- Stamp each Draft with a **`source_version`** (a hash/`updated_at` of the Source at
  generation time).
- Before publishing, compare to the Source's current version. On mismatch → the Post
  moves to **`source_changed`** (a re-review hold), not auto-publish; notify. The human
  re-approves or regenerates.
- A **deleted/unpublished** Source → same `source_changed` hold with a "source gone"
  reason (a syndication-style dangling-backlink risk if we linked to it).

## 4. Partial fan-out failure

One Angle fans out to N per-platform Drafts in one job. A failure on one platform must
not sink the set.

- Each platform Draft is an **independent row**; the fan-out job settles them
  individually. A failed platform → that Draft is **`generation_failed`** with the
  concrete reason (e.g. `image_gen_not_configured` when the Gemini key is unset and
  nano-banana Pro no-ops, mirroring `gbp_posts_service.py`'s 503; or a copy-validation
  failure).
- The **succeeded** platforms' Drafts are fully usable and enter review normally.
- **Per-platform retry** — a `generation_failed` Draft can be regenerated alone without
  re-running the whole Angle set.
- The image is **optional**: a platform that tolerates text-only (X, Facebook) still
  yields an approvable Draft if only the image step failed; a platform that requires an
  image (Pinterest) marks the Draft `needs_image` rather than approvable.

## 5. Empty / degenerate states

| State | Handling |
|---|---|
| **Competitor with no public posts** (private/dormant handle) | The Signal records `insufficient_data` and is skipped in Angle grounding — never blocks the run; a note surfaces so the human can fix the handle. |
| **Client with zero connected accounts** enters the autonomous loop | The Social Manager loop produces **Drafts** but cannot schedule/publish; it emits a **setup task** (PACE) + a notification, and does not spend the publish budget. A client with *no* accounts and *no* Source content is a no-op (logged), not an error. |
| **No Source available** (new client, nothing generated yet) | Creator offers only "manual topic" + "competitor top-performer"; the autonomous loop no-ops with a "no source material" note rather than inventing content. |
| **Angle proposal returns nothing** (LLM failure) | Degrade to a single deterministic default Angle (repurpose-as-is) + a note; never a blank run. |

## 6. Idempotency & double-publish (reuse GBP-Posts guards)

- A Post with `provider_post_id` already set is **already published** — the publish job
  short-circuits (Guard 1).
- A Post left in `publishing` by an interrupted worker is **adopted** on requeue, not
  re-posted (Guard 2 / orphan-adopt).
- Async provider verdicts (REJECTED/LIVE) are reconciled back onto the Post by the sync
  job, emitting on newly-rejected — exactly the GBP-Posts pattern.

## 7. New Post statuses this introduces

Beyond the happy-path `draft → approved → scheduled → published`:
`blocked_account`, `source_changed`, `generation_failed`, `needs_image`, `expired`,
`rejected` (provider). All non-terminal except `published`/`expired`/`rejected`.
