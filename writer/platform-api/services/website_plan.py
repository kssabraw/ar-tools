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
# Auto-generated service variations (brands + narrower types) are their own
# matrix; the reference flags a large one for link-equity review at the same
# threshold as the geo matrix.
VARIATION_SIGNOFF_THRESHOLD = 200
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
# Areas We Serve — **ratified at 6 by the owner, 2026-08-06**, settling the open
# threshold in reference note R6. R6 offered two candidates (>= 2 cities, which
# v3.5 adopted, versus the SOP's looser nav-overflow implication); 6 is a third
# answer and supersedes the >= 2 in the vendored v3.6 capture, which needs
# re-vendoring once the Doc is updated.
#
# The consequence worth knowing: a 2-5 city site gets location pages and a
# matrix but no location hub, so nothing in the global nav points at the
# location silo. Those cities are still reached from the homepage's
# LocationCardGrid, from every matrix page's structural links, and from the HTML
# sitemap — §4.1 rule 4 lists Areas We Serve as "where applicable", so a site
# under the threshold is conformant without one.
AREAS_WE_SERVE_TRIGGER = 6

# Reference §5.3 (Pillar / Hub Page): "A topic cluster of >= 5 planned/existing
# posts" triggers a pillar. The pillar is the cluster parent — a silo with fewer
# than this many posts is not a pillar, just a handful of posts, so no hub page
# is planned for it. Counted over EVERGREEN posts only: the reference is explicit
# that News/Commentary is non-evergreen and "excluded from pillar-cluster math".
PILLAR_CLUSTER_MIN = 5

# The five blog formats the template's `posts` collection renders (reference
# §5.3). `format` is a PLAN-time decision, not a writer-time one — it changes the
# geo rule, the schema, and whether the post counts toward pillar-cluster math.
POST_FORMATS = frozenset(
    {"informational_cluster", "listicle", "comparison", "local_geo", "news"}
)
DEFAULT_POST_FORMAT = "informational_cluster"
# News is the sole non-evergreen format (reference §5.3); everything else feeds a
# pillar. The exclusion lives here so a change to the format set can't silently
# drop it from the cluster math.
EVERGREEN_FORMATS = POST_FORMATS - {"news"}

# Human labels for the writer brief, so the notes read as a brief rather than a
# machine token. Angle guidance stays in the content SOP; this only names the shape.
_FORMAT_LABELS = {
    "informational_cluster": "informational cluster post (answer-first, feeds its pillar)",
    "listicle": "listicle / roundup post (N-item, scannable, deliberately ordered)",
    "comparison": "informational comparison post (verdict-first, even-handed, never a sales page)",
    "local_geo": "local geo post (genuinely useful local content with an organic service-area tie)",
    "news": "news / commentary post (timely, dated, non-evergreen)",
}

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
    "post",
    "pillar",
]

GEO_SITE_TYPES = frozenset({"local_business", "lead_gen"})

# The kinds of service variation a catalog service can auto-generate child pages
# for. A "brand" modifier is an equipment manufacturer (Carrier AC Repair) — its
# own keyword vector, rendered as a brand × service page. A "type" modifier is a
# narrower kind of the service (Oak Tree Removal) — a sub-service. Both live at
# /{service}/{modifier}/; the kind decides the page type, the title, and the
# eventual content angle. Default "type": a bare modifier is a narrower service
# far more often than a brand.
VARIATION_KINDS = frozenset({"brand", "type"})


@dataclass(frozen=True)
class ServiceVariation:
    """A modifier that auto-generates a child page under a service."""

    label: str
    kind: str = "type"


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
    # Modifiers this service auto-generates child pages for — equipment brands
    # (Carrier) and/or narrower service types (Oak Tree Removal). Empty for most
    # services; their presence is the opt-in.
    variations: tuple[ServiceVariation, ...] = ()

    @property
    def brands(self) -> tuple[str, ...]:
        """The equipment-brand labels among the variations. Kept so callers that
        only care about brands (and the pre-generalization tests) still read a
        flat brand list."""
        return tuple(v.label for v in self.variations if v.kind == "brand")


