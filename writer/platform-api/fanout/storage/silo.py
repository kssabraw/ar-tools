"""Storage operations for sessions and topics (M2 silo discovery).

Reads that serve a user and ownership checks go through the user-scoped client
so RLS enforces visibility. Writes the backend orchestrates go through the
service client after ownership has been verified.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from fanout.pipeline.article_planning.models import PlanResult
from fanout.pipeline.models import ProposedSilo
from fanout.pipeline.relevance import GatedKeyword
from fanout.storage.supabase_client import (
    ensure_scratch_project,
    get_service_client,
    get_user_client,
)

logger = logging.getLogger(__name__)


def _norm(kw: str) -> str:
    return " ".join((kw or "").strip().lower().split())


def _to_float(v) -> float | None:
    """Coerce a Postgres `numeric` (which the client may hand back as a Decimal or
    string) to a plain float for the JSON API, so the frontend never gets a string
    where it expects a number. None stays None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _vector_literal(vector: list[float]) -> str:
    # pgvector accepts its text form "[a,b,c]".
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"

# Columns returned to the API — never the raw embedding vector.
_TOPIC_COLS = (
    "id, session_id, name, rationale, relationship_type, supporting_evidence, "
    "source, is_broader_class, is_gated_for_competitor_mining, created_at"
)


