"""Hand off selected Keyword Research keywords into the Fanout Content Scheduler.

Builds a ready-to-schedule Fanout session directly from a set of already-
researched keywords — no re-discovery, no re-billing — so a user goes from
research to scheduled content in a couple of clicks. Assembled from suite code
using the Fanout's storage layer (``fanout.storage.silo``); the vendored Fanout
backend stays untouched.

Each selected keyword becomes one cluster (= one scheduled article) whose
primary keyword is that term, under a single container topic. The session is
linked to the current client (so blog / local-SEO / service-page content types
all work at schedule time) and marked ``complete`` so the Fanout workspace shows
its schedule view immediately — the frontend then lands the user on
``/fanout/session/{id}/schedule``.

The pure row-assembly helpers (``prepare_selection`` / ``build_handoff_rows``)
are unit-tested; the orchestrator does the I/O.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested.
# ---------------------------------------------------------------------------
def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").strip().lower().split())


# The fanout.cluster_intent enum. DataForSEO's search_intent vocabulary
# (informational / navigational / commercial / transactional) is a strict subset,
# so a research keyword's measured intent maps straight through — and it matters:
# the writer picks section patterns, the CTA template and the H2 word floor off
# this value (fanout/writer/pipeline.py), so defaulting a "buy X" keyword to
# informational writes the wrong page.
VALID_CLUSTER_INTENTS = frozenset(
    {"informational", "commercial", "transactional", "comparison", "navigational"}
)
DEFAULT_CLUSTER_INTENT = "informational"


def map_intent(search_intent: Optional[str]) -> str:
    """A research row's DataForSEO search_intent -> a valid cluster_intent.
    Unknown/absent values fall back to informational. Pure."""
    v = (search_intent or "").strip().lower()
    return v if v in VALID_CLUSTER_INTENTS else DEFAULT_CLUSTER_INTENT


def dedupe_keywords(keywords: list[str]) -> list[str]:
    """Dedupe (case-insensitively, order-preserving), dropping blanks. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords or []:
        k = (kw or "").strip()
        nk = _norm(k)
        if k and nk not in seen:
            seen.add(nk)
            out.append(k)
    return out


def prepare_selection(keywords: list[str], cap: int) -> list[str]:
    """Dedupe + cap a selected keyword list. A non-positive cap yields nothing
    (the setting is a maximum, so 0 means 'none' — never 'unlimited'). Pure."""
    out = dedupe_keywords(keywords)
    return out[:cap] if cap > 0 else []


def build_handoff_rows(
    selected: list[str],
    metrics: dict[str, dict],
    session_id: str,
    topic_id: str,
) -> tuple[list[dict], list[dict]]:
    """Assemble the (keyword_rows, cluster_rows) to write for a handoff.

    One cluster per selected keyword, each cluster's ``primary_keyword_id``
    pointing at its keyword row (ids generated up front to resolve the
    keywords<->clusters FK cycle before any write). Metrics — including the
    measured search intent, which drives how the article gets written — are
    carried over from the research run. Pure."""
    kw_rows: list[dict] = []
    cluster_rows: list[dict] = []
    for kw in selected:
        kid = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        m = metrics.get(_norm(kw)) or {}
        kw_rows.append({
            "id": kid,
            "session_id": session_id,
            "topic_id": topic_id,
            "keyword": kw,
            "sources": ["keyword_research"],
            "status": "active",
            "is_primary_for_cluster": True,
            "volume": m.get("volume"),
            "cpc_usd": m.get("cpc_usd"),
            "keyword_difficulty": m.get("keyword_difficulty"),
            "competition_index": m.get("competition_index"),
        })
        cluster_rows.append({
            "id": cid,
            "topic_id": topic_id,
            "name": kw,
            "intent": map_intent(m.get("search_intent")),
            "suggested_h2s": [],
            "peer_article_links": [],
            "is_gap_placeholder": False,
            "primary_keyword_id": kid,
        })
    return kw_rows, cluster_rows


