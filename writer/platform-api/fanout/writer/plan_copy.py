"""Copy a research session's content plan onto another client (no new research).

The reusable asset in a Fanout session is its *content plan* — the topics and the
per-topic clusters (one article per cluster), each cluster anchored to a primary
keyword. That plan is client-agnostic (the same "retatrutide" article list works
for any store selling it); what differs per client is brand voice, internal-link
domain, and publish destination — all resolved at *generation* time from the
linked client, not stored in the plan.

So "copy the schedule to another client" is: clone the topics + clusters + each
cluster's *primary* keyword into a fresh session linked to the target client, and
stop there. The heavy keyword corpus (supporting keywords) and the embeddings are
deliberately NOT copied — the scheduler only needs the cluster + its primary
keyword to generate an article (see `scheduler._process_run`), briefs are cached
globally by keyword so the source's already-built ones get reused, and internal
linking degrades gracefully. The new session carries no schedule: the user picks
cadence / start date / publishing later via the normal Schedule flow.

Circular-FK note: `clusters.primary_keyword_id -> keywords.id` and
`keywords.cluster_id -> clusters.id` are both NON-deferrable, so neither table can
be inserted first with both sides set. We break the cycle by inserting clusters
with a null `primary_keyword_id`, then the keywords (whose `cluster_id` now
resolves), then back-filling `primary_keyword_id` with a keyed upsert.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

logger = logging.getLogger(__name__)

# PostgREST bulk-write / URL-length safe chunk sizes.
_INSERT_CHUNK = 500
_IN_CHUNK = 120
_READ_PAGE = 1000


def _new_id() -> str:
    return str(uuid.uuid4())


# ----- pure row builders (unit-tested; no IO) -------------------------------


def build_topic_rows(
    topics: list[dict], new_session_id: str, *, id_fn: Callable[[], str] = _new_id
) -> tuple[list[dict], dict[str, str]]:
    """Rows to insert into `topics` for the copy + a {old_topic_id: new_topic_id} map."""
    topic_map = {t["id"]: id_fn() for t in topics}
    rows = [
        {
            "id": topic_map[t["id"]],
            "session_id": new_session_id,
            "name": t["name"],
            "rationale": t.get("rationale"),
            "relationship_type": t.get("relationship_type") or "property_or_mechanism",
            "source": t.get("source") or "llm_proposed",
            "is_broader_class": bool(t.get("is_broader_class")),
            "is_gated_for_competitor_mining": bool(t.get("is_gated_for_competitor_mining")),
            "supporting_evidence": t.get("supporting_evidence"),
        }
        for t in topics
    ]
    return rows, topic_map


def build_cluster_rows(
    clusters: list[dict], topic_map: dict[str, str], *, id_fn: Callable[[], str] = _new_id
) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """Rows to insert into `clusters` (with `primary_keyword_id` left NULL — back-filled
    after the keywords land), plus a {old_cluster_id: new_cluster_id} map and a
    {old_primary_keyword_id: new_primary_keyword_id} map (only for clusters that have one).

    Clusters whose topic didn't map (defensive — shouldn't happen for a coherent
    session) are dropped."""
    cluster_map: dict[str, str] = {}
    pk_map: dict[str, str] = {}
    rows: list[dict] = []
    for c in clusters:
        new_topic_id = topic_map.get(c.get("topic_id"))
        if not new_topic_id:
            continue
        new_cluster_id = id_fn()
        cluster_map[c["id"]] = new_cluster_id
        pkid = c.get("primary_keyword_id")
        if pkid and pkid not in pk_map:
            pk_map[pkid] = id_fn()
        rows.append(
            {
                "id": new_cluster_id,
                "topic_id": new_topic_id,
                "name": c["name"],
                # Set in the back-fill pass once the keyword rows exist.
                "primary_keyword_id": None,
                "intent": c.get("intent") or "informational",
                "suggested_h2s": c.get("suggested_h2s") or [],
                "source_statistical_grouping_id": c.get("source_statistical_grouping_id"),
                "orchestrator_notes": c.get("orchestrator_notes"),
                "is_user_edited": bool(c.get("is_user_edited")),
                "is_gap_placeholder": bool(c.get("is_gap_placeholder")),
                "intent_locked": bool(c.get("intent_locked")),
                "slug": c.get("slug"),
                # peer_article_links intentionally reset ({} default) — it holds
                # source cluster ids and interlinking re-derives per session.
            }
        )
    return rows, cluster_map, pk_map


def build_keyword_rows(
    keywords: list[dict],
    new_session_id: str,
    topic_map: dict[str, str],
    cluster_map: dict[str, str],
    pk_map: dict[str, str],
) -> list[dict]:
    """Rows to insert into `keywords` for the copied *primary* keywords, remapped onto
    the new session/topic/cluster ids. A keyword whose id isn't in `pk_map`, or whose
    topic didn't map, is skipped (its cluster then simply keeps a null primary keyword —
    the same as an unplanned cluster in the source)."""
    rows: list[dict] = []
    for kw in keywords:
        new_id = pk_map.get(kw["id"])
        new_topic_id = topic_map.get(kw.get("topic_id"))
        if not new_id or not new_topic_id:
            continue
        rows.append(
            {
                "id": new_id,
                "session_id": new_session_id,
                "topic_id": new_topic_id,
                "cluster_id": cluster_map.get(kw.get("cluster_id")),
                "keyword": kw["keyword"],
                "volume": kw.get("volume"),
                "cpc_usd": kw.get("cpc_usd"),
                "competition_index": kw.get("competition_index"),
                "keyword_difficulty": kw.get("keyword_difficulty"),
                "relevance_score": kw.get("relevance_score"),
                "sources": kw.get("sources") or [],
                "status": kw.get("status") or "active",
                "is_primary_for_cluster": True,
                "serp_top_urls": kw.get("serp_top_urls"),
            }
        )
    return rows


def build_primary_backfill(clusters: list[dict], cluster_map: dict[str, str],
                           pk_map: dict[str, str]) -> list[dict]:
    """Minimal {id, primary_keyword_id} rows to upsert onto the freshly-inserted clusters,
    wiring each copied cluster to its copied primary keyword (only where both mapped)."""
    out: list[dict] = []
    for c in clusters:
        new_cluster_id = cluster_map.get(c["id"])
        new_pk = pk_map.get(c.get("primary_keyword_id"))
        if new_cluster_id and new_pk:
            out.append({"id": new_cluster_id, "primary_keyword_id": new_pk})
    return out


# ----- IO helpers -----------------------------------------------------------


def _fetch_by_in(client, table: str, select: str, col: str, vals: list[str]) -> list[dict]:
    """Read every row where `col in vals`, chunking `vals` (URL-length safe) and paging
    each chunk above the ~1000-row PostgREST cap."""
    out: list[dict] = []
    seen = list(dict.fromkeys(v for v in vals if v))
    for i in range(0, len(seen), _IN_CHUNK):
        batch = seen[i : i + _IN_CHUNK]
        page = 0
        while True:
            rows = (
                client.table(table).select(select).in_(col, batch)
                .range(page * _READ_PAGE, page * _READ_PAGE + _READ_PAGE - 1)
                .execute().data or []
            )
            out.extend(rows)
            if len(rows) < _READ_PAGE:
                break
            page += 1
    return out


def _insert_chunked(client, table: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT_CHUNK):
        client.table(table).insert(rows[i : i + _INSERT_CHUNK]).execute()


def _upsert_chunked(client, table: str, rows: list[dict]) -> None:
    for i in range(0, len(rows), _INSERT_CHUNK):
        client.table(table).upsert(rows[i : i + _INSERT_CHUNK], on_conflict="id").execute()


# ----- orchestrator ---------------------------------------------------------


def copy_plan_to_client(*, source_session_id: str, target_client_id: str, user_id: str) -> dict:
    """Clone the source session's plan (topics + clusters + primary keywords) into a new,
    unscheduled session linked to `target_client_id`, owned by `user_id`. Returns
    {new_session_id, topics, clusters, keywords}. Raises ValueError if the source is gone."""
    from fanout.storage import silo as store
    from fanout.storage.supabase_client import get_service_client

    client = get_service_client()
    source = store.get_session(source_session_id)
    if not source:
        raise ValueError("source session not found")

    # 1) New session (linked to the target client), created straight into `complete`
    #    — it's a ready-to-schedule plan, not a run to re-execute. The site base URL
    #    is resolved from the target client's website at schedule time, so we don't
    #    copy the source's Nova-specific site_base_url / extra_link_urls.
    project_id = store.resolve_project_id(user_id, None)
    new_session = store.create_session(
        user_id=user_id,
        project_id=project_id,
        client_id=target_client_id,
        seed_keyword=source.get("seed_keyword") or "",
        audience_hint=source.get("audience_hint"),
        disambiguation_hint=source.get("disambiguation_hint"),
        settings=dict(source.get("settings") or {}),
        location_code=store.session_location_code(source),
    )
    new_session_id = new_session["id"]

    # Steps 2-5 are separate PostgREST writes (no cross-table txn). If any fails
    # partway, hard-delete the just-created session so a half-copied plan (topics
    # but no clusters, or clusters with a null primary keyword) never lingers in
    # the target client's list — delete cascades to topics/clusters/keywords.
    try:
        store.update_session(
            new_session_id,
            {
                "status": "complete",
                "detected_audience": source.get("detected_audience"),
                "disambiguation_choice": source.get("disambiguation_choice"),
                "aliases": source.get("aliases") or [],
                "peer_entities": source.get("peer_entities") or [],
            },
        )

        # 2) Topics.
        src_topics = (
            client.table("topics")
            .select(
                "id, name, rationale, relationship_type, source, is_broader_class, "
                "is_gated_for_competitor_mining, supporting_evidence"
            )
            .eq("session_id", source_session_id)
            .execute().data or []
        )
        topic_rows, topic_map = build_topic_rows(src_topics, new_session_id)
        _insert_chunked(client, "topics", topic_rows)

        # 3) Clusters (entire plan) — inserted with a null primary_keyword_id.
        src_clusters = _fetch_by_in(
            client, "clusters",
            "id, topic_id, name, primary_keyword_id, intent, suggested_h2s, "
            "source_statistical_grouping_id, orchestrator_notes, is_user_edited, "
            "is_gap_placeholder, intent_locked, slug",
            "topic_id", list(topic_map.keys()),
        )
        cluster_rows, cluster_map, pk_map = build_cluster_rows(src_clusters, topic_map)
        _insert_chunked(client, "clusters", cluster_rows)

        # 4) Primary keywords (only) — cluster_id now resolves.
        src_pks = _fetch_by_in(
            client, "keywords",
            "id, cluster_id, topic_id, keyword, volume, cpc_usd, competition_index, "
            "keyword_difficulty, relevance_score, sources, status, is_primary_for_cluster, "
            "serp_top_urls",
            "id", list(pk_map.keys()),
        )
        keyword_rows = build_keyword_rows(src_pks, new_session_id, topic_map, cluster_map, pk_map)
        _insert_chunked(client, "keywords", keyword_rows)

        # 5) Back-fill clusters.primary_keyword_id (keywords now exist). Guarded
        #    against a source primary keyword that no longer exists (deleted row):
        #    such a cluster stays null instead of pointing at a missing keyword.
        inserted_pk_ids = {r["id"] for r in keyword_rows}
        backfill = [
            row for row in build_primary_backfill(src_clusters, cluster_map, pk_map)
            if row["primary_keyword_id"] in inserted_pk_ids
        ]
        _upsert_chunked(client, "clusters", backfill)
    except Exception:
        try:
            store.delete_session(new_session_id)
        except Exception as cleanup_exc:  # noqa: BLE001 — surface the ORIGINAL error
            logger.warning("plan_copy_cleanup_failed",
                           extra={"event": "plan_copy_cleanup_failed",
                                  "new_session_id": new_session_id,
                                  "reason": repr(cleanup_exc)})
        raise

    logger.info(
        "plan_copied",
        extra={
            "event": "plan_copied",
            "source_session_id": source_session_id,
            "new_session_id": new_session_id,
            "target_client_id": target_client_id,
            "topics": len(topic_rows),
            "clusters": len(cluster_rows),
            "keywords": len(keyword_rows),
        },
    )
    return {
        "new_session_id": new_session_id,
        "topics": len(topic_rows),
        "clusters": len(cluster_rows),
        "keywords": len(keyword_rows),
    }
