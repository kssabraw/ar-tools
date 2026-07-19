"""Existing-site pattern discovery job — populates clients.github_inferred_patterns.

Reads the client's repo Git tree (GitHub Git Trees API) and its live sitemap
(site_page_index), runs the pure inference engine (services/slug_inference), and
stores the descriptor the publish path follows (SOP "site always wins"). The
descriptor shape:
  {"content_paths": {content_type: repo_path},        # from the repo tree
   "url": {separator, trailing_slash, extension, prefixes},  # from the sitemap
   "inferred_at": iso8601, "source": "repo_tree+sitemap|repo_tree|sitemap|none"}

Best-effort throughout: a missing token/repo skips the tree, a missing website
skips the sitemap, and either failing leaves the other's signal intact.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from config import settings
from services.slug_inference import (
    build_reconcile_index,
    infer_content_paths_from_repo_tree,
    infer_nesting_from_tree,
    infer_slug_patterns,
    parse_frontmatter_slug,
)

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def enqueue_github_infer(client_id: str) -> None:
    """Queue a github_infer_patterns job for a client (best-effort — never raises
    into the caller so a client create/update can't fail over discovery)."""
    try:
        from db.supabase_client import get_supabase

        supabase = get_supabase()
        # Idempotent: skip if an unstarted job for this client is already queued,
        # so N rapid saves don't pile up N discovery jobs.
        existing = (
            supabase.table("async_jobs")
            .select("id")
            .eq("job_type", "github_infer_patterns")
            .eq("entity_id", client_id)
            .eq("status", "pending")
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        supabase.table("async_jobs").insert(
            {
                "job_type": "github_infer_patterns",
                "entity_id": client_id,
                "payload": {"client_id": client_id},
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — advisory enqueue
        logger.warning("github_infer.enqueue_failed", extra={"client_id": client_id, "error": str(exc)})


def parse_tree_response(body: dict) -> list[str]:
    """The blob (file) paths from a Git Trees API response. Logs a warning if the
    response was truncated (a very large repo → partial inference)."""
    if isinstance(body, dict) and body.get("truncated"):
        logger.warning("github_infer.tree_truncated", extra={"sha": body.get("sha")})
    tree = body.get("tree") if isinstance(body, dict) else None
    if not isinstance(tree, list):
        return []
    return [t["path"] for t in tree if isinstance(t, dict) and t.get("type") == "blob" and t.get("path")]


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def fetch_repo_tree(repo: str, branch: str, token: str) -> list[str]:
    """Recursively list a repo branch's file paths via the Git Trees API. Returns
    [] on any error (best-effort). The branch is path-escaped so a branch name
    containing '/' (e.g. release/x) resolves instead of 404ing."""
    url = f"{_GITHUB_API}/repos/{repo}/git/trees/{quote(branch, safe='')}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(url, headers=_gh_headers(token), params={"recursive": "1"})
        if resp.status_code != 200:
            logger.warning("github_infer.tree_failed", extra={"repo": repo, "status": resp.status_code})
            return []
        return parse_tree_response(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("github_infer.tree_error", extra={"repo": repo, "error": str(exc)})
        return []


async def fetch_frontmatter_slugs(
    repo: str, branch: str, token: str, paths: list[str], *, cap: int, concurrency: int
) -> dict[str, str]:
    """Read each file's frontmatter `slug` via the Contents API (bounded by `cap`,
    concurrent up to `concurrency`). Returns {path: slug} for files that declare
    one — the slug-override index that lets the reconcile catch a page whose path
    doesn't reflect its slug. Best-effort per file; runs off the publish hot path."""
    if cap <= 0 or not paths:
        return {}
    targets = paths[:cap]
    sem = asyncio.Semaphore(max(1, concurrency))
    out: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30) as http:
        async def _one(path: str) -> None:
            async with sem:
                try:
                    r = await http.get(
                        f"{_GITHUB_API}/repos/{repo}/contents/{quote(path, safe='/')}",
                        headers=_gh_headers(token),
                        params={"ref": branch},
                    )
                    if r.status_code != 200:
                        return
                    content = (r.json() or {}).get("content")
                    if not content:
                        return
                    text = base64.b64decode(content).decode("utf-8", "ignore")
                    slug = parse_frontmatter_slug(text)
                    if slug:
                        out[path] = slug
                except (httpx.HTTPError, ValueError, binascii.Error):
                    return

        await asyncio.gather(*(_one(p) for p in targets))
    return out


def assemble_inferred(
    *,
    tree_paths: list[str],
    urls: list[str],
    now_iso: str,
    frontmatter_slugs: dict[str, str] | None = None,
) -> dict:
    """Combine the repo-tree content paths + nesting + reconcile index and the
    sitemap URL conventions into the stored descriptor. Pure — the fetches happen
    in the caller."""
    content_paths = infer_content_paths_from_repo_tree(tree_paths) if tree_paths else {}
    url = infer_slug_patterns(urls) if urls else {}
    nesting = infer_nesting_from_tree(tree_paths, content_paths) if tree_paths else {}
    reconcile_index = (
        build_reconcile_index(tree_paths, content_paths, frontmatter_slugs) if tree_paths else {}
    )
    sources = []
    if tree_paths:
        sources.append("repo_tree")
    if urls:
        sources.append("sitemap")
    return {
        "content_paths": content_paths,
        "url": url,
        "nesting": nesting,
        "reconcile_index": reconcile_index,
        "inferred_at": now_iso,
        "source": "+".join(sources) or "none",
    }


async def run_github_infer_job(job: dict) -> None:
    """Discover a client's existing-site URL/slug conventions and store them."""
    from db.supabase_client import get_supabase

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    logger.info("github_infer_started", extra={"job_id": job_id, "client_id": client_id})
    try:
        row = (
            supabase.table("clients")
            .select("github_repo, github_branch, website_url")
            .eq("id", client_id)
            .single()
            .execute()
        )
        client = row.data or {}
        repo = (client.get("github_repo") or "").strip()
        branch = (client.get("github_branch") or settings.github_default_branch or "main").strip()
        website = (client.get("website_url") or "").strip()

        tree_paths: list[str] = []
        frontmatter_slugs: dict[str, str] = {}
        if repo and settings.github_publish_token:
            token = settings.github_publish_token
            tree_paths = await fetch_repo_tree(repo, branch, token)
            # Frontmatter slug-override index (bounded, off the publish hot path):
            # read Markdown files under the detected collections so the reconcile
            # can match a page whose path doesn't reflect its slug.
            content_paths = infer_content_paths_from_repo_tree(tree_paths)
            if content_paths and settings.github_infer_max_frontmatter_reads:
                cps = tuple(content_paths.values())
                candidates = [
                    p
                    for p in tree_paths
                    if p.lower().endswith((".md", ".mdx"))
                    and any(p == cp or p.startswith(cp + "/") for cp in cps)
                ]
                frontmatter_slugs = await fetch_frontmatter_slugs(
                    repo,
                    branch,
                    token,
                    candidates,
                    cap=settings.github_infer_max_frontmatter_reads,
                    concurrency=settings.github_infer_frontmatter_concurrency,
                )

        urls: list[str] = []
        if website:
            # Lazy import: keep the pure inference importable without the DataForSEO
            # / Supabase-backed discovery stack.
            from services.site_page_index import discover_site_urls

            # Sitemap-only: never auto-spend on the DataForSEO site: fallback for
            # a background discovery job.
            urls, _source = await discover_site_urls(
                website, settings.dataforseo_default_location_code, use_paid_fallback=False
            )

        descriptor = assemble_inferred(
            tree_paths=tree_paths,
            urls=urls,
            now_iso=datetime.now(timezone.utc).isoformat(),
            frontmatter_slugs=frontmatter_slugs,
        )
        supabase.table("clients").update({"github_inferred_patterns": descriptor}).eq("id", client_id).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "result": descriptor, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info(
            "github_infer_complete",
            extra={"job_id": job_id, "client_id": client_id, "source": descriptor["source"]},
        )
    except Exception as exc:  # noqa: BLE001 — job boundary
        logger.warning("github_infer_failed", extra={"job_id": job_id, "client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
