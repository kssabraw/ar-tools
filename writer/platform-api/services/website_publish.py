"""Website Builder — publishing a page, i.e. committing its file into the site repo.

"Publish" here is the name of a code path, not an outward-facing act: it writes
a markdown file into a private GitHub repo, whose own Actions workflow then
builds and deploys it. Nothing in this module talks to the internet-facing side
of a site.

Three properties shape the design:

1. **The body is resolved from its source record, never snapshotted.** A service
   page's text lives in `local_seo_pages`, so reoptimizing it and republishing
   is one action rather than a copy that drifts from the original. Only pages
   with no upstream record (composed core pages, static legal pages) carry their
   own content on the row.
2. **The gate runs here, not at generation.** Generation always completes and
   always persists; a page that fails sits at draft carrying the reason
   (PRD §5.1), which keeps failures inspectable and retry cheap.
3. **Idempotency is keyed on the rendered bytes.** "A retry never creates a
   second commit" cannot mean "a page is committed at most once" — a reoptimized
   page has to be able to ship. Committing *unchanged* content is the no-op.

One job per page, staggered, for the reasons the Local SEO bulk path documents:
each unit stays well under the stale-job reaper's timeout, and a staggered
`scheduled_at` lets interactive work overtake the rest of a batch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import website_content, website_deploy
from services.github_publish import commit_files_to_github
from services.html_to_markdown import html_to_markdown

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Stable error code, not prose."""


@dataclass(frozen=True)
class SourceContent:
    """A page's body plus everything its publish gate needs to judge it."""

    body: str
    title: str
    description: str = ""
    jsonld: Optional[dict] = None
    composite: Optional[float] = None
    voice: Optional[dict] = None
    writer_schema_version: Optional[str] = None
    facts_consistent: bool = True


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def parse_jsonld(raw: Any) -> Optional[dict]:
    """The generator's schema payload as an object the frontmatter can carry.

    nlp-api emits `schema_json` as a string, sometimes wrapped in a
    `<script type="application/ld+json">` tag. The template's zod contract wants
    a mapping, so anything else — a bare list, a `@graph` array, unparseable
    text — is dropped rather than smuggled through as a string: a page shipping
    without JSON-LD is a small loss, a page failing the site build is not.
    """
    if isinstance(raw, dict):
        return raw or None
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("<"):
        start, end = text.find(">"), text.rfind("<")
        if start == -1 or end <= start:
            return None
        text = text[start + 1 : end].strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(parsed, dict):
        return parsed or None
    if isinstance(parsed, list):
        # A @graph-style array: take the first object rather than guessing at a
        # merge, since the template injects one object verbatim.
        for item in parsed:
            if isinstance(item, dict) and item:
                return item
    return None