# ---------------------------------------------------------------------------
# Orchestration (I/O).
# ---------------------------------------------------------------------------
def send_keywords_to_scheduler(
    client_id: str, run_id: str, keywords: list[str], user_id: str
) -> dict:
    """Create a ready-to-schedule Fanout session from selected research keywords.

    Returns {session_id, cluster_count, requested, skipped_over_limit,
    skipped_unknown, limit, schedule_url} — the skip counts let the caller report
    anything the cap or the run-membership check dropped. Raises ValueError with a
    string code for expected failures (scheduler_disabled / run_not_found /
    no_keywords / no_matching_keywords)."""
    # Lazy import so a fanout-package import issue can never break platform-api
    # startup, and to avoid any import-time cycle at router registration.
    from fanout.storage import silo as fstore
    from fanout.storage.supabase_client import get_service_client as fanout_client

    cap = settings.keyword_research_scheduler_max
    if cap <= 0:
        raise ValueError("scheduler_disabled")

    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs")
        .select("id, seeds, location_code")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        raise ValueError("run_not_found")
    run = runs[0]

    deduped = dedupe_keywords(keywords)
    if not deduped:
        raise ValueError("no_keywords")
    candidates = deduped[:cap]
    skipped_over_limit = len(deduped) - len(candidates)

    # Read back only the keywords being scheduled, and only from THIS run. That
    # bounds the query (<= cap rows rather than the run's full ~1k) and doubles as
    # validation: a keyword that isn't part of the run never becomes an article.
    metrics: dict[str, dict] = {}
    for s in range(0, len(candidates), 200):
        rows = (
            supabase.table("keyword_research_keywords")
            .select("keyword, volume, cpc_usd, keyword_difficulty, "
                    "competition_index, search_intent")
            .eq("run_id", run_id).in_("keyword", candidates[s:s + 200]).execute()
        ).data or []
        for r in rows:
            metrics[_norm(r["keyword"])] = r
    selected = [k for k in candidates if _norm(k) in metrics]
    skipped_unknown = len(candidates) - len(selected)
    if not selected:
        raise ValueError("no_matching_keywords")

    seed_label = (", ".join(run.get("seeds") or []) or "Keyword Research")[:180]
    loc = run.get("location_code")
    location_code = (
        loc if loc in fstore.SUPPORTED_LOCATION_CODES else fstore.DEFAULT_LOCATION_CODE
    )

    # 1. Session (linked to the client, marked complete so the schedule view shows).
    project_id = fstore.resolve_project_id(user_id, None)
    session = fstore.create_session(
        user_id=user_id, project_id=project_id, seed_keyword=seed_label,
        audience_hint=None, disambiguation_hint=None,
        settings={"content_type": "blog_post", "source": "keyword_research",
                  "keyword_research_run_id": run_id},
        location_code=location_code, client_id=client_id,
    )
    session_id = session["id"]

    # The rest is several unbatched writes with no transaction around them. A
    # half-written handoff is worse than none: a session with keywords but no
    # clusters still lists in the Fanout workspace as a normal finished session
    # with zero articles, and a retry would stack another one. So on any failure
    # the session is deleted (topics/keywords/clusters cascade) and the caller
    # sees a clean error.
    try:
        fstore.update_session(session_id, {"status": "complete"})

        # 2. One container topic to hang the clusters off.
        topic = fstore.insert_custom_topic(
            session_id, name=seed_label, rationale="Imported from Keyword Research",
            relationship_type="broader_class", is_broader_class=True,
        )
        topic_id = topic["id"]

        # 3. Keyword rows + one cluster each (the keywords<->clusters FK cycle is
        #    resolved by inserting keywords first, then clusters, then linking
        #    cluster_id back onto the keywords via a pk upsert).
        kw_rows, cluster_rows = build_handoff_rows(
            selected, metrics, session_id, topic_id
        )
        client = fanout_client()
        for s in range(0, len(kw_rows), 500):
            client.table("keywords").insert(kw_rows[s:s + 500]).execute()
        for s in range(0, len(cluster_rows), 200):
            client.table("clusters").insert(cluster_rows[s:s + 200]).execute()
        for kw, cl in zip(kw_rows, cluster_rows):
            kw["cluster_id"] = cl["id"]
        for s in range(0, len(kw_rows), 500):
            client.table("keywords").upsert(kw_rows[s:s + 500]).execute()
    except Exception:
        try:
            fstore.delete_session(session_id)
        except Exception:
            logger.warning("keyword_research.handoff_cleanup_failed",
                           extra={"session_id": session_id})
        raise

    logger.info("keyword_research.handoff",
                extra={"client_id": client_id, "run_id": run_id,
                       "session_id": session_id, "clusters": len(cluster_rows),
                       "skipped_over_limit": skipped_over_limit,
                       "skipped_unknown": skipped_unknown})
    return {
        "session_id": session_id,
        "cluster_count": len(cluster_rows),
        # What the caller asked for vs what was scheduled, so the UI can say so
        # instead of silently dropping the difference.
        "requested": len(deduped),
        "skipped_over_limit": skipped_over_limit,
        "skipped_unknown": skipped_unknown,
        "limit": cap,
        "schedule_url": f"/fanout/session/{session_id}/schedule",
    }
