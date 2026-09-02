# Local SEO — Plan Silo: Existing-Page Matching + Upload-Your-Own Targets — v1.0

**Status:** Built and merged to `main`.
**Owner:** Kyle
**Last updated:** 2026-09-02
**Relationship to other work:** part of the Local SEO content module (#2), inside the Plan Silo tab (`local-seo-module-integration-plan-v1_0.md`). Directly built on by **`local-seo-matrix-plan-v1_0.md`** (the durable Service × Location Matrix), which reuses everything documented here — the cross-product/list parsers, the marking, and the "Upload your own" panel — as its cell source and coverage check.

> **One-line summary.** Plan Silo's existing-page check now actually checks the client's live site against the *keyword* (not just the bare place name), so a published `<service> <city>` page is correctly flagged `on_site` instead of a false `missing` — and the team can now supply their own page targets (a services × locations matrix, or a pasted/CSV list) instead of only the AI-discovered plan, checked and bulk-created the same way.

Covers two merged PRs:

| PR | Commit (squash, `main`) | What it did |
|---|---|---|
| [#951](https://github.com/kssabraw/ar-tools/pull/951) | `0280d0f` | Fixed the false-`missing` bug; added content-word-set matchers; added national (city-less) service-page matching. |
| [#953](https://github.com/kssabraw/ar-tools/pull/953) | `8f0162f` | Added "Upload your own targets" (matrix + list/CSV); scoped the national-page match to the seed city only ("Option B"). |

---

## 1. The problem (#951)

Plan Silo (`services/local_seo_silo.py`) proposes page targets under two kinds of silo — service variations (`"<modifier> <service> <city>"`) and neighborhoods/target cities (`"<service> <sub-area>"`) — and marks each one `found` (already generated in the tool), `on_site` (already live on the client's own site), or `missing` (offer it for creation).

Before #951, the live-site check only ever looked for a **generic, bare place-name page** — a URL whose path contained an exact segment equal to the place's slug, e.g. `/inner-west/` matching "Inner West". It never checked the actual planned keyword (`"roof restoration melbourne"`) against the site at all. Two consequences:

- A client with a real, published `/roof-restoration-melbourne/` page still had "roof restoration melbourne" offered as `missing` on every replan — the tool never learned the page existed.
- Service-variation pages (which carry no `location_name` — see §2) were never checked against the live site at all; they could only resolve to `found` (an in-tool `local_seo_pages` row) or `missing`.

The fix is `services/site_page_index.py`'s new content-word-set matchers, wired into `local_seo_silo._to_items` via a new `_match_page_on_site` helper.

### Discovery: sitemap first, DataForSEO `site:` fallback

Before any matching happens, the client's live URLs have to be discovered (`site_page_index.discover_site_urls`, unchanged by either PR — it predates them, but the matching improvements only matter because it feeds them a real URL list):

1. **Sitemap** — read `robots.txt` for `Sitemap:` directives, plus the conventional `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml` paths. Sitemap-index files are followed **one level** into their child sitemaps. Bounded by `local_seo_sitemap_max_files` (30) / `local_seo_sitemap_max_urls` (5000).
2. **DataForSEO `site:<domain>` fallback** — only when no sitemap is readable at all, a live organic SERP query for `site:<domain>` supplies the URL list instead (depth `local_seo_site_index_dataforseo_depth`=100).

Discovery never raises: no website on file, no readable sitemap and no indexed pages, or a network failure all degrade to an empty URL list plus a `degraded_notes` entry explaining why (`_build_site_url_list` in `local_seo_silo.py`) — every page then shows as `missing` rather than the plan aborting.

---

## 2. The matching model

### 2.1 Content-word-set equality

The core primitive, `site_page_index.content_tokens(text)`, reduces a string to its lowercase, alphanumeric, non-generic words as a `frozenset`:

```python
content_tokens("Roof Restoration Melbourne")  # → {"roof", "restoration", "melbourne"}
content_tokens("drain-cleaning-services")     # → {"drain", "cleaning"}   ("services" dropped)
```

`_GENERIC_TOKENS` strips connectors and structural wrapper words that don't distinguish a page: `the/a/an/and/or/for/of/in/on/to/your/our/near/me`, `service(s)`, `page(s)`, `index`, file extensions (`html`/`htm`/`php`/`aspx`), and area/location directory words (`area(s)`, `location(s)`, `region(s)`, `serving`).

A live URL's path is turned into one or two such sets by `page_match_keys(url)`:

1. the **final path segment** alone — so `/roof-restoration-melbourne/` → `{roof, restoration, melbourne}`; and
2. the **union of every non-generic segment** — so a nested `/service-areas/roof-restoration/melbourne/` also reduces to `{roof, restoration, melbourne}` once the generic `service-areas` directory drops out.

Both keys are content-word **sets**, so word order never matters (`/melbourne-roof-restoration/` matches the same as `/roof-restoration-melbourne/`), while an extra distinguishing word keeps a genuinely different page distinct — `/emergency-roof-restoration-melbourne/` does **not** match `"roof restoration melbourne"`, because its key carries an extra `emergency` token the keyword doesn't have.

`build_page_token_index(urls)` builds a `{frozenset[str]: url}` map across the whole discovered URL list (first URL wins per key — sitemaps tend to list canonical pages first), and `match_site_page_for_keyword(keyword, index)` looks a keyword up by its own `content_tokens` set. A keyword whose content words are all generic (e.g. bare "services") never matches anything.

### 2.2 Content/store URLs are excluded, not matched

A URL is dropped from the index entirely — `page_match_keys` returns `[]` for it — when any of its path segments is one of `_NON_PAGE_SEGMENTS`: `blog(s)`, `post(s)`, `article(s)`, `news`, `story/stories`, `tag(s)`, `category/categories`, `topic(s)`, `author(s)`, `product(s)`, `shop`, `store`, `cart`, `checkout`, `account`, `feed`, `rss`, `search`, `privacy`, `terms`, `cookie(s)`, `sitemap`, `wp-content`, `wp-json`, `wp-admin`. This keeps a blog post that merely *mentions* a service (`/blog/why-roof-restoration-melbourne/`) or a product page from ever being read as that service's landing page.

### 2.3 National (city-less) service pages

Some businesses publish one page per service with **no geo in the slug** at all (`/roof-restoration/`) rather than one page per city. `match_site_service_page(keyword, place_name, index)` strips the place's own content words out of the keyword and looks up what remains:

```
"roof restoration melbourne" − {melbourne} → {roof, restoration} → /roof-restoration/
```

It's a strict fallback: it returns `None` when stripping the place removes nothing (an empty diff, or a diff identical to the full keyword) — that case belongs to the exact-keyword matcher in §2.1, not here. A **modified variation** still resolves to its *own* national page rather than the bare service page — `"storm damage roof restoration melbourne"` strips to `{storm, damage, roof, restoration}` and matches `/storm-damage-roof-restoration/`, never `/roof-restoration/` — so distinct variations stay distinct targets even under the city-less fallback.

### 2.4 Option B — the national match is scoped to the seed/primary city only (#953)

#951 shipped the national-service matcher scoped to *every* target, which meant one `/roof-restoration/` page could suppress every suburb and city page the plan proposed — the opposite of what a per-locality silo plan is for. #953 fixed this ("Option B" in the PR): `_match_page_on_site` (`local_seo_silo.py`) now runs the national fallback **only** for a page that carries **no `location_name`** — i.e. the seed-city base page.

```python
def _match_page_on_site(page, token_index, place_index, seed_city=""):
    for kw in [page["keyword"], *page.get("supporting_keywords", [])]:
        if url := site_page_index.match_site_page_for_keyword(kw, token_index):
            return url
    if not page.get("location_name"):
        # seed-city base page: a national city-less page counts as coverage
        return site_page_index.match_site_service_page(page["keyword"], seed_city, token_index)
    # area/other-city target: only a generic PLACE page counts — never the
    # national page
    return site_page_index.match_site_location_page(page["location_name"], place_index)
```

Every planned target carries a `location_name` **except** the one base `"<service> <city>"` page for the seed city itself (service-variation pages never carry one either — see below). So:

- The seed city's base page can be covered by a bare `/roof-restoration/` — right for a genuinely single-city business.
- A suburb ("Inner West"), a target city ("Geelong"), or any other locality-tagged target is **never** suppressed by that same national page — it's still offered, because a dedicated page per locality is the entire point of the plan.

Matching runs specific→general: exact keyword match, then the national-page fallback (seed city only), then — for `location_name`-carrying pages — a bare generic place page (`/melbourne/`, via `match_site_location_page`, unchanged from before either PR).

### 2.5 Guiding asymmetry: err toward offering

Both PRs' docstrings state the design rule explicitly, and it's worth restating because it explains every scoping choice above: **a false `on_site` silently hides a page the business should have; a false `missing` is just an ignorable extra row in the plan.** Every ambiguous case (Option B's per-locality scoping, the content/store exclusion list, the strict-fallback rule in §2.3) resolves in the direction that offers a page rather than hides one.

### 2.6 What carries `location_name`

- **Service-variation pages** (the Sonnet-generated `"<modifier> <service> <city>"` pages) never carry `location_name` — all are matched only via §2.1/§2.3 as if they were the seed-city page in Option B's terms (they're never area-scoped in the first place).
- **The seed city's own base `"<service> <city>"` page** — deliberately omitted, so Option B's national-page coverage applies to it.
- **Neighborhood/sub-area pages, and every other target city's own base page** — carry the bare place name so a generic location page can also cover them (§2.4's third branch).
- The user-uploaded matrix (§3) mirrors this exactly: every `"<service> <location>"` cell carries `location_name` *except* the cell whose location slugifies to the same seed city — see §3.2.

---

## 3. Upload your own targets (#953)

`services/local_seo_targets.py` lets the team supply their own Plan Silo page targets instead of relying on the AI planner (`local_seo_silo._generate_service_pages` + neighborhood discovery). Two input shapes, both parsed to the exact same `{"silo": name, "pages": [{keyword, supporting_keywords, location_name?}]}` list the AI planner produces, so everything downstream — marking, the bulk-create UI, the future Matrix — is shared code.

### 3.1 Matrix mode

`build_matrix_silos(services_text, locations_text, seed_city="")` takes two newline-separated lists and builds the full Cartesian product, one silo per service:

- `keyword = f"{service} {location}"`.
- Composed keywords are deduped globally (case-insensitive, first occurrence wins) — a `"Roofing"` / `"roofing"` duplicate collapses to one row.
- Blank lines are dropped.
- Every page carries `location_name = location` — **except** the cell whose location slugifies to the same `seed_city` (`slugify_place` comparison), which omits it so Option B's national-page match applies to it, mirroring how the AI planner treats its own seed-city base page (§2.6).

### 3.2 List / CSV mode

`parse_list_rows(text)` reads the pasted text through Python's `csv` reader (so plain newline-separated text and comma-separated rows both parse):

- **No header row** (no cell matches a known keyword-column alias) → columns are **positional**: column 0 is the keyword, column 1 is the group/silo.
- **A header row present** (any cell in `{keyword, keywords, page, target, topic, page target}`) → columns are matched **by name** against alias sets:
  - keyword: `keyword`, `keywords`, `page`, `target`, `topic`, `page target`
  - group/silo: `group`, `silo`, `category`, `section`, `cluster`
  - location: `location`, `location_name`, `area`, `city`, `suburb`, `place`, `neighborhood`
  - supporting keywords: `supporting`, `supporting_keywords`, `secondary`, `variants`, `also` — split on `;` or `,`, deduped, empty parts dropped.
- Rows with an empty keyword are skipped; keywords are deduped case-insensitively (first wins).

`build_list_silos(text, default_group="Custom targets")` groups the parsed rows by their `group` column (falling back to the default) into the same `{silo, pages}` shape, preserving first-seen group order.

`build_silos(input_mode, services, locations, targets, seed_city="")` is the single dispatch point both the router and the matrix-plan doc's later reuse call through — `"matrix"` → `build_matrix_silos`, anything else → `build_list_silos`.

### 3.3 Size cap

`cap_silos(per_silo, cap=3000)` trims the total page count across all silos to a **3,000-target** ceiling, dropping from the end (preserving silo and page order; a silo emptied by the trim is dropped entirely) and returning a `degraded_notes` entry only when trimming actually happened. The cap exists because a matrix's size is unbounded by the user's own input (a 500×500 paste is 250,000 combinations) — the AI plan is naturally bounded by what the LLM returns, so it needed no equivalent cap.

### 3.4 Orchestration — reuses the AI plan's marking wholesale

`plan_custom_targets(client_id, input_mode, services, locations, targets, location, location_code)`:

1. Parses the seed city out of `location` (`local_seo_silo._parse_area`).
2. Dispatches to `build_silos(...)`, then `cap_silos(...)`.
3. Calls `local_seo_silo._build_site_url_list(client_id, location_code)` — the exact same sitemap/DataForSEO discovery described in §1.
4. Calls `local_seo_silo._to_items(per_silo, client_id, site_urls, seed_city)` — the exact same found/on_site/missing marking described in §2, including in-tool `local_seo_pages` lookups (a page already generated in the tool wins over a live-site match) and the Option B national-page scoping.

No new marking logic exists for uploaded targets — they enter the identical `_to_items` codepath the AI plan uses, at the cost of one extra positional argument (`seed_city`) that was already there.

### 3.5 API and frontend

- **Endpoint:** `POST /clients/{client_id}/local-seo/custom-targets` (`routers/local_seo.py`), request/response models `LocalSeoCustomTargetsRequest` / `LocalSeoCustomTargetsResult` (`models/local_seo.py`). `input_mode: Literal["matrix", "list"]`; `services`/`locations` (matrix mode) or `targets` (list mode); `location` + optional `location_code` (resolved server-side through the shared `locations_service.resolve_location`, same as every other Local SEO route).
- **Synchronous, read-only, not freeze-gated.** The route does not call `services.freeze.assert_not_frozen` (unlike the generation/bulk-create routes it feeds into) because it only parses input and reads the client's site + `local_seo_pages` table — it creates nothing. It makes no LLM call and no paid call beyond the same sitemap-first/DataForSEO-fallback site discovery every Plan Silo run already performs. Response time is dominated entirely by that site discovery.
- **Frontend:** `components/localseo/CustomTargetsPanel.tsx`, mounted behind an **"AI plan / Upload your own"** toggle on the Plan Silo tab (`pages/LocalSeoContent.tsx`, `planMode` state). The panel has its own Matrix/List-CSV sub-toggle, a CSV file-upload affordance (appended into the same textarea the list mode reads), a "Check N targets" button, and — once checked — renders through the **same** `RelatedPagesList` + `BulkCreateBar` components the AI plan's results use, so selecting and bulk-creating the `missing` rows is identical either way.
- Actual page **creation** is unaffected by this feature: selecting targets and hitting bulk-create still goes through the existing, freeze-gated `local_seo_generate` bulk path (`enqueue_generate_bulk` / `POST …/local-seo/generate-bulk`) — this feature only changes how targets are *proposed and checked*, never how they're written.

---

## 4. Data flow (end to end)

```
AI plan:                                          Upload your own:
  seed service + city                               services × locations, OR
  → Sonnet service-variation pages                    a pasted/CSV list
  → geocode-verified Neighborhoods silo             → build_matrix_silos / build_list_silos
  → target_cities.resolve_target_cities             → cap_silos (3,000 ceiling)
    → per-city silos                                          │
              │                                                │
              └──────────────────┬─────────────────────────────┘
                                  ▼
                   local_seo_silo._build_site_url_list(client_id, location_code)
                     (sitemap discovery, DataForSEO site: fallback)
                                  ▼
                   site_page_index.build_page_token_index(site_urls)
                   site_page_index.build_location_slug_index(site_urls)
                                  ▼
                   local_seo_silo._to_items(per_silo, client_id, site_urls, seed_city)
                     for each page:
                       local_seo_pages lookup  → found (wins)
                       else _match_page_on_site → on_site / missing
                                  ▼
                   [{keyword, group, status, url, supporting_keywords}, ...]
                                  ▼
                   RelatedPagesList (select) + BulkCreateBar
                                  ▼
                   existing freeze-gated bulk-create path (local_seo_generate)
```

---

## 5. Design decisions and rationale

| Decision | Rationale |
|---|---|
| Content-word-**set** equality (not substring, not exact string) | Order-insensitive so `/melbourne-roof-restoration/` and `/roof-restoration-melbourne/` are recognized as the same page; generic wrapper words stripped so `/service-areas/` directories don't defeat nested-layout matching; but an *extra* distinguishing word (`emergency`, `commercial`, `cbd`) still keeps two pages distinct. |
| Both a final-segment key and a whole-URL non-generic-union key (`page_match_keys` returns up to two) | Covers flat layouts (`/roof-restoration-melbourne/`) and nested layouts (`/service-areas/roof-restoration/melbourne/`) with the same matcher, without needing to know the site's URL scheme in advance. |
| Content/store segments (`blog`, `product`, `shop`, …) excluded from the index entirely | A URL that *mentions* a service isn't that service's landing page; without this exclusion a blog post title containing the right words would falsely suppress a real target. |
| National-service fallback is a strict "diff must be non-empty and non-identical" check | Keeps it a true fallback — the exact-keyword matcher (§2.1) already owns the case where the place contributes nothing to the diff; without the guard the fallback could accidentally re-match what the primary matcher already covers or over-match on a place-less keyword. |
| Option B: national match scoped to the seed-city base page only, never to any target with a `location_name` | The earlier (#951) unscoped version let one national page suppress every locality target the plan proposed — directly contradicting the point of a per-locality silo plan. Scoping to "no `location_name`" reuses the exact same field the AI planner already sets (or omits) per page, so no new page attribute was needed. |
| Guiding asymmetry: prefer a false `missing` over a false `on_site` | A hidden wanted page is a silent, hard-to-notice failure (the business never gets offered a page it needs); an extra `missing` row is a one-click ignore. Every close call in the matcher design resolves this way. |
| Upload-your-own reuses `_to_items`/`_build_site_url_list` wholesale rather than a parallel marking path | One marking implementation for both AI-discovered and user-supplied targets means every future fix to matching (like Option B) benefits both paths automatically, and the Matrix module built afterward could adopt the same call shape with zero new marking code. |
| `/local-seo/custom-targets` is synchronous, not an `async_jobs` job | Unlike page generation, it does no LLM call and its only network cost is the same sitemap discovery Plan Silo already performs synchronously-inline (well under typical request timeouts); making it a job would add polling overhead for no real benefit. |
| Not freeze-gated | It's read-only — it never creates a page, doc, or job that writes content. Freeze only needs to gate the point where content is actually produced or published, which stays the existing bulk-create/generate path. |
| 3,000-target cap on uploaded matrices | A user-declared matrix has no natural size bound the way an LLM-bounded AI plan does; the cap protects the synchronous response and any downstream bulk-create from a pathological paste (e.g. 500×500). |

---

## 6. Known limitations (as built)

- **One batch location per check.** Both matrix and list modes take a single `location`/`location_code` for the whole batch — every target is checked and would generate under that one area's SERP/DataForSEO context, even if a matrix logically spans multiple metros. Per-combination location codes are an explicit, acknowledged follow-up (picked up by the later Service × Location Matrix plan, which the local-seo-matrix-plan-v1_0.md doc describes as its own "§3.2" scope).
- **The frontend's pre-check count is pre-dedup.** `CustomTargetsPanel.tsx`'s `matrixCount` (shown on the "Check N targets" button before submission) is the raw `services × locations` product, computed client-side from line counts — it does not account for the backend's case-insensitive dedup in `build_matrix_silos`/`parse_list_rows`. The actual number of distinct targets checked can be lower than what the button displays; the real count only appears after the check completes (in the results summary strip).
- **No route-level or frontend unit tests.** Per this repo's existing testing convention (pure service-logic units, mocked; no FastAPI `TestClient` harness), both PRs test the pure parsing/matching functions directly (`test_site_page_index.py`, `test_local_seo_silo.py`, `test_local_seo_targets.py`) but not the FastAPI route itself or the React components — those are verified by `tsc`/build and manual testing, matching how the rest of the Local SEO frontend is covered.
- **The AI planner's national-page Option B scoping is implicit, not attribute-driven beyond `location_name`.** A page is treated as "the seed-city base page" purely by the absence of `location_name` — there is no explicit `is_seed_city_base` flag. This is intentional (reuses an existing field) but means any future silo/page kind that omits `location_name` for an unrelated reason would also, silently, become eligible for national-page coverage; anyone adding a new page kind should check this before leaving `location_name` unset.
- **`LocalSeoSiloPlanItem.status`'s docstring is stale.** `models/local_seo.py` documents the field as `'found' (a page already exists) | 'missing'` — it does not mention `'on_site'`, even though `_to_items` has produced that third status since #951. The code (`local_seo_silo._to_items`) is authoritative; the docstring should read `'found' | 'on_site' | 'missing'`. Not fixed here since this document is describing shipped behavior, not amending code.

---

## 7. Pointers into the code

| Concern | File |
|---|---|
| URL discovery (sitemap + DataForSEO fallback) | `writer/platform-api/services/site_page_index.py` — `discover_site_urls`, `_fetch_sitemap_urls`, `_fetch_google_indexed_urls` |
| Content-word-set matchers (pure) | `writer/platform-api/services/site_page_index.py` — `content_tokens`, `page_match_keys`, `build_page_token_index`, `match_site_page_for_keyword`, `match_site_service_page`, `build_location_slug_index`, `match_site_location_page` |
| Plan Silo marking (found/on_site/missing) | `writer/platform-api/services/local_seo_silo.py` — `_to_items`, `_match_page_on_site`, `_build_site_url_list`, `_parse_area` |
| Upload-your-own parsers + orchestration | `writer/platform-api/services/local_seo_targets.py` — `build_matrix_silos`, `parse_list_rows`, `build_list_silos`, `build_silos`, `cap_silos`, `plan_custom_targets` |
| Request/response models | `writer/platform-api/models/local_seo.py` — `LocalSeoCustomTargetsRequest`, `LocalSeoCustomTargetsResult`, `LocalSeoSiloPlanItem` |
| Route | `writer/platform-api/routers/local_seo.py` — `POST /clients/{client_id}/local-seo/custom-targets` |
| Tests | `writer/platform-api/tests/test_site_page_index.py`, `test_local_seo_silo.py`, `test_local_seo_targets.py` |
| Frontend panel + toggle | `frontend/src/components/localseo/CustomTargetsPanel.tsx`, `frontend/src/components/localseo/api.ts` (`customTargets`), `frontend/src/components/localseo/types.ts` (`CustomTargetsResult`), `frontend/src/pages/LocalSeoContent.tsx` (`planMode` toggle) |
