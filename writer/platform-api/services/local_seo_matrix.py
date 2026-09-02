"""Local SEO — service × location matrix: the pure planner core (Phase 0).

Design: docs/modules/local-seo-matrix-plan-v1_0.md. A client offers N services
across M locations; the matrix is the persisted N×M grid of "<service>
<location>" page targets, each cell carrying its coverage state and, once
generated, its page.

This module is the **pure** half — no I/O, no settings reads, every function
unit-testable with plain dicts. It layers on two things that already exist:

  * the cross product itself comes from `local_seo_targets.build_matrix_silos`
    (#953) — there is deliberately no second implementation of "services ×
    locations → keywords" here; `cells_from_silos` only attaches slugs, axis
    positions and the rendered URL path; and
  * existing-page marking is `local_seo_silo._to_items` (#951), called by the
    store half, not re-implemented.

What is new here: the URL pattern → cell path rendering, the gap-fill diff on
axis edits, sibling internal-link selection and the deterministic link
guarantee, the runnable-cell / release-batch selectors, and the cost estimate +
scale gates. The store, API, jobs and UI (Phases 1+) call these.
"""

from __future__ import annotations

import math
import re
from html import escape
from typing import Iterable, Optional
from urllib.parse import urlparse

from services import local_seo_targets
from services.website_plan import MATRIX_SIGNOFF_THRESHOLD, slugify

# ── URL pattern → cell path ───────────────────────────────────────────────────

# Presets offered in the builder (plan §3.3). The default is WordPress-flat —
# the most common client site; the second is the Website Builder's
# location-first matrix, so a later matrix → site-plan bridge is a no-op.
DEFAULT_URL_PATTERN = "/{service}-{location}/"

# "App only" is a publish destination that keeps every generated page in the app
# (Saved Pages + the matrix grid) and never pushes it to Google Docs / WordPress
# / GitHub. A cell's terminal state stays `done`; the auto-publish-after-generate
# (drip) and the bulk "publish done cells" both short-circuit on it.
APP_ONLY = "app_only"


def publishes_externally(destination: Optional[str]) -> bool:
    """True when a destination actually pushes a page off the app. `app_only`
    (and an empty destination, which is never a real external target) do not."""
    return bool(destination) and destination != APP_ONLY
URL_PATTERN_PRESETS: tuple[str, ...] = (
    DEFAULT_URL_PATTERN,
    "/{location}/{service}/",
    "/{service}/{location}/",
)
_SERVICE_TOKEN = "{service}"
_LOCATION_TOKEN = "{location}"


def validate_url_pattern(pattern: str) -> list[str]:
    """Problems with a URL pattern, or ``[]`` when it is usable.

    Both tokens are required: a pattern missing `{location}` renders every cell of
    a service to the same path (and a pattern missing `{service}` every cell of a
    location), which would make sibling links point at the wrong page."""
    p = (pattern or "").strip()
    errors: list[str] = []
    if not p:
        return ["url_pattern_empty"]
    if _SERVICE_TOKEN not in p:
        errors.append("url_pattern_missing_service_token")
    if _LOCATION_TOKEN not in p:
        errors.append("url_pattern_missing_location_token")
    if re.search(r"\{(?!service\}|location\})[^}]*\}", p):
        errors.append("url_pattern_unknown_token")
    return errors


def render_path(pattern: str, service_slug: str, location_slug: str) -> str:
    """Substitute the tokens and normalise to ``/a/b/`` form (leading + trailing
    slash, no doubled slashes) — the same shape the Website Builder's `_path`
    produces, so paths compare cleanly across the two modules."""
    raw = (pattern or DEFAULT_URL_PATTERN).replace(_SERVICE_TOKEN, service_slug).replace(
        _LOCATION_TOKEN, location_slug
    )
    parts = [seg for seg in raw.split("/") if seg.strip()]
    return f"/{'/'.join(parts)}/" if parts else "/"


# ── cells ─────────────────────────────────────────────────────────────────────

