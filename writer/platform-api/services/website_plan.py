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

# Reference §1.2. A service, city or pillar slug colliding with one of these is
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
# The >40 figure is UNRATIFIED in the reference and was ruled too high by the
# owner (2026-08-04). Advisory only until a figure is ratified into the SOP's
# link-equity section — it must not block approval.
LINKS_PER_INDEX_ADVISORY = 25
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


@dataclass
class PlanIssue:
    kind: Literal["reserved_slug", "duplicate_path", "matrix_signoff", "links_advisory"]
    blocking: bool
    detail: str


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
    """Non-CORE pages, each carrying the trigger that matched it."""
    out: list[PlannedPage] = []
    top_level = [s for s in catalog if not s.parent_slug]

    if len(top_level) > SERVICES_INDEX_TRIGGER:
        out.append(
            PlannedPage(
                _path("services"),
                "services_index",
                "Services",
                f"nav overflow: {len(top_level)} services > {SERVICES_INDEX_TRIGGER}",
                tier=2,
            )
        )
    if multi_city and len(list(cities)) > 1:
        out.append(
            PlannedPage(
                _path("areas-we-serve"),
                "areas_we_serve",
                "Areas We Serve",
                "multi-city business",
                tier=2,
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


def links_per_index(pages: Iterable[PlannedPage]) -> dict[str, int]:
    """Outbound structural body links per index-ish page.

    Calculable before anything is generated precisely because structural linking
    is deterministic (PRD §4.8b). The global nav/footer set is deliberately NOT
    counted: it appears on every page by SOP mandate, so counting it would put
    every legitimate city page over any useful threshold and train people to
    ignore the warning.
    """
    counts: dict[str, int] = {}
    by_path = list(pages)

    for page in by_path:
        if page.page_type not in {"location", "service", "services_index", "areas_we_serve", "blog_archive"}:
            continue
        depth = len([s for s in page.path.split("/") if s])
        children = [
            p
            for p in by_path
            if p.path.startswith(page.path)
            and p.path != page.path
            and len([s for s in p.path.split("/") if s]) == depth + 1
        ]
        counts[page.path] = len(children)

    return counts


def scale_gates(matrix_count: int, links: dict[str, int]) -> list[PlanIssue]:
    """Blocking warnings at plan review — never silent truncations."""
    issues: list[PlanIssue] = []

    if matrix_count > MATRIX_SIGNOFF_THRESHOLD:
        issues.append(
            PlanIssue(
                "matrix_signoff",
                True,
                f"matrix is {matrix_count} pages (> {MATRIX_SIGNOFF_THRESHOLD}) — needs human sign-off",
            )
        )

    over = {p: n for p, n in links.items() if n > LINKS_PER_INDEX_ADVISORY}
    for path, n in sorted(over.items()):
        issues.append(
            PlanIssue(
                "links_advisory",
                # Advisory, not blocking: the figure is unratified (reference
                # §1.2) and a number that blocks work needs ratifying first.
                False,
                f"{path} carries {n} outbound structural links (advisory > {LINKS_PER_INDEX_ADVISORY})",
            )
        )

    return issues


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
    issues = check_paths(pages) + scale_gates(len(matrix), links)

    pages.sort(key=lambda p: (p.tier, p.path))
    return SitePlan(pages=pages, issues=issues, matrix_count=len(matrix), links_per_index=links)


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