def content_hash(files: dict[str, bytes]) -> str:
    """A stable digest of exactly what would be committed.

    Paths are sorted so two runs producing the same files in a different order
    hash the same; the frontmatter emitter is byte-stable by design, so an
    unchanged page really does hash unchanged.
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[path])
        digest.update(b"\0")
    return digest.hexdigest()


def commit_message(page: dict) -> str:
    route = page.get("route") or "/"
    return f"Publish {route}"


def is_unchanged(page: dict, new_hash: str) -> bool:
    """Whether committing this page again would be a no-op.

    Both conditions matter: a matching hash with no recorded commit means the
    previous attempt failed *after* rendering, and that page has never shipped.
    """
    return bool(page.get("commit_sha")) and page.get("content_hash") == new_hash


def source_from_local_seo(row: dict) -> SourceContent:
    """A service / location / local-landing page, from its `local_seo_pages` row."""
    voice = row.get("voice_violations")
    return SourceContent(
        body=html_to_markdown(row.get("content_html") or ""),
        title=(row.get("page_title") or row.get("keyword") or "").strip(),
        description=(row.get("meta_description") or "").strip(),
        jsonld=parse_jsonld(row.get("schema_json")),
        composite=row.get("composite_score"),
        voice=voice if isinstance(voice, dict) else None,
    )


def source_from_content(content: dict) -> SourceContent:
    """A composed or static page, from the content stored on the page row.

    `composite` is read here even though a core page has no target query and is
    never scored: the row is the store for any page with no upstream record, so
    if something did score one, that is where the number would be. Absent stays
    absent — and for a geo page type, absent is a hold rather than a pass.
    """
    content = content or {}
    return SourceContent(
        body=content.get("body") or "",
        title=(content.get("title") or "").strip(),
        description=(content.get("description") or "").strip(),
        jsonld=content.get("jsonld") if isinstance(content.get("jsonld"), dict) else None,
        composite=content.get("composite"),
        voice=content.get("voice") if isinstance(content.get("voice"), dict) else None,
        facts_consistent=bool(content.get("facts_consistent", True)),
    )


def build_files(page: dict, source: SourceContent) -> dict[str, bytes]:
    """The one file this page commits, rendered through the shared contract."""
    plan = page.get("plan") or {}
    extra = dict(plan.get("frontmatter") or {})
    if source.jsonld:
        extra["jsonld"] = source.jsonld
    if page.get("source_id"):
        extra["sourceId"] = str(page["source_id"])
    stored = (page.get("content") or {}).get("frontmatter")
    if isinstance(stored, dict):
        extra.update(stored)

    return website_content.files_for_pages(
        [
            {
                "route": page.get("route") or "",
                "page_type": page.get("page_type") or "",
                "title": source.title or page.get("title") or "",
                "description": source.description,
                "body": source.body,
                "extra": extra,
            }
        ]
    )


def held_dedupe_key(website_id: str, when: datetime) -> str:
    """One held-page notification per site per day, not one per page.

    PRD §5.4 asks for one per batch; a batch has no id here (one job per page is
    what keeps each unit under the reaper), so the day is the batch proxy. The
    uniqueness is enforced by the notifications table's own index, so concurrent
    publish jobs cannot race a duplicate through.
    """
    return f"website_page_held:{website_id}:{when.date().isoformat()}"


# --------------------------------------------------------------------------
# Enqueue
# --------------------------------------------------------------------------


def _spaced_at(index: int) -> str:
    spacing = max(0, int(settings.website_publish_job_spacing_seconds))
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


def enqueue_publish(
    *,
    website_id: str,
    client_id: str,
    page_ids: list[str],
    user_id: str,
    force: bool = False,
) -> list[str]:
    """One `website_page_publish` job per page, staggered. Returns the job ids."""
    rows = []
    for page_id in page_ids:
        rows.append(
            {
                "job_type": "website_page_publish",
                "entity_id": website_id,
                "scheduled_at": _spaced_at(len(rows)),
                "payload": {
                    "website_id": website_id,
                    "client_id": client_id,
                    "page_id": page_id,
                    "user_id": user_id,
                    "force": bool(force),
                },
            }
        )
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [r["id"] for r in (res.data or [])]


# --------------------------------------------------------------------------
# The job
# --------------------------------------------------------------------------


def _load(page_id: str) -> tuple[dict, dict]:
    supabase = get_supabase()
    pages = (
        supabase.table("website_pages").select("*").eq("id", page_id).limit(1).execute()
    ).data
    if not pages:
        raise PublishError("website_page_not_found")
    page = pages[0]
    sites = (
        supabase.table("websites").select("*").eq("id", page["website_id"]).limit(1).execute()
    ).data
    if not sites:
        raise PublishError("website_not_found")
    return page, sites[0]


def resolve_source(page: dict) -> SourceContent:
    """The page's body and gate inputs, from wherever they actually live."""
    supabase = get_supabase()
    kind = page.get("content_source") or "composed"

    if kind == "local_seo_page":
        if not page.get("source_id"):
            raise PublishError("page_has_no_source_record")
        rows = (
            supabase.table("local_seo_pages")
            .select("*")
            .eq("id", page["source_id"])
            .limit(1)
            .execute()
        ).data
        if not rows:
            raise PublishError("source_record_not_found")
        return source_from_local_seo(rows[0])

    if kind == "run":
        # Informational posts are Phase 4. What exists today is the rendering the
        # pipeline already stores; a run without one is held rather than
        # reconstructed here, so there is exactly one assembler for article
        # markdown in the suite.
        if not page.get("source_id"):
            raise PublishError("page_has_no_source_record")
        rows = (
            supabase.table("module_outputs")
            .select("module, output_payload")
            .eq("run_id", page["source_id"])
            .in_("module", ["sources_cited", "service_writer", "writer"])
            .eq("status", "complete")
            .order("created_at", desc=True)
            .execute()
        ).data or []
        body, version, voice = "", None, None
        for row in rows:
            payload = row.get("output_payload") or {}
            metadata = payload.get("metadata") or {}
            body = body or ((payload.get("renderings") or {}).get("markdown") or "")
            version = version or payload.get("schema_version")
            if voice is None:
                candidate = payload.get("voice_compliance") or metadata.get("voice_scorecard")
                voice = candidate if isinstance(candidate, dict) else None
        if not body.strip():
            raise PublishError("run_markdown_unavailable")
        content = page.get("content") or {}
        return SourceContent(
            body=body,
            title=(content.get("title") or page.get("title") or "").strip(),
            description=(content.get("description") or "").strip(),
            voice=voice,
            writer_schema_version=version,
        )

    return source_from_content(page.get("content") or {"title": page.get("title")})


