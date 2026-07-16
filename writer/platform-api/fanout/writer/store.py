"""Writer article persistence (`fanout.article_outputs`). Latest-by-generated_at wins
(history kept). Reads run as the service role here; the API GET is RLS-scoped to a
visible session."""

from __future__ import annotations

from fanout.storage.supabase_client import get_service_client


def list_session_articles(session_id: str) -> list[dict]:
    """Latest generated article per cluster for a session, metadata only (no bodies — those
    are large; the reader fetches one at a time). Paged so it stays correct above PostgREST's
    ~1000-row cap; keeps the newest row per cluster_id."""
    client = get_service_client()
    latest: dict[str, dict] = {}
    page = 0
    while True:
        rows = (client.table("article_outputs")
                .select("id, cluster_id, total_word_count, cost_usd, schema_version_effective, "
                        "generated_at, scheduled_article_run_id")
                .eq("session_id", session_id).order("generated_at", desc=True)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        for r in rows:
            latest.setdefault(r["cluster_id"], r)        # desc order -> first seen is newest
        if len(rows) < 1000:
            break
        page += 1
    return list(latest.values())


def get_session_article_markdown(session_id: str) -> list[tuple[str, str]]:
    """(cluster_id, article_markdown) for the latest article per cluster — the bodies for the
    'Download all' zip. Paged; newest row per cluster_id wins."""
    client = get_service_client()
    latest: dict[str, str] = {}
    page = 0
    while True:
        rows = (client.table("article_outputs")
                .select("cluster_id, article_markdown, generated_at")
                .eq("session_id", session_id).order("generated_at", desc=True)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        for r in rows:
            if r["cluster_id"] not in latest and r.get("article_markdown"):
                latest[r["cluster_id"]] = r["article_markdown"]
        if len(rows) < 1000:
            break
        page += 1
    return list(latest.items())


def list_generated_cluster_ids(session_id: str) -> set[str]:
    """Cluster ids in the session that already have at least one generated article —
    the link injector's gate so an article never links a planned-but-unwritten peer.
    Paged past PostgREST's ~1000-row cap."""
    client = get_service_client()
    ids: set[str] = set()
    page = 0
    while True:
        rows = (client.table("article_outputs")
                .select("cluster_id")
                .eq("session_id", session_id)
                .range(page * 1000, page * 1000 + 999).execute().data or [])
        ids.update(r["cluster_id"] for r in rows if r.get("cluster_id"))
        if len(rows) < 1000:
            break
        page += 1
    return ids


def get_latest_article(cluster_id: str) -> dict | None:
    res = (
        get_service_client()
        .table("article_outputs")
        .select("*")
        .eq("cluster_id", cluster_id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def save_article(
    *, cluster_id: str, session_id: str, article_json: dict, article_markdown: str,
    article_html: str, total_word_count: int | None, cost_usd: float | None,
    schema_version_effective: str, scheduled_article_run_id: str | None = None,
) -> dict:
    res = (
        get_service_client()
        .table("article_outputs")
        .insert({
            "cluster_id": cluster_id, "session_id": session_id,
            "article_json": article_json, "article_markdown": article_markdown,
            "article_html": article_html, "total_word_count": total_word_count,
            "cost_usd": cost_usd, "schema_version_effective": schema_version_effective,
            "scheduled_article_run_id": scheduled_article_run_id,
        })
        .execute()
    )
    return res.data[0]


def set_suite_run_id(article_output_id: str, suite_run_id: str) -> None:
    """Record the mirrored suite blog run on the Fan-out article (traceability)."""
    (
        get_service_client()
        .table("article_outputs")
        .update({"suite_run_id": suite_run_id})
        .eq("id", article_output_id)
        .execute()
    )
