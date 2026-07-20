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


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _read_existing_pubdate(http: httpx.AsyncClient, repo: str, path: str, branch: str, headers: dict) -> str | None:
    """The existing content file's `pubDate` (so a re-publish keeps it). Best-effort."""
    try:
        resp = await http.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{path}", headers=headers, params={"ref": branch}
        )
        if resp.status_code != 200:
            return None
        decoded = base64.b64decode(resp.json().get("content") or "").decode("utf-8", "replace")
        m = _PUBDATE_RE.search(decoded)
        return m.group(1) if m else None
    except (httpx.HTTPError, ValueError, binascii.Error):
        return None


async def commit_files_to_github(
    *,
    repo: str,
    branch: str,
    token: str,
    files: dict[str, bytes],
    message: str,
) -> dict:
    """Commit multiple files in ONE commit via the Git Data API (blobs → tree →
    commit → ref update), so a post's markdown and all its images land together.
    Overwrites paths in place (the tree is layered on the branch's current tree).
    Returns {commit_sha, tree_sha}. Raises GitHubPublishError on any failure."""
    if not files:
        raise GitHubPublishError("content_is_empty")
    headers = _gh_headers(token)
    base = f"{_GITHUB_API}/repos/{repo}/git"

    async with httpx.AsyncClient(timeout=60) as http:
        try:
            # 1. Branch head → base commit + base tree.
            ref = await http.get(f"{base}/ref/heads/{branch}", headers=headers)
            if ref.status_code != 200:
                raise GitHubPublishError(f"github_ref_error_{ref.status_code}")
            base_commit_sha = ref.json()["object"]["sha"]
            commit = await http.get(f"{base}/commits/{base_commit_sha}", headers=headers)
            if commit.status_code != 200:
                raise GitHubPublishError(f"github_commit_read_error_{commit.status_code}")
            base_tree_sha = commit.json()["tree"]["sha"]

            # 2. One blob per file (base64-encoded so binary images survive).
            tree_entries = []
            for path, content in files.items():
                blob = await http.post(
                    f"{base}/blobs",
                    headers=headers,
                    json={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
                )
                if blob.status_code not in (200, 201):
                    raise GitHubPublishError(f"github_blob_error_{blob.status_code}")
                tree_entries.append(
                    {"path": path.lstrip("/"), "mode": "100644", "type": "blob", "sha": blob.json()["sha"]}
                )

            # 3. Tree layered on the branch's current tree, 4. commit, 5. move ref.
            tree = await http.post(
                f"{base}/trees", headers=headers, json={"base_tree": base_tree_sha, "tree": tree_entries}
            )
            if tree.status_code not in (200, 201):
                raise GitHubPublishError(f"github_tree_error_{tree.status_code}")
            new_tree_sha = tree.json()["sha"]

            new_commit = await http.post(
                f"{base}/commits",
                headers=headers,
                json={"message": message, "tree": new_tree_sha, "parents": [base_commit_sha]},
            )
            if new_commit.status_code not in (200, 201):
                raise GitHubPublishError(f"github_commit_error_{new_commit.status_code}")
            new_commit_sha = new_commit.json()["sha"]

            upd = await http.patch(
                f"{base}/refs/heads/{branch}", headers=headers, json={"sha": new_commit_sha}
            )
            if upd.status_code not in (200, 201):
                raise GitHubPublishError(f"github_ref_update_error_{upd.status_code}")
        except httpx.HTTPError as exc:
            raise GitHubPublishError(f"github_request_failed: {exc}") from exc

    return {"commit_sha": new_commit_sha, "tree_sha": new_tree_sha}


async def publish_blog_with_images_to_github(
    *,
    client: dict,
    title: str,
    body: str,
    image_files: dict[str, bytes],
    slug: str | None = None,
    description: str | None = None,
    content_type: str | None = None,
    location: str | None = None,
    hero_image: str | None = None,
    schema: str | None = None,
) -> dict:
    """Commit a blog post's markdown + its generated images atomically. `body` is
    the markdown (already carrying `![](/…)` body-image references); `image_files`
    maps each image's repo path → PNG bytes; `hero_image` is the hero's site path
    for the frontmatter. Returns {path, html_url, commit_sha}."""
    token = settings.github_publish_token
    if not token:
        raise GitHubPublishError("github_not_configured")
    repo = (client.get("github_repo") or "").strip()
    if not repo:
        raise GitHubPublishError("github_repo_not_set")
    if not (body or "").strip():
        raise GitHubPublishError("content_is_empty")

    branch = (client.get("github_branch") or settings.github_default_branch or "main").strip()
    from services.publish_targeting import resolve_publish_target

    target = resolve_publish_target(content_type, slug or title, client=client, location=location)
    md_path = target["file_path"]

    async with httpx.AsyncClient(timeout=30) as http:
        existing_pub_date = await _read_existing_pubdate(http, repo, md_path, branch, _gh_headers(token))

    file_md = build_markdown_file(
        title,
        body,
        description or derive_description(body),
        slug=target["frontmatter_slug"],
        pub_date=existing_pub_date,
        hero_image=hero_image,
        schema=schema,
    )

    files: dict[str, bytes] = {md_path: file_md.encode("utf-8")}
    files.update(image_files)

    result = await commit_files_to_github(
        repo=repo, branch=branch, token=token, files=files, message=f"content: {title or md_path}"
    )
    return {
        "path": md_path,
        "html_url": f"https://github.com/{repo}/blob/{branch}/{md_path}",
        "commit_sha": result["commit_sha"],
    }