# Cells in these states are offered for generation by default; everything else
# either already has coverage, is in flight, or is deliberately parked.
RUNNABLE_STATUSES = frozenset({"missing", "failed"})
# Pre-existing coverage — offered only when the user explicitly includes them.
COVERED_STATUSES = frozenset({"found", "on_site"})
# A cell that dropped off the axes but kept its page. Never linked, never run.
PARKED_STATUSES = frozenset({"skipped"})

_CellKey = tuple[str, str]


def cell_key(cell: dict) -> _CellKey:
    """The identity of a cell within its matrix: (service_slug, location_slug)."""
    return (cell.get("service_slug") or "", cell.get("location_slug") or "")


def cells_from_silos(
    silos: Iterable[dict],
    url_pattern: str = DEFAULT_URL_PATTERN,
    *,
    locations: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Attach slugs, axis positions and the rendered path to #953's silo shape.

    `silos` is exactly what `local_seo_targets.build_matrix_silos` returns — one
    silo per service, each page a "<service> <location>" keyword. Service order is
    the silo order; location order is the position of the page's location in
    `locations` (the matrix's location axis) when given, else the page order
    within the first silo. A page whose `location_name` was omitted (the seed-city
    base cell — see `local_seo_targets.build_matrix_silos`) recovers its location
    by stripping the service label from the keyword.

    Returns plain dicts with the DB column names (plan §2), status ``missing``."""
    loc_order: dict[str, int] = {}
    if locations is not None:
        for i, name in enumerate(locations):
            loc_order.setdefault(slugify(name), i)

    cells: list[dict] = []
    for s_idx, silo in enumerate(silos):
        service_label = (silo.get("silo") or "").strip()
        service_slug = slugify(service_label)
        if not service_slug:
            continue
        for p_idx, page in enumerate(silo.get("pages") or []):
            keyword = (page.get("keyword") or "").strip()
            location_name = (page.get("location_name") or "").strip()
            if not location_name:
                location_name = _location_from_keyword(keyword, service_label)
            location_slug = slugify(location_name)
            if not keyword or not location_slug:
                continue
            l_idx = loc_order.get(location_slug)
            if l_idx is None:
                l_idx = loc_order.setdefault(location_slug, len(loc_order) if locations is None else p_idx)
            cells.append(
                {
                    "service_label": service_label,
                    "service_slug": service_slug,
                    "location_name": location_name,
                    "location_slug": location_slug,
                    "service_order": s_idx,
                    "location_order": l_idx,
                    "keyword": keyword,
                    "path": render_path(url_pattern, service_slug, location_slug),
                    "status": "missing",
                }
            )
    return cells


def _location_from_keyword(keyword: str, service_label: str) -> str:
    """"Roof Restoration Melbourne" with service "Roof Restoration" → "Melbourne"."""
    kw, svc = keyword.strip(), service_label.strip()
    if svc and kw.lower().startswith(svc.lower()):
        return kw[len(svc):].strip()
    return kw


def diff_cells(existing: Iterable[dict], desired: Iterable[dict]) -> dict:
    """Gap-fill plan when the axes are edited.

    Returns ``{"add": [...], "remove": [...], "skip": [...], "keep": [...]}``:
      * ``add``    — desired cells with no existing counterpart (insert as
                     ``missing``);
      * ``remove`` — existing cells no longer desired that have NO page (safe to
                     delete);
      * ``skip``   — existing cells no longer desired that DO have a page — never
                     deleted, marked ``skipped`` so a finished page is never
                     orphaned by a typo on the axis;
      * ``keep``   — existing cells still desired (untouched — status, page, job
                     all preserved; a previously ``skipped`` cell that reappears on
                     the axes is returned here too, for the caller to un-park).
    Identity is (service_slug, location_slug)."""
    existing_by_key = {cell_key(c): c for c in existing}
    desired_keys = {cell_key(c) for c in desired}

    add = [c for c in desired if cell_key(c) not in existing_by_key]
    remove: list[dict] = []
    skip: list[dict] = []
    keep: list[dict] = []
    for key, cell in existing_by_key.items():
        if key in desired_keys:
            keep.append(cell)
        elif cell.get("page_id"):
            skip.append(cell)
        else:
            remove.append(cell)
    return {"add": add, "remove": remove, "skip": skip, "keep": keep}


def select_runnable(
    cells: Iterable[dict],
    cell_ids: Optional[Iterable[str]] = None,
    *,
    include_covered: bool = False,
) -> list[dict]:
    """The cells a generate request acts on.

    With no `cell_ids`, every ``missing``/``failed`` cell (plus ``found``/``on_site``
    when `include_covered`). With `cell_ids`, exactly those cells — but never one
    that is in flight, done, published or parked, so a stale UI selection can't
    re-run a cell that already has a page."""
    wanted = set(cell_ids) if cell_ids is not None else None
    allowed = RUNNABLE_STATUSES | (COVERED_STATUSES if include_covered or wanted is not None else frozenset())
    out: list[dict] = []
    for c in cells:
        if wanted is not None and c.get("id") not in wanted:
            continue
        if c.get("status") in allowed:
            out.append(c)
    return out


def select_release_batch(cells: Iterable[dict], count: int) -> list[dict]:
    """The next `count` cells a drip release should claim — runnable, unclaimed
    (`released_at` unset), walked **location-major** (every service for one
    location before the next location), so a location's silo completes sooner
    and its sibling links resolve earlier. Deterministic for a given grid."""
    if count <= 0:
        return []
    pool = [
        c for c in cells
        if c.get("status") in RUNNABLE_STATUSES and not c.get("released_at")
    ]
    pool.sort(key=lambda c: (c.get("location_order", 0), c.get("service_order", 0), c.get("keyword", "")))
    return pool[:count]


# ── sibling internal links ────────────────────────────────────────────────────

SAME_LOCATION = "same_location_other_service"
SAME_SERVICE = "same_service_other_location"


def anchor_text(cell: dict) -> str:
    """"Tile roof restoration in Hawthorn" — natural-case service + location."""
    service = (cell.get("service_label") or "").strip()
    location = (cell.get("location_name") or "").strip()
    if service and location:
        return f"{service[:1].upper()}{service[1:]} in {location}"
    return (cell.get("keyword") or "").strip()


def cell_url(cell: dict, base_url: str) -> str:
    """The URL a sibling link points at: the cell's known live URL when it is
    actually live (``on_site`` / ``published``), else the planned path under
    `base_url`. A relative path is returned when there is no base."""
    if cell.get("status") in {"on_site", "published"} and cell.get("url"):
        return str(cell["url"])
    base = (base_url or "").strip().rstrip("/")
    path = cell.get("path") or "/"
    return f"{base}{path}" if base else path


def _distance(a: Optional[tuple], b: Optional[tuple]) -> float:
    if not a or not b:
        return math.inf
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def sibling_links(
    cell: dict,
    cells: Iterable[dict],
    base_url: str = "",
    *,
    location_cap: int = 4,
    max_links: int = 10,
    coords: Optional[dict[str, tuple]] = None,
) -> list[dict]:
    """The internal links a cell's page should carry (plan §4.1):
    ``[{anchor, url, relation}]``.

      * every OTHER service in this location (`same_location_other_service`) —
        typically 2–6, the silo's spine; then
      * up to `location_cap` other locations for this service
        (`same_service_other_location`), nearest-first when `coords`
        (``{location_slug: (lat, lng)}``) covers both, else axis order.

    Hard cap `max_links` overall so a 20-location matrix cannot link-stuff.
    Parked (``skipped``) cells are never linked; the cell never links to itself."""
    me = cell_key(cell)
    others = [
        c for c in cells
        if cell_key(c) != me and c.get("status") not in PARKED_STATUSES
    ]

    same_loc = [c for c in others if c.get("location_slug") == cell.get("location_slug")]
    same_loc.sort(key=lambda c: (c.get("service_order", 0), c.get("service_slug", "")))

    same_svc = [c for c in others if c.get("service_slug") == cell.get("service_slug")]
    here = (coords or {}).get(cell.get("location_slug") or "")
    if coords and here:
        same_svc.sort(
            key=lambda c: (
                _distance(here, coords.get(c.get("location_slug") or "")),
                c.get("location_order", 0),
                c.get("location_slug", ""),
            )
        )
    else:
        same_svc.sort(key=lambda c: (c.get("location_order", 0), c.get("location_slug", "")))
    same_svc = same_svc[: max(0, location_cap)]

    out: list[dict] = []
    seen: set[str] = set()
    for relation, group in ((SAME_LOCATION, same_loc), (SAME_SERVICE, same_svc)):
        for c in group:
            if len(out) >= max_links:
                return out
            url = cell_url(c, base_url)
            if url in seen:
                continue
            seen.add(url)
            out.append({"anchor": anchor_text(c), "url": url, "relation": relation})
    return out


# ── deterministic link guarantee ──────────────────────────────────────────────

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_LINKS_BLOCK_RE = re.compile(
    r"""<section[^>]*data-matrix-links[^>]*>.*?</section>""", re.IGNORECASE | re.DOTALL
)


def _path_key(url: str) -> str:
    """Compare links by path only, trailing slash and case insensitive — the host
    of an internal link may legitimately vary (www / non-www, staging / live)."""
    try:
        path = urlparse((url or "").strip()).path or "/"
    except ValueError:
        path = url or "/"
    return path.rstrip("/").lower() or "/"


def check_internal_links(html: str, links: Iterable[dict]) -> dict:
    """Which of `links` the page actually carries.

    Returns ``{"expected": n, "present": [url, ...], "missing": [link, ...]}``.
    Matching is by URL path (see `_path_key`); a link is present when any
    ``href`` on the page resolves to the same path."""
    hrefs = {_path_key(h) for h in _HREF_RE.findall(html or "")}
    present: list[str] = []
    missing: list[dict] = []
    expected = 0
    for link in links:
        expected += 1
        if _path_key(link.get("url", "")) in hrefs:
            present.append(link["url"])
        else:
            missing.append(link)
    return {"expected": expected, "present": present, "missing": missing}


def render_links_block(
    links: Iterable[dict],
    *,
    services_heading: str = "Related services",
    areas_heading: str = "Nearby areas",
) -> str:
    """A compact, deterministic block listing `links`, grouped by relation.
    Marked with ``data-matrix-links`` so a re-run replaces rather than stacks."""
    groups: dict[str, list[dict]] = {SAME_LOCATION: [], SAME_SERVICE: []}
    for link in links:
        groups.setdefault(link.get("relation") or SAME_LOCATION, []).append(link)
    parts: list[str] = []
    for relation, heading in ((SAME_LOCATION, services_heading), (SAME_SERVICE, areas_heading)):
        items = groups.get(relation) or []
        if not items:
            continue
        lis = "".join(
            f'<li><a href="{escape(str(l.get("url", "")), quote=True)}">'
            f'{escape(str(l.get("anchor", "")))}</a></li>'
            for l in items
        )
        parts.append(f"<h3>{escape(heading)}</h3><ul>{lis}</ul>")
    if not parts:
        return ""
    return f'<section data-matrix-links="1">{"".join(parts)}</section>'


def append_links_block(html: str, block: str) -> str:
    """Insert `block` before the closing ``</article>`` (else at the end),
    replacing any earlier matrix-links block so the operation is idempotent."""
    body = _LINKS_BLOCK_RE.sub("", html or "")
    if not block:
        return body
    idx = body.lower().rfind("</article>")
    if idx == -1:
        return f"{body}\n{block}"
    return f"{body[:idx]}{block}\n{body[idx:]}"


def ensure_internal_links(html: str, links: list[dict]) -> tuple[str, dict]:
    """The guarantee (plan §4.3): whatever the writer did, the page leaves with
    every sibling link. Links the writer already placed are left alone; only the
    missing ones are appended in a compact block. Returns ``(html, coverage)``
    where coverage is the post-append `check_internal_links` result plus
    ``appended`` (how many were added by the block)."""
    before = check_internal_links(html, links)
    out = html or ""
    if before["missing"]:
        out = append_links_block(out, render_links_block(before["missing"]))
    after = check_internal_links(out, links)
    after["appended"] = len(before["missing"])
    return out, after


# ── estimate + gates ──────────────────────────────────────────────────────────


def estimate(count: int, *, cost_per_page_usd: float, minutes_per_page: float) -> dict:
    """What a run of `count` cells costs: ``{count, est_cost_usd, est_minutes}``.
    Minutes are wall-clock on the single worker (cells run back-to-back)."""
    n = max(0, int(count))
    return {
        "count": n,
        "est_cost_usd": round(n * float(cost_per_page_usd), 2),
        "est_minutes": int(round(n * float(minutes_per_page))),
    }


def scale_gates(
    total_cells: int,
    run_count: int,
    *,
    max_per_run: int,
    signoff_threshold: int = MATRIX_SIGNOFF_THRESHOLD,
    signoff_acknowledged: bool = False,
) -> list[dict]:
    """Blocking issues for a run: ``[{kind, message, blocking}]``.

      * ``matrix_signoff_required`` — the WHOLE matrix is over the Website
        Builder's link-equity sign-off line; acknowledgeable (like the builder's);
      * ``matrix_cell_limit`` — this run asks for more cells than one immediate
        batch may take; not acknowledgeable — split the run or use the drip."""
    issues: list[dict] = []
    if total_cells > signoff_threshold and not signoff_acknowledged:
        issues.append(
            {
                "kind": "matrix_signoff_required",
                "message": (
                    f"matrix is {total_cells} pages (> {signoff_threshold}) — needs sign-off "
                    "before generating"
                ),
                "blocking": True,
            }
        )
    if run_count > max_per_run:
        issues.append(
            {
                "kind": "matrix_cell_limit",
                "message": (
                    f"{run_count} cells requested; at most {max_per_run} per immediate run — "
                    "select fewer, or schedule a release"
                ),
                "blocking": True,
            }
        )
    return issues


# ── convenience: axes → cells in one step ─────────────────────────────────────


def build_cells(
    services: Iterable[str],
    locations: Iterable[str],
    *,
    url_pattern: str = DEFAULT_URL_PATTERN,
    seed_city: str = "",
) -> list[dict]:
    """Structured axes → cells, through #953's parser (so the keyword composition
    and dedup are shared byte-for-byte with the one-shot mode)."""
    locs = [l for l in (str(x).strip() for x in locations) if l]
    silos = local_seo_targets.build_matrix_silos(
        "\n".join(str(s).strip() for s in services if str(s).strip()),
        "\n".join(locs),
        seed_city=seed_city,
    )
    return cells_from_silos(silos, url_pattern, locations=locs)


# ── store-side pure helpers (Phase 1) ─────────────────────────────────────────
# Used by `local_seo_matrix_store`; kept here so they stay I/O-free + testable.


def normalize_services(raw: Iterable) -> list[dict]:
    """``["Roof restoration", {"label": "Gutters"}]`` → ``[{label, slug}]``,
    deduped by slug (first wins), blanks dropped."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        label = (item.get("label") if isinstance(item, dict) else item) or ""
        label = str(label).strip()
        slug = slugify(label)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append({"label": label, "slug": slug})
    return out


