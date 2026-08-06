"""Website Builder — the site plan: which pages a site may contain.

A site plan is an **instance of the Page Type Reference catalog, not a free
composition** (PRD §4.1). This module encodes the reference's planner rules so
the inventory is derived rather than invented.

The division of labour that matters here:

* **The CORE inventory is deterministic** from the service catalog × cities.
  Reference §2 rule 2 makes it unconditional for the family, so it is computed,
  not proposed — no model is involved and no paid call is made.
* **Plan Silo contributes discovery, not structure.** It emits keyword-shaped
  groups (`{silo, pages: [{keyword, location_name}]}`) — useful for finding
  which neighborhoods and target cities exist, useless as a page inventory,
  because a keyword is not a page type and the reference is explicit that page
  type is declared by the planner and never inferred.

Everything here is pure, so the whole inventory — including the scale gates a
human signs off on — is testable without touching a database or an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

# The one definition of "the template renders this from data, so there is no
# body to write or commit" — imported rather than restated, because a page type
# that drifts between the two lists is a page that plans but never publishes.
from services.website_content import TEMPLATE_ONLY_PAGE_TYPES, UNRENDERABLE_PAGE_TYPES

# Reference v3.6 §1.2. A service, city or pillar slug colliding with one of these is
# a planning error to surface, never to silently resolve. Kept in sync with the
# template's src/lib/routes.ts — the template fails the build on the same set,
# which is the backstop for anything that slips past planning.
RESERVED_ROOT_SLUGS = frozenset(
    {
        "about-us",
        "services",
        "areas-we-serve",
        "blog",
        "contact-us",
        "privacy-policy",
        "faq",
        "specials",
        "warranty",
        "projects",
        "glossary",
        "bio",
        "compare",
        "lp",
        "reviews",
        # Module additions (PRD §4.8c), pending ratification into the reference.
        "sitemap",
        "search",
        "404",
    }
)

# `cost` is reserved at the SECOND level under a service, not at root.
RESERVED_SECOND_LEVEL = frozenset({"cost"})

# Root precedence when slugs collide (reference §1.2).
PRECEDENCE = ("utility", "service", "city", "pillar")

# The page types that legitimately own a reserved root slug. This keys on TYPE,
# not on whether a page is CORE: top-level service pages are also CORE, but a
# service named "Reviews" must still collide with the reserved /reviews/.
# Precedence is utility > service > city > pillar, and only the first tier is
# exempt.
UTILITY_PAGE_TYPES = frozenset(
    {
        "home",
        "about",
        "contact",
        "privacy",
        "blog_archive",
        "sitemap",
        "services_index",
        "areas_we_serve",
    }
)

# Scale gates (PRD §4.3).
MATRIX_SIGNOFF_THRESHOLD = 200
# **Ratified at 25** — by the owner 2026-08-05, and upstream in the reference
# itself at v3.6 §1.2 / planner rule 7, which supersedes the unratified >40
# heuristic. The number and what it counts ratify together: **body links only**,
# excluding the SOP-mandated global nav/footer set — see `links_per_index`.
# Being ratified it BLOCKS approval until acknowledged (PRD §4.3/§8.D); while it
# was advisory it could not, because a number that stops work has to be agreed
# first.
LINKS_PER_INDEX_MAX = 25
# A Services index is triggered when the nav would otherwise overflow.
SERVICES_INDEX_TRIGGER = 8

PageType = Literal[
    "home",
    "about",
    "contact",
    "privacy",
    "blog_archive",
    "sitemap",
    "services_index",
    "areas_we_serve",
    "service",
    "sub_service",
    "location",
    "neighborhood",
    "local_landing",
]

GEO_SITE_TYPES = frozenset({"local_business", "lead_gen"})


@dataclass(frozen=True)
class ServiceEntry:
    """One billable job from the client's user-entered catalog (PRD §4.10).

    Never derived from GBP categories: a category is a taxonomy label and a
    service is a billable job, so wiring one into the other would silently
    produce the wrong page inventory.
    """

    name: str
    slug: str
    teaser: str = ""
    order: int = 100
    # Per-service pruning control the catalog requires for thin cells — a minor
    # service crossed with every city is how a matrix doubles for no return.
    include_in_matrix: bool = True
    parent_slug: Optional[str] = None


@dataclass(frozen=True)
class CityEntry:
    name: str
    slug: str
    # Only neighborhoods that passed the Maps entity test belong here; the
    # geocode containment check establishes location, not entity status.
    neighborhoods: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PlannedPage:
    path: str
    page_type: str
    title: str
    # Why this page was proposed. CORE entries say so; everything else names the
    # trigger that matched, so a reviewer can see *why*, not just *that*.
    trigger: str
    tier: int = 1

    @property
    def is_core(self) -> bool:
        return self.trigger == "CORE"

    @property
    def is_core_conditional(self) -> bool:
        """Auto-triggered infrastructure (reference v3.5, note R6).

        Kept distinct from `is_core` rather than folded into it: the reference
        draws the same line, and a reviewer reads "expected on this site" very
        differently from "unconditional for the family". Both are different
        again from an optional type that happened to match a trigger.
        """
        return self.trigger.startswith("CORE-conditional")


@dataclass
class PlanIssue:
    kind: Literal[
        "reserved_slug",
        "duplicate_path",
        "matrix_signoff",
        "link_budget",
        "single_service_matrix",
        "missing_template",
        "portfolio_conflict",
    ]
    blocking: bool
    detail: str
    # Whether a human may sign this off and proceed. Scale gates are
    # "blocking until acknowledged" (PRD §4.3, §8.D) — a big matrix is a
    # judgement call, so it needs a decision, not a wall. Planning *errors*
    # (a reserved-slug collision, two entries claiming one path) are never
    # acknowledgeable: they are wrong, not large, and the fix is to edit the
    # catalog.
    acknowledgeable: bool = False


@dataclass
class SitePlan:
    pages: list[PlannedPage] = field(default_factory=list)
    issues: list[PlanIssue] = field(default_factory=list)
    matrix_count: int = 0
    links_per_index: dict[str, int] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return any(i.blocking for i in self.issues)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    return _SLUG_RE.sub("-", (value or "").lower()).strip("-")


def _path(*segments: str) -> str:
    """Every URL carries a trailing slash (reference §1.2)."""
    parts = [s.strip("/") for s in segments if s and s.strip("/")]
    return f"/{'/'.join(parts)}/" if parts else "/"


def core_pages(site_type: str) -> list[PlannedPage]:
    """The fixed pages every site gets, whatever its shape.

    On a lead_gen property these render differently — no NAP on contact, an
    About page that states the site is a matching service (PRD §4.12.2) — but
    the page set itself is the same.
    """
    pages = [
        PlannedPage("/", "home", "Home", "CORE"),
        PlannedPage(_path("about-us"), "about", "About Us", "CORE"),
        PlannedPage(_path("contact-us"), "contact", "Contact Us", "CORE"),
        PlannedPage(_path("privacy-policy"), "privacy", "Privacy Policy", "CORE"),
        PlannedPage(_path("sitemap"), "sitemap", "Sitemap", "CORE"),
    ]
    if site_type in GEO_SITE_TYPES or site_type == "informational":
        pages.append(PlannedPage(_path("blog"), "blog_archive", "Blog", "CORE"))
    return pages


def service_pages(catalog: Iterable[ServiceEntry]) -> list[PlannedPage]:
    """Top-level services at /{service-slug}/, sub-services beneath their parent.

    No /services/ prefix — local top-level pages sit at root level
    (reference §1.1 R1).
    """
    entries = sorted(catalog, key=lambda s: (s.order, s.slug))
    by_slug = {s.slug: s for s in entries}
    out: list[PlannedPage] = []

    for svc in entries:
        if svc.parent_slug and svc.parent_slug in by_slug:
            out.append(
                PlannedPage(
                    _path(svc.parent_slug, svc.slug),
                    "sub_service",
                    svc.name,
                    f"sub-service of {by_slug[svc.parent_slug].name}",
                    tier=2,
                )
            )
        else:
            out.append(PlannedPage(_path(svc.slug), "service", svc.name, "CORE"))
    return out


def location_pages(cities: Iterable[CityEntry], *, multi_city: bool) -> list[PlannedPage]:
    """City pages and their neighborhoods.

    A single-city business gets **no location pages** — its service pages
    geo-target the one city instead (reference §1.2, the explicit exception).
    """
    if not multi_city:
        return []

    out: list[PlannedPage] = []
    for city in cities:
        out.append(PlannedPage(_path(city.slug), "location", city.name, "CORE"))
        for name, slug in city.neighborhoods:
            out.append(
                PlannedPage(
                    _path(city.slug, slug),
                    "neighborhood",
                    f"{name}",
                    "Maps entity test passed",
                    tier=3,
                )
            )
    return out


def matrix_pages(
    catalog: Iterable[ServiceEntry], cities: Iterable[CityEntry], *, multi_city: bool
) -> list[PlannedPage]:
    """The service × city matrix — location-first at /{city}/{service}/.

    CORE only for multi-city businesses. Cities produce matrix cells;
    neighborhoods do not (PRD §4.12.3) — neighborhood × service is the
    hyper-specific third level, which stays escalation-only. Without that line
    15 cities × 4 neighborhoods × 10 services is 600 pages instead of 150.
    """
    if not multi_city:
        return []

    services = [s for s in catalog if s.include_in_matrix and not s.parent_slug]
    out: list[PlannedPage] = []
    for city in cities:
        for svc in sorted(services, key=lambda s: (s.order, s.slug)):
            out.append(
                PlannedPage(
                    _path(city.slug, svc.slug),
                    "local_landing",
                    f"{svc.name} in {city.name}",
                    "CORE (multi-city matrix)",
                    tier=1,
                )
            )
    return out


def conditional_pages(
    catalog: Iterable[ServiceEntry], cities: Iterable[CityEntry], *, multi_city: bool
) -> list[PlannedPage]:
    """The **CORE-conditional** hubs: auto-triggered infrastructure, not add-ons.

    Reference v3.5 (note R6) promoted both of these out of "optional /
    case-by-case". They fire on essentially every real multi-city or
    multi-service site, so the planner includes them automatically when their
    trigger is met — planner rule 2, which is explicit that they are "expected,
    not optional".

    Two consequences worth stating, because both are easy to get wrong later:

    * **Inclusion is not tier-gated.** They sit at Tier 4 ("hubs once children
      exist"), but PRD Q12's "v1 proposes Tiers 1–3 by default" is about which
      *optional* types get proposed. A CORE-conditional entry is included on its
      trigger regardless of tier; a future tier filter must not drop them.
    * **Their trigger is met long before a writer exists for them.** Both are
      Writer #6 page types (§4.7's load-bearing gap) and the house template has
      no route for either, so today they are planned, reported at plan review,
      and neither generable nor publishable. That is deliberate: the SOP's
      global nav/footer set requires Areas We Serve on a multi-city site, so
      dropping it from the plan would hide a real structural requirement rather
      than track it.
    """
    out: list[PlannedPage] = []
    top_level = [s for s in catalog if not s.parent_slug]

    if len(top_level) > SERVICES_INDEX_TRIGGER:
        out.append(
            PlannedPage(
                _path("services"),
                "services_index",
                "Services",
                f"CORE-conditional (auto): {len(top_level)} top-level services "
                f"> {SERVICES_INDEX_TRIGGER}, too many for a nav dropdown",
                tier=4,
            )
        )
    # >= 2 targeted cities. The reference adopts this threshold and flags it for
    # SOP ratification against a looser nav-overflow reading (R6) — if the SOP
    # settles on nav overflow, this is the line that changes.
    if multi_city and len(list(cities)) > 1:
        out.append(
            PlannedPage(
                _path("areas-we-serve"),
                "areas_we_serve",
                "Areas We Serve",
                "CORE-conditional (auto): multi-city site (>= 2 location pages)",
                tier=4,
            )
        )
    return out


def check_paths(pages: Iterable[PlannedPage]) -> list[PlanIssue]:
    """Reserved-slug collisions and two entries claiming one path.

    Both are blocking. The reference calls them planning errors to surface
    rather than silently resolve, and a wrong URL outlives the mistake that made
    it — published slugs are immutable, so the cost of getting this wrong is a
    permanent 301 rather than an edit.
    """
    issues: list[PlanIssue] = []
    seen: dict[str, str] = {}

    for page in pages:
        segs = [s for s in page.path.split("/") if s]

        # A utility page legitimately occupies its reserved slug; a
        # service/city/pillar claiming one is an error (precedence: utility wins).
        if page.page_type not in UTILITY_PAGE_TYPES:
            if len(segs) == 1 and segs[0] in RESERVED_ROOT_SLUGS:
                issues.append(
                    PlanIssue("reserved_slug", True, f'"{page.title}" claims reserved root slug "{segs[0]}"')
                )
        if len(segs) == 2 and segs[1] in RESERVED_SECOND_LEVEL:
            issues.append(
                PlanIssue("reserved_slug", True, f'"{page.title}" claims reserved second-level slug "{segs[1]}"')
            )

        prior = seen.get(page.path)
        if prior:
            issues.append(
                PlanIssue("duplicate_path", True, f'"{prior}" and "{page.title}" both claim {page.path}')
            )
        else:
            seen[page.path] = page.title

    return issues


INDEX_PAGE_TYPES = frozenset(
    {"location", "service", "services_index", "areas_we_serve", "blog_archive"}
)


def links_per_index(pages: Iterable[PlannedPage]) -> dict[str, int]:
    """Outbound structural body links per index page, per PRD §4.8b.

    Calculable before anything is generated precisely because structural linking
    is deterministic — the template renders these from frontmatter and no model
    is involved, so the volume follows from the plan itself.

    Counted per §4.8b's table, which is NOT the same as "pages nested under this
    path":

    * **City page** → the services offered in that city (its matrix cells), its
      neighborhoods, and the Areas We Serve page where one exists.
    * **Service page** → its sub-services **and the cities where the service is
      offered**. Those city links are the ones a path-prefix count misses
      entirely, and on a 15-city site they are the whole number.
    * **Services index** → every top-level service. **Areas We Serve** → every
      city. **Blog archive** → its published posts (zero at plan time on a local
      site; the fan-out owns an informational site's post plan).

    The global nav/footer set is deliberately NOT counted: it appears on every
    page by SOP mandate, so counting it would put every legitimate city page
    over any useful threshold and train people to ignore the number. That
    exclusion is half of what the 25 figure ratifies — the number and what it
    counts ratify together.
    """
    by_path = list(pages)
    counts: dict[str, int] = {}

    matrix = [p for p in by_path if p.page_type in {"local_landing", "hyper_local"}]
    has_areas_page = any(p.page_type == "areas_we_serve" for p in by_path)

    for page in by_path:
        if page.page_type not in INDEX_PAGE_TYPES:
            continue
        segs = [s for s in page.path.split("/") if s]

        if page.page_type == "location":
            city = segs[0] if segs else ""
            services_here = sum(1 for p in matrix if _segments(p.path)[:1] == [city])
            neighborhoods = sum(
                1
                for p in by_path
                if p.page_type == "neighborhood" and _segments(p.path)[:1] == [city]
            )
            counts[page.path] = services_here + neighborhoods + (1 if has_areas_page else 0)

        elif page.page_type == "service":
            slug = segs[0] if segs else ""
            sub_services = sum(
                1
                for p in by_path
                if p.page_type == "sub_service" and _segments(p.path)[:1] == [slug]
            )
            cities_offering = sum(
                1 for p in matrix if _segments(p.path)[1:2] == [slug]
            )
            counts[page.path] = sub_services + cities_offering

        elif page.page_type == "services_index":
            counts[page.path] = sum(1 for p in by_path if p.page_type == "service")

        elif page.page_type == "areas_we_serve":
            counts[page.path] = sum(1 for p in by_path if p.page_type == "location")

        elif page.page_type == "blog_archive":
            counts[page.path] = sum(1 for p in by_path if p.page_type == "post")

    return counts


def scale_gates(matrix_count: int, links: dict[str, int]) -> list[PlanIssue]:
    """Scale gates at plan review — blocking sign-offs, never silent truncations.

    Both are `acknowledgeable`: §4.3 and §8.D describe them as blocking *until
    acknowledged*, which is a sign-off, not a wall. Without that distinction a
    site with a legitimately large matrix could never be approved at all, and
    the only way out would be to lie to the planner.
    """
    issues: list[PlanIssue] = []

    if matrix_count > MATRIX_SIGNOFF_THRESHOLD:
        issues.append(
            PlanIssue(
                "matrix_signoff",
                True,
                f"matrix is {matrix_count} pages (> {MATRIX_SIGNOFF_THRESHOLD}) — needs human sign-off",
                acknowledgeable=True,
            )
        )

    over = {p: n for p, n in links.items() if n > LINKS_PER_INDEX_MAX}
    for path, n in sorted(over.items()):
        issues.append(
            PlanIssue(
                "link_budget",
                True,
                f"{path} carries {n} outbound structural body links "
                f"(> {LINKS_PER_INDEX_MAX}) — trim the index or split the silo",
                acknowledgeable=True,
            )
        )

    return issues


def single_service_gate(
    catalog: Iterable[ServiceEntry], *, multi_city: bool
) -> list[PlanIssue]:
    """Warn when the matrix duplicates the city pages it sits under.

    The reference has an explicit single-*city* exception (no location pages, no
    matrix) but no mirror for a single-*service* business. With one service and
    several cities, /{city}/ and /{city}/{service}/ are two pages chasing one
    query — the top-level location page's own geo term. That is a planning
    problem, not a generation one, so it surfaces here.

    Advisory rather than blocking: which of the two pages to drop is a judgement
    about the business (a one-service contractor may genuinely want the deeper
    page as the money page), and the rule itself is not in the reference yet.
    """
    matrix_services = [s for s in catalog if s.include_in_matrix and not s.parent_slug]
    if multi_city and len(matrix_services) == 1:
        slug = matrix_services[0].slug
        return [
            PlanIssue(
                "single_service_matrix",
                False,
                f'one matrix service ("{slug}"): every /{{city}}/{slug}/ targets the same '
                f"query as its /{{city}}/ page — keep one of the two per city",
            )
        ]
    return []


def template_coverage_gate(pages: Iterable[PlannedPage]) -> list[PlanIssue]:
    """Page types the house template has no way to render (PRD §4.4).

    Reported at plan review rather than discovered at publish, which is the
    failure this prevents: a planned page that can never become a URL. Today
    that is the Services index and Areas We Serve — both Writer #6's page types,
    the one archetype that unlocks five page types across both site shapes
    (PRD §4.7, Q14).

    **Blocking, but acknowledgeable** (owner ruling 2026-08-06). §4.4 calls it a
    hard stop and offers three recoveries — drop the type, add the screen in
    Claude Design and re-upload, or map it onto an existing template — none of
    which exists yet, so a bare hard stop would be a wall rather than a gate. A
    named sign-off is the honest middle: somebody records that they know these
    pages will not ship, and that record survives. When the theme compiler
    lands, drop `acknowledgeable` and this becomes §4.4 as written.

    Empty in practice today: the two hubs that used to trip it now have routes.
    It stands ready for the ⭐ extension types, which have ratified URLs and no
    templates.
    """
    missing = sorted({p.page_type for p in pages if p.page_type in UNRENDERABLE_PAGE_TYPES})
    if not missing:
        return []
    return [
        PlanIssue(
            "missing_template",
            True,
            f"the approved theme has no template for: {', '.join(missing)} — these pages "
            "cannot be generated or published; drop them, add the screen to the design, "
            "or map them onto an existing template",
            acknowledgeable=True,
        )
    ]


def build_plan(
    *,
    site_type: str,
    catalog: Iterable[ServiceEntry],
    cities: Iterable[CityEntry],
) -> SitePlan:
    """The full inventory for a site, ordered by priority tier."""
    catalog = list(catalog)
    cities = list(cities)
    multi_city = len(cities) > 1

    pages = core_pages(site_type)
    if site_type in GEO_SITE_TYPES:
        pages += service_pages(catalog)
        pages += location_pages(cities, multi_city=multi_city)
        matrix = matrix_pages(catalog, cities, multi_city=multi_city)
        pages += matrix
        pages += conditional_pages(catalog, cities, multi_city=multi_city)
    else:
        matrix = []

    links = links_per_index(pages)
    issues = (
        check_paths(pages)
        + scale_gates(len(matrix), links)
        + single_service_gate(catalog, multi_city=multi_city)
        + template_coverage_gate(pages)
    )

    pages.sort(key=lambda p: (p.tier, p.path))
    return SitePlan(pages=pages, issues=issues, matrix_count=len(matrix), links_per_index=links)


# --------------------------------------------------------------------------
# Plan row payloads — what a planned page carries into generation and publish
# --------------------------------------------------------------------------

# Page types the nlp-api local generator can write today (PRD §4.7). Everything
# else is planned but not generable, and says so rather than being promised.
NLP_PAGE_TYPES = frozenset({"service", "sub_service", "location", "neighborhood", "local_landing"})

# Written by the core-pages generator (plan §4.6), which is Phase 3 and unbuilt.
CORE_PAGE_TYPES = frozenset({"home", "about", "contact", "privacy"})


def _segments(path: str) -> list[str]:
    return [s for s in (path or "").split("/") if s]


def frontmatter_extra(
    page: PlannedPage,
    *,
    services: dict[str, ServiceEntry],
    cities: dict[str, CityEntry],
) -> dict:
    """The collection-specific frontmatter fields this page's entry needs.

    The template's zod schemas require more than title/path/pageType on two
    collections — `locations` needs `locationName`, `local-landing` needs the
    city and service on both axes — and a missing required field fails the whole
    site build, not just that page. They are derived here, at plan time, from
    the catalog the path was built from, rather than re-parsed out of the URL at
    publish time: the reference is explicit that meaning is declared, never
    inferred from segments.
    """
    segs = _segments(page.path)
    out: dict = {}

    if page.page_type in {"service", "sub_service", "brand_service"}:
        svc = services.get(segs[-1]) if segs else None
        if svc:
            out["teaser"] = svc.teaser
            out["order"] = svc.order
        if page.page_type == "sub_service" and len(segs) >= 2:
            out["parentService"] = segs[0]

    elif page.page_type == "location":
        city = cities.get(segs[0]) if segs else None
        out["locationName"] = city.name if city else page.title

    elif page.page_type == "neighborhood":
        out["locationName"] = page.title
        if len(segs) >= 2:
            out["parentCity"] = segs[0]

    elif page.page_type in {"local_landing", "hyper_local"} and len(segs) >= 2:
        city, svc = cities.get(segs[0]), services.get(segs[1])
        out["citySlug"] = segs[0]
        out["serviceSlug"] = segs[1]
        out["locationName"] = city.name if city else segs[0]
        out["serviceName"] = svc.name if svc else segs[1]
        if svc:
            out["teaser"] = svc.teaser

    return out


def generation_inputs(
    page: PlannedPage,
    *,
    services: dict[str, ServiceEntry],
    cities: dict[str, CityEntry],
    primary_service: Optional[str] = None,
    primary_city: Optional[str] = None,
) -> dict:
    """What engine writes this page, and what it needs to be told.

    Returns `{engine, keyword, location}` — `engine` is None when nothing in the
    suite can write this page type, which is deliberately visible rather than
    silently skipped (PRD §4.7: "the plan tab must not propose a page type
    without showing its engine status").

    The keyword/location split follows the SOP's targeting rules, which differ
    by page type in a way the URL alone does not carry:

    * a **service page** is never geo-targeted, so the keyword is the bare
      service and the location only scopes the SERP analysis;
    * a **location page** targets the geo head term — the primary service plus
      the city, not a specific service;
    * a **local landing page** targets the specific service in that city.
    """
    if page.page_type in TEMPLATE_ONLY_PAGE_TYPES:
        return {"engine": "template", "keyword": None, "location": None}
    if page.page_type in CORE_PAGE_TYPES:
        return {"engine": "core_pages", "keyword": None, "location": None}
    if page.page_type not in NLP_PAGE_TYPES:
        return {"engine": None, "keyword": None, "location": None}

    segs = _segments(page.path)

    if page.page_type in {"service", "sub_service"}:
        svc = services.get(segs[-1]) if segs else None
        return {
            "engine": "nlp",
            "keyword": svc.name if svc else page.title,
            "location": primary_city,
        }

    if page.page_type == "location":
        city = cities.get(segs[0]) if segs else None
        city_name = city.name if city else page.title
        head = primary_service or ""
        return {
            "engine": "nlp",
            "keyword": f"{head} {city_name}".strip(),
            "location": city_name,
        }

    if page.page_type == "neighborhood":
        parent = cities.get(segs[0]) if segs else None
        head = primary_service or ""
        return {
            "engine": "nlp",
            "keyword": f"{head} {page.title}".strip(),
            # The DataForSEO location is the city; a neighborhood is rarely a
            # resolvable location code, and the geo signal is in the keyword.
            "location": parent.name if parent else page.title,
        }

    # local_landing / hyper_local
    city = cities.get(segs[0]) if len(segs) >= 1 else None
    svc = services.get(segs[1]) if len(segs) >= 2 else None
    city_name = city.name if city else (segs[0] if segs else "")
    svc_name = svc.name if svc else (segs[1] if len(segs) >= 2 else "")
    return {
        "engine": "nlp",
        "keyword": f"{svc_name} {city_name}".strip(),
        "location": city_name,
    }


def plan_payload(
    page: PlannedPage,
    *,
    services: dict[str, ServiceEntry],
    cities: dict[str, CityEntry],
    primary_service: Optional[str] = None,
    primary_city: Optional[str] = None,
) -> dict:
    """Everything a plan row carries besides its route, type, trigger and tier."""
    inputs = generation_inputs(
        page,
        services=services,
        cities=cities,
        primary_service=primary_service,
        primary_city=primary_city,
    )
    return {**inputs, "frontmatter": frontmatter_extra(page, services=services, cities=cities)}


def matrix_cells(routes: Iterable[str]) -> set[tuple[str, str]]:
    """The (city, service) cells a set of `/{city}/{service}/` routes claims."""
    cells: set[tuple[str, str]] = set()
    for route in routes:
        segs = _segments(route)
        if len(segs) == 2:
            cells.add((segs[0], segs[1]))
    return cells


def portfolio_conflicts(
    own_routes: Iterable[str], others: Iterable[dict]
) -> list[PlanIssue]:
    """Overlapping service × city cells against every other site (PRD §4.12.4).

    Client sites never overlapped — each client had its own footprint. Owned
    properties break that, and the two collisions are not equally serious:

    * **property vs client** competes with a client for their own keywords on
      the agency's own infrastructure. That is a relationship failure, and it
      surfaces at renewal rather than at launch, so it blocks and needs an
      explicit admin override.
    * **property vs property** splits our own results, which is our problem to
      make deliberately. It warns.

    `others` rows are `{name, kind, routes}` where kind is 'client' or
    'owned_property'.
    """
    mine = matrix_cells(own_routes)
    if not mine:
        return []

    issues: list[PlanIssue] = []
    for other in others:
        overlap = sorted(mine & matrix_cells(other.get("routes") or []))
        if not overlap:
            continue
        is_client = (other.get("kind") or "client") == "client"
        shown = ", ".join(f"/{c}/{s}/" for c, s in overlap[:5])
        more = f" (+{len(overlap) - 5} more)" if len(overlap) > 5 else ""
        issues.append(
            PlanIssue(
                "portfolio_conflict",
                is_client,
                f'{"client" if is_client else "property"} site "{other.get("name") or "?"}" '
                f"already claims {len(overlap)} of these cells: {shown}{more}",
            )
        )
    return issues


def cities_from_silo_plan(per_silo: list[dict]) -> list[CityEntry]:
    """Lift discovered places out of a Plan Silo result.

    Plan Silo is a *discovery* tool here, not a page planner: it emits
    keyword-shaped groups, and a keyword is not a page type. Only its
    `location_name` values are used — the structure comes from the catalog.
    """
    by_name: dict[str, set[str]] = {}
    for group in per_silo or []:
        for page in group.get("pages") or []:
            name = (page.get("location_name") or "").strip()
            if name:
                by_name.setdefault(name, set())
    return [CityEntry(name=n, slug=slugify(n)) for n in sorted(by_name)]
