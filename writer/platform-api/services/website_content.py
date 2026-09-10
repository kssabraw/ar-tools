"""Website Builder — turning generated content into committable site files.

Three jobs, in order:

1. **Where a page lives in the repo.** A collection is a content *shape*, not a
   page type, so sub-services share the services collection and neighborhoods
   share locations (template `src/content.config.ts`).
2. **The frontmatter contract.** Every routed entry declares its full `path` and
   its `pageType`, because the Page Type Reference is explicit that page type is
   declared by the planner and never inferred from the URL.
3. **The publish gate.** §5.2–§5.4: a page that fails is held at draft carrying
   the reason, never silently dropped and never silently shipped.

Generation always completes and always persists; the gate runs at publish, which
keeps failures inspectable and retry cheap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional

# §5.2 — the number the suite already uses to decide a live page is good enough
# to leave alone. A second, website-specific threshold would make "good enough"
# mean two things depending on destination.
SEO_COMPOSITE_THRESHOLD = 75.0

# Which content collection each page type is stored in. Keyed by page type
# because the collection is a shape: a sub-service is a service-shaped document
# at a deeper path, not a different kind of thing.
_COLLECTION_BY_PAGE_TYPE: dict[str, str] = {
    "service": "services",
    "sub_service": "services",
    "brand_service": "services",
    # A cost page is a service-shaped document at /{service}/cost/ — same
    # collection as its parent service, a deeper path.
    "cost": "services",
    "location": "locations",
    "neighborhood": "locations",
    "local_landing": "local-landing",
    "hyper_local": "local-landing",
    "post": "posts",
    # Pillar/hub pages get their own collection: they route at top level
    # (/{topic-slug}/) and render differently from a flat blog post, so the
    # template needs to tell them apart by collection, not just page type.
    "pillar": "pillars",
    # Commercial X-vs-Y comparison — its own collection + /compare/ route, since
    # it renders as a verdict-first article, unlike a service or a post.
    "comparison": "comparisons",
    # A project / case study — its own collection + /projects/ route; renders
    # structured job facts (stats/photos/testimonial) around the narrative body.
    "project": "projects",
    # A problem / symptom page — a blog post in the flat blog silo
    # (/blog/{symptom-slug}/), so it shares the posts collection + blog route; only
    # its diagnostic-triage brief differs from an ordinary post.
    "problem": "posts",
    "home": "pages",
    "about": "pages",
    "contact": "pages",
    "privacy": "pages",
    # The standalone FAQ and the two Writer-#6 hubs are id-addressed `pages`
    # entries (like the core pages) — their content is `sections` frontmatter the
    # template's own route renders, not a routed markdown body.
    "faq": "pages",
    "services_index": "pages",
    "areas_we_serve": "pages",
    # Offers/specials and Warranty/guarantee are ⭐ extension singletons — one per
    # site at their reserved root slug (/specials/, /warranty/). Like the FAQ they
    # are id-addressed `pages` entries whose structured, operator-supplied facts
    # ride in `sections` frontmatter and are rendered by their own static route;
    # both are invent-nothing (offer terms/expiry and warranty coverage are legal
    # facts a writer must never fabricate).
    "offers": "pages",
    "warranty": "pages",
}

# Core pages are addressed by a fixed entry id, because the template looks them
# up by name (`corePage('about-us')`) rather than by path.
_CORE_ENTRY_ID = {
    "home": "home",
    "about": "about-us",
    "contact": "contact-us",
    "privacy": "privacy-policy",
}

# The full set of `pages`-collection entries addressed by id rather than by a
# routed path: the core pages, plus the standalone FAQ and the two Writer-#6 hubs.
# The template renders each from its own static route via `corePage(<id>)`, so
# these entries carry no `path`/`pageType` frontmatter (the `pages` collection
# schema has neither). The ids match what those routes look up:
# `corePage('faq')`, `corePage('services')`, `corePage('areas-we-serve')`.
_ID_ADDRESSED_ENTRY_ID = {
    **_CORE_ENTRY_ID,
    "faq": "faq",
    "services_index": "services",
    "areas_we_serve": "areas-we-serve",
    # The extension singletons live at their reserved slug: /specials/ → the
    # `specials` entry, /warranty/ → the `warranty` entry. Their routes look them
    # up by id (`corePage('specials')` / `corePage('warranty')`), so they carry
    # no path/pageType frontmatter — exactly like the FAQ.
    "offers": "specials",
    "warranty": "warranty",
}

# Page types the house template renders from data alone — no generated body, so
# nothing to gate and nothing to write.
#
# Blog archive and the HTML sitemap render entirely from the published set and
# have no narrative at all. The two hubs used to be here too, but Writer #6 gives
# them optional narrative copy (a `pages` entry keyed by id), so they moved out —
# see HUB_PAGE_TYPES for how they still render from data when no narrative exists.
TEMPLATE_ONLY_PAGE_TYPES = frozenset({"blog_archive", "sitemap"})

# The Writer-#6 hubs. Their auto-list always renders from the published set (the
# hub's own route reads the collections directly, so the URL works regardless),
# and Writer #6 adds an optional narrative committed as a `pages` entry. Because
# the narrative is optional, a hub with none is published as a data page (no file
# committed) rather than held — publish handles this grace, distinct from a
# genuinely ungenerated service page.
HUB_PAGE_TYPES = frozenset({"services_index", "areas_we_serve"})

# Page types whose content is `sections` frontmatter written by the core-pages
# generator, with an empty markdown body. For these, an empty body is normal and
# a populated `sections` map is the real content — so the publish body gate must
# look at `sections`, not just the body. (home renders its hero/section copy from
# `sections`; faq renders its Q&A; the two hubs render their lede/authority.)
SECTION_CONTENT_PAGE_TYPES = frozenset(
    {"home", "faq", "services_index", "areas_we_serve", "project", "offers", "warranty"}
)

# Planned page types the house template cannot render at all — no route, no
# collection entry, no writer. Reported at plan review (PRD §4.4) rather than
# discovered at publish.
#
# Empty today, and deliberately kept rather than deleted: every ⭐ extension type
# that has a ratified URL now also has a route and an engine (cost, problem,
# brand × service, FAQ, projects, comparison, offers, warranty), but a future
# catalog type with a ratified URL and no template would land here, so the first
# plan that proposes one needs this check to already exist.
UNRENDERABLE_PAGE_TYPES: frozenset[str] = frozenset()

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ContentError(Exception):
    """Stable error code, not prose."""


@dataclass(frozen=True)
class PublishVerdict:
    allowed: bool
    reason: str = ""
    # True when a staff+ user may force past this. A facts-consistency failure
    # never is: it is a liability question, not a quality preference.
    overridable: bool = False


def collection_of(page_type: str) -> str:
    try:
        return _COLLECTION_BY_PAGE_TYPE[page_type]
    except KeyError as exc:
        raise ContentError(f"no_collection_for_page_type:{page_type}") from exc


def entry_id(path: str, page_type: str) -> str:
    """Stable file stem for a page.

    Derived from the full path rather than the last segment, because segments
    repeat across the matrix: `/anaheim/ac-repair/` and `/brea/ac-repair/` would
    otherwise both be `ac-repair.md` and the second would overwrite the first.

    Two collections are addressed by id instead of by path, so they are exempt:
    core pages, which the template looks up by name (`corePage('about-us')`),
    and posts, whose route is `/blog/[...slug]` with the entry id AS the slug —
    a full-path id there would publish `/blog/blog-my-post/`. Post slugs are
    unique site-wide by construction (the blog is flat and its slugs are checked
    against the reserved list), so the last segment is safe.
    """
    if page_type in _ID_ADDRESSED_ENTRY_ID:
        return _ID_ADDRESSED_ENTRY_ID[page_type]
    segs = [s for s in (path or "").split("/") if s]
    if not segs:
        return "index"
    if page_type in ("post", "problem"):
        # Both live in the flat blog silo at /blog/{slug}/, and the blog route
        # uses the entry id AS the slug, so a full-path id would publish
        # /blog/blog-{slug}/. Blog slugs are unique site-wide by construction.
        segs = segs[-1:]
    return _SLUG_RE.sub("-", "-".join(segs).lower()).strip("-")


def repo_path(path: str, page_type: str) -> str:
    """Where the markdown file goes inside the site repo."""
    return f"src/content/{collection_of(page_type)}/{entry_id(path, page_type)}.md"


def _yaml_scalar(value: Any) -> str:
    """Emit one frontmatter value.

    A hand-rolled emitter rather than PyYAML, for two reasons: the field set is
    closed and known, and the output must be **byte-stable** across runs so a
    re-publish with unchanged content produces no diff. A library's formatting
    choices are not a stable contract.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_scalar(v) for v in value) + "]"
    if isinstance(value, dict):
        # Inline flow mapping keeps the emitter small; jsonld is the only dict
        # field and the template reads it as an opaque object.
        inner = ", ".join(f"{_yaml_scalar(str(k))}: {_yaml_scalar(v)}" for k, v in sorted(value.items()))
        return "{" + inner + "}"
    text = str(value)
    # Always quote strings: titles routinely contain ':' ("Roof Repair: Fast"),
    # which is the single most common way hand-built frontmatter breaks.
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def render_frontmatter(fields: dict[str, Any]) -> str:
    """Deterministic YAML block. Keys emitted in a fixed order, empties dropped."""
    order = [
        "title",
        "description",
        "path",
        "pageType",
        "locationName",
        "serviceName",
        "citySlug",
        "serviceSlug",
        "parentService",
        "parentCity",
        "teaser",
        "order",
        "category",
        "format",
        "author",
        "readingTime",
        "silo",
        "cluster",
        "publishDate",
        "updatedDate",
        "reviewBy",
        "heroImage",
        "heroImageAlt",
        "draft",
        "sourceId",
        "sections",
        "jsonld",
    ]
    lines = ["---"]
    for key in order:
        if key not in fields:
            continue
        value = fields[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def build_markdown(*, fields: dict[str, Any], body: str) -> str:
    """A complete content file: frontmatter + body, newline-terminated."""
    return f"{render_frontmatter(fields)}\n\n{(body or '').strip()}\n"


def frontmatter_for(
    *,
    path: str,
    page_type: str,
    title: str,
    description: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The declared fields every routed entry carries.

    `path` and `pageType` are non-negotiable: several page types share one URL
    slot, so the template cannot recover the type from the URL and must be told.
    Core pages are exempt — they are addressed by entry id, not by path.
    """
    fields: dict[str, Any] = {"title": title, "description": description}
    if page_type not in _ID_ADDRESSED_ENTRY_ID:
        if not path.startswith("/") or not path.endswith("/"):
            raise ContentError("path_must_have_leading_and_trailing_slash")
        fields["path"] = path
        fields["pageType"] = page_type
    fields.update(extra or {})
    return fields


def publish_verdict(
    *,
    page_type: str,
    composite: Optional[float] = None,
    voice: Optional[dict] = None,
    facts_consistent: bool = True,
    writer_schema_version: Optional[str] = None,
    frontmatter: Optional[dict[str, Any]] = None,
) -> PublishVerdict:
    """Whether a page may go live (§5.2–§5.4).

    Deliberately reuses the suite's existing bars rather than inventing website
    ones, and is stricter exactly where no human is in the loop.
    """
    # §5.3 / §5.6 — the same hard block everywhere. A page must not claim
    # something the business has not told us; that is a liability question, so
    # no role may override it.
    if not facts_consistent:
        return PublishVerdict(False, "facts_consistency_failed", overridable=False)

    voice = voice or {}
    critical = [v for v in (voice.get("violations") or []) if v.get("severity") == "critical"]

    if page_type in {"service", "sub_service", "cost", "location", "neighborhood", "local_landing", "hyper_local"}:
        if composite is None:
            # Scoring failed or never ran. "Unscored" and "scored 81" must not
            # mean the same thing at the gate — the rest of this module holds
            # when it does not know (a degraded run, an unwritten body), and a
            # silent pass here is the one place the 75 bar could be skipped
            # without anyone seeing it. Overridable, because a scoring outage
            # should cost one click and not a day.
            return PublishVerdict(False, "seo_composite_missing", overridable=True)
        if composite < SEO_COMPOSITE_THRESHOLD:
            return PublishVerdict(
                False, f"seo_composite_below_threshold:{composite:.1f}", overridable=True
            )
        if critical:
            return PublishVerdict(False, "voice_violation", overridable=True)
        return PublishVerdict(True)

    if page_type == "post":
        # Auto-publish means nobody reads these before the public does, so the
        # machine gate is stricter than where a human is in the loop.
        if critical:
            return PublishVerdict(False, "voice_violation", overridable=False)
        if writer_schema_version and "-degraded" in writer_schema_version:
            # A degraded run was written with zero brand context. The suite has
            # already shipped one such article by accident; it must never reach
            # a live site unread.
            return PublishVerdict(False, "writer_run_degraded", overridable=False)
        fm = frontmatter or {}
        missing = [k for k in ("title", "description", "format") if not fm.get(k)]
        if missing:
            return PublishVerdict(False, f"frontmatter_incomplete:{','.join(missing)}", overridable=False)
        if fm.get("format") == "news" and not fm.get("reviewBy"):
            # Non-evergreen + auto-publish + no expiry is how a site ends up
            # ranking on outdated information indefinitely.
            return PublishVerdict(False, "news_post_missing_review_date", overridable=False)
        return PublishVerdict(True)

    if page_type in {"pillar", "comparison", "problem"}:
        # A pillar, a commercial comparison and a diagnostic problem/symptom page
        # are all blog Writer runs — informational content that ships with no
        # human reading it first — so they carry the same non-overridable machine
        # gate as a post. None has a `format`/`reviewBy` (never a news reaction);
        # all must carry title + description.
        if critical:
            return PublishVerdict(False, "voice_violation", overridable=False)
        if writer_schema_version and "-degraded" in writer_schema_version:
            return PublishVerdict(False, "writer_run_degraded", overridable=False)
        fm = frontmatter or {}
        missing = [k for k in ("title", "description") if not fm.get(k)]
        if missing:
            return PublishVerdict(False, f"frontmatter_incomplete:{','.join(missing)}", overridable=False)
        return PublishVerdict(True)

    # Core pages and the structured extension singletons (offers / warranty):
    # their content is operator-supplied facts, not a scored body, so facts
    # consistency (checked above) is the real gate. A critical voice finding is
    # overridable, like a core page — there is no auto-published prose here that a
    # human hasn't entered.
    if critical:
        return PublishVerdict(False, "voice_violation", overridable=True)
    return PublishVerdict(True)


def files_for_pages(pages: Iterable[dict]) -> dict[str, bytes]:
    """Map repo path → file bytes for a batch of pages ready to commit.

    Keyed by path, so two pages resolving to one file is impossible by
    construction — the last writer would otherwise silently win.
    """
    out: dict[str, bytes] = {}
    for page in pages:
        page_type = page["page_type"]
        if page_type in TEMPLATE_ONLY_PAGE_TYPES:
            continue
        path = page.get("route") or page.get("path") or ""
        target = repo_path(path, page_type)
        if target in out:
            raise ContentError(f"duplicate_repo_path:{target}")
        fields = frontmatter_for(
            path=path,
            page_type=page_type,
            title=page.get("title") or "",
            description=page.get("description") or "",
            extra=page.get("extra") or {},
        )
        out[target] = build_markdown(fields=fields, body=page.get("body") or "").encode("utf-8")
    return out


def redirects_file(superseded: Iterable[dict]) -> str:
    """Cloudflare `_redirects` content for renamed slugs.

    Published slugs are immutable (reference §1.2): a rename keeps the old path
    as a 301 to its replacement. The artifact is committed on the same deploy as
    the rename, so the redirect ships atomically with the change that caused it.
    """
    lines: list[str] = []
    for row in superseded:
        src = (row.get("route") or "").strip()
        dst = (row.get("redirect_to") or "").strip()
        if src and dst and src != dst:
            lines.append(f"{src} {dst} 301")
    return "\n".join(sorted(set(lines))) + ("\n" if lines else "")