@dataclass(frozen=True)
class CityEntry:
    name: str
    slug: str
    # Only neighborhoods that passed the Maps entity test belong here; the
    # geocode containment check establishes location, not entity status.
    neighborhoods: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PostEntry:
    """One planned blog post — a cluster child (reference §5.3).

    Planned per cluster, never ad hoc: every post carries a target `format` and a
    `silo` (its pillar's slug) *before* generation, which is the reference's
    explicit planner rule. `keyword` is the term the writer targets; the rest is
    the editorial brief threaded into the Writer as run notes.
    """

    slug: str
    title: str
    silo: str
    format: str = DEFAULT_POST_FORMAT
    keyword: str = ""
    cluster: str = ""
    buyer_problem: str = ""
    search_intent: str = ""
    funnel_stage: str = ""
    questions: tuple[str, ...] = ()
    target_keywords: tuple[str, ...] = ()

    @property
    def is_evergreen(self) -> bool:
        return self.format in EVERGREEN_FORMATS


@dataclass(frozen=True)
class PillarEntry:
    """A topic silo and its planned posts (reference §5.3, Content & Authority).

    A silo maps to the strategist's *pillar*; each of its posts maps to a
    strategist *cluster*. A pillar/hub PAGE is only emitted for a silo once it
    reaches PILLAR_CLUSTER_MIN evergreen posts — below that it is a cluster of
    posts with no parent, which is not the page type the reference describes.
    """

    slug: str
    title: str
    posts: tuple[PostEntry, ...] = ()

    @property
    def evergreen_count(self) -> int:
        return sum(1 for p in self.posts if p.is_evergreen)

    @property
    def has_pillar_page(self) -> bool:
        return self.evergreen_count >= PILLAR_CLUSTER_MIN


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


def _deslug(slug: str) -> str:
    """A slug back to a human label, for the rare fallback where the canonical
    name isn't on the page title. `carrier-ac` -> `Carrier Ac`. Lossy — the real
    name always wins where it exists; this only keeps a keyword from being empty.
    """
    return (slug or "").replace("-", " ").replace("_", " ").strip().title()


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


def service_variation_pages(catalog: Iterable[ServiceEntry]) -> list[PlannedPage]:
    """Auto-generated variation pages at /{service-slug}/{modifier-slug}/.

    One page per (top-level service, variation). The variation's KIND decides
    what it becomes — both live in the same URL namespace, so the type is
    declared here, never inferred from the path:

    * **brand** → a **brand × service** page ("Carrier AC Repair"): the modifier
      is a distinct keyword vector, so the title puts the brand in front of the
      service and the page is a brand_service.
    * **type** → a **sub-service** page ("Oak Tree Removal"): the modifier IS the
      narrower service, so the label stands alone as the title — no "<modifier>
      <service>" composition, which is what produced "Oak Trees Tree Removal".

    Restricted to top-level services: a sub-service already lives two segments
    deep, and /{parent}/{sub}/{modifier}/ is not the ratified pattern — that depth
    is the hyper-local escalation, not a variation cell. Slugs are deduped within
    a service; a collision with a hand-added sub-service surfaces as a
    duplicate_path the reviewer resolves.
    """
    out: list[PlannedPage] = []
    for svc in sorted(catalog, key=lambda s: (s.order, s.slug)):
        if svc.parent_slug:
            continue
        seen: set[str] = set()
        for variation in svc.variations:
            label = (variation.label or "").strip()
            slug = slugify(label)
            if not label or not slug or slug in seen:
                continue
            seen.add(slug)
            if variation.kind == "brand":
                out.append(
                    PlannedPage(
                        _path(svc.slug, slug),
                        "brand_service",
                        f"{label} {svc.name}",
                        f"brand × service (auto): {label}",
                        tier=4,
                    )
                )
            else:
                out.append(
                    PlannedPage(
                        _path(svc.slug, slug),
                        "sub_service",
                        label,
                        f"service variation (auto): {label}",
                        tier=2,
                    )
                )
    return out


def brand_service_pages(catalog: Iterable[ServiceEntry]) -> list[PlannedPage]:
    """The brand-kind subset of the variation pages. Kept as a named seam for
    callers and tests that care specifically about brand × service."""
    return [p for p in service_variation_pages(catalog) if p.page_type == "brand_service"]


