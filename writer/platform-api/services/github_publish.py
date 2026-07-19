"""Publish finished suite content to a client's GitHub repo as Astro content
Markdown.

Mirrors the Topic Fan-out GitHub publish convention (YAML frontmatter + a file
under the repo's content path) but is self-contained in the suite so it doesn't
couple to the vendored `fanout` package. Dormant until `GITHUB_PUBLISH_TOKEN` is
set on the platform; each client supplies the target `github_repo` /
`github_branch` / `github_content_path`.

Commits via the GitHub Contents API (create or update in place), so re-publishing
the same slug overwrites the file rather than erroring.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from datetime import date

import httpx

from config import settings
from services.slug_rules import build_slug

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubPublishError(Exception):
    """Raised on any GitHub publish failure (config or transport)."""


def slugify(text: str) -> str:
    """Leaf-slug for a content file name. Delegates to the SOP slug engine
    (`slug_rules.build_slug` — tokens, year strip, apostrophes, etc.), with a
    non-empty fallback so a blank source still yields a valid file name."""
    return build_slug(text) or "page"


def resolve_github_path(client: dict, content_type: str | None) -> str:
    """Pick the repo content path a piece of content commits into.

    SOP precedence (`site always wins`):
      1. the INFERRED existing-site content path (`github_inferred_patterns.
         content_paths[content_type]`) — the live site is authoritative;
      2. the per-client override map (`github_content_paths[content_type]`);
      3. the single default (`github_content_path`);
      4. the server-side `github_default_content_path`.

    All returned values are `/`-stripped; a blank/whitespace-only or non-string
    entry is treated as unset (falls through). An empty string is a valid result
    (commit at the repo root)."""
    # 1. Inferred existing-site path wins.
    inferred = client.get("github_inferred_patterns")
    if content_type and isinstance(inferred, dict):
        content_paths = inferred.get("content_paths")
        if isinstance(content_paths, dict):
            val = content_paths.get(content_type)
            if isinstance(val, str) and val.strip():
                return val.strip().strip("/")
    # 2. Per-client override map.
    paths = client.get("github_content_paths")
    if content_type and isinstance(paths, dict):
        specific = paths.get(content_type)
        if isinstance(specific, str) and specific.strip():
            return specific.strip().strip("/")
    # 3. Single default.
    default = client.get("github_content_path")
    if isinstance(default, str) and default.strip():
        return default.strip().strip("/")
    # 4. Per-type server default (so service/location pages don't land in blog),
    #    then the single server default.
    server_map = settings.github_default_content_paths or {}
    if content_type and isinstance(server_map, dict):
        val = server_map.get(content_type)
        if isinstance(val, str) and val.strip():
            return val.strip().strip("/")
    return (settings.github_default_content_path or "").strip("/")


# Description derivation: heading elements/lines, lists, tables and images are
# structural, not prose — skip them and take the first real paragraph.
_HTML_HEADING_RE = re.compile(r"<h[1-6][^>]*>.*?</h[1-6]>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_ORDERED_RE = re.compile(r"^\d+[.)]\s")
_PUBDATE_RE = re.compile(r"^pubDate:\s*(.+?)\s*$", re.MULTILINE)


def derive_description(body: str, limit: int = 160) -> str | None:
    """First real paragraph of prose as a meta-description fallback (mirrors the
    Fan-out convention — many collection schemas require `description`). Handles
    Markdown and HTML bodies (Local SEO pages publish HTML): heading elements are
    dropped with their text, remaining tags stripped, heading/list/table/quote
    lines and images skipped, inline marks removed, and the result clipped to
    `limit` on a word boundary."""
    text = _HTML_HEADING_RE.sub("\n", body or "")
    text = _HTML_TAG_RE.sub(" ", text)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", "*", "+", ">", "|", "`")):
            continue
        if _MD_ORDERED_RE.match(line):
            continue
        line = _MD_IMAGE_RE.sub("", line)
        line = _MD_LINK_RE.sub(r"\1", line)
        line = re.sub(r"[*_`]", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if len(line) <= limit:
            return line
        cut = line[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        return f"{cut}…"
    return None


def build_markdown_file(
    title: str,
    body: str,
    description: str | None = None,
    slug: str | None = None,
    pub_date: str | date | None = None,
    hero_image: str | None = None,
    schema: str | None = None,
) -> str:
    """A minimal Astro-style content file: YAML frontmatter + body. Values are
    JSON-encoded so titles with quotes/colons stay valid YAML. `slug` is the
    content-collection nested slug (deep nesting — the collection route supplies
    any /blog//shop/ prefix). `pubDate` is always emitted (blog collection
    schemas commonly require it): a date renders as an unquoted ISO date, a
    string is kept verbatim (the re-publish path preserves the existing file's
    scalar), absent → today. `hero_image` (the run's featured image URL) emits
    as `heroImage` when present. `schema` is the page's JSON-LD (a JSON string);
    it's emitted as a JSON-encoded frontmatter string the Astro layout parses and
    renders in <head> — the value is written verbatim (already valid JSON)."""
    lines = ["---", f"title: {json.dumps(title or '')}"]
    if description:
        lines.append(f"description: {json.dumps(description)}")
    when = pub_date if isinstance(pub_date, str) else (pub_date or date.today()).isoformat()
    lines.append(f"pubDate: {when}")
    if hero_image:
        lines.append(f"heroImage: {json.dumps(hero_image)}")
    if slug:
        lines.append(f"slug: {json.dumps(slug)}")
    if schema and schema.strip():
        lines.append(f"schema: {json.dumps(schema)}")
    lines.append("---")
    return f"{chr(10).join(lines)}\n\n{body.rstrip()}\n"


async def publish_to_github(
    *,
    client: dict,
    title: str,
    body: str,
    slug: str | None = None,
    description: str | None = None,
    content_type: str | None = None,
    location: str | None = None,
    hero_image: str | None = None,
    schema: str | None = None,
) -> dict:
    """Commit one piece of content to the client's repo. Returns
    {path, html_url, commit_sha}. Raises GitHubPublishError on failure."""
    token = settings.github_publish_token
    if not token:
        raise GitHubPublishError("github_not_configured")
    repo = (client.get("github_repo") or "").strip()
    if not repo:
        raise GitHubPublishError("github_repo_not_set")
    if not (body or "").strip():
        raise GitHubPublishError("content_is_empty")

    branch = (client.get("github_branch") or settings.github_default_branch or "main").strip()
    # Resolve the repo file path + nested collection slug per SOP (content_path
    # precedence 'site always wins' + deep per-type nesting). Lazy import to avoid
    # a publish_targeting ↔ github_publish import cycle.
    from services.publish_targeting import resolve_publish_target

    target = resolve_publish_target(content_type, slug or title, client=client, location=location)
    path = target["file_path"]

    url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as http:
        # Look up an existing file's sha so a re-publish updates in place —
        # keeping its pubDate, so an updated post doesn't jump to "newest".
        sha: str | None = None
        existing_pub_date: str | None = None
        try:
            existing = await http.get(url, headers=headers, params={"ref": branch})
            if existing.status_code == 200:
                data = existing.json()
                sha = data.get("sha")
                try:
                    decoded = base64.b64decode(data.get("content") or "").decode("utf-8", "replace")
                    m = _PUBDATE_RE.search(decoded)
                    if m:
                        existing_pub_date = m.group(1)
                except (binascii.Error, ValueError):
                    pass
        except httpx.HTTPError:
            pass  # treat as create

        file_md = build_markdown_file(
            title,
            body,
            description or derive_description(body),
            slug=target["frontmatter_slug"],
            pub_date=existing_pub_date,
            hero_image=hero_image,
            schema=schema,
        )

        payload = {
            "message": f"content: {title or path}",
            "content": base64.b64encode(file_md.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        try:
            resp = await http.put(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise GitHubPublishError(f"github_request_failed: {exc}") from exc

    if resp.status_code not in (200, 201):
        logger.error(
            "github.publish_failed",
            extra={"repo": repo, "status": resp.status_code, "body": resp.text[:300]},
        )
        raise GitHubPublishError(f"github_error_{resp.status_code}")

    data = resp.json()
    return {
        "path": path,
        "html_url": (data.get("content") or {}).get("html_url"),
        "commit_sha": (data.get("commit") or {}).get("sha"),
    }
