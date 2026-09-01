# Domain Intelligence — User Guide

A step-by-step tutorial for the Domain Intelligence tool inside AR Tools. No code, no terminal —
everything here happens in the dashboard.

> **What this tool is.** Point it at **any domain** — a competitor, a prospect, or the client's
> own site — and get a paid, dated snapshot of its estimated organic traffic, ranked keywords,
> and authority, plus keyword-gap and competitor-discovery analysis. It's the "SEMrush clone"
> layer, distinct from **Competitive Intel** (the curated, cross-module registry of a client's
> named competitors that this tool hangs off of) and from **Backlink Explorer**.

---

## Before you start

- **No role gate** — any logged-in user can use it, but every action spends from a **shared daily
  paid-call budget** (default 200 calls/day, agency-wide). The page header always shows **"Budget
  left today: N calls"** in gray, red at zero — every trigger button disables when it hits zero.
- **Snapshots are cached 24 hours.** Re-analyzing the same domain inside that window is free and
  silently re-serves the stored snapshot — there's no "force refresh" button in the UI.
- **Standalone or per-client.** The sidebar's own **Domain Intel** entry (`/domain-intel`) is
  client-less and offers Domain lookup only; opening it from a client workspace unlocks Keyword
  gap and Discover too, since those need the client's registered competitors.

---

## The big picture

Three modes, as segmented buttons: **Domain lookup**, **Keyword gap**, **Discover**. (A fourth,
**Backlink gap**, exists on the backend but has no button in this version of the UI — see the
FAQ.)

1. **Domain lookup** — analyze any single domain.
2. **Keyword gap** — what your registered competitors rank for that the client doesn't (or ranks
   poorly for).
3. **Discover** — find new candidate competitors by SERP overlap, and add them to the registry.

---

## Step 1 — Domain lookup

Type a domain (placeholder `competitor.com`), pick a role (**Competitor / Prospect / Own site**),
and click **Analyze**. It auto-prefills with the client's own hostname on first load. History
chips below the search box let you reopen a domain you've already analyzed.

Once a snapshot exists, three sub-tabs appear:

- **Overview** — KPI tiles (est. monthly traffic, keywords ranked, Domain Rating, referring
  domains, est. traffic value) plus a "Content mix" bar showing informational/commercial/
  transactional/navigational intent split.
- **Ranked Keywords** — keyword / position / volume / CPC / KD / intent / est. value / URL, with
  **Export CSV**.
- **Pages** — ranked keywords grouped by ranking URL, with estimated traffic and value per page,
  with **Export CSV**.

---

## Step 2 — Keyword gap (client workspace only)

"Keywords your registered competitors rank for that {client} doesn't — or ranks poorly for."
**Run gap analysis** compares the client against its **Competitive Intel** registry. Each row is
tagged **missing** (client doesn't rank at all) or **weak** (client ranks worse than a set
threshold while the competitor ranks well), with an **opportunity score**. If nothing's
registered, a note tells you to add competitors in Competitive Intel first. **Export CSV** is
available here too.

---

## Step 3 — Discover

"Domains that share the most search results with {client} — candidate competitors." Click **Find
competitors** (one paid call) for a table of domain / shared keywords / avg position / organic
keywords, each with an **Add** button that registers it in Competitive Intel — already-registered
domains show a green **"Registered"** tag instead. Needs the client's website set; otherwise you
get a "Client website unknown" note.

---

## Quick reference

| I want to… | Where |
|---|---|
| Look up any domain's traffic/keywords/authority | Domain lookup tab |
| Find keywords competitors rank for that we don't | Keyword gap tab (client workspace) → **Run gap analysis** |
| Discover new competitor domains | Discover tab → **Find competitors** |
| See which pages pull the most traffic on a domain | Domain lookup → **Pages** sub-tab |
| Download a ranked-keyword list | Domain lookup → Ranked Keywords → **Export CSV** |
| Check today's remaining budget | Top of the page, next to the intro text |
| Add a discovered competitor to the registry | Discover → **Add** |
| Re-check a domain you already analyzed | Click its history chip, then Analyze (free within 24h) |

---

## FAQ

**I clicked Analyze again and nothing seemed to cost anything.**
Snapshots cache for 24 hours — re-analyzing the same domain inside that window silently re-serves
the stored snapshot for free.

**Where's the Backlink Gap tab?**
It's built on the backend but isn't wired into this version of the frontend — only Domain lookup,
Keyword gap, and Discover are clickable today.

**The Keyword Gap / Discover tabs disappeared.**
They only render inside a client workspace — the standalone sidebar entry shows Domain lookup
only, since gap/discover need a client's registered competitors.

**Discover said "Client website unknown."**
The client record needs a website URL set before Discover (or the auto-prefill) can resolve a
domain to compare against.

**Every button is greyed out.**
The shared daily paid-call budget is exhausted — it resets the next day. Check "Budget left today"
at the top of the page.