def variation_scale_gate(count: int) -> list[PlanIssue]:
    """Link-equity sign-off for a large auto-generated variation matrix
    (reference: brand × service "flag > 200 for link-equity review"; the same
    concern applies to any large service × modifier set). Blocking but
    acknowledgeable, like the other scale gates — a legitimately large catalog
    needs a recorded decision, not a wall.
    """
    if count > VARIATION_SIGNOFF_THRESHOLD:
        return [
            PlanIssue(
                "variation_scale",
                True,
                f"{count} auto-generated service variation pages (> {VARIATION_SIGNOFF_THRESHOLD}) — "
                "link-equity review before approval",
                acknowledgeable=True,
            )
        ]
    return []


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
    city_count = len(list(cities))
    if multi_city and city_count >= AREAS_WE_SERVE_TRIGGER:
        out.append(
            PlannedPage(
                _path("areas-we-serve"),
                "areas_we_serve",
                "Areas We Serve",
                f"CORE-conditional (auto): {city_count} location pages "
                f">= {AREAS_WE_SERVE_TRIGGER}",
                tier=4,
            )
        )
    return out


# --------------------------------------------------------------------------
# Content & Authority family (reference §5.3) — the informational site's plan
# --------------------------------------------------------------------------


def normalize_format(value: Optional[str]) -> str:
    """A stored/posted format token, normalized to one the template renders."""
    fmt = (value or "").strip().lower()
    return fmt if fmt in POST_FORMATS else DEFAULT_POST_FORMAT


def content_plan_pillars(content_plan: Optional[dict]) -> list[PillarEntry]:
    """Parse the site-owned content plan (`websites.config.content_plan`).

    The Website Builder OWNS this inventory (it does not read a research run at
    build time): the strategist plan may *seed* it once, but after that it is a
    durable property of the site, editable and surviving a re-research. The shape
    mirrors what `keyword_topic_strategist` emits — pillars -> clusters — with
    each strategist cluster becoming one post.

    Post slugs are made unique site-wide (posts are flat under /blog/): a
    collision is dropped here rather than left to surface as a duplicate-path
    planning error, because two clusters legitimately titled the same thing under
    different pillars is a naming quirk, not a plan error. The first wins.
    """
    out: list[PillarEntry] = []
    seen_post_slugs: set[str] = set()
    seen_pillar_slugs: set[str] = set()

    for pillar in (content_plan or {}).get("pillars") or []:
        title = (pillar.get("title") or pillar.get("pillar") or "").strip()
        if not title:
            continue
        slug = slugify(pillar.get("slug") or title)
        if not slug or slug in seen_pillar_slugs:
            continue
        seen_pillar_slugs.add(slug)

        posts: list[PostEntry] = []
        for raw in pillar.get("posts") or pillar.get("clusters") or []:
            p_title = (raw.get("title") or "").strip()
            if not p_title:
                continue
            p_slug = slugify(raw.get("slug") or p_title)
            if not p_slug or p_slug in seen_post_slugs:
                continue
            seen_post_slugs.add(p_slug)
            questions = tuple(
                str(q).strip() for q in (raw.get("questions") or []) if str(q).strip()
            )
            target_kw = tuple(
                str(k).strip()
                for k in (raw.get("target_keywords") or [])
                if str(k).strip()
            )
            posts.append(
                PostEntry(
                    slug=p_slug,
                    title=p_title,
                    silo=slug,
                    format=normalize_format(raw.get("format")),
                    keyword=(raw.get("keyword") or "").strip()
                    or (target_kw[0] if target_kw else p_title),
                    cluster=(raw.get("cluster") or "").strip() or title,
                    buyer_problem=(raw.get("buyer_problem") or "").strip(),
                    search_intent=(raw.get("search_intent") or "").strip().lower(),
                    funnel_stage=(raw.get("funnel_stage") or "").strip().upper(),
                    questions=questions,
                    target_keywords=target_kw,
                )
            )
        out.append(PillarEntry(slug=slug, title=title, posts=tuple(posts)))
    return out


