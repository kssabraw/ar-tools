"""Commit article files to a GitHub repo via the Contents API (httpx). Create-or-update: a
re-push of the same path updates the file in place (a real commit, so the repo keeps history).
The token is a fine-grained PAT with Contents:write on the target repo (env, dormant if unset)."""

from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_API = "https://api.github.com"


class GitHubPublishError(RuntimeError):
    """A push failed (auth, missing repo/branch, conflict) — the API maps it to a clear error."""


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_existing_sha(repo: str, path: str, branch: str, token: str, client: httpx.Client) -> str | None:
    """The blob SHA of an existing file at path@branch (needed to update it), or None if new."""
    r = client.get(f"{_API}/repos/{repo}/contents/{path}", params={"ref": branch},
                   headers=_headers(token))
    if r.status_code == 200:
        return r.json().get("sha")
    if r.status_code == 404:
        return None
    raise GitHubPublishError(f"GitHub read failed ({r.status_code}): {r.text[:200]}")


def commit_file(
    *, repo: str, path: str, content: str, message: str, branch: str, token: str,
    timeout_s: float = 30.0,
) -> dict:
    """Create or update one file at `path` on `branch`. Returns {path, html_url, commit_sha}."""
    if not token:
        raise GitHubPublishError("GitHub publishing is not configured (no token).")
    with httpx.Client(timeout=timeout_s) as client:
        sha = _get_existing_sha(repo, path, branch, token, client)
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        r = client.put(f"{_API}/repos/{repo}/contents/{path}", json=payload, headers=_headers(token))
    if r.status_code not in (200, 201):
        raise GitHubPublishError(f"GitHub commit failed ({r.status_code}): {r.text[:200]}")
    body = r.json()
    return {
        "path": path,
        "html_url": (body.get("content") or {}).get("html_url"),
        "commit_sha": (body.get("commit") or {}).get("sha"),
    }


def commit_tree(
    *, repo: str, branch: str, files: list[tuple[str, str]], message: str, token: str,
    timeout_s: float = 60.0,
) -> dict:
    """Commit many files in ONE commit via the Git Data API (base ref → tree with inline blob
    content → commit → move ref). ~4 calls regardless of file count, so 'Push all' is fast +
    atomic. Returns {committed, commit_sha}."""
    if not token:
        raise GitHubPublishError("GitHub publishing is not configured (no token).")
    if not files:
        return {"committed": 0, "commit_sha": None}
    h = _headers(token)
    with httpx.Client(timeout=timeout_s) as client:
        def _ok(r: httpx.Response, what: str) -> dict:
            if r.status_code not in (200, 201):
                raise GitHubPublishError(f"GitHub {what} failed ({r.status_code}): {r.text[:200]}")
            return r.json()

        ref = _ok(client.get(f"{_API}/repos/{repo}/git/ref/heads/{branch}", headers=h), "ref read")
        base_commit_sha = ref["object"]["sha"]
        base_commit = _ok(client.get(f"{_API}/repos/{repo}/git/commits/{base_commit_sha}", headers=h),
                          "commit read")
        base_tree_sha = base_commit["tree"]["sha"]

        tree_entries = [
            {"path": path, "mode": "100644", "type": "blob", "content": content}
            for path, content in files
        ]
        tree = _ok(client.post(f"{_API}/repos/{repo}/git/trees",
                               json={"base_tree": base_tree_sha, "tree": tree_entries}, headers=h),
                   "tree create")
        commit = _ok(client.post(f"{_API}/repos/{repo}/git/commits",
                                 json={"message": message, "tree": tree["sha"],
                                       "parents": [base_commit_sha]}, headers=h),
                     "commit create")
        _ok(client.patch(f"{_API}/repos/{repo}/git/refs/heads/{branch}",
                         json={"sha": commit["sha"]}, headers=h), "ref update")
    return {"committed": len(files), "commit_sha": commit["sha"]}