def normalize_locations(raw: Iterable) -> list[dict]:
    """``["Hawthorn", {"name": "Moorabbin", "location_code": 1234, ...}]`` →
    ``[{name, slug, location_code, canonical, source}]``, deduped by slug (first
    wins). A per-row `location_code` (+ its canonical DataForSEO name) is the
    opt-in to generate that location's cells at its own code instead of the
    matrix's metro anchor (plan §3.2)."""
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            code = item.get("location_code")
            canonical = (item.get("canonical") or "") or None
            source = (item.get("source") or "manual") or "manual"
        else:
            name, code, canonical, source = str(item or "").strip(), None, None, "manual"
        slug = slugify(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(
            {
                "name": name,
                "slug": slug,
                "location_code": int(code) if code is not None else None,
                "canonical": canonical,
                "source": source,
            }
        )
    return out


def cells_to_silos(cells: Iterable[dict], seed_city: str = "") -> list[dict]:
    """Cells → the silo shape the existing-page marking reads
    (`local_seo_silo._to_items`): one silo per service, every page carrying its
    `location_name` EXCEPT the seed-city cell (plan §3.5 — so the national
    city-less page can cover it, exactly as `build_matrix_silos` does)."""
    seed_slug = slugify(seed_city or "")
    by_service: dict[str, dict] = {}
    for c in cells:
        silo = by_service.setdefault(
            c.get("service_slug") or "", {"silo": c.get("service_label") or "", "pages": []}
        )
        page = {"keyword": c.get("keyword") or "", "supporting_keywords": []}
        if not seed_slug or (c.get("location_slug") or "") != seed_slug:
            page["location_name"] = c.get("location_name") or ""
        silo["pages"].append(page)
    return [s for s in by_service.values() if s["pages"]]


# Coverage marking may only move a cell between these three states — a cell that
# is in flight, done, published or parked is never touched by a re-check.
_COVERAGE_STATUSES = frozenset({"missing", "found", "on_site"})


def apply_coverage(cells: Iterable[dict], items: Iterable[dict]) -> list[tuple[str, dict]]:
    """Turn `_to_items` output (``[{keyword, status, url}]``) into cell patches:
    ``[(cell_id, {status, url})]`` for every cell whose coverage CHANGED. Only
    cells currently in a coverage state are eligible (never downgrade a generated
    page to ``missing``); `url` is cleared when a cell reverts to ``missing``."""
    by_kw = {(i.get("keyword") or "").strip().lower(): i for i in items}
    patches: list[tuple[str, dict]] = []
    for c in cells:
        if c.get("status") not in _COVERAGE_STATUSES:
            continue
        item = by_kw.get((c.get("keyword") or "").strip().lower())
        if not item:
            continue
        status = item.get("status") or "missing"
        url = item.get("url") if status in {"found", "on_site"} else None
        if status != c.get("status") or (url or None) != (c.get("url") or None):
            patches.append((c["id"], {"status": status, "url": url}))
    return patches


# async_jobs status → cell status for a cell's generate job.
_JOB_TO_CELL = {"pending": "queued", "running": "generating", "complete": "done", "failed": "failed"}
_GENERATING = frozenset({"queued", "generating"})
_IN_FLIGHT = frozenset({"queued", "generating", "publishing"})


def reconcile_cell_updates(cells: Iterable[dict], jobs: dict[str, dict]) -> list[tuple[str, dict]]:
    """Read-side reconciliation (plan §5.1): for every in-flight cell whose job row
    is in `jobs` (``{job_id: {status, result, error}}``), the patch that brings the
    cell up to date, or nothing when it already is.

    Generate jobs: a ``complete`` job with no ``page_id`` in its result is treated
    as failed (the generator persists the page before completing, so that would
    mean the page write was lost). Publish jobs (a ``publishing`` cell): the job
    result carries the outcome ``{status, url, error}`` the job also wrote to the
    cell directly — re-applied here in case that write was lost; a ``failed``
    job is `publish_failed`. A job row that is missing entirely (reaped/deleted)
    fails the cell so it can be re-run."""
    patches: list[tuple[str, dict]] = []
    for c in cells:
        if c.get("status") not in _IN_FLIGHT or not c.get("job_id"):
            continue
        job = jobs.get(str(c["job_id"]))
        if c.get("status") == "publishing":
            patch = _reconcile_publishing(job)
            if patch:
                patches.append((c["id"], patch))
            continue
        if job is None:
            patches.append((c["id"], {"status": "failed", "error": "job_not_found"}))
            continue
        new_status = _JOB_TO_CELL.get(job.get("status") or "", "queued")
        patch: dict = {}
        if new_status == "done":
            page_id = (job.get("result") or {}).get("page_id")
            if page_id:
                patch = {"status": "done", "page_id": page_id, "error": None}
            else:
                patch = {"status": "failed", "error": "page_missing_after_generate"}
        elif new_status == "failed":
            patch = {"status": "failed", "error": (job.get("error") or "generation_failed")[:500]}
        elif new_status != c.get("status"):
            patch = {"status": new_status}
        if patch:
            patches.append((c["id"], patch))
    return patches


def _reconcile_publishing(job: Optional[dict]) -> dict:
    """The patch for a `publishing` cell given its publish job row (or None)."""
    if job is None:
        return {"status": "publish_failed", "error": "job_not_found"}
    js = job.get("status") or ""
    if js in ("pending", "running"):
        return {}
    if js == "failed":
        return {"status": "publish_failed", "error": (job.get("error") or "publish_failed")[:500]}
    result = job.get("result") or {}
    status = result.get("status") or "publish_failed"
    if status not in {"published", "publish_failed", "publish_blocked"}:
        status = "publish_failed"
    return {"status": status, "url": result.get("url"), "error": result.get("error")}


# Cells a bulk publish acts on by default: generated but never (successfully)
# published. `publish_blocked` needs the explicit per-cell override (force_voice)
# and `published` an explicit re-publish, so both are only reachable by id.
PUBLISHABLE_DEFAULT = frozenset({"done", "publish_failed"})
PUBLISHABLE_BY_ID = frozenset({"done", "publish_failed", "publish_blocked", "published"})


def select_publishable(cells: Iterable[dict], cell_ids: Optional[Iterable[str]] = None) -> list[dict]:
    """The cells a bulk publish enqueues (plan §5.3): with no ids, every cell that
    has a page and is `done` / `publish_failed`; with ids, exactly those cells if
    they have a page and are not in flight (a `publish_blocked` cell re-tried with
    `force_voice`, or a `published` cell re-published on purpose)."""
    wanted = set(cell_ids) if cell_ids is not None else None
    allowed = PUBLISHABLE_BY_ID if wanted is not None else PUBLISHABLE_DEFAULT
    return [
        c for c in cells
        if c.get("page_id")
        and c.get("status") in allowed
        and (wanted is None or c.get("id") in wanted)
    ]


def service_labels_from_pages(per_silo: Iterable[dict], city: str) -> list[dict]:
    """The silo planner composes "<modifier> <service> <city>" keywords; the
    matrix's service axis wants "<modifier> <service>". Strip the trailing city
    (case-insensitive) → ``[{label, group}]``, deduped by slug."""
    city_l = (city or "").strip().lower()
    out: list[dict] = []
    seen: set[str] = set()
    for silo in per_silo or []:
        group = silo.get("silo") or ""
        for page in silo.get("pages") or []:
            kw = (page.get("keyword") or "").strip()
            label = kw
            if city_l and kw.lower().endswith(city_l):
                label = kw[: len(kw) - len(city_l)].strip()
            slug = slugify(label)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            out.append({"label": label, "group": group})
    return out


def coverage_counts(cells: Iterable[dict]) -> dict[str, int]:
    """``{status: count}`` over every known status (zeros included) + ``total``."""
    counts = {
        s: 0
        for s in (
            "missing", "found", "on_site", "queued", "generating", "done", "failed",
            "publishing", "published", "publish_failed", "publish_blocked", "skipped",
        )
    }
    total = 0
    for c in cells:
        total += 1
        counts[c.get("status") or "missing"] = counts.get(c.get("status") or "missing", 0) + 1
    counts["total"] = total
    return counts


# ── auto-publish outcome (drip release, plan §5.2) ────────────────────────────


def publish_outcome_from_error(detail: str) -> tuple[str, Optional[str], str]:
    """Map a failed `publish_page` into a cell outcome ``(status, url, error)``.
    A voice block (409 ``voice_violation[: words]``) is `publish_blocked` — the
    page exists and a human can "Publish anyway"; anything else is
    `publish_failed`."""
    text = (detail or "").strip() or "publish_failed"
    code = text.split(":", 1)[0].strip()
    if code == "voice_violation":
        return "publish_blocked", None, text[:500]
    return "publish_failed", None, text[:500]


def publish_outcome_from_result(result: dict) -> tuple[str, Optional[str], Optional[str]]:
    """A successful `publish_page` → ``("published", url, None)``; the URL is the
    first the destination reports (site URL, Doc URL, edit URL)."""
    url = result.get("url") or result.get("doc_url") or result.get("edit_url") or None
    return "published", url, None
