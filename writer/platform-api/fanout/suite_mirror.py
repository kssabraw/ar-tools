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


# ── Reverse mirror: a reoptimized suite run → the Fan-out article ────────────
#
# Reoptimizing a Fan-out blog article runs the suite blog score/reopt spine on
# its mirrored suite run (`suite_run_id`). That produces a new sources_cited
# attempt on the SUITE side; the Fan-out article (the source of truth the Fan-out
# Articles library reads) is then stale. `reflect_reoptimized_run_to_fanout`
# writes the improved article back onto a fresh `fanout.article_outputs` row —
# the symmetric inverse of the forward mirror (identical section schema, so this
# is faithful, not lossy). Best-effort by contract, like the forward mirror.


def read_suite_run_article(suite_run_id: str) -> dict:
    """The mirrored suite run's latest reoptimized article: sections (from the
    highest-attempt `sources_cited`), the on-page title (brief → writer → run
    keyword), and its latest `blog_score` composite. Read as the suite service
    role."""
    supabase = _get_supabase()

    def _latest(module: str) -> dict:
        rows = (
            supabase.table("module_outputs")
            .select("output_payload, attempt_number")
            .eq("run_id", suite_run_id).eq("module", module).eq("status", "complete")
            .order("attempt_number", desc=True).limit(1).execute()
        ).data or []
        return (rows[0].get("output_payload") if rows else None) or {}

    sc = _latest("sources_cited")
    sections = ((sc.get("enriched_article") or {}).get("article")) or []
    title = (
        (_latest("brief").get("title") or "").strip()
        or (_latest("writer").get("title") or "").strip()
    )
    score = _latest("blog_score")
    return {
        "sections": sections,
        "title": title,
        "composite_score": score.get("composite_score"),
        "composite_status": score.get("composite_status"),
    }


def _sections_to_markdown(sections: list, title: str) -> str:
    """Render the reoptimized suite ``sources_cited`` sections to Markdown.

    Suite sections combine heading + body in ONE entry ({order, level, heading,
    body}, figures carry raw ``html``) — unlike the Fan-out writer's split
    heading/body items — so this mirrors ``blog_page_score._sections_to_markdown``
    rather than reusing the Fan-out serializer (which would drop the body of a
    heading-carrying section). Blog bodies start at H2; the title is the H1."""
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    ordered = sorted([s for s in sections if isinstance(s, dict)], key=lambda s: s.get("order", 0))
    for s in ordered:
        if s.get("type") == "figure":
            fig = (s.get("html") or "").strip()
            if fig:
                parts.append(fig)
            continue
        level = str(s.get("level") or "").upper()
        if level == "H1" or s.get("type") == "title":
            continue  # the title (H1) is emitted once, above
        heading = (s.get("heading") or "").strip()
        body = (s.get("body") or "").strip()
        if heading and body:
            parts.append(f"## {heading}\n\n{body}")
        elif heading:
            parts.append(f"## {heading}")
        elif body:
            parts.append(body)
    return ("\n\n".join(parts).strip() + "\n") if parts else ""


def _word_count(sections: list) -> int:
    total = 0
    for s in sections:
        if isinstance(s, dict) and s.get("type") != "figure":
            total += len((f"{s.get('heading') or ''} {s.get('body') or ''}").split())
    return total


def build_reflected_article(prior_article_json: dict, sections: list, title: str) -> dict:
    """Pure: fold the reoptimized suite sections + title into the prior Fan-out
    ``article_json``, re-render Markdown/HTML (suite section shape), and recompute
    the word count. Returns the persistable fields (article_json / article_markdown
    / article_html / total_word_count). Non-body fields (seo_title, metadata
    extras, client_context_summary) are preserved."""
    from services.markdown_html import markdown_to_html

    new_json = dict(prior_article_json or {})
    new_json["article"] = sections
    if title:
        new_json["title"] = title

    markdown = _sections_to_markdown(sections, new_json.get("title") or title)
    html = markdown_to_html(markdown) if markdown.strip() else ""
    word_count = _word_count(sections)

    new_json["article_markdown"] = markdown
    new_json["article_html"] = html
    if isinstance(new_json.get("metadata"), dict):
        new_json["metadata"] = {**new_json["metadata"], "total_word_count": word_count}

    return {
        "article_json": new_json,
        "article_markdown": markdown,
        "article_html": html,
        "total_word_count": word_count,
    }


def reflect_reoptimized_run_to_fanout(
    *,
    cluster_id: str,
    session_id: str,
    suite_run_id: str,
    prior_article_json: dict,
    cost_usd: float | None = None,
) -> dict | None:
    """Write a reoptimized suite run's article back onto a fresh
    `fanout.article_outputs` row (latest-by-generated_at wins, so the Fan-out
    Articles library shows it). Returns the new row, or None if the suite run has
    no reoptimized article yet. Best-effort — callers wrap in try/except."""
    from fanout.writer import store as article_store

    suite = read_suite_run_article(suite_run_id)
    sections = suite.get("sections") or []
    if not sections:
        return None
    built = build_reflected_article(prior_article_json or {}, sections, suite.get("title") or "")
    saved = article_store.save_article(
        cluster_id=cluster_id,
        session_id=session_id,
        article_json=built["article_json"],
        article_markdown=built["article_markdown"],
        article_html=built["article_html"],
        total_word_count=built["total_word_count"],
        cost_usd=cost_usd,
        schema_version_effective=(prior_article_json or {})
        .get("client_context_summary", {})
        .get("schema_version_effective", "1.7-no-context"),
        suite_run_id=suite_run_id,
        composite_score=suite.get("composite_score"),
        composite_status=suite.get("composite_status"),
    )
    logger.info(
        "fanout.blog_reflected_from_suite",
        extra={"cluster_id": cluster_id, "suite_run_id": suite_run_id,
               "sections": len(sections), "composite": suite.get("composite_score")},
    )
    return saved