def _hold(page: dict, website: dict, reason: str) -> dict:
    get_supabase().table("website_pages").update(
        {"status": "draft", "error": reason, "updated_at": "now()"}
    ).eq("id", page["id"]).execute()

    from services import notifications

    notifications.emit(
        website.get("client_id"),
        "website_page_held",
        f"Website page held: {website.get('name') or 'site'}",
        summary=f"{page.get('route')} — {reason}",
        severity="warning",
        payload={"website_id": website["id"], "page_id": page["id"], "reason": reason},
        dedupe_key=held_dedupe_key(website["id"], datetime.now(timezone.utc)),
    )
    logger.info(
        "website_publish.held",
        extra={"page_id": page["id"], "route": page.get("route"), "reason": reason},
    )
    return {"page_id": page["id"], "published": False, "reason": reason}


async def publish_page(
    *, page_id: str, user_id: str = "", force: bool = False
) -> dict:
    """Gate a page, commit it, and record the deploy it triggered."""
    supabase = get_supabase()
    page, website = _load(page_id)

    if (page.get("page_type") or "") in website_content.TEMPLATE_ONLY_PAGE_TYPES:
        # The template renders these from the published set; there is no file to
        # write, so marking them published is the honest end state rather than a
        # permanent draft nobody can clear.
        supabase.table("website_pages").update(
            {"status": "published", "error": None, "published_at": "now()", "updated_at": "now()"}
        ).eq("id", page_id).execute()
        return {"page_id": page_id, "published": True, "template_only": True}

    repo = website.get("github_repo")
    if not repo:
        raise PublishError("website_not_provisioned")

    source = resolve_source(page)
    if not (source.body or "").strip():
        # A planned page nobody has written yet, or one whose page type has no
        # engine at all (Areas We Serve, a Services index). Committing an empty
        # file would ship a real URL with nothing on it, which is worse than a
        # page that is visibly still a draft.
        return _hold(page, website, "body_not_generated")

    verdict = website_content.publish_verdict(
        page_type=page.get("page_type") or "",
        composite=source.composite,
        voice=source.voice,
        facts_consistent=source.facts_consistent,
        writer_schema_version=source.writer_schema_version,
        frontmatter=(page.get("plan") or {}).get("frontmatter"),
    )
    forced = False
    if not verdict.allowed:
        if not (force and verdict.overridable):
            return _hold(page, website, verdict.reason)
        # A gate that no role may pass is not negotiable at any role: a facts
        # inconsistency is a liability question, not a quality preference.
        forced = True

    files = build_files(page, source)
    new_hash = content_hash(files)
    if is_unchanged(page, new_hash):
        logger.info("website_publish.unchanged", extra={"page_id": page_id})
        return {"page_id": page_id, "published": True, "commit_sha": page["commit_sha"],
                "unchanged": True}

    # Superseded routes ride the same commit as the change that caused them, so
    # a rename's 301 can never ship a deploy behind the rename itself.
    superseded = (
        supabase.table("website_pages")
        .select("route, redirect_to")
        .eq("website_id", website["id"])
        .not_.is_("superseded_at", "null")
        .execute()
    ).data or []
    redirects = website_content.redirects_file(superseded)
    if redirects:
        files["public/_redirects"] = redirects.encode("utf-8")

    repo_path = next(iter(k for k in files if k.startswith("src/content/")), None)
    try:
        result = await commit_files_to_github(
            repo=repo,
            branch=settings.website_default_branch,
            token=settings.github_sites_token,
            files=files,
            message=commit_message(page),
        )
    except Exception as exc:  # noqa: BLE001 — the failure belongs on the row
        supabase.table("website_pages").update(
            {"status": "failed", "error": str(exc)[:500], "updated_at": "now()"}
        ).eq("id", page_id).execute()
        raise

    commit_sha = result.get("commit_sha")
    supabase.table("website_pages").update(
        {
            "status": "published",
            "error": None,
            "repo_path": repo_path,
            "commit_sha": commit_sha,
            "content_hash": new_hash,
            "published_at": "now()",
            "updated_at": "now()",
        }
    ).eq("id", page_id).execute()

    website_deploy.record_deploy(
        website_id=website["id"],
        commit_sha=commit_sha,
        trigger="publish",
        meta={
            "pages": [page_id],
            # PRD §5.7 — an override invisible after the fact is
            # indistinguishable from a bug.
            "overrides": (
                [{"page_id": page_id, "gate": verdict.reason, "forced_by": user_id}]
                if forced
                else []
            ),
        },
    )
    logger.info(
        "website_publish.committed",
        extra={"page_id": page_id, "route": page.get("route"), "sha": commit_sha},
    )
    return {"page_id": page_id, "published": True, "commit_sha": commit_sha, "forced": forced}


async def run_publish_job(job: dict) -> None:
    """async_jobs handler for `website_page_publish`."""
    payload = job.get("payload") or {}
    supabase = get_supabase()
    try:
        result = await publish_page(
            page_id=payload["page_id"],
            user_id=payload.get("user_id") or "",
            force=bool(payload.get("force")),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001 — record it for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning(
            "website_publish.job_failed", extra={"job_id": job["id"], "error": str(detail)}
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