def informational_pages(pillars: Iterable[PillarEntry]) -> list[PlannedPage]:
    """Post pages, and a pillar/hub page for any silo that earns one (§5.3).

    A post is `/blog/{slug}/` in the flat blog silo; a pillar is `/{topic-slug}/`
    at top level. The pillar is emitted only once its silo reaches
    PILLAR_CLUSTER_MIN evergreen posts — news posts don't count, so a silo of
    five news reactions never mints a hub.
    """
    out: list[PlannedPage] = []
    for pillar in pillars:
        for post in pillar.posts:
            out.append(
                PlannedPage(
                    _path("blog", post.slug),
                    "post",
                    post.title,
                    f"cluster: {pillar.title}",
                    tier=3,
                )
            )
        if pillar.has_pillar_page:
            out.append(
                PlannedPage(
                    _path(pillar.slug),
                    "pillar",
                    pillar.title,
                    f"CORE-conditional (auto): {pillar.evergreen_count} evergreen "
                    f"posts >= {PILLAR_CLUSTER_MIN}",
                    tier=2,
                )
            )
    return out


def compose_post_notes(post: PostEntry, pillar_title: str) -> str:
    """The editorial brief threaded into the blog Writer as per-run notes.

    The blog brief is keyword-driven and globally cached, so it can't carry this
    post's angle — the angle rides on writer notes instead, exactly as the
    Keyword Research "Write this post" handoff does.
    """
    lines = [
        f"Blog post for this site's content plan, in the \"{pillar_title}\" topic silo.",
        f"Working title: {post.title}",
        f"Format: {_FORMAT_LABELS.get(post.format, post.format)}.",
    ]
    if post.buyer_problem:
        lines.append(f"Reader problem this must resolve: {post.buyer_problem}")
    if post.search_intent or post.funnel_stage:
        bits = [b for b in (post.search_intent, post.funnel_stage) if b]
        lines.append("Search intent / funnel stage: " + " · ".join(bits))
    if post.questions:
        lines.append("Answer these reader questions: " + "; ".join(post.questions))
    if post.target_keywords:
        lines.append(
            "Work these related keywords in naturally: "
            + ", ".join(post.target_keywords)
        )
    lines.append(
        "Follow the format's structure from the content SOP; the client brand "
        "guide governs voice."
    )
    return "\n".join(lines)


def pillar_title_for(
    silo_slug: str, pillars: Optional[dict[str, PillarEntry]]
) -> Optional[str]:
    """The human pillar title for a silo slug, from a path-keyed pillar map."""
    for pillar in (pillars or {}).values():
        if pillar.slug == silo_slug:
            return pillar.title
    return None


def compose_pillar_notes(pillar: PillarEntry) -> str:
    """The brief for a pillar/hub — a comprehensive 2,000-4,000 word survey (§5.3)."""
    children = [p.title for p in pillar.posts]
    lines = [
        f'Pillar / hub page: the authoritative parent for the "{pillar.title}" topic silo.',
        "Cover the whole topic comprehensively at 2,000-4,000 words. Each section "
        "must deliver standalone value AND route the reader to a deeper child post "
        "— never a thin link list.",
    ]
    if children:
        lines.append(
            "Child posts in this cluster to summarise and link down to: "
            + "; ".join(children)
        )
    lines.append("The client brand guide governs voice.")
    return "\n".join(lines)


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


