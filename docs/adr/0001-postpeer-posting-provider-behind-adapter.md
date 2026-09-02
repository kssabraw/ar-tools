# PostPeer as the v1 social posting provider, behind a swappable adapter

**Status:** accepted (2026-09-02)

The Social Media module needs to publish to clients' own Twitter/X, Facebook,
Instagram, Pinterest and YouTube accounts with the least possible client
friction. We chose **PostPeer** (postpeer.dev) — it hosts the per-account OAuth
so a client one-click-connects their own account (no per-platform Meta/X apps for
us, no app-review on the client's side) and is cheap (~$6–8.50 / 1,000 posts).
But PostPeer is a tiny indie product with no SLA or status page, so it must not
be a single point of failure: **all publishing goes through our own posting
**adapter** interface** (`connect_url` / `post` / `status`), with PostPeer as the
first implementation and a mature provider (Ayrshare is the reference) as a
drop-in fallback.

## Considered options

- **Direct per-platform integrations** — we stand up and get reviewed our own
  Meta/X/Pinterest/Google apps. Rejected: weeks of app review, high client-side
  friction, five separate maintenance burdens.
- **A more mature unified provider (Ayrshare/Blotato) as the primary** — same
  client-friction profile as PostPeer, more expensive, still third-party. Kept as
  the adapter's fallback rather than the default, on cost.

## Consequences

- No module code depends on PostPeer directly; swapping providers is one adapter
  implementation, not a refactor.
- Two vendor facts must be confirmed before/at Phase 0 and can change the choice:
  (1) does PostPeer publish under its *own* platform-reviewed apps (→ true
  one-click connect)? (2) who pays X's **$0.20-per-link-post** tax?
- Platform realities bind us regardless of provider: Instagram publishing needs
  the client on a **Business/Creator** account; the X link tax applies to any
  posting layer.
