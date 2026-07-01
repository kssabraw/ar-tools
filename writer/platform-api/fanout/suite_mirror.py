"""Mirror a Fan-out blog article into the suite as a first-class blog run.

Fan-out blog outputs live in ``fanout.article_outputs``. When the Fan-out session
is linked to a suite client, we *also* write the article into the suite's public
``runs`` + ``module_outputs`` tables as a completed ``blog_post`` run — the same
shape the 5-module pipeline produces — so the article shows up in Saved Articles
and is publishable (Google Docs / WordPress) exactly like a natively-generated
blog post, and flows into client reporting.

This mirrors the existing convergence for Fan-out *local-SEO* outputs (which are
written straight into the suite's ``local_seo_pages``). The Fan-out writer's
``article[]`` uses the identical section schema (``order`` / ``level`` /
``heading`` / ``body``) that the suite's ``sources_cited`` output does, so this
is a faithful copy with no lossy conversion.

Best-effort by contract: the suite tables are separate and a failure here must
never affect Fan-out generation — callers wrap this in a try/except.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_supabase():
    """The suite (public-schema) service-role client. Imported lazily so this
    module stays importable without the full platform-api dependency stack."""
    from db.supabase_client import get_supabase
    return get_supabase()


def build_module_outputs(run_id: str, title: str, sections: list) -> list[dict]:
    """The three synthetic ``module_outputs`` rows a mirrored blog run needs:

    - ``brief`` carries the title (the Saved Articles list + run-detail read the
      brief's ``title``),
    - ``writer`` carries the title (the expanded article card reads the writer's
      ``title``),
    - ``sources_cited`` carries the article sections under
      ``enriched_article.article`` — the single field both the publish flow
      (``routers/publish.py::_resolve_content``) and the Articles UI render from.
    """
    return [
        {"run_id": run_id, "module": "brief", "status": "complete",
         "output_payload": {"title": title}},
        {"run_id": run_id, "module": "writer", "status": "complete",
         "output_payload": {"title": title}},
        {"run_id": run_id, "module": "sources_cited", "status": "complete",
         "output_payload": {"enriched_article": {"article": sections}}},
    ]


def mirror_blog_article_to_suite(
    *,
    session: dict,
    keyword: str,
    article_json: dict,
    cost_usd: float | None = None,
    user_id: str | None = None,
) -> str | None:
    """Create a completed suite ``blog_post`` run mirroring a Fan-out article.

    Returns the new suite run id, or ``None`` when the session is not linked to a
    suite client (nothing to mirror into — e.g. an owner-global session).
    """
    client_id = (session or {}).get("client_id")
    if not client_id:
        return None

    title = (article_json.get("title") or "").strip() or keyword
    sections = article_json.get("article") or []

    supabase = _get_supabase()
    run_row = {
        "client_id": client_id,
        "keyword": keyword,
        "content_type": "blog_post",
        "status": "complete",
        "total_cost_usd": cost_usd,
        "started_at": "now()",
        "completed_at": "now()",
    }
    if user_id:
        run_row["created_by"] = user_id

    inserted = supabase.table("runs").insert(run_row).execute()
    run_id = inserted.data[0]["id"]

    supabase.table("module_outputs").insert(
        build_module_outputs(run_id, title, sections)
    ).execute()

    logger.info(
        "fanout.blog_mirrored_to_suite",
        extra={"run_id": run_id, "client_id": client_id, "keyword": keyword,
               "sections": len(sections)},
    )
    return run_id