# Pillar is an index page too (it links down to every cluster child), but its
# link count depends on the silo->post mapping that a flat PlannedPage list does
# not carry, so it is injected in `build_plan` from the content plan rather than
# derived here.
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
    content_plan: Optional[dict] = None,
) -> SitePlan:
    """The full inventory for a site, ordered by priority tier.

    A geo site is planned from its service catalog x cities; the content plan
    (pillars -> posts) is planned for EVERY site type on top of that, because
    blog posts are cross-family (reference §5.3: "every site family uses them")
    — a local business's blog is where its informational cluster posts and its
    SOP-sanctioned Local Geo posts live, feeding the same silos as its money
    pages. An informational site simply has no geo half. So the two halves
    compose; a local site with a content plan gets both, and its blog archive is
    no longer a page with nothing planned to fill it.
    """
    catalog = list(catalog)
    cities = list(cities)
    multi_city = len(cities) > 1

    pages = core_pages(site_type)
    variation_pages: list[PlannedPage] = []
    if site_type in GEO_SITE_TYPES:
        pages += service_pages(catalog)
        pages += location_pages(cities, multi_city=multi_city)
        matrix = matrix_pages(catalog, cities, multi_city=multi_city)
        pages += matrix
        pages += conditional_pages(catalog, cities, multi_city=multi_city)
        # Service variations: brands (brand × service) + narrower types
        # (sub-services), opted in per top-level service. brand_service leaves
        # add no index links; sub-service variations ride the normal service
        # linking like any other sub-service.
        variation_pages = service_variation_pages(catalog)
        pages += variation_pages
    else:
        matrix = []

    # The blog: planned for every site type from its own content plan (empty when
    # a site has none, so this is inert on a geo site that hasn't seeded one).
    pillars = content_plan_pillars(content_plan)
    pages += informational_pages(pillars)

    links = links_per_index(pages)
    # A pillar links down to every child post in its silo (reference §5.3). The
    # count comes from the content plan, not the flat page list, so it is added
    # here where both are in hand — then it rides the same link-budget gate.
    planned_pillar_paths = {p.path for p in pages if p.page_type == "pillar"}
    for pillar in pillars:
        path = _path(pillar.slug)
        if path in planned_pillar_paths:
            links[path] = len(pillar.posts)
    issues = (
        check_paths(pages)
        + scale_gates(len(matrix), links)
        + variation_scale_gate(len(variation_pages))
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
# `brand_service` (brand × service) and `hyper_local` (subservice × geo) are
# service/local-landing variants — the same nlp writer, a different keyword vector.
NLP_PAGE_TYPES = frozenset(
    {"service", "sub_service", "brand_service", "location", "neighborhood", "local_landing", "hyper_local"}
)

# Written by the core-pages generator (plan §4.6), which is Phase 3 and unbuilt.
CORE_PAGE_TYPES = frozenset({"home", "about", "contact", "privacy"})

# Written by starting a suite blog Writer run and linking it back
# (content_source="run") — the publish side already assembles the body from the
# run's `module_outputs` markdown. A post is one cluster child; a pillar is the
# comprehensive hub. Both are blog_post runs; the editorial angle rides on the
# run's writer notes, since the blog brief is keyword-driven and globally cached.
RUN_PAGE_TYPES = frozenset({"post", "pillar"})


def _segments(path: str) -> list[str]:
    return [s for s in (path or "").split("/") if s]


def frontmatter_extra(
    page: PlannedPage,
    *,
    services: dict[str, ServiceEntry],
    cities: dict[str, CityEntry],
    posts: Optional[dict[str, PostEntry]] = None,
    pillars: Optional[dict[str, PillarEntry]] = None,
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

    if page.page_type in {"service", "sub_service"}:
        svc = services.get(segs[-1]) if segs else None
        if svc:
            out["teaser"] = svc.teaser
            out["order"] = svc.order
        if page.page_type == "sub_service" and len(segs) >= 2:
            out["parentService"] = segs[0]

    elif page.page_type == "brand_service":
        # /{service-slug}/{brand-slug}/ — the SERVICE is the first segment (the
        # brand is segs[-1]), so teaser/order and the breadcrumb parent come from
        # segs[0], not segs[-1] as the sibling service branch assumes.
        svc = services.get(segs[0]) if segs else None
        if svc:
            out["teaser"] = svc.teaser
            out["order"] = svc.order
        if len(segs) >= 2:
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

    elif page.page_type == "post":
        # `format` is required by the publish gate (auto-publish means the format
        # decides the geo rule and the schema), so it is declared here at plan
        # time, never left to the writer. `silo`/`cluster`/`category` place the
        # post in its topic silo so the pillar and blog archive can group it.
        post = (posts or {}).get(page.path)
        out["format"] = post.format if post else DEFAULT_POST_FORMAT
        if post:
            out["silo"] = post.silo
            out["cluster"] = post.cluster
            # The blog archive groups by category; the human silo name reads
            # better than the slug.
            out["category"] = pillar_title_for(post.silo, pillars) or post.cluster

    elif page.page_type == "pillar":
        pillar = (pillars or {}).get(page.path)
        if pillar:
            out["silo"] = pillar.slug

    return out


def generation_inputs(
    page: PlannedPage,
    *,
    services: dict[str, ServiceEntry],
    cities: dict[str, CityEntry],
    posts: Optional[dict[str, PostEntry]] = None,
    pillars: Optional[dict[str, PillarEntry]] = None,
    primary_service: Optional[str] = None,
    primary_city: Optional[str] = None,
) -> dict:
    """What engine writes this page, and what it needs to be told.

    Returns `{engine, keyword, location}` (plus `content_type`/`notes` for the
    `run` engine) — `engine` is None when nothing in the suite can write this
    page type, which is deliberately visible rather than silently skipped
    (PRD §4.7: "the plan tab must not propose a page type without showing its
    engine status").

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

    if page.page_type == "post":
        post = (posts or {}).get(page.path)
        return {
            "engine": "run",
            "content_type": "blog_post",
            "keyword": (post.keyword if post else page.title),
            "location": None,
            "notes": compose_post_notes(
                post, pillar_title_for(post.silo, pillars) or post.cluster
            )
            if post
            else "",
        }
    if page.page_type == "pillar":
        pillar = (pillars or {}).get(page.path)
        return {
            "engine": "run",
            "content_type": "blog_post",
            "keyword": (pillar.title if pillar else page.title),
            "location": None,
            "notes": compose_pillar_notes(pillar) if pillar else "",
        }

    if page.page_type not in NLP_PAGE_TYPES:
        return {"engine": None, "keyword": None, "location": None}

    segs = _segments(page.path)

    if page.page_type in {"service", "sub_service"}:
        svc = services.get(segs[-1]) if segs else None
        if svc:
            # A real catalog service/sub-service: its own name is the keyword.
            return {"engine": "nlp", "keyword": svc.name, "location": primary_city}
        # A synthetic sub-service (an auto-generated `type` variation) has no
        # catalog entry, so its title is a bare label ("Oak Trees", "Emergency").
        # Left alone, two services with the same bare label would produce the
        # same keyword + location and thus near-identical pages — so scope it by
        # the parent service, skipping the join when the service name is already
        # in the label (so a fully-named "Oak Tree Removal" doesn't double up).
        keyword = page.title
        parent = services.get(segs[0]) if page.page_type == "sub_service" and len(segs) >= 2 else None
        if parent and parent.name.lower() not in keyword.lower():
            keyword = f"{keyword} {parent.name}".strip()
        return {"engine": "nlp", "keyword": keyword, "location": primary_city}

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

    if page.page_type == "brand_service":
        # /{service-slug}/{brand-slug}/ — the brand modifier is the keyword vector
        # ("Carrier AC Repair"). Geo-agnostic like a service page, so the city
        # only scopes the SERP analysis. The brand name lives on the title the
        # emitter set ("<Brand> <Service>"), since no catalog entry carries it.
        svc = services.get(segs[0]) if segs else None
        svc_name = svc.name if svc else (segs[0] if segs else "")
        keyword = (page.title or "").strip() or (
            f"{_deslug(segs[1])} {svc_name}".strip() if len(segs) >= 2 else svc_name
        )
        return {"engine": "nlp", "keyword": keyword, "location": primary_city}

    if page.page_type == "hyper_local":
        # /{city}/{service}/{subservice}/ (or /{city}/{neighborhood}/{subservice}/):
        # the most granular geo need. The city anchors the DataForSEO location; the
        # specific subservice+geo is the keyword, carried on the page's own title.
        city = cities.get(segs[0]) if segs else None
        city_name = city.name if city else (segs[0] if segs else "")
        keyword = (page.title or "").strip() or (
            f"{_deslug(segs[-1])} {city_name}".strip() if segs else ""
        )
        return {"engine": "nlp", "keyword": keyword, "location": city_name}

    # local_landing
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
    posts: Optional[dict[str, PostEntry]] = None,
    pillars: Optional[dict[str, PillarEntry]] = None,
    primary_service: Optional[str] = None,
    primary_city: Optional[str] = None,
) -> dict:
    """Everything a plan row carries besides its route, type, trigger and tier."""
    inputs = generation_inputs(
        page,
        services=services,
        cities=cities,
        posts=posts,
        pillars=pillars,
        primary_service=primary_service,
        primary_city=primary_city,
    )
    return {
        **inputs,
        "frontmatter": frontmatter_extra(
            page, services=services, cities=cities, posts=posts, pillars=pillars
        ),
    }


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
