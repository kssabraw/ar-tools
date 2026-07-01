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
import json
import logging
import re

import httpx

from config import settings

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubPublishError(Exception):
    """Raised on any GitHub publish failure (config or transport)."""


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "page"


def build_markdown_file(title: str, body: str, description: str | None = None) -> str:
    """A minimal Astro-style content file: YAML frontmatter + body. Values are
    JSON-encoded so titles with quotes/colons stay valid YAML."""
    lines = ["---", f"title: {json.dumps(title or '')}"]
    if description:
        lines.append(f"description: {json.dumps(description)}")
    lines.append("---")
    return f"{chr(10).join(lines)}\n\n{body.rstrip()}\n"


async def publish_to_github(
    *,
    client: dict,
    title: str,
    body: str,
    slug: str | None = None,
    description: str | None = None,
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
    content_path = (
        client.get("github_content_path") or settings.github_default_content_path
    ).strip("/")
    file_slug = slugify(slug or title)
    path = f"{content_path}/{file_slug}.md" if content_path else f"{file_slug}.md"
    file_md = build_markdown_file(title, body, description)

    url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as http:
        # Look up an existing file's sha so a re-publish updates in place.
        sha: str | None = None
        try:
            existing = await http.get(url, headers=headers, params={"ref": branch})
            if existing.status_code == 200:
                sha = existing.json().get("sha")
        except httpx.HTTPError:
            pass  # treat as create

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
