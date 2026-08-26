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

    if (website.get("site_type") or "") not in ("informational",):
        raise SeedError("content_plan_only_for_informational_sites")

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