def project_visible_to_user(access_token: str, project_id: str) -> bool:
    """True if RLS lets this user see the project (i.e. they may attach a
    session to it). Prevents attaching a session to a project the caller does
    not own (PRD §13: INSERTs gated by the same scope)."""
    res = (
        get_user_client(access_token)
        .table("projects")
        .select("id")
        .eq("id", project_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


def resolve_project_id(user_id: str, project_id: str | None) -> str:
    if project_id:
        return project_id
    return ensure_scratch_project(user_id)["id"]


# Supported English-market location codes (E1, 2026-06-17). DataForSEO localizes
# by location_code; language stays "en". Mirrors the DB check constraint in
# 20260617000000_session_location.sql and the frontend dropdown map.
SUPPORTED_LOCATION_CODES: frozenset[int] = frozenset({2840, 2826, 2124, 2036, 2554})
DEFAULT_LOCATION_CODE = 2840


def session_location_code(session: dict) -> int:
    """The DataForSEO location_code for a session (E1). Defaults to US (2840) for
    rows created before the column existed / any missing value."""
    code = session.get("location_code")
    return int(code) if code in SUPPORTED_LOCATION_CODES else DEFAULT_LOCATION_CODE


def create_session(
    *,
    user_id: str,
    project_id: str,
    seed_keyword: str,
    audience_hint: str | None,
    disambiguation_hint: str | None,
    settings: dict,
    location_code: int = DEFAULT_LOCATION_CODE,
    client_id: str | None = None,
) -> dict:
    # Tag the session with the active embedding model so its stored vectors are
    # never compared against another provider's space (freeze-old-sessions guard,
    # 2026-06-15). Lazy import to avoid an import-time cycle.
    from fanout.llm import active_embedding_model

    row = (
        get_service_client()
        .table("sessions")
        .insert(
            {
                "user_id": user_id,
                "project_id": project_id,
                "client_id": client_id,
                "seed_keyword": seed_keyword,
                "audience_hint": audience_hint,
                "disambiguation_hint": disambiguation_hint,
                "settings": settings,
                "status": "running_pre_review",
                "location_code": location_code,
                "embedding_model": active_embedding_model(),
            }
        )
        .execute()
    )
    return row.data[0]


def session_visible_to_user(access_token: str, session_id: str) -> dict | None:
    """Return the session if RLS lets this user see it, else None."""
    res = (
        get_user_client(access_token)
        .table("sessions")
        .select("*")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def update_session(session_id: str, fields: dict) -> dict:
    row = (
        get_service_client()
        .table("sessions")
        .update(fields)
        .eq("id", session_id)
        .execute()
    )
    return row.data[0]


def get_session_cost(session_id: str) -> tuple[float, dict]:
    """Current cumulative (actual_cost_usd, cost_breakdown) for a session, the
    base a new run adds its metered spend onto (PRD §16.4)."""
    res = (
        get_service_client()
        .table("sessions")
        .select("actual_cost_usd, cost_breakdown")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    row = res.data[0] if res.data else {}
    return float(row.get("actual_cost_usd") or 0.0), dict(row.get("cost_breakdown") or {})


def flush_session_cost(session_id: str, total: float, breakdown: dict) -> None:
    """Single-row UPDATE of the running cost (PRD §16.4 — accumulator flush). Kept
    to two columns so it never collides with a job's status write on other cols.
    NOTE: absolute write — only safe under the one-writer-per-session guard. Concurrent
    writers (the M15 scheduler) must use `increment_session_cost` instead."""
    (
        get_service_client()
        .table("sessions")
        .update({"actual_cost_usd": total, "cost_breakdown": breakdown})
        .eq("id", session_id)
        .execute()
    )


def increment_session_cost(session_id: str, delta_total: float, delta_breakdown: dict) -> None:
    """Atomic, row-locked delta increment of the running cost (PRD §16.4). Safe under
    concurrent writers (the M15 scheduler drains several same-session writes at once), where
    the absolute `flush_session_cost` would lose updates. No-op deltas are still cheap; callers
    skip empty ones."""
    get_service_client().rpc("increment_session_cost", {
        "p_session_id": session_id,
        "p_delta": delta_total,
        "p_breakdown_delta": delta_breakdown or {},
    }).execute()


def get_session_debug(session_id: str) -> dict:
    """Raw debug payload for the Owner debug view (PRD §15.3 #8): the statistical
    clustering log (Louvain groupings) + the orchestrator log (per-topic
    merge/split/drop rationales + dedup collisions) + the cost attribution + the
    architecture link-health audit (§15.2 #3 no-orphan / no-dangling)."""
    session = get_session(session_id) or {}
    arch = (
        get_service_client()
        .table("site_architecture")
        .select("architecture_json")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
        .data
    )
    link_health = (
        (arch[0].get("architecture_json") or {}).get("link_health") if arch else None
    )
    return {
        "status": session.get("status"),
        "seed_keyword": session.get("seed_keyword"),
        "estimated_cost_usd": _to_float(session.get("estimated_cost_usd")),
        "actual_cost_usd": _to_float(session.get("actual_cost_usd")),
        "cost_breakdown": {
            k: _to_float(v) for k, v in (session.get("cost_breakdown") or {}).items()
        },
        "statistical_clustering_log": session.get("statistical_clustering_log"),
        "orchestrator_log": session.get("orchestrator_log"),
        "architecture_link_health": link_health,
    }


def try_mark_running(session_id: str) -> bool:
    """Atomically claim a session for a pipeline run: set status='running' only
    if it isn't already running. Returns True if this caller acquired the run,
    False if a run was already in progress. The `neq` makes the check-and-set a
    single guarded UPDATE, so two concurrent callers can't both proceed
    (prevents duplicate rows + double API spend on a double-submit/retry).
    Clears any stale last_error from a prior failed run."""
    res = (
        get_service_client()
        .table("sessions")
        .update({"status": "running", "last_error": None})
        .eq("id", session_id)
        .neq("status", "running")
        .execute()
    )
    return bool(res.data)


def try_mark_cancelled(session_id: str) -> bool:
    """Atomically flip a running session to cancelled. Returns True if this caller
    landed the transition (status was 'running'), False if there was no run to
    cancel (status was already cancelled, complete, error, awaiting_*, etc.).
    Mirrors the try_mark_running check-and-set so two concurrent /cancel calls
    can't both claim a cancel."""
    res = (
        get_service_client()
        .table("sessions")
        .update({"status": "cancelled", "last_error": "Cancelled by user"})
        .eq("id", session_id)
        .eq("status", "running")
        .execute()
    )
    return bool(res.data)


def try_finalize_running(session_id: str, fields: dict) -> bool:
    """Write a job's terminal field set only if the session is still 'running' —
    so a worker that races past a concurrent /cancel doesn't overwrite the
    'cancelled' status with its own success/error finish (or vice versa). Returns
    True if the update landed."""
    res = (
        get_service_client()
        .table("sessions")
        .update(fields)
        .eq("id", session_id)
        .eq("status", "running")
        .execute()
    )
    return bool(res.data)


def get_session(session_id: str) -> dict | None:
    """Service-side session fetch (no RLS), for background jobs that run after the
    request has returned and have no user token."""
    res = (
        get_service_client()
        .table("sessions")
        .select("*")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def delete_topics_for_session(session_id: str) -> None:
    get_service_client().table("topics").delete().eq("session_id", session_id).execute()


def insert_proposed_topics(session_id: str, silos: list[ProposedSilo]) -> list[dict]:
    if not silos:
        return []
    payload = [
        {
            "session_id": session_id,
            "name": s.name,
            "rationale": s.rationale,
            "relationship_type": s.relationship_type.value,
            "supporting_evidence": s.supporting_evidence,
            "source": "llm_proposed",
            "is_broader_class": s.is_broader_class,
        }
        for s in silos
    ]
    res = get_service_client().table("topics").insert(payload).execute()
    return res.data


def list_topics(session_id: str) -> list[dict]:
    res = (
        get_service_client()
        .table("topics")
        .select(_TOPIC_COLS)
        .eq("session_id", session_id)
        .order("created_at")
        .order("id")
        .execute()
    )
    return res.data


def insert_custom_topic(
    session_id: str,
    *,
    name: str,
    rationale: str | None,
    relationship_type: str,
    is_broader_class: bool,
) -> dict:
    res = (
        get_service_client()
        .table("topics")
        .insert(
            {
                "session_id": session_id,
                "name": name,
                "rationale": rationale,
                "relationship_type": relationship_type,
                "source": "user_added",
                "is_broader_class": is_broader_class,
            }
        )
        .execute()
    )
    # Re-fetch with the restricted column set so the embedding is never returned.
    return get_topic(res.data[0]["id"])


def get_topic(topic_id: str) -> dict | None:
    res = (
        get_service_client()
        .table("topics")
        .select(_TOPIC_COLS)
        .eq("id", topic_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def update_topic(topic_id: str, fields: dict) -> dict:
    get_service_client().table("topics").update(fields).eq("id", topic_id).execute()
    # Re-fetch with the restricted column set so the embedding is never returned.
    return get_topic(topic_id)


def delete_topic(topic_id: str) -> None:
    get_service_client().table("topics").delete().eq("id", topic_id).execute()


# ---- M3 keyword expansion -------------------------------------------------
_KEYWORD_COLS = (
    "id, topic_id, cluster_id, keyword, sources, status, relevance_score, "
    "is_primary_for_cluster, orchestrator_drop_reason, "
    "volume, cpc_usd, keyword_difficulty, competition_index, metrics_updated_at, "
    "created_at"
)


def delete_keywords_for_session(session_id: str) -> None:
    get_service_client().table("keywords").delete().eq("session_id", session_id).execute()


def insert_keywords(session_id: str, per_topic: dict[str, dict[str, list[str]]]) -> int:
    rows = [
        {"session_id": session_id, "topic_id": tid, "keyword": kw, "sources": sources}
        for tid, kws in per_topic.items()
        for kw, sources in kws.items()
    ]
    client = get_service_client()
    for start in range(0, len(rows), 500):
        client.table("keywords").insert(rows[start : start + 500]).execute()
    return len(rows)


def list_keywords(
    session_id: str,
    topic_id: str | None = None,
    status: str | None = None,
    statuses: list[str] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    q = (
        get_service_client()
        .table("keywords")
        .select(_KEYWORD_COLS)
        .eq("session_id", session_id)
    )
    if topic_id:
        q = q.eq("topic_id", topic_id)
    if statuses:
        q = q.in_("status", statuses)
    elif status:
        q = q.eq("status", status)
    # (created_at, id) is a total order so offset pagination is stable — without
    # the unique id tiebreaker, rows with tied created_at (bulk inserts share a
    # timestamp) can shift across page boundaries and duplicate/skip in the
    # Table/Cluster views' paged "all keywords" fetch.
    res = q.order("created_at").order("id").range(offset, offset + limit - 1).execute()
    return res.data


_SURVIVING_STATUSES = ("active", "excluded", "covered")


def list_clustered_keywords_with_embeddings(session_id: str) -> list[dict]:
    """Every surviving keyword that's been assigned to a cluster, with its
    embedding vector pulled along. Feeds the Cluster View's display-time dedup
    (cluster_dedupe). Embeddings are parsed from pgvector's text form to a
    Python list (None when null — old rows pre-migration, or non-active rows
    that the gate never embedded). Skips keywords without a cluster_id since
    the dedup runs per cluster."""
    client = get_service_client()
    out: list[dict] = []
    offset = 0
    page = 1000
    while True:
        res = (
            client.table("keywords")
            .select(
                "id, topic_id, cluster_id, keyword, sources, status, "
                "relevance_score, is_primary_for_cluster, "
                "volume, cpc_usd, keyword_difficulty, competition_index, "
                "embedding"
            )
            .eq("session_id", session_id)
            .in_("status", list(_SURVIVING_STATUSES))
            .not_.is_("cluster_id", "null")
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            emb = row.get("embedding")
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except (ValueError, TypeError):
                    emb = None
            row["embedding"] = emb
        out.extend(rows)
        if len(rows) < page:
            break
        offset += page
    return out


def list_surviving_keywords(session_id: str) -> list[dict]:
    """Every surviving keyword (active / excluded / covered) for a session, paged.
    This is the pool the Table/Cluster views show (PRD §9.1), so it's what the
    flat + topic-grouped CSV exports build from (PRD §12 "matching the data shown
    in the UI"). Excludes the gate/orchestrator-discarded statuses
    (filtered_relevance / filtered_junk / dropped_by_orchestrator). Volume / KD /
    CPC columns now populate when §7.8 metrics enrichment ran for the session
    (otherwise they're null and render blank in the CSV)."""
    client = get_service_client()
    out: list[dict] = []
    offset = 0
    page = 1000
    while True:
        res = (
            client.table("keywords")
            .select(
                "topic_id, cluster_id, keyword, sources, status, relevance_score, "
                "volume, cpc_usd, keyword_difficulty, competition_index"
            )
            .eq("session_id", session_id)
            .in_("status", list(_SURVIVING_STATUSES))
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        out.extend(rows)
        if len(rows) < page:
            break
        offset += page
    return out


def list_keywords_by_ids(session_id: str, keyword_ids: list[str]) -> list[dict]:
    """Fetch keyword rows by id, scoped to a session for safety (a stale or
    cross-session id silently drops). Carries the same column projection as
    list_surviving_keywords so the flat CSV builder consumes either shape.
    Paged via batched `in_` filters so PostgREST's URL length doesn't blow up
    on large selections."""
    if not keyword_ids:
        return []
    # PostgREST URL caps the in() length; batch defensively even though the
    # Table View selection is unlikely to exceed a few hundred ids.
    client = get_service_client()
    out: list[dict] = []
    batch = 300
    for start in range(0, len(keyword_ids), batch):
        ids = keyword_ids[start : start + batch]
        res = (
            client.table("keywords")
            .select(
                "topic_id, cluster_id, keyword, sources, status, relevance_score, "
                "volume, cpc_usd, keyword_difficulty, competition_index"
            )
            .eq("session_id", session_id)
            .in_("id", ids)
            .execute()
        )
        out.extend(res.data or [])
    return out


def list_sessions(
    access_token: str, project_id: str, include_archived: bool = False
) -> list[dict]:
    """Sessions under a project for the Session Browser (PRD §9.4), newest first.
    RLS-scoped: only sessions the caller may see are returned. Each row carries a
    derived `coverage_mode` (from settings) and a `cluster_count` (planned-article
    count) so the browser can show run status at a glance. Archived sessions are
    hidden unless `include_archived` (§9.4 soft-archive)."""
    q = (
        get_user_client(access_token)
        .table("sessions")
        .select(
            "id, seed_keyword, status, settings, archived, created_at, completed_at"
        )
        .eq("project_id", project_id)
    )
    if not include_archived:
        q = q.eq("archived", False)
    rows = q.order("created_at", desc=True).execute().data
    return _browser_session_rows(rows)


def list_client_sessions(
    access_token: str, client_id: str, include_archived: bool = False
) -> list[dict]:
    """Sessions belonging to an AR Tools client (client-scoped runs view),
    newest first. RLS-scoped like `list_sessions`; same row shape so the browser
    renders them identically. Used when the Fanout UI is opened from a client's
    Content Scheduler card."""
    q = (
        get_user_client(access_token)
        .table("sessions")
        .select(
            "id, seed_keyword, status, settings, archived, created_at, completed_at"
        )
        .eq("client_id", client_id)
    )
    if not include_archived:
        q = q.eq("archived", False)
    rows = q.order("created_at", desc=True).execute().data
    return _browser_session_rows(rows)


def _browser_session_rows(rows: list[dict]) -> list[dict]:
    """Shape session rows for the Session Browser: derive coverage_mode from
    settings and attach the planned-article (cluster) count."""
    if not rows:
        return []
    session_ids = [r["id"] for r in rows]
    counts = _cluster_counts_by_session(session_ids)
    out = []
    for r in rows:
        settings = r.get("settings") or {}
        out.append(
            {
                "id": r["id"],
                "seed_keyword": r["seed_keyword"],
                "status": r["status"],
                "coverage_mode": settings.get("coverage_mode", "standard"),
                "cluster_count": counts.get(r["id"], 0),
                "archived": r.get("archived", False),
                "created_at": r["created_at"],
                "completed_at": r.get("completed_at"),
            }
        )
    return out


def _cluster_counts_by_session(session_ids: list[str]) -> dict[str, int]:
    """Map session_id -> planned-article (cluster) count. Clusters reference
    topics, not sessions, so we hop through topics. Service client: RLS visibility
    was already decided by the user-scoped session read upstream."""
    client = get_service_client()
    topics = (
        client.table("topics")
        .select("id, session_id")
        .in_("session_id", session_ids)
        .execute()
    ).data
    if not topics:
        return {}
    topic_to_session = {t["id"]: t["session_id"] for t in topics}
    clusters = (
        client.table("clusters")
        .select("topic_id")
        .in_("topic_id", list(topic_to_session))
        .execute()
    ).data
    counts: dict[str, int] = {}
    for c in clusters:
        sid = topic_to_session.get(c["topic_id"])
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


# ---- M4 deep-mine gating, relevance, clustering ---------------------------
def set_topics_gating(session_id: str, gated_topic_ids: list[str]) -> None:
    """Mark which silos are gated for competitor mining (PRD §7.2). Clears the
    flag on all of the session's topics, then sets it on the selected ones."""
    client = get_service_client()
    client.table("topics").update({"is_gated_for_competitor_mining": False}).eq(
        "session_id", session_id
    ).execute()
    if gated_topic_ids:
        client.table("topics").update({"is_gated_for_competitor_mining": True}).eq(
            "session_id", session_id
        ).in_("id", gated_topic_ids).execute()


def get_topic_embeddings(session_id: str) -> dict[str, list[float] | None]:
    """topic_id -> embedding vector (parsed from pgvector's text form), for the
    relevance gate. Never exposed through the API."""
    res = (
        get_service_client()
        .table("topics")
        .select("id, embedding")
        .eq("session_id", session_id)
        .execute()
    )
    out: dict[str, list[float] | None] = {}
    for row in res.data:
        emb = row.get("embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except (ValueError, TypeError):
                emb = None
        out[row["id"]] = emb
    return out


def get_active_keyword_relevance(
    session_id: str, page_size: int = 1000,
) -> dict[str, dict[str, float]]:
    """topic_id -> {keyword: relevance_score} for every active keyword in the
    session. Drives the article planner's orphan-promotion quality floor;
    ungated/filtered keywords are excluded. Paged so large pools are safe."""
    client = get_service_client()
    out: dict[str, dict[str, float]] = {}
    offset = 0
    while True:
        res = (
            client.table("keywords")
            .select("topic_id, keyword, relevance_score")
            .eq("session_id", session_id)
            .eq("status", "active")
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            tid = r.get("topic_id")
            kw = r.get("keyword")
            score = r.get("relevance_score")
            if not tid or not kw or score is None:
                continue
            out.setdefault(tid, {})[kw] = float(score)
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def list_all_keyword_pool(session_id: str) -> dict[str, dict[str, list[str]]]:
    """Reconstruct the pre-gate candidate pool (topic_id -> {keyword: sources})
    from every stored keyword row, regardless of current status. Used by the
    re-gate path to re-run the relevance gate + clustering on the already-
    collected keywords without re-hitting DataForSEO. Paged for large pools."""
    client = get_service_client()
    pool: dict[str, dict[str, list[str]]] = {}
    offset = 0
    page = 1000
    while True:
        res = (
            client.table("keywords")
            .select("topic_id, keyword, sources")
            .eq("session_id", session_id)
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            pool.setdefault(r["topic_id"], {})[r["keyword"]] = r.get("sources") or []
        if len(rows) < page:
            break
        offset += page
    return pool


def insert_classified_keywords(
    session_id: str, per_topic: dict[str, list[GatedKeyword]]
) -> int:
    """Persist gate output: every keyword with its status (active /
    filtered_relevance / filtered_junk) and relevance_score. Nothing is dropped.

    Active keywords also persist the per-keyword embedding the gate already
    computed (the same vector §7.9 clustering consumes in memory), so the
    display-time within-cluster dedup (`cluster_dedupe`) can run cosine without
    re-embedding. Non-active rows leave it null — the dedup never reads them."""
    rows = [
        {
            "session_id": session_id,
            "topic_id": tid,
            "keyword": g.keyword,
            "sources": g.sources,
            "status": g.status,
            "relevance_score": g.relevance_score,
            "embedding": _vector_literal(g.embedding) if g.embedding else None,
        }
        for tid, kws in per_topic.items()
        for g in kws
    ]
    client = get_service_client()
    for start in range(0, len(rows), 500):
        client.table("keywords").insert(rows[start : start + 500]).execute()
    return len(rows)


_METRIC_COLS = ("volume", "cpc_usd", "keyword_difficulty", "competition_index")


def update_keyword_metrics(
    session_id: str, metrics_by_keyword: dict[str, dict]
) -> int:
    """Bulk-apply DataForSEO Labs `keyword_overview` results to a session's
    keyword rows (PRD §7.8). Looks up `(session_id, keyword) -> id` in one paged
    scan, then issues per-row UPDATEs in small parallel batches so a few
    thousand rows finish in seconds (PostgREST has no per-row-values bulk
    update). Only the active set is updated — callers are expected to pass the
    active pool — but the keyword-text lookup is status-agnostic so a future
    enrich-on-demand path can reuse the helper. Sets metrics_updated_at as a
    point-in-time snapshot timestamp (PRD §7.8: no on-read refresh)."""
    if not metrics_by_keyword:
        return 0
    client = get_service_client()

    # 1) Resolve keyword text -> row id for this session, in pages.
    target_keywords = set(metrics_by_keyword.keys())
    id_by_keyword: dict[str, str] = {}
    offset = 0
    page = 1000
    while True:
        res = (
            client.table("keywords")
            .select("id, keyword")
            .eq("session_id", session_id)
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            kw = r.get("keyword")
            if kw in target_keywords and kw not in id_by_keyword:
                id_by_keyword[kw] = r["id"]
        if len(rows) < page:
            break
        offset += page

    if not id_by_keyword:
        return 0

    # 2) Issue per-row updates in parallel. Bound the pool to keep the
    # PostgREST connection count sane (~8 concurrent).
    from concurrent.futures import ThreadPoolExecutor as _Pool

    ts = datetime.now(timezone.utc).isoformat()

    def _apply(kw: str, kid: str) -> bool:
        m = metrics_by_keyword.get(kw) or {}
        fields = {col: m.get(col) for col in _METRIC_COLS}
        fields["metrics_updated_at"] = ts
        client.table("keywords").update(fields).eq("id", kid).execute()
        return True

    updated = 0
    with _Pool(max_workers=8) as pool:
        futures = [pool.submit(_apply, kw, kid) for kw, kid in id_by_keyword.items()]
        for f in futures:
            try:
                if f.result():
                    updated += 1
            except Exception:  # noqa: BLE001 — a single-row failure is non-fatal
                continue
    return updated


def set_topic_embedding(topic_id: str, vector: list[float]) -> None:
    get_service_client().table("topics").update(
        {"embedding": _vector_literal(vector)}
    ).eq("id", topic_id).execute()


# ---- M5 article planning persistence (PRD §7.10, §13) ---------------------
def get_active_keyword_index(session_id: str) -> dict[tuple[str, str], str]:
    """Session-wide `normalized keyword -> keyword row id` for the session's
    active keywords (the only pool the orchestrator saw). Session-wide (not
    topic-keyed) so a cluster in topic A can carry keywords whose row-level
    topic_id is B — needed for the cross-topic peer-entity-grouping pass, which
    assigns each peer article to a single home topic regardless of where
    Lever-3 routed each keyword. With Lever-3 on (default), each normalized
    text has exactly one active row, so the lookup is unambiguous. Paged: a
    broad silo can hold well over PostgREST's 1000-row default."""
    client = get_service_client()
    index: dict[str, str] = {}
    offset = 0
    page = 1000
    while True:
        res = (
            client.table("keywords")
            .select("id, topic_id, keyword")
            .eq("session_id", session_id)
            .eq("status", "active")
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = res.data or []
        for r in rows:
            index.setdefault(_norm(r["keyword"]), r["id"])
        if len(rows) < page:
            break
        offset += page
    return index


def reset_article_planning(session_id: str) -> None:
    """Clear any prior article-planning output so /plan-articles is idempotent
    (and re-runnable). Resets keyword orchestrator fields, un-drops
    orchestrator-dropped keywords, and deletes clusters + coverage gaps. Also
    drops any stored site architecture: it's derived from the clusters (M6, §7.11)
    by cluster id, so once the clusters are deleted + re-created (with fresh ids)
    the old architecture's article references dangle. A re-plan therefore requires
    a fresh /architecture run; clearing it here keeps the summary's `architecture`
    flag honest rather than reporting a stale graph as present."""
    client = get_service_client()
    # Un-drop keywords the orchestrator dropped on a previous run.
    client.table("keywords").update({"status": "active"}).eq(
        "session_id", session_id
    ).eq("status", "dropped_by_orchestrator").execute()
    # Clear per-keyword cluster linkage.
    client.table("keywords").update(
        {
            "cluster_id": None,
            "is_primary_for_cluster": False,
            "serp_top_urls": None,
            "orchestrator_drop_reason": None,
        }
    ).eq("session_id", session_id).execute()

    delete_architecture(session_id)

    topic_ids = [t["id"] for t in list_topics(session_id)]
    if topic_ids:
        client.table("coverage_gaps").delete().in_("topic_id", topic_ids).execute()
        client.table("clusters").delete().in_("topic_id", topic_ids).execute()


def delete_architecture(session_id: str) -> None:
    """Drop the session's stored site architecture. The architecture (M6 §7.11) is
    a snapshot keyed on cluster ids, so any edit that adds/removes/repoints clusters
    must invalidate it or its article references dangle — a fresh /architecture run
    rebuilds it. Keeps the summary's `architecture` flag honest."""
    get_service_client().table("site_architecture").delete().eq(
        "session_id", session_id
    ).execute()


def persist_article_plan(session_id: str, result: PlanResult, embed_fn) -> dict:
    """Write the orchestrator's plan: clusters, keyword linkage, dropped keywords,
    peer links, coverage gaps.

    Cluster ids are generated client-side so the clusters<->keywords FK cycle and
    the cross-cluster peer links resolve up front — clusters are then *bulk*
    inserted fully-formed (primary_keyword_id, peer_article_links, centroid all
    included), removing the per-row read-back and backfill (review M1). All
    read-only computation (embeddings, row building) happens before any write, so
    a transient failure can't leave a half-written plan beyond what the next run's
    reset_article_planning cleans up (review M2)."""
    client = get_service_client()
    kw_index = get_active_keyword_index(session_id)
    articles = [(p.topic_id, a) for p in result.per_topic for a in p.articles]

    # ---- compute everything before writing (M2) --------------------------
    cluster_ids = [str(uuid.uuid4()) for _ in articles]
    primary_to_cluster: dict[str, str] = {}
    for cid, (_tid, art) in zip(cluster_ids, articles):
        primary_to_cluster.setdefault(_norm(art.primary_keyword), cid)

    primary_embeddings = embed_fn([art.primary_keyword for _, art in articles]) if articles else []
    emb_ok = len(primary_embeddings) == len(articles)

    cluster_rows: list[dict] = []
    primary_kw_ids: list[str | None] = []
    support_ids_per: list[list[str]] = []
    for idx, (cid, (topic_id, art)) in enumerate(zip(cluster_ids, articles)):
        # Session-wide lookup — a cluster (e.g. a cross-topic peer article)
        # may carry keywords whose row-level topic_id differs from the cluster's.
        pkid = kw_index.get(_norm(art.primary_keyword))
        primary_kw_ids.append(pkid)
        support_ids_per.append(
            [kid for sk in art.supporting_keywords
             if (kid := kw_index.get(_norm(sk))) is not None]
        )
        peer_ids = list(dict.fromkeys(
            primary_to_cluster[_norm(pk)]
            for pk in art.peer_primary_keywords
            if _norm(pk) in primary_to_cluster and primary_to_cluster[_norm(pk)] != cid
        ))
        row = {
            "id": cid,
            "topic_id": topic_id,
            "name": art.primary_keyword,
            "intent": art.intent,
            "suggested_h2s": art.suggested_h2s,
            "peer_article_links": peer_ids,
            "source_statistical_grouping_id": art.source_statistical_grouping_id,
            "orchestrator_notes": art.orchestrator_notes,
            "is_gap_placeholder": False,
        }
        if pkid:
            row["primary_keyword_id"] = pkid
        if emb_ok:
            row["centroid_embedding"] = _vector_literal(primary_embeddings[idx])
        cluster_rows.append(row)

    drops_by_reason: dict[str, list[str]] = {}
    for plan in result.per_topic:
        for d in plan.dropped:
            kid = kw_index.get(_norm(d.keyword))
            if kid:
                drops_by_reason.setdefault(d.reason or "", []).append(kid)

    # Coverage gaps are auto-accepted (owner decision): each becomes an empty
    # placeholder article named by its target keyword — no article title or
    # rationale is surfaced — so the plan needs no manual gap triage. The gap row
    # is recorded as 'accepted' pointing at its placeholder cluster. A gap with
    # neither a keyword nor a title is skipped.
    gap_cluster_rows: list[dict] = []
    gap_rows: list[dict] = []
    for plan in result.per_topic:
        for g in plan.gaps:
            gap_name = (g.target_keyword or g.suggested_title or "").strip()
            if not gap_name:
                continue
            gap_cluster_id = str(uuid.uuid4())
            gap_cluster_rows.append(
                {
                    "id": gap_cluster_id,
                    "topic_id": plan.topic_id,
                    "name": gap_name,
                    "is_gap_placeholder": True,
                    "is_user_edited": True,
                }
            )
            gap_rows.append(
                {
                    "topic_id": plan.topic_id,
                    "suggested_title": g.suggested_title,
                    "target_keyword": g.target_keyword,
                    "rationale": g.rationale,
                    "status": "accepted",
                    "accepted_cluster_id": gap_cluster_id,
                }
            )

    # ---- write phase -----------------------------------------------------
    for start in range(0, len(cluster_rows), 200):
        client.table("clusters").insert(cluster_rows[start : start + 200]).execute()

    primary_ids: list[str] = []
    for idx, cid in enumerate(cluster_ids):
        pkid = primary_kw_ids[idx]
        link_ids = ([pkid] if pkid else []) + support_ids_per[idx]
        if link_ids:
            client.table("keywords").update({"cluster_id": cid}).in_("id", link_ids).execute()
        if pkid:
            primary_ids.append(pkid)
            serp = articles[idx][1].serp_top_urls
            if serp:
                client.table("keywords").update({"serp_top_urls": serp}).eq("id", pkid).execute()
    for start in range(0, len(primary_ids), 500):
        batch = primary_ids[start : start + 500]
        if batch:
            client.table("keywords").update({"is_primary_for_cluster": True}).in_(
                "id", batch
            ).execute()

    dropped = 0
    for reason, ids in drops_by_reason.items():
        for start in range(0, len(ids), 500):
            client.table("keywords").update(
                {"status": "dropped_by_orchestrator", "orchestrator_drop_reason": reason}
            ).in_("id", ids[start : start + 500]).execute()
        dropped += len(ids)

    # Placeholder clusters first — coverage_gaps.accepted_cluster_id FKs them.
    for start in range(0, len(gap_cluster_rows), 200):
        client.table("clusters").insert(gap_cluster_rows[start : start + 200]).execute()
    for start in range(0, len(gap_rows), 500):
        client.table("coverage_gaps").insert(gap_rows[start : start + 500]).execute()

    return {
        "clusters": len(cluster_rows) + len(gap_cluster_rows),
        "dropped": dropped,
        "gaps": len(gap_rows),
    }


def list_clusters_link_info(session_id: str) -> list[dict]:
    """Minimal per-cluster fields the M15 link injector needs (id, topic_id, name,
    primary_keyword_id, slug), joined up through topics."""
    topic_ids = [t["id"] for t in list_topics(session_id)]
    if not topic_ids:
        return []
    res = (
        get_service_client()
        .table("clusters")
        .select("id, topic_id, name, primary_keyword_id, slug")
        .in_("topic_id", topic_ids)
        .order("created_at")
        .execute()
    )
    return res.data


def ensure_session_slugs(session_id: str) -> dict[str, str]:
    """Assign a stable `clusters.slug` to every cluster in the session that lacks one
    (deduped within its silo/topic), persist the new ones, and return `{cluster_id: slug}`.
    Idempotent — after the first run every cluster has a slug, so later calls write nothing
    (drip-safe: a target's URL is fixed before it's generated)."""
    from collections import defaultdict

    from fanout.writer.slugs import assign_slugs

    clusters = list_clusters_link_info(session_id)
    if not clusters:
        return {}
    kw = get_keyword_texts([c["primary_keyword_id"] for c in clusters if c.get("primary_keyword_id")])

    by_topic: dict[str, list[tuple[str, str]]] = defaultdict(list)
    existing: dict[str, dict[str, str]] = defaultdict(dict)
    for c in clusters:
        src = kw.get(c.get("primary_keyword_id")) or c.get("name") or "page"
        by_topic[c["topic_id"]].append((c["id"], src))
        if c.get("slug"):
            existing[c["topic_id"]][c["id"]] = c["slug"]

    result: dict[str, str] = {}
    client = get_service_client()
    for tid, items in by_topic.items():
        assigned = assign_slugs(items, existing=existing[tid])
        for cid, slug in assigned.items():
            result[cid] = slug
            if existing[tid].get(cid) != slug:   # only write the new/changed ones
                client.table("clusters").update({"slug": slug}).eq("id", cid).execute()
    return result


def list_clusters(session_id: str) -> list[dict]:
    """Article units for a session, joined up through topics. Read-only summary
    (full editing UI is M7); never returns the centroid embedding."""
    topic_ids = [t["id"] for t in list_topics(session_id)]
    if not topic_ids:
        return []
    res = (
        get_service_client()
        .table("clusters")
        .select(
            "id, topic_id, name, primary_keyword_id, intent, suggested_h2s, "
            "peer_article_links, source_statistical_grouping_id, orchestrator_notes, "
            "is_user_edited, is_gap_placeholder, created_at"
        )
        .in_("topic_id", topic_ids)
        .order("created_at")
        .execute()
    )
    return res.data


def _count(table: str, **eqs) -> int:
    q = get_service_client().table(table).select("id", count="exact", head=True)
    for col, val in eqs.items():
        q = q.eq(col, val)
    return q.execute().count or 0


def _count_status_safe(session_id: str, status: str) -> int:
    """Status-count helper that tolerates a status value Postgres doesn't know
    yet (e.g. the `filtered_language` enum addition deployed without its
    migration). A real DB error would propagate from `_count` and 500 the
    polled summary endpoint; here we log + return 0 so the rest of the payload
    still renders. Migration 20260604000001 makes this branch dead code."""
    try:
        return _count("keywords", session_id=session_id, status=status)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "status_count_skipped",
            extra={"event": "status_count_skipped", "status": status,
                   "session_id": session_id, "reason": repr(exc)},
        )
        return 0


_EMPTY_EXPANSION = {
    "counts": {"active": 0, "filtered_relevance": 0,
               "filtered_junk": 0, "filtered_language": 0},
    "topics": [],
}


def get_pipeline_summary(session_id: str) -> dict:
    """Status + expansion/plan counts for polling and the result views. `plan` is
    null until the article-planning orchestrator has run.

    While a run is in progress the counts aren't meaningful and the UI shows a
    spinner, so we short-circuit to a cheap status-only payload — this endpoint is
    polled every few seconds, and the full aggregation only needs to run once the
    run reaches a terminal status (review M4)."""
    session = get_session(session_id) or {}
    status = session.get("status")
    last_error = session.get("last_error")
    # Approval state (PRD §11.3): always surfaced so the VA's waiting screen can
    # show the estimate, and the Owner's note on a reject decision.
    approval = {
        "required": bool(session.get("approval_required")),
        "estimated_cost_usd": _to_float(session.get("estimated_cost_usd")),
        "note": session.get("approval_note"),
        "decided_at": session.get("approval_decision_at"),
    }
    # Live cost (PRD §8.4 / §16.4) — surfaced in every payload (incl. the cheap
    # running one) so the cost banner updates as the background job flushes.
    cost = {
        "estimated_cost_usd": _to_float(session.get("estimated_cost_usd")),
        "actual_cost_usd": _to_float(session.get("actual_cost_usd")),
        "breakdown": {
            k: _to_float(v) for k, v in (session.get("cost_breakdown") or {}).items()
        },
    }
    # A run-in-progress, or a session parked at the approval gate, has no
    # meaningful expansion/plan counts yet — return the cheap status-only payload
    # (this endpoint is polled every few seconds).
    if status in ("running", "pending_approval", "rejected"):
        return {"status": status, "last_error": last_error, "approval": approval,
                "cost": cost, "expansion": _EMPTY_EXPANSION, "plan": None,
                "architecture": None}

    topics = list_topics(session_id)
    topic_ids = [t["id"] for t in topics]
    clog_topics = (session.get("statistical_clustering_log") or {}).get("topics") or {}
    olog = session.get("orchestrator_log") or {}

    client = get_service_client()
    clusters = (
        client.table("clusters").select("id, topic_id").in_("topic_id", topic_ids).execute().data
        if topic_ids else []
    )
    gaps = (
        client.table("coverage_gaps").select("id, topic_id").in_("topic_id", topic_ids)
        .execute().data
        if topic_ids else []
    )
    clusters_by_topic: dict[str, int] = {}
    gaps_by_topic: dict[str, int] = {}
    for c in clusters:
        clusters_by_topic[c["topic_id"]] = clusters_by_topic.get(c["topic_id"], 0) + 1
    for g in gaps:
        gaps_by_topic[g["topic_id"]] = gaps_by_topic.get(g["topic_id"], 0) + 1

    expansion_topics = []
    for t in topics:
        tid = t["id"]
        expansion_topics.append({
            "topic_id": tid,
            "name": t["name"],
            "active": _count("keywords", topic_id=tid, status="active"),
            "total": _count("keywords", topic_id=tid),
            "grouping_count": (clog_topics.get(tid) or {}).get("grouping_count", 0),
        })

    arch_row = (
        client.table("site_architecture")
        .select("generated_at, is_user_edited")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
        .data
    )
    architecture = arch_row[0] if arch_row else None

    has_plan = bool(clusters) or bool(olog)
    plan = None
    if has_plan:
        plan = {
            "clusters": len(clusters),
            "gaps": len(gaps),
            "dropped": _count("keywords", session_id=session_id,
                              status="dropped_by_orchestrator"),
            "collisions": len((olog.get("dedup") or {}).get("collisions") or []),
            "topics": [
                {
                    "topic_id": t["id"],
                    "name": t["name"],
                    "articles": clusters_by_topic.get(t["id"], 0),
                    "gaps": gaps_by_topic.get(t["id"], 0),
                }
                for t in topics
            ],
        }

    counts = {
        "active": _count("keywords", session_id=session_id, status="active"),
        "filtered_relevance": _count("keywords", session_id=session_id,
                                     status="filtered_relevance"),
        "filtered_junk": _count("keywords", session_id=session_id,
                                status="filtered_junk"),
        "filtered_language": _count_status_safe(session_id, "filtered_language"),
    }

    # Settling guard. The expand/regate/fanout jobs persist the full gated keyword
    # pool *before* flipping the session to `awaiting_article_planning`, so a
    # terminal status reporting a completely empty pool means this read raced
    # ahead of the just-committed writes becoming visible. Rather than let the UI
    # latch on "pipeline complete · 0 keywords" (the poller stops once status
    # leaves `running`), report the run as still `running` so polling continues
    # and the next read lands on real counts. Scoped to runs that actually
    # produced clustering groupings, so a genuinely empty run still reports its
    # honest zero.
    if (
        status == "awaiting_article_planning"
        and sum(counts.values()) == 0
        and any((clog_topics.get(t["id"]) or {}).get("grouping_count", 0) for t in topics)
    ):
        return {"status": "running", "last_error": last_error, "approval": approval,
                "cost": cost, "expansion": _EMPTY_EXPANSION, "plan": None,
                "architecture": None}

    return {
        "status": session.get("status"),
        "last_error": session.get("last_error"),
        "approval": approval,
        "cost": cost,
        "expansion": {
            "counts": counts,
            "topics": expansion_topics,
        },
        "plan": plan,
        "architecture": architecture,
    }


def list_coverage_gaps(session_id: str) -> list[dict]:
    topic_ids = [t["id"] for t in list_topics(session_id)]
    if not topic_ids:
        return []
    res = (
        get_service_client()
        .table("coverage_gaps")
        .select("id, topic_id, suggested_title, target_keyword, rationale, status, "
                "accepted_cluster_id, created_at")
        .in_("topic_id", topic_ids)
        .order("created_at")
        .execute()
    )
    return res.data


# ---- M6 site architecture (PRD §7.11, §13) --------------------------------
def get_cluster_centroids(session_id: str) -> dict[str, list[float] | None]:
    """cluster_id -> centroid embedding (parsed from pgvector's text form), for
    the architecture step's same-silo lateral linking. Never exposed via the API."""
    topic_ids = [t["id"] for t in list_topics(session_id)]
    if not topic_ids:
        return {}
    res = (
        get_service_client()
        .table("clusters")
        .select("id, centroid_embedding")
        .in_("topic_id", topic_ids)
        .execute()
    )
    out: dict[str, list[float] | None] = {}
    for row in res.data:
        emb = row.get("centroid_embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except (ValueError, TypeError):
                emb = None
        out[row["id"]] = emb
    return out


def get_keyword_texts(keyword_ids: list[str]) -> dict[str, str]:
    """keyword_id -> keyword text, for the cluster primary keywords the
    architecture step shows the LLM. Paged to stay under PostgREST's row cap."""
    ids = [kid for kid in dict.fromkeys(keyword_ids) if kid]
    if not ids:
        return {}
    client = get_service_client()
    out: dict[str, str] = {}
    for start in range(0, len(ids), 500):
        res = (
            client.table("keywords")
            .select("id, keyword")
            .in_("id", ids[start : start + 500])
            .execute()
        )
        for r in res.data or []:
            out[r["id"]] = r["keyword"]
    return out


def get_cluster_supporting_keywords(cluster_id: str, *, limit: int = 60) -> list[str]:
    """The cluster's non-primary keyword texts (the clustered research that the brief's
    primary keyword doesn't directly drive). Feeds the brief H3 pool + the coverage audit."""
    return [r["keyword"] for r in get_cluster_keyword_rows(cluster_id, limit=limit)
            if not r.get("is_primary_for_cluster")]


def get_cluster_keyword_rows(cluster_id: str, *, limit: int = 200) -> list[dict]:
    """The cluster's keyword rows ({id, keyword, is_primary_for_cluster}) — used to map the
    coverage audit's uncovered keyword *texts* back to row ids for the auto-split."""
    res = (
        get_service_client()
        .table("keywords")
        .select("id, keyword, is_primary_for_cluster")
        .eq("cluster_id", cluster_id)
        .limit(limit)
        .execute()
    )
    return res.data or []


def mark_cluster_auto_split(cluster_id: str) -> None:
    """Flag a cluster as auto-split so its own write won't re-prompt to split (recursion guard)."""
    get_service_client().table("clusters").update({"auto_split": True}).eq("id", cluster_id).execute()


def persist_architecture(session_id: str, architecture_json: dict) -> dict:
    """Upsert the session's one architecture row (PRD §13: session_id is the PK,
    so a re-generate replaces in place). Regeneration resets is_user_edited and
    refreshes generated_at."""
    row = {
        "session_id": session_id,
        "architecture_json": architecture_json,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_user_edited": False,
    }
    res = (
        get_service_client()
        .table("site_architecture")
        .upsert(row, on_conflict="session_id")
        .execute()
    )
    return res.data[0] if res.data else row


def get_architecture(session_id: str) -> dict | None:
    res = (
        get_service_client()
        .table("site_architecture")
        .select("session_id, architecture_json, generated_at, is_user_edited")
        .eq("session_id", session_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---- M7b cluster + keyword editing (PRD §9.1 / §9.2) ----------------------
# A manual edit can change cluster membership; the centroid embedding is only
# consumed by a *subsequent* re-plan's cross-topic dedup (which rebuilds every
# cluster from scratch), so membership-changing edits invalidate it (set NULL)
# rather than paying for an embedding call the next dedup will discard anyway.
_CLUSTER_COLS = (
    "id, topic_id, name, primary_keyword_id, intent, intent_locked, suggested_h2s, "
    "peer_article_links, source_statistical_grouping_id, orchestrator_notes, "
    "is_user_edited, is_gap_placeholder, auto_split, created_at"
)


def get_cluster(cluster_id: str) -> dict | None:
    res = (
        get_service_client()
        .table("clusters")
        .select(_CLUSTER_COLS)
        .eq("id", cluster_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def cluster_session_id(cluster_id: str) -> str | None:
    """Resolve cluster -> topic -> session, for ownership checks."""
    cluster = get_cluster(cluster_id)
    if not cluster:
        return None
    topic = get_topic(cluster["topic_id"])
    return topic["session_id"] if topic else None


def update_cluster(cluster_id: str, fields: dict) -> dict:
    """Edit an article's editorial fields (name / intent / H2s). Always flags the
    row user-edited so a later re-gen knows it was touched (PRD §13). A deliberate
    intent edit also locks it (`intent_locked`) so the Brief Generator honors it as an
    authoritative override instead of re-classifying."""
    extra = {"is_user_edited": True}
    if "intent" in fields:
        extra["intent_locked"] = True
    get_service_client().table("clusters").update(
        {**fields, **extra}
    ).eq("id", cluster_id).execute()
    return get_cluster(cluster_id)


def sync_cluster_intent(cluster_id: str, intent: str) -> None:
    """Write the Brief Generator's freshly-classified intent back onto the cluster so the
    Cluster-view dropdown reflects it. A SYSTEM write — it does NOT set is_user_edited or
    intent_locked, so a later reclassification can still update it (and an owner's locked
    choice is never reached here, since the caller skips the sync when locked)."""
    get_service_client().table("clusters").update(
        {"intent": intent}
    ).eq("id", cluster_id).execute()


def promote_primary(cluster_id: str, keyword_id: str) -> dict:
    """Make keyword_id the cluster's primary; the old primary becomes supporting
    (§9.2). Raises ValueError if the keyword isn't a member of the cluster —
    otherwise primary_keyword_id could be left pointing at a foreign keyword."""
    client = get_service_client()
    member = (
        client.table("keywords")
        .select("id")
        .eq("id", keyword_id)
        .eq("cluster_id", cluster_id)
        .limit(1)
        .execute()
    )
    if not member.data:
        raise ValueError("Keyword is not in this article.")
    client.table("keywords").update({"is_primary_for_cluster": False}).eq(
        "cluster_id", cluster_id
    ).execute()
    client.table("keywords").update({"is_primary_for_cluster": True}).eq(
        "id", keyword_id
    ).eq("cluster_id", cluster_id).execute()
    client.table("clusters").update(
        {"primary_keyword_id": keyword_id, "is_user_edited": True}
    ).eq("id", cluster_id).execute()
    return get_cluster(cluster_id)


def delete_cluster(cluster_id: str) -> None:
    """Delete an article. Its keywords drop to the Unassigned bucket (cluster_id
    NULL) within their topic — keywords are never destroyed (§9.2). Any peer
    links and accepted-gap pointer to this cluster are cleaned up."""
    sid = cluster_session_id(cluster_id)
    client = get_service_client()
    client.table("keywords").update(
        {"cluster_id": None, "is_primary_for_cluster": False}
    ).eq("cluster_id", cluster_id).execute()
    client.table("coverage_gaps").update({"accepted_cluster_id": None}).eq(
        "accepted_cluster_id", cluster_id
    ).execute()
    client.table("clusters").delete().eq("id", cluster_id).execute()
    if sid:
        _remove_cluster_from_peers(sid, [cluster_id])
        delete_architecture(sid)


def move_keywords(
    session_id: str, keyword_ids: list[str], cluster_id: str | None
) -> int:
    """Reassign keywords to a cluster, or to Unassigned when cluster_id is None
    (§9.1 / §9.2). Scoped to the session so a caller can't touch another session's
    keywords. A moved keyword loses its primary flag, and follows its target
    cluster's topic so cluster.topic_id and keyword.topic_id stay consistent."""
    if not keyword_ids:
        return 0
    client = get_service_client()
    fields: dict = {"cluster_id": cluster_id, "is_primary_for_cluster": False}
    if cluster_id:
        target = get_cluster(cluster_id)
        if target:
            fields["topic_id"] = target["topic_id"]
    res = (
        client.table("keywords")
        .update(fields)
        .eq("session_id", session_id)
        .in_("id", keyword_ids)
        .execute()
    )
    # A cluster whose primary was just moved out now points at a foreign keyword.
    client.table("clusters").update({"primary_keyword_id": None}).in_(
        "primary_keyword_id", keyword_ids
    ).execute()
    if cluster_id:
        client.table("clusters").update({"is_user_edited": True}).eq(
            "id", cluster_id
        ).execute()
    return len(res.data or [])


def set_keywords_status(session_id: str, keyword_ids: list[str], status: str) -> int:
    """Bulk status change for Table View actions (exclude / mark covered / restore
    to active), scoped to the session (§9.1)."""
    if not keyword_ids:
        return 0
    res = (
        get_service_client()
        .table("keywords")
        .update({"status": status})
        .eq("session_id", session_id)
        .in_("id", keyword_ids)
        .execute()
    )
    return len(res.data or [])


def merge_clusters(
    session_id: str, survivor_id: str, merged_ids: list[str], name: str | None = None
) -> dict:
    """Merge articles into the survivor (§9.2): repoint every member keyword,
    union the H2 outlines, fold peer links onto the survivor, delete the others.
    Centroid is invalidated (see module note)."""
    survivor = get_cluster(survivor_id)
    if not survivor:
        raise ValueError("survivor cluster not found")
    others = [cid for cid in merged_ids if cid != survivor_id]
    if not others:
        return survivor

    client = get_service_client()
    combined_h2 = list(survivor.get("suggested_h2s") or [])
    for cid in others:
        c = get_cluster(cid)
        for h2 in (c.get("suggested_h2s") or []) if c else []:
            if h2 not in combined_h2:
                combined_h2.append(h2)

    client.table("keywords").update(
        {"cluster_id": survivor_id, "is_primary_for_cluster": False, "topic_id": survivor["topic_id"]}
    ).in_("cluster_id", others).execute()
    # Survivor keeps its own primary flag/keyword.
    if survivor.get("primary_keyword_id"):
        client.table("keywords").update({"is_primary_for_cluster": True}).eq(
            "id", survivor["primary_keyword_id"]
        ).eq("cluster_id", survivor_id).execute()
    client.table("clusters").delete().in_("id", others).execute()
    fields: dict = {
        "suggested_h2s": combined_h2,
        "centroid_embedding": None,
        "is_user_edited": True,
    }
    if name:
        fields["name"] = name
    client.table("clusters").update(fields).eq("id", survivor_id).execute()
    _remove_cluster_from_peers(session_id, others, replacement=survivor_id)
    delete_architecture(session_id)
    return get_cluster(survivor_id)


def split_cluster(
    source_id: str,
    keyword_ids: list[str],
    new_name: str,
    new_primary_id: str | None = None,
) -> dict:
    """Manual split (§9.2 option a): move the selected keywords into a brand-new
    article in the same topic. The orchestrator-rerun split (option b) is deferred.
    Centroid is left NULL (rebuilt on a re-plan)."""
    source = get_cluster(source_id)
    if not source:
        raise ValueError("source cluster not found")
    client = get_service_client()
    # Restrict to keywords that are actually in the source — so the new article's
    # primary can never be a non-member, and we never steal another cluster's kw.
    member_ids = [
        r["id"]
        for r in client.table("keywords")
        .select("id")
        .eq("cluster_id", source_id)
        .in_("id", keyword_ids)
        .execute()
        .data
        or []
    ]
    if not member_ids:
        raise ValueError("None of the selected keywords belong to this article.")
    primary = new_primary_id if new_primary_id in member_ids else member_ids[0]

    new_id = str(uuid.uuid4())
    client.table("clusters").insert(
        {
            "id": new_id,
            "topic_id": source["topic_id"],
            "name": new_name,
            "primary_keyword_id": primary,
            "intent": source["intent"],
            "is_user_edited": True,
        }
    ).execute()
    client.table("keywords").update(
        {"cluster_id": new_id, "is_primary_for_cluster": False}
    ).in_("id", member_ids).execute()
    client.table("keywords").update({"is_primary_for_cluster": True}).eq(
        "id", primary
    ).eq("cluster_id", new_id).execute()
    # If the source's primary moved to the new article, the source loses its primary.
    if source.get("primary_keyword_id") in member_ids:
        client.table("clusters").update({"primary_keyword_id": None}).eq(
            "id", source_id
        ).execute()
    client.table("clusters").update(
        {"centroid_embedding": None, "is_user_edited": True}
    ).eq("id", source_id).execute()
    sid = cluster_session_id(source_id)
    if sid:
        delete_architecture(sid)
    return get_cluster(new_id)


def _remove_cluster_from_peers(
    session_id: str, removed_ids: list[str], replacement: str | None = None
) -> None:
    """Scrub deleted/merged cluster ids out of every other cluster's
    peer_article_links (uuid[]), optionally substituting the merge survivor.
    Keeps the Cluster View's "Links to" from showing dangling ids."""
    topic_ids = [t["id"] for t in list_topics(session_id)]
    if not topic_ids:
        return
    client = get_service_client()
    rows = (
        client.table("clusters")
        .select("id, peer_article_links")
        .in_("topic_id", topic_ids)
        .execute()
    ).data
    removed = set(removed_ids)
    for r in rows or []:
        links = r.get("peer_article_links") or []
        if not any(lid in removed for lid in links):
            continue
        new_links: list[str] = []
        for lid in links:
            sub = replacement if lid in removed else lid
            if sub and sub != r["id"] and sub not in new_links:
                new_links.append(sub)
        client.table("clusters").update({"peer_article_links": new_links}).eq(
            "id", r["id"]
        ).execute()


# ---- M7b coverage-gap decisions (PRD §9.2) --------------------------------
def get_gap(gap_id: str) -> dict | None:
    res = (
        get_service_client()
        .table("coverage_gaps")
        .select("id, topic_id, suggested_title, target_keyword, rationale, status, "
                "accepted_cluster_id, created_at")
        .eq("id", gap_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def accept_gap(gap_id: str) -> dict:
    """Accept a coverage gap: create an empty placeholder article in the gap's
    topic (no keywords yet — the Brief Generator fills it) and mark the gap
    accepted, pointing at the new cluster (§9.2)."""
    gap = get_gap(gap_id)
    if not gap:
        raise ValueError("gap not found")
    # Idempotent: a gap already accepted keeps its existing placeholder article
    # rather than spawning a duplicate on a double-submit.
    if gap.get("status") == "accepted" and gap.get("accepted_cluster_id"):
        existing = get_cluster(gap["accepted_cluster_id"])
        if existing:
            return existing
    client = get_service_client()
    new_id = str(uuid.uuid4())
    client.table("clusters").insert(
        {
            "id": new_id,
            "topic_id": gap["topic_id"],
            "name": gap.get("target_keyword") or gap["suggested_title"],
            "is_gap_placeholder": True,
            "is_user_edited": True,
        }
    ).execute()
    client.table("coverage_gaps").update(
        {"status": "accepted", "accepted_cluster_id": new_id}
    ).eq("id", gap_id).execute()
    topic = get_topic(gap["topic_id"])
    if topic:
        delete_architecture(topic["session_id"])
    return get_cluster(new_id)


def dismiss_gap(gap_id: str) -> None:
    get_service_client().table("coverage_gaps").update({"status": "dismissed"}).eq(
        "id", gap_id
    ).execute()


# ---- M7b session-browser mutations (PRD §9.4) -----------------------------
def move_session(session_id: str, project_id: str) -> dict:
    return update_session(session_id, {"project_id": project_id})


def set_session_archived(session_id: str, archived: bool) -> dict:
    return update_session(session_id, {"archived": archived})


def delete_session(session_id: str) -> None:
    """Hard-delete a session; topics/keywords/clusters cascade (FK on delete
    cascade). Irreversible — the API gates this behind explicit user intent."""
    get_service_client().table("sessions").delete().eq("id", session_id).execute()


# ---- M9 approval workflow + workspace settings (PRD §11.3 / §11.4) ---------
def get_workspace_settings() -> dict:
    """The singleton workspace-settings row (PRD §11.4, id=1). Service-side read;
    callers expose only the non-sensitive fields. Falls back to the v1.7 defaults
    if the row is somehow absent so the cost gate always has a soft cap."""
    res = (
        get_service_client()
        .table("workspace_settings")
        .select("*")
        .eq("id", 1)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return {
        "va_soft_cap_usd": 5.00,
        "owner_cost_confirm_threshold_usd": 6.00,
        "default_relevance_threshold": 0.62,
    }


def count_gated_topics(session_id: str) -> int:
    """Number of silos the user gated for competitor mining (the seed is always
    mined separately and isn't counted here). Drives the cost estimate."""
    return _count("topics", session_id=session_id, is_gated_for_competitor_mining=True)


def list_pending_approvals() -> list[dict]:
    """Every session awaiting an approval decision (PRD §11.3 step 4), newest
    first, enriched with the requesting VA's display name + the project name +
    the deep-mine count so the Owner queue can render a row without N+1 reads.
    Service-side (the API gates this behind require_owner)."""
    client = get_service_client()
    rows = (
        client.table("sessions")
        .select(
            "id, user_id, project_id, seed_keyword, settings, "
            "estimated_cost_usd, created_at"
        )
        .eq("status", "pending_approval")
        .order("created_at", desc=True)
        .execute()
        .data
    )
    if not rows:
        return []

    user_ids = list({r["user_id"] for r in rows})
    project_ids = list({r["project_id"] for r in rows})
    session_ids = [r["id"] for r in rows]

    profiles = (
        client.table("user_profiles")
        .select("user_id, display_name")
        .in_("user_id", user_ids)
        .execute()
        .data
    )
    name_by_user = {p["user_id"]: p.get("display_name") for p in profiles}
    projects = (
        client.table("projects").select("id, name").in_("id", project_ids).execute().data
    )
    name_by_project = {p["id"]: p["name"] for p in projects}

    # Deep-mine counts per session in one pass over the relevant topics.
    topics = (
        client.table("topics")
        .select("session_id, is_gated_for_competitor_mining")
        .in_("session_id", session_ids)
        .execute()
        .data
    )
    gated_by_session: dict[str, int] = {}
    for t in topics:
        if t.get("is_gated_for_competitor_mining"):
            gated_by_session[t["session_id"]] = gated_by_session.get(t["session_id"], 0) + 1

    out = []
    for r in rows:
        settings = r.get("settings") or {}
        out.append(
            {
                "session_id": r["id"],
                "va_display_name": name_by_user.get(r["user_id"]),
                "project_name": name_by_project.get(r["project_id"]),
                "seed_keyword": r["seed_keyword"],
                "coverage_mode": settings.get("coverage_mode", "standard"),
                "recursive_fanout": bool(settings.get("recursive_fanout")),
                "topic_count": settings.get("topic_count"),
                "deep_mine_count": gated_by_session.get(r["id"], 0),
                "estimated_cost_usd": r.get("estimated_cost_usd"),
                "submitted_at": r["created_at"],
            }
        )
    return out
