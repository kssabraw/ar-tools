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


def prepare_selection(keywords: list[str], cap: int) -> list[str]:
    """Dedupe (case-insensitively, order-preserving) + cap a selected keyword
    list. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords or []:
        k = (kw or "").strip()
        nk = _norm(k)
        if k and nk not in seen:
            seen.add(nk)
            out.append(k)
    return out[: max(0, cap)] if cap else out


def build_handoff_rows(
    selected: list[str],
    metrics: dict[str, dict],
    session_id: str,
    topic_id: str,
) -> tuple[list[dict], list[dict]]:
    """Assemble the (keyword_rows, cluster_rows) to write for a handoff.

    One cluster per selected keyword, each cluster's ``primary_keyword_id``
    pointing at its keyword row (ids generated up front to resolve the
    keywords<->clusters FK cycle before any write). Metrics are carried over from
    the research run where present. ``intent`` is a fixed valid IntentType
    ('informational') — DataForSEO's commercial/transactional search-intent values
    are NOT valid cluster intents, so they're deliberately not mapped. Pure."""
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
            "intent": "informational",
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

    Returns {session_id, cluster_count, schedule_url}. Raises ValueError with a
    string code for expected failures (run_not_found / no_keywords)."""
    # Lazy import so a fanout-package import issue can never break platform-api
    # startup, and to avoid any import-time cycle at router registration.
    from fanout.storage import silo as fstore
    from fanout.storage.supabase_client import get_service_client as fanout_client

    supabase = get_supabase()
    runs = (
        supabase.table("keyword_research_runs")
        .select("id, seeds, location_code")
        .eq("id", run_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not runs:
        raise ValueError("run_not_found")
    run = runs[0]

    selected = prepare_selection(keywords, settings.keyword_research_scheduler_max)
    if not selected:
        raise ValueError("no_keywords")

    # Stored metrics for enrichment (best-effort — a keyword with no stored row
    # simply carries null metrics into the session).
    rows = (
        supabase.table("keyword_research_keywords")
        .select("keyword, volume, cpc_usd, keyword_difficulty, competition_index")
        .eq("run_id", run_id).execute()
    ).data or []
    metrics = {_norm(r["keyword"]): r for r in rows}

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
    kw_rows, cluster_rows = build_handoff_rows(selected, metrics, session_id, topic_id)
    client = fanout_client()
    for s in range(0, len(kw_rows), 500):
        client.table("keywords").insert(kw_rows[s:s + 500]).execute()
    for s in range(0, len(cluster_rows), 200):
        client.table("clusters").insert(cluster_rows[s:s + 200]).execute()
    for kw, cl in zip(kw_rows, cluster_rows):
        kw["cluster_id"] = cl["id"]
    for s in range(0, len(kw_rows), 500):
        client.table("keywords").upsert(kw_rows[s:s + 500]).execute()

    logger.info("keyword_research.handoff",
                extra={"client_id": client_id, "run_id": run_id,
                       "session_id": session_id, "clusters": len(cluster_rows)})
    return {
        "session_id": session_id,
        "cluster_count": len(cluster_rows),
        "schedule_url": f"/fanout/session/{session_id}/schedule",
    }
