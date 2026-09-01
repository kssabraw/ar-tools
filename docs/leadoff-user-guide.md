# LeadOff — User Guide

A step-by-step tutorial for LeadOff inside AR Tools. No code, no terminal — everything here
happens in the dashboard.

> **What this tool is.** LeadOff is the agency's **pre-client** market-selection tool — "which
> city/category should we go pursue next," graded across tens of thousands of scanned US
> city×category markets. It has no per-client view of its own; the one bridge into the rest of the
> suite is the **"Create client from this market"** handoff. It is not a rank tracker, not a
> reporting tool, and not something you use once a client already exists.

---

## Before you start

- **Anyone logged in can browse.** The graded board, a market brief, and Neighborhoods are free,
  read-only, and open to any role.
- **Spending money or creating a client needs staff/admin.** Tryout, Scout, Map refresh, City
  Finder, and the create-client handoff are all staff-role actions — a `team_member` (VA) account
  can look but not spend or create.
- **A per-user daily budget guard.** Every paid action checks a shared **$5.00/user/day** cap
  before running; hit it and you're told to wait until tomorrow.
- **Grades, Beatability, Proximity, and Placement are all reading aids** layered on top of the raw
  sabermetric grade — none of them (except the enrichment layer described below) change the grade
  itself; they help you interpret it.

---

## The big picture

1. Start on the **graded board** — filter/sort scanned markets by category, city, or county.
2. Drill into a **Market Brief** for the economics, the competitive field, and where the field is
   weak.
3. When a market isn't on the board (or a category was never scanned), spend a little to check it
   with **Tryout** or find cities with **City Finder**.
4. Deepen an already-promising market's brief with a **Scout** pull.
5. When you're ready, **create a client** straight from the brief — it pre-seeds competitors and
   goals.

---

## Step 1 — Browse the graded board

Sidebar → **LeadOff**. The board shows every scanned market with a grade (**A+** through **F**),
sortable by **Opportunity** (default — a "hidden gem" score), **Grade** (raw value), **ROI**,
**Profit**, **Expected $/mo**, **Expected leads**, or **Demand**.

- **Smart search** — free text like *"roofers in Cleveland"* — one AI call resolves it to a
  scanned category + location.
- **Filters**: City, State, County (once a state is typed), Category, Min demand, plus assumption
  sliders — **Capture %** (the realistic share of demand you'd win once ranked) and a **Lead
  value** preset (Conservative/Mid/Optimistic).
- **HOT?/COLD?** badges flag demand that's 2× (or 0.5×) the city norm — worth a manual double-check
  before trusting it.
- **Beatability** chip (Soft/Moderate/Tough) — a reading aid summarizing how weak the field is; it
  never feeds the grade.
- **Export CSV**, and client-side pagination (50 rows/page).

Click any row to open its **Market Brief** in a side panel.

---

## Step 2 — Read a Market Brief

- **Economics** — Opportunity score, Expected $/mo, win likelihood, profit after costs, payback
  period, a cost breakdown, and regressed demand.
- **Field forensics** — Beatability, reviews needed to beat #3, how the field compares to
  comparable cities, and the top-5 competitor list (with a footprint sub-line: site pages, brand
  mentions, NAP mentions).
- **Scouting report** — link gap (true RD), review velocity, momentum, demand growth — populated
  only after a **Scout** has run; otherwise it tells you so.
- **Proximity** — an octant coverage map of where competitors defend the territory, underserved-
  direction callouts, and (once live GBP pins exist) the **Placement Advisor**'s suggested "best
  areas to plant a GBP" zones, plus a candidate scorer for any specific address.

---

## Step 3 — Paid actions (staff/admin only)

Every paid action shows its estimated cost before you commit:

| Action | Roughly | For |
|---|---|---|
| **Tryout** | ~$0.20 typical (reserves up to $1 worst-case) | Score any off-list US city ≥10k population |
| **Scout** | ~$0.10–1, cache-cheapened | Fill in RD, review velocity, and demand trend for a market's brief |
| **Map refresh** | ~$0.004 | Just re-pull the live competitor GBP pins for the map |
| **City Finder** | ~$0.06/city (API-only — reachable via SerMaStr chat, not a page in this UI) | Find cities for a category not yet on the board |

All of these are async — you can leave and check back.

---

## Step 4 — Create a client from a market

At the bottom of a Market Brief, **"Create client from this market"** — name required, website
optional (LeadOff is research-first). On submit it creates the client through the normal path,
seeds the top-5 board competitors into Competitive Intel, and records the effort targets (reviews
to beat #3, link budget) as a campaign goal — then takes you straight to the new client workspace.

---

## Step 5 — Neighborhoods

A separate precomputed tab of nameable sub-area combos (neighborhoods/districts), filterable by
metro/state/service, sorted by demand or ROI — note supply is approximately the parent metro's, so
pick these on demand and economics, not the competition columns.

---

## Quick reference

| I want to… | Where |
|---|---|
| Find graded markets for a category | The board → filter by Category (or Smart search) |
| See the economics and competitors for one market | Click a board row → Market Brief |
| Score an off-list city | Market Brief → **Run tryout** (staff/admin) |
| Get deeper competitor/link/trend data on a market | Market Brief → **Scout this market** (staff/admin) |
| Just refresh the competitor map | **Map refresh (~$0.004)** |
| Find cities for a category not on the board | Ask SerMaStr, or `City Finder` via the API |
| Turn a market into a real client | Market Brief → **Create client from this market** |
| See sub-area (neighborhood) targets | **Neighborhoods** tab |
| Check today's remaining spend | The per-user daily budget guard, shown before each paid action |

---

## FAQ

**Why does the Tryout badge say ~$0.20 but my budget dropped more?**
The badge shows a typical cost; the system reserves a worst-case amount against your daily budget
up front — the actual charge is usually lower.

**I can't run a Tryout or create a client.**
Those need the staff or admin role — a `team_member` account can browse and read but not spend or
create.

**I can't find "City Finder" anywhere on the LeadOff page.**
There's genuinely no tab for it in this version of the UI — it's reachable today only through the
API or by asking SerMaStr in chat.

**The Proximity/Placement cards say "not scouted yet."**
The live-GBP map and the Placement Advisor's zones only populate once a Scout or Tryout has
captured real competitor GBP pins for that market — before that you only see the lower-fidelity
Census-centroid octant bars.

**Why can't I create a client as a VA?**
Client creation from LeadOff is a staff-role action, same as everywhere else client creation
happens in the suite.
