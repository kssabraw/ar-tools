"""Website Builder — seeding an informational site's content plan.

The Website Builder OWNS an informational site's cluster inventory (it does not
read a research run at build time). But typing pillars and clusters by hand when
the suite already researched them would be wasteful, so this module is the
one-shot **seed bridge**: it copies the client's latest
`keyword_topic_strategist` plan — which already emits exactly the pillars ->
clusters shape the planner consumes — into `websites.config.content_plan`.

After the import the plan is the site's own data: editable in the plan tab,
durable across a re-research, and re-planned deterministically. The strategist
plan is the seed, not a live dependency.

The mapping is a faithful copy with two deliberate transforms:

* each strategist **cluster becomes one post** (its `target_keywords[0]` is the
  post's target keyword; the whole cluster brief rides along), and
* a post's **`format` is inferred** from its title's intent (reference §5.3
  planner triggers) — "best / types / ways" -> listicle, "A vs B" -> comparison,
  everything else the default informational cluster post. News and local-geo are
  never auto-seeded: news is non-evergreen and planned separately, and local-geo
  is a geo-site format.

The pure mapper (`plan_to_content_plan`) is unit-tested; `import_from_strategist`
does the I/O.
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase
from services import website_plan

logger = logging.getLogger(__name__)


class SeedError(Exception):
    """Stable error code, not prose."""


def infer_format(title: str) -> str:
    """A post format from its title's intent (reference §5.3 planner triggers).

    Conservative: only the two clearly-signalled formats are inferred, and the
    default is the evergreen informational cluster post. News and local-geo are
    never inferred — news is excluded from cluster planning and local-geo is a
    geo-site format.
    """
    t = f" {(title or '').lower()} "
    if " vs " in t or " versus " in t:
        return "comparison"
    listicle_signals = (
        "best ",
        "types of",
        "ways to",
        "examples",
        "ideas",
        "tips",
        "checklist",
    )
    if any(sig in t for sig in listicle_signals) or _starts_with_number(title):
        return "listicle"
    return website_plan.DEFAULT_POST_FORMAT


def _starts_with_number(title: str) -> bool:
    head = (title or "").strip().split(" ", 1)[0]
    return head[:1].isdigit()


def plan_to_content_plan(plan: Optional[dict]) -> dict:
    """A `keyword_topic_strategist` plan -> a site `content_plan`. Pure.

    Empty pillars, empty clusters and blank titles are dropped, so a partial or
    malformed strategist plan yields a smaller-but-valid content plan rather than
    a raising one. The output is exactly what `website_plan.content_plan_pillars`
    parses, so the seed and the planner cannot disagree about the shape.
    """
    pillars_out: list[dict] = []
    for pillar in (plan or {}).get("pillars") or []:
        title = (pillar.get("pillar") or pillar.get("title") or "").strip()
        if not title:
            continue
        posts: list[dict] = []
        for cluster in pillar.get("clusters") or pillar.get("posts") or []:
            c_title = (cluster.get("title") or "").strip()
            if not c_title:
                continue
            target_kw = [
                str(k).strip()
                for k in (cluster.get("target_keywords") or [])
                if str(k).strip()
            ]
            posts.append(
                {
                    "title": c_title,
                    "slug": website_plan.slugify(c_title),
                    "format": infer_format(c_title),
                    "keyword": target_kw[0] if target_kw else c_title,
                    "target_keywords": target_kw,
                    "buyer_problem": (cluster.get("buyer_problem") or "").strip(),
                    "search_intent": (cluster.get("search_intent") or "").strip(),
                    "funnel_stage": (cluster.get("funnel_stage") or "").strip(),
                    "questions": [
                        str(q).strip()
                        for q in (cluster.get("questions") or [])
                        if str(q).strip()
                    ],
                }
            )
        if not posts:
            continue
        pillars_out.append(
            {"title": title, "slug": website_plan.slugify(title), "posts": posts}
        )
    return {"pillars": pillars_out}


# ---------------------------------------------------------------------------
# Fanout session -> content plan (a second seed source)
# ---------------------------------------------------------------------------
# The Fanout content scheduler groups a client's keywords into silos (topics) and
# clusters (one article each). A finished run is therefore already the pillars ->
# posts shape this planner wants, so it is a second seed source alongside the
# strategist plan. Option 1 (owner ruling): always regenerate fresh — the seed
# copies only the topics/keywords, and the site writes its own posts through the
# run engine; it never links to whatever articles the Fanout may already have
# generated.

# Fanout's cluster_intent enum -> a blog format where the mapping is unambiguous.
# Only 'comparison' names a format directly; every other intent is an
# informational post whose shape is inferred from its title (listicle/vs), so the
# intent doesn't override a clearer title signal.
_FANOUT_INTENT_FORMAT = {"comparison": "comparison"}


def fanout_intent_format(intent: Optional[str], title: str) -> str:
    """A post format from a Fanout cluster's intent + title. Pure.

    The title heuristic wins when it's decisive (an "A vs B" or an enumerated
    listicle title), because it is more specific than the coarse intent enum; the
    intent only forces `comparison` when the title didn't already imply a format.
    """
    inferred = infer_format(title)
    if inferred != website_plan.DEFAULT_POST_FORMAT:
        return inferred
    return _FANOUT_INTENT_FORMAT.get((intent or "").strip().lower(), inferred)


def fanout_to_content_plan(
    topics: list[dict],
    clusters: list[dict],
    keywords_by_cluster: dict[str, dict],
) -> dict:
    """A Fanout session's topics + clusters -> a site `content_plan`. Pure.

    `keywords_by_cluster` maps a cluster id to `{"primary": str, "supporting":
    [str, ...]}`. Gap-placeholder clusters (a coverage hole the Fanout noted but
    never wrote) are skipped — they are not real posts. A topic with no real
    clusters contributes no pillar. Post slugs are made unique site-wide, first
    wins, exactly as the strategist mapper does.
    """
    topic_name = {t["id"]: (t.get("name") or "").strip() for t in topics}
    by_topic: dict[str, list[dict]] = {}
    for cluster in clusters:
        if cluster.get("is_gap_placeholder"):
            continue
        by_topic.setdefault(cluster.get("topic_id"), []).append(cluster)

    pillars_out: list[dict] = []
    seen_post_slugs: set[str] = set()
    for topic in topics:
        name = topic_name.get(topic["id"], "")
        rows = by_topic.get(topic["id"]) or []
        if not name or not rows:
            continue
        posts: list[dict] = []
        for cluster in rows:
            title = (cluster.get("name") or "").strip()
            if not title:
                continue
            slug = website_plan.slugify(title)
            if not slug or slug in seen_post_slugs:
                continue
            seen_post_slugs.add(slug)
            kw = keywords_by_cluster.get(cluster["id"]) or {}
            supporting = [k for k in (kw.get("supporting") or []) if k]
            primary = (kw.get("primary") or "").strip() or (
                supporting[0] if supporting else title
            )
            posts.append(
                {
                    "title": title,
                    "slug": slug,
                    "format": fanout_intent_format(cluster.get("intent"), title),
                    "keyword": primary,
                    "target_keywords": supporting,
                }
            )
        if posts:
            pillars_out.append(
                {"title": name, "slug": website_plan.slugify(name), "posts": posts}
            )
    return {"pillars": pillars_out}


def import_from_fanout(
    website: dict, *, session_id: str, replace: bool = False
) -> dict:
    """Seed `config.content_plan` from a finished Fanout session's silos/clusters.

    Only reads the Fanout's topics + keywords (option 1 — always regenerate
    fresh); it never links to the session's generated articles. Refuses to
    clobber an edited plan unless `replace` is set, and refuses a session that
    belongs to a DIFFERENT client than this site (a linked session carries a
    client_id; an unlinked one carries none and is allowed, since option 1 needs
    only the keywords).
    """
    # Valid for any site type — a local site's blog seeds from a Fanout run too.
    config = dict(website.get("config") or {})
    existing = config.get("content_plan") or {}
    if (existing.get("pillars") or []) and not replace:
        raise SeedError("content_plan_exists")

    # Lazy import so a fanout-package issue can never break platform-api startup
    # or this module's import (it is imported by the router at registration).
    from fanout.storage import silo as fstore
    from fanout.storage.supabase_client import get_service_client as fanout_client

    session = fstore.get_session(session_id)
    if not session:
        raise SeedError("fanout_session_not_found")
    session_client = session.get("client_id")
    if session_client and str(session_client) != str(website["client_id"]):
        raise SeedError("fanout_session_other_client")

    topics = fstore.list_topics(session_id) or []
    if not topics:
        raise SeedError("fanout_session_empty")
    clusters = fstore.paged_cluster_rows(
        [t["id"] for t in topics],
        "id, topic_id, name, intent, primary_keyword_id, is_gap_placeholder",
    )
    keywords_by_cluster = _fanout_keywords_by_cluster(fanout_client(), session_id)

    content_plan = fanout_to_content_plan(topics, clusters, keywords_by_cluster)
    if not content_plan["pillars"]:
        raise SeedError("fanout_session_empty")

    config["content_plan"] = content_plan
    get_supabase().table("websites").update(
        {"config": config, "updated_at": "now()"}
    ).eq("id", website["id"]).execute()

    summary = plan_summary(content_plan)
    logger.info(
        "website_content_plan.seeded_fanout",
        extra={"website_id": website["id"], "session_id": session_id, **summary},
    )
    return {"seeded": True, "source_session_id": session_id, **summary}


def _fanout_keywords_by_cluster(client, session_id: str) -> dict[str, dict]:
    """{cluster_id: {"primary": str, "supporting": [str, ...]}} for a session.

    Reads the session's clustered keywords paged (PostgREST silently truncates an
    unpaged select at 1000 rows), keeping the primary keyword and the active
    supporting keywords per cluster.
    """
    out: dict[str, dict] = {}
    offset, page = 0, 1000
    while True:
        rows = (
            client.table("keywords")
            .select("cluster_id, keyword, is_primary_for_cluster, status")
            .eq("session_id", session_id)
            .not_.is_("cluster_id", "null")
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        ).data or []
        for row in rows:
            cid = row.get("cluster_id")
            kw = (row.get("keyword") or "").strip()
            if not cid or not kw:
                continue
            slot = out.setdefault(cid, {"primary": "", "supporting": []})
            if row.get("is_primary_for_cluster"):
                slot["primary"] = kw
            # An 'active' keyword survived the relevance gate; a filtered one is
            # noise we don't want to seed as a target keyword.
            if (row.get("status") or "active") == "active" and kw not in slot["supporting"]:
                slot["supporting"].append(kw)
        if len(rows) < page:
            break
        offset += page
    return out


def plan_summary(content_plan: dict) -> dict:
    """Counts for the caller to report — how many pillars, posts, and hubs."""
    pillars = website_plan.content_plan_pillars(content_plan)
    return {
        "pillars": len(pillars),
        "posts": sum(len(p.posts) for p in pillars),
        # A hub is only planned once a silo reaches the evergreen-post threshold.
        "hubs": sum(1 for p in pillars if p.has_pillar_page),
    }


def import_from_strategist(website: dict, *, replace: bool = False) -> dict:
    """Seed `config.content_plan` from the client's latest strategist plan.

    Refuses to silently clobber an edited plan: if the site already has a content
    plan, `replace` must be set. Best-effort about the research run — a client
    with no topic-research run, or one whose latest run has no strategist plan,
    is reported (`no_strategist_plan`) rather than seeded with nothing.
    """
    from services import keyword_topic_research

    # Every site type has a blog (reference §5.3: posts are cross-family), so a
    # content plan is valid on a local site too — it seeds that site's blog.
    config = dict(website.get("config") or {})
    existing = config.get("content_plan") or {}
    if (existing.get("pillars") or []) and not replace:
        raise SeedError("content_plan_exists")

    run = keyword_topic_research.latest_run(website["client_id"])
    plan = (run or {}).get("plan") if run else None
    if not plan or not (plan.get("pillars") or []):
        raise SeedError("no_strategist_plan")

    content_plan = plan_to_content_plan(plan)
    if not content_plan["pillars"]:
        raise SeedError("no_strategist_plan")

    config["content_plan"] = content_plan
    get_supabase().table("websites").update(
        {"config": config, "updated_at": "now()"}
    ).eq("id", website["id"]).execute()

    summary = plan_summary(content_plan)
    logger.info(
        "website_content_plan.seeded",
        extra={"website_id": website["id"], "run_id": (run or {}).get("id"), **summary},
    )
    return {"seeded": True, "source_run_id": (run or {}).get("id"), **summary}
